"""
DEPRECATED: This file is the v1 single-workflow engine.
All mode-specific workflows are now in apps/worker/modes/.
This file is kept as reference only.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.postgres.aio import PostgresSaver
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from pydantic import BaseModel, Field
from structlog import get_logger

from apps.worker.llm_gateway import LLMGateway, ModelTier, get_gateway
from libs.adapters.openalex import OpenAlexAdapter
from libs.adapters.scholar_fusion import ScholarFusionService
from libs.adapters.semantic_scholar import SemanticScholarAdapter
from services.parser import detect_arxiv_id, parse_paper
from libs.prompts.templates import (
    CLAIM_OUTPUT_SCHEMA,
    GAP_OUTPUT_SCHEMA,
    INNOVATION_CARD_SCHEMA,
    PAPER_SUMMARY_SCHEMA,
    PLANNER_OUTPUT_SCHEMA,
    VERIFIER_OUTPUT_SCHEMA,
    PromptName,
    get_schema,
    get_system_prompt,
)

logger = get_logger(__name__)

# Cost estimates per 1K tokens (rough approximations)
_COST_PER_1K_INPUT = {ModelTier.HIGH: 0.005, ModelTier.MEDIUM: 0.00015, ModelTier.LOW: 0.00008}
_COST_PER_1K_OUTPUT = {ModelTier.HIGH: 0.015, ModelTier.MEDIUM: 0.0006, ModelTier.LOW: 0.0004}


def _estimate_cost(result: dict[str, Any], tier: ModelTier) -> float:
    """Estimate USD cost from an LLM result dict containing usage info."""
    usage = result.get("usage", {})
    prompt_tokens = usage.get("prompt_tokens", 0)
    completion_tokens = usage.get("completion_tokens", 0)
    cost = (
        (prompt_tokens / 1000) * _COST_PER_1K_INPUT.get(tier, 0.005)
        + (completion_tokens / 1000) * _COST_PER_1K_OUTPUT.get(tier, 0.015)
    )
    return cost


def _normalize_title(title: str) -> str:
    """Normalize a paper title for deduplication."""
    if not title:
        return ""
    normalized = title.lower()
    normalized = "".join(c if c.isalnum() or c.isspace() else " " for c in normalized)
    return " ".join(normalized.split())


# ============================================
# Graph State Definition
# ============================================


class GraphState(BaseModel):
    """
    The state of the research workflow graph.

    This is passed between nodes and persisted for recovery.
    """

    # Run identification
    run_id: UUID = Field(default_factory=uuid4)
    thread_id: str = ""

    # Research configuration
    topic: str = ""
    goal_type: str = "survey_plus_innovations"
    keywords: list[str] = Field(default_factory=list)
    exclude_keywords: list[str] = Field(default_factory=list)

    # Budget tracking
    max_papers: int = 150
    max_fulltext_reads: int = 40
    max_cost_usd: float = 30.0
    current_cost_usd: float = 0.0
    papers_discovered: int = 0
    papers_read: int = 0

    # Papers
    seed_paper_ids: list[str] = Field(default_factory=list)
    candidate_paper_ids: list[str] = Field(default_factory=list)
    selected_paper_ids: list[str] = Field(default_factory=list)
    read_paper_ids: list[str] = Field(default_factory=list)

    # Queries
    pending_queries: list[dict[str, Any]] = Field(default_factory=list)
    executed_queries: list[str] = Field(default_factory=list)

    # Analysis
    clusters: list[dict[str, Any]] = Field(default_factory=list)
    contradictions: list[dict[str, Any]] = Field(default_factory=list)
    gaps: list[dict[str, Any]] = Field(default_factory=list)

    # Hypotheses
    hypotheses: list[dict[str, Any]] = Field(default_factory=list)
    verified_hypothesis_ids: list[str] = Field(default_factory=list)
    rejected_hypothesis_ids: list[str] = Field(default_factory=list)

    # Control flow
    current_step: str = "init"
    iteration_count: int = 0
    max_iterations: int = 10
    saturation_score: float = 0.0
    should_pause: bool = False
    pause_reason: str | None = None
    should_stop: bool = False
    stop_reason: str | None = None

    # Messages (for LLM interactions)
    messages: Annotated[list[dict[str, Any]], add_messages] = Field(default_factory=list)

    # Outputs
    report_markdown: str = ""
    export_urls: list[str] = Field(default_factory=list)

    # Errors and warnings
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    class Config:
        arbitrary_types_allowed = True


# ============================================
# Node Functions
# ============================================


async def plan_research(state: GraphState) -> dict[str, Any]:
    """
    Plan the research: decompose topic into questions and queries via LLM.
    """
    updates: dict[str, Any] = {
        "current_step": "plan_research",
    }
    errors: list[str] = list(state.errors)
    cost = state.current_cost_usd
    topic = state.topic
    keywords = state.keywords
    exclude_keywords = state.exclude_keywords

    gateway = get_gateway()

    # ------------------------------------------------------------------
    # Step 1 - Use the PLANNER prompt to decompose the topic
    # ------------------------------------------------------------------
    try:
        planner_system = get_system_prompt(PromptName.PLANNER)
        user_content = (
            f"Research topic: {topic}\n"
            f"Keywords: {', '.join(keywords) if keywords else 'none'}\n"
            f"Exclude keywords: {', '.join(exclude_keywords) if exclude_keywords else 'none'}\n"
            f"Goal type: {state.goal_type}\n"
            f"Max papers: {state.max_papers}\n"
        )

        planner_result = await gateway.chat_json(
            messages=[
                {"role": "system", "content": planner_system},
                {"role": "user", "content": user_content},
            ],
            tier=ModelTier.HIGH,
            schema=PLANNER_OUTPUT_SCHEMA,
        )

        research_questions = planner_result.get("research_questions", [])
        coverage_targets = planner_result.get("coverage_targets", [])
        query_plans = planner_result.get("query_plans", [])

        cost += _estimate_cost(planner_result, ModelTier.HIGH) if isinstance(planner_result, dict) and "usage" in planner_result else 0.01

        logger.info("plan_research.planner_done", questions=len(research_questions), query_plans=len(query_plans))
    except Exception as exc:
        logger.error("plan_research.planner_failed", error=str(exc))
        errors.append(f"Planner LLM call failed: {exc}")
        research_questions = []
        coverage_targets = []
        query_plans = []

    # ------------------------------------------------------------------
    # Step 2 - Use QUERY_REWRITE to generate structured search queries
    # ------------------------------------------------------------------
    pending_queries: list[dict[str, Any]] = []

    try:
        qr_system = get_system_prompt(PromptName.QUERY_REWRITE)
        qr_user = (
            f"Topic: {topic}\n"
            f"Research questions:\n" + "\n".join(f"- {q}" for q in research_questions[:10]) + "\n"
            f"Keywords: {', '.join(keywords) if keywords else 'none'}\n"
            f"Exclude: {', '.join(exclude_keywords) if exclude_keywords else 'none'}\n"
        )

        qr_result = await gateway.chat_json(
            messages=[
                {"role": "system", "content": qr_system},
                {"role": "user", "content": qr_user},
            ],
            tier=ModelTier.MEDIUM,
            schema=get_schema(PromptName.QUERY_REWRITE),
        )

        cost += _estimate_cost(qr_result, ModelTier.MEDIUM) if isinstance(qr_result, dict) and "usage" in qr_result else 0.002

        # qr_result should be a list (or wrapped in a key)
        raw_queries = qr_result if isinstance(qr_result, list) else qr_result.get("queries", [])
        for idx, q in enumerate(raw_queries):
            pending_queries.append({
                "query": q.get("query", ""),
                "type": q.get("intent", "primary"),
                "source": "both",
                "priority": idx + 1,
                "year": q.get("year"),
                "fields_of_study": q.get("fieldsOfStudy"),
                "min_citation_count": q.get("minCitationCount"),
                "open_access_pdf": q.get("openAccessPdf"),
            })

        logger.info("plan_research.query_rewrite_done", queries=len(pending_queries))
    except Exception as exc:
        logger.error("plan_research.query_rewrite_failed", error=str(exc))
        errors.append(f"Query rewrite LLM call failed: {exc}")

    # Fallback: if LLM calls failed, build basic queries from topic + keywords
    if not pending_queries:
        pending_queries.append({
            "query": topic,
            "type": "primary",
            "source": "both",
            "priority": 1,
        })
        for kw in keywords[:5]:
            pending_queries.append({
                "query": f"{topic} {kw}",
                "type": "keyword_expand",
                "source": "both",
                "priority": 2,
            })

    # Also fold in any query_plans from the planner that weren't captured
    existing_query_texts = {q["query"].lower() for q in pending_queries}
    for qp in query_plans:
        q_text = qp.get("query", "")
        if q_text and q_text.lower() not in existing_query_texts:
            pending_queries.append({
                "query": q_text,
                "type": qp.get("type", "primary"),
                "source": qp.get("source", "both"),
                "priority": qp.get("priority", 5),
            })

    updates["pending_queries"] = pending_queries
    updates["current_cost_usd"] = cost
    updates["errors"] = errors
    updates["messages"] = [{
        "role": "assistant",
        "content": (
            f"Research plan created: {len(research_questions)} questions, "
            f"{len(pending_queries)} search queries, "
            f"{len(coverage_targets)} coverage targets."
        ),
    }]

    return updates


async def ingest_seeds(state: GraphState) -> dict[str, Any]:
    """
    Ingest and parse seed papers via ScholarFusionService.
    """
    updates: dict[str, Any] = {
        "current_step": "ingest_seeds",
    }
    errors: list[str] = list(state.errors)
    seed_ids = state.seed_paper_ids

    if not seed_ids:
        updates["messages"] = [{
            "role": "assistant",
            "content": "No seed papers to ingest, skipping.",
        }]
        return updates

    fusion = ScholarFusionService(
        s2_api_key=os.getenv("S2_API_KEY"),
        openalex_email=os.getenv("OPENALEX_EMAIL"),
        crossref_email=os.getenv("CROSSREF_EMAIL"),
        unpaywall_email=os.getenv("UNPAYWALL_EMAIL"),
    )

    ingested: list[str] = []
    new_candidates: list[str] = []

    try:
        for seed_id in seed_ids:
            try:
                # Determine the identifier type and resolve
                kwargs: dict[str, str] = {}
                if seed_id.startswith("10."):
                    kwargs["doi"] = seed_id
                elif seed_id.startswith("S2:"):
                    kwargs["s2_id"] = seed_id.removeprefix("S2:")
                elif seed_id.startswith("OA:"):
                    kwargs["openalex_id"] = seed_id.removeprefix("OA:")
                else:
                    # Assume it could be an S2 paper ID or a title
                    kwargs["s2_id"] = seed_id

                fused = await fusion.resolve_paper(**kwargs)
                if fused is not None:
                    pid = fused.s2_paper_id or fused.doi or str(fused.id)
                    ingested.append(pid)
                    if pid not in state.candidate_paper_ids:
                        new_candidates.append(pid)
                    logger.info("ingest_seeds.resolved", seed_id=seed_id, title=fused.canonical_title[:80])
                else:
                    errors.append(f"Could not resolve seed paper: {seed_id}")
                    logger.warning("ingest_seeds.not_found", seed_id=seed_id)

            except Exception as exc:
                logger.error("ingest_seeds.seed_failed", seed_id=seed_id, error=str(exc))
                errors.append(f"Seed ingestion failed for {seed_id}: {exc}")
    finally:
        await fusion.close()

    updates["candidate_paper_ids"] = list(state.candidate_paper_ids) + new_candidates
    updates["papers_discovered"] = state.papers_discovered + len(new_candidates)
    updates["errors"] = errors
    updates["messages"] = [{
        "role": "assistant",
        "content": f"Ingested {len(ingested)}/{len(seed_ids)} seed papers. {len(new_candidates)} new candidates added.",
    }]

    return updates


async def search_sources(state: GraphState) -> dict[str, Any]:
    """
    Execute pending queries against Semantic Scholar and OpenAlex.
    """
    updates: dict[str, Any] = {
        "current_step": "search_sources",
    }
    errors: list[str] = list(state.errors)

    queries_to_run = state.pending_queries[:5]  # Limit per iteration
    remaining_queries = state.pending_queries[5:]

    s2 = SemanticScholarAdapter(api_key=os.getenv("S2_API_KEY"))
    oa = OpenAlexAdapter(email=os.getenv("OPENALEX_EMAIL"))

    executed: list[str] = []
    new_candidates: list[str] = []
    seen_titles: set[str] = {_normalize_title(pid) for pid in state.candidate_paper_ids}

    try:
        for query_spec in queries_to_run:
            query_text = query_spec.get("query", "")
            if not query_text:
                continue

            executed.append(query_text)
            source = query_spec.get("source", "both")
            year = query_spec.get("year")
            fields_of_study = query_spec.get("fields_of_study")
            min_citation_count = query_spec.get("min_citation_count")

            # --- Semantic Scholar ---
            if source in ("both", "semantic_scholar"):
                try:
                    s2_params: dict[str, Any] = {"query": query_text, "limit": 50}
                    if year:
                        s2_params["year"] = year
                    if fields_of_study:
                        s2_params["fields_of_study"] = fields_of_study
                    if min_citation_count:
                        s2_params["min_citation_count"] = min_citation_count

                    s2_result = await s2.search_papers(**s2_params)
                    for paper in s2_result.get("data", []):
                        title = paper.get("title", "")
                        norm = _normalize_title(title)
                        if norm and norm not in seen_titles:
                            seen_titles.add(norm)
                            pid = paper.get("paperId", "")
                            if pid:
                                new_candidates.append(pid)

                    logger.info(
                        "search_sources.s2_done",
                        query=query_text[:60],
                        results=len(s2_result.get("data", [])),
                    )
                except Exception as exc:
                    logger.error("search_sources.s2_failed", query=query_text[:60], error=str(exc))
                    errors.append(f"S2 search failed for '{query_text[:40]}': {exc}")

            # --- OpenAlex ---
            if source in ("both", "openalex"):
                try:
                    oa_result = await oa.search_works(query=query_text, per_page=50)
                    for work in oa_result.get("results", []):
                        title = work.get("display_name") or work.get("title", "")
                        norm = _normalize_title(title)
                        if norm and norm not in seen_titles:
                            seen_titles.add(norm)
                            oa_id = work.get("id", "").split("/")[-1] if work.get("id") else ""
                            if oa_id:
                                new_candidates.append(f"OA:{oa_id}")

                    logger.info(
                        "search_sources.oa_done",
                        query=query_text[:60],
                        results=len(oa_result.get("results", [])),
                    )
                except Exception as exc:
                    logger.error("search_sources.oa_failed", query=query_text[:60], error=str(exc))
                    errors.append(f"OpenAlex search failed for '{query_text[:40]}': {exc}")
    finally:
        await s2.close()
        await oa.close()

    updates["executed_queries"] = list(state.executed_queries) + executed
    updates["pending_queries"] = remaining_queries
    updates["candidate_paper_ids"] = list(state.candidate_paper_ids) + new_candidates
    updates["papers_discovered"] = state.papers_discovered + len(new_candidates)
    updates["errors"] = errors
    updates["messages"] = [{
        "role": "assistant",
        "content": (
            f"Searched {len(executed)} queries. "
            f"Found {len(new_candidates)} new candidate papers "
            f"(total candidates: {len(state.candidate_paper_ids) + len(new_candidates)})."
        ),
    }]

    return updates


async def rank_candidates(state: GraphState) -> dict[str, Any]:
    """
    Rank candidate papers and select top-K for deep reading.

    Scoring signals: semantic, keyword, citation, impact, recency, diversity, trust, access.
    """
    updates: dict[str, Any] = {
        "current_step": "rank_candidates",
    }

    already_read = set(state.read_paper_ids)
    budget_remaining = max(0, state.max_fulltext_reads - state.papers_read)

    # Filter out already-read papers
    unread_candidates = [pid for pid in state.candidate_paper_ids if pid not in already_read]

    if not unread_candidates or budget_remaining <= 0:
        updates["selected_paper_ids"] = []
        updates["messages"] = [{
            "role": "assistant",
            "content": "No unread candidates or read budget exhausted.",
        }]
        return updates

    # ------------------------------------------------------------------
    # Score each candidate with available signals
    # ------------------------------------------------------------------
    topic_lower = state.topic.lower()
    kw_set = {kw.lower() for kw in state.keywords}
    current_year = datetime.utcnow().year

    scored: list[tuple[str, float]] = []
    for pid in unread_candidates:
        # We don't have full metadata cached in state, so use heuristic signals
        # based on what we can derive from the ID and position.
        signals: dict[str, float] = {}

        # Keyword signal: if the paper ID string hints at topical relevance
        signals["keyword"] = 0.5  # neutral baseline

        # Recency: prefer papers discovered later (likely from more refined queries)
        discovery_order = state.candidate_paper_ids.index(pid) if pid in state.candidate_paper_ids else 0
        total_candidates = max(len(state.candidate_paper_ids), 1)
        signals["recency"] = 0.3 + 0.7 * (discovery_order / total_candidates)

        # Diversity: prefer papers from underrepresented sources
        is_openalex = pid.startswith("OA:")
        s2_count = sum(1 for p in state.candidate_paper_ids if not p.startswith("OA:"))
        oa_count = sum(1 for p in state.candidate_paper_ids if p.startswith("OA:"))
        if is_openalex:
            signals["diversity"] = 0.7 if oa_count < s2_count else 0.4
        else:
            signals["diversity"] = 0.7 if s2_count < oa_count else 0.4

        # Trust: seed papers get a boost
        signals["trust"] = 0.9 if pid in state.seed_paper_ids else 0.5

        # Access: OpenAlex papers are typically OA-linked
        signals["access"] = 0.6 if is_openalex else 0.5

        # Combined weighted score
        weights = {
            "keyword": 0.20,
            "recency": 0.15,
            "diversity": 0.15,
            "trust": 0.20,
            "access": 0.10,
        }
        # Remaining weight (0.20) goes to a uniform base to avoid zero scores
        final_score = sum(signals.get(k, 0.0) * w for k, w in weights.items()) + 0.20 * 0.5

        scored.append((pid, final_score))

    # Sort descending by score
    scored.sort(key=lambda x: x[1], reverse=True)

    # Select top-K within budget
    top_k = min(budget_remaining, 5)  # max 5 per iteration
    selected = [pid for pid, _ in scored[:top_k]]

    updates["selected_paper_ids"] = selected
    updates["messages"] = [{
        "role": "assistant",
        "content": f"Ranked {len(scored)} candidates, selected {len(selected)} for deep reading.",
    }]

    return updates


async def deep_read(state: GraphState) -> dict[str, Any]:
    """
    Deep read selected papers: summarize and extract claims via LLM.
    """
    updates: dict[str, Any] = {
        "current_step": "deep_read",
    }
    errors: list[str] = list(state.errors)
    cost = state.current_cost_usd

    papers_to_read = [pid for pid in state.selected_paper_ids if pid not in state.read_paper_ids]
    if not papers_to_read:
        updates["messages"] = [{
            "role": "assistant",
            "content": "No papers selected for deep reading.",
        }]
        return updates

    gateway = get_gateway()
    fusion = ScholarFusionService(
        s2_api_key=os.getenv("S2_API_KEY"),
        openalex_email=os.getenv("OPENALEX_EMAIL"),
        crossref_email=os.getenv("CROSSREF_EMAIL"),
        unpaywall_email=os.getenv("UNPAYWALL_EMAIL"),
    )

    newly_read: list[str] = []
    summaries: list[dict[str, Any]] = []
    all_claims: list[dict[str, Any]] = []

    try:
        for pid in papers_to_read:
            try:
                # Resolve the paper to get abstract/metadata
                kwargs: dict[str, str] = {}
                if pid.startswith("OA:"):
                    kwargs["openalex_id"] = pid.removeprefix("OA:")
                elif pid.startswith("10."):
                    kwargs["doi"] = pid
                else:
                    kwargs["s2_id"] = pid

                fused = await fusion.resolve_paper(**kwargs)
                if fused is None:
                    errors.append(f"Could not resolve paper for deep read: {pid}")
                    continue

                paper_title = fused.canonical_title or pid

                # ---- Try LaTeX parsing for arXiv papers ----
                paper_text = fused.abstract or ""
                parsed_sections_text = ""
                arxiv_id = detect_arxiv_id(pid)
                if not arxiv_id and fused.doi:
                    arxiv_id = detect_arxiv_id(fused.doi)

                if arxiv_id:
                    try:
                        parsed = await parse_paper(arxiv_id)
                        if parsed.parse_quality != "low" and parsed.sections:
                            # Build rich text from LaTeX-parsed sections
                            section_texts = []
                            for sec in parsed.sections:
                                sec_header = f"## {sec.title}" if sec.title else ""
                                sec_body = "\n".join(sec.paragraphs) if sec.paragraphs else ""
                                if sec_header or sec_body:
                                    section_texts.append(f"{sec_header}\n{sec_body}")
                            parsed_sections_text = "\n\n".join(section_texts)
                            if parsed.abstract:
                                paper_text = parsed.abstract
                            if parsed.title:
                                paper_title = parsed.title
                            logger.info(
                                "deep_read.latex_parsed",
                                pid=pid,
                                sections=len(parsed.sections),
                                refs=len(parsed.references),
                            )
                    except Exception as exc:
                        logger.debug("deep_read.latex_fallback", pid=pid, error=str(exc))

                # Use parsed sections if available, otherwise abstract only
                full_paper_content = parsed_sections_text or paper_text

                # ---- Paper Summary ----
                try:
                    summary_system = get_system_prompt(PromptName.PAPER_SUMMARY)
                    summary_user = (
                        f"Paper title: {paper_title}\n"
                        f"Year: {fused.year or 'unknown'}\n"
                        f"Venue: {fused.venue or 'unknown'}\n"
                        f"{'Full paper content' if parsed_sections_text else 'Abstract'}:\n"
                        f"{full_paper_content[:12000]}\n"
                    )

                    summary_result = await gateway.chat_json(
                        messages=[
                            {"role": "system", "content": summary_system},
                            {"role": "user", "content": summary_user},
                        ],
                        tier=ModelTier.HIGH,
                        schema=PAPER_SUMMARY_SCHEMA,
                    )
                    if isinstance(summary_result, dict):
                        summary_result["paper_id"] = pid
                        summaries.append(summary_result)
                        cost += _estimate_cost(summary_result, ModelTier.HIGH) if "usage" in summary_result else 0.01

                except Exception as exc:
                    logger.error("deep_read.summary_failed", pid=pid, error=str(exc))
                    errors.append(f"Summary LLM failed for {pid}: {exc}")

                # ---- Claim Extraction ----
                try:
                    claim_system = get_system_prompt(PromptName.CLAIM_EXTRACTION)
                    claim_user = (
                        f"Paper: {paper_title}\n"
                        f"Text chunk:\n{full_paper_content[:8000]}\n"
                    )

                    claim_result = await gateway.chat_json(
                        messages=[
                            {"role": "system", "content": claim_system},
                            {"role": "user", "content": claim_user},
                        ],
                        tier=ModelTier.MEDIUM,
                        schema=CLAIM_OUTPUT_SCHEMA,
                    )
                    if isinstance(claim_result, list):
                        for claim in claim_result:
                            claim["source_paper_id"] = pid
                        all_claims.extend(claim_result)
                    elif isinstance(claim_result, dict) and "claims" in claim_result:
                        for claim in claim_result["claims"]:
                            claim["source_paper_id"] = pid
                        all_claims.extend(claim_result["claims"])

                    cost += _estimate_cost(claim_result, ModelTier.MEDIUM) if isinstance(claim_result, dict) and "usage" in claim_result else 0.003

                except Exception as exc:
                    logger.error("deep_read.claims_failed", pid=pid, error=str(exc))
                    errors.append(f"Claim extraction failed for {pid}: {exc}")

                newly_read.append(pid)
                logger.info("deep_read.paper_done", pid=pid, title=paper_title[:60])

            except Exception as exc:
                logger.error("deep_read.paper_error", pid=pid, error=str(exc))
                errors.append(f"Deep read failed for {pid}: {exc}")
    finally:
        await fusion.close()

    updates["read_paper_ids"] = list(state.read_paper_ids) + newly_read
    updates["papers_read"] = state.papers_read + len(newly_read)
    updates["current_cost_usd"] = cost
    updates["errors"] = errors
    updates["messages"] = [{
        "role": "assistant",
        "content": (
            f"Deep read {len(newly_read)} papers. "
            f"Generated {len(summaries)} summaries, extracted {len(all_claims)} claims. "
            f"Total papers read: {state.papers_read + len(newly_read)}."
        ),
    }]

    return updates


async def analyze_content(state: GraphState) -> dict[str, Any]:
    """
    Analyze read papers: clustering, contradiction detection, gap finding via LLM.
    """
    updates: dict[str, Any] = {
        "current_step": "analyze_content",
    }
    errors: list[str] = list(state.errors)
    cost = state.current_cost_usd

    gateway = get_gateway()

    # Build a text summary of what we know so far for the analysis prompts
    read_summary = (
        f"Topic: {state.topic}\n"
        f"Papers read: {state.papers_read}\n"
        f"Read paper IDs: {', '.join(state.read_paper_ids[:20])}\n"
        f"Existing clusters: {len(state.clusters)}\n"
        f"Existing contradictions: {len(state.contradictions)}\n"
        f"Existing gaps: {len(state.gaps)}\n"
        f"Keywords: {', '.join(state.keywords)}\n"
    )

    new_clusters: list[dict[str, Any]] = list(state.clusters)
    new_contradictions: list[dict[str, Any]] = list(state.contradictions)
    new_gaps: list[dict[str, Any]] = list(state.gaps)
    saturation_score = state.saturation_score

    # ---- Cluster Labeling ----
    try:
        cluster_system = get_system_prompt(PromptName.CLUSTER_LABELING)
        cluster_user = (
            f"Research context:\n{read_summary}\n"
            f"Papers read so far (IDs): {', '.join(state.read_paper_ids[:30])}\n"
            f"Please identify and label research clusters from the papers discovered.\n"
        )

        cluster_result = await gateway.chat_json(
            messages=[
                {"role": "system", "content": cluster_system},
                {"role": "user", "content": cluster_user},
            ],
            tier=ModelTier.MEDIUM,
        )
        cost += _estimate_cost(cluster_result, ModelTier.MEDIUM) if isinstance(cluster_result, dict) and "usage" in cluster_result else 0.003

        if isinstance(cluster_result, list):
            new_clusters = cluster_result
        elif isinstance(cluster_result, dict):
            if "clusters" in cluster_result:
                new_clusters = cluster_result["clusters"]
            else:
                new_clusters = [cluster_result]

        logger.info("analyze_content.clusters_done", count=len(new_clusters))
    except Exception as exc:
        logger.error("analyze_content.clustering_failed", error=str(exc))
        errors.append(f"Clustering failed: {exc}")

    # ---- Contradiction Detection ----
    try:
        contra_system = get_system_prompt(PromptName.CONTRADICTION_JUDGE)
        contra_user = (
            f"Research context:\n{read_summary}\n"
            f"Clusters found: {json.dumps(new_clusters[:5], default=str)}\n"
            f"Identify contradictions between claims in the papers.\n"
        )

        contra_result = await gateway.chat_json(
            messages=[
                {"role": "system", "content": contra_system},
                {"role": "user", "content": contra_user},
            ],
            tier=ModelTier.MEDIUM,
        )
        cost += _estimate_cost(contra_result, ModelTier.MEDIUM) if isinstance(contra_result, dict) and "usage" in contra_result else 0.003

        if isinstance(contra_result, list):
            new_contradictions = contra_result
        elif isinstance(contra_result, dict):
            if "contradictions" in contra_result:
                new_contradictions = contra_result["contradictions"]
            else:
                new_contradictions = [contra_result]

        logger.info("analyze_content.contradictions_done", count=len(new_contradictions))
    except Exception as exc:
        logger.error("analyze_content.contradiction_failed", error=str(exc))
        errors.append(f"Contradiction detection failed: {exc}")

    # ---- Gap Analysis ----
    try:
        gap_system = get_system_prompt(PromptName.GAP_ANALYSIS)
        gap_user = (
            f"Research context:\n{read_summary}\n"
            f"Clusters: {json.dumps(new_clusters[:5], default=str)}\n"
            f"Contradictions: {json.dumps(new_contradictions[:5], default=str)}\n"
            f"Identify research gaps.\n"
        )

        gap_result = await gateway.chat_json(
            messages=[
                {"role": "system", "content": gap_system},
                {"role": "user", "content": gap_user},
            ],
            tier=ModelTier.MEDIUM,
            schema=GAP_OUTPUT_SCHEMA,
        )
        cost += _estimate_cost(gap_result, ModelTier.MEDIUM) if isinstance(gap_result, dict) and "usage" in gap_result else 0.003

        if isinstance(gap_result, list):
            new_gaps = gap_result
        elif isinstance(gap_result, dict):
            if "gaps" in gap_result:
                new_gaps = gap_result["gaps"]
            else:
                new_gaps = [gap_result]

        logger.info("analyze_content.gaps_done", count=len(new_gaps))
    except Exception as exc:
        logger.error("analyze_content.gap_analysis_failed", error=str(exc))
        errors.append(f"Gap analysis failed: {exc}")

    # ---- Update saturation score ----
    # Saturation heuristic: ratio of repeated/overlapping findings across iterations
    papers_read = state.papers_read
    max_reads = max(state.max_fulltext_reads, 1)
    cluster_count = len(new_clusters)
    gap_count = len(new_gaps)

    # Simple saturation: as we read more papers, if clusters stay stable, saturation rises
    read_ratio = papers_read / max_reads
    # If we have clusters and few new gaps, we're more saturated
    if cluster_count > 0 and gap_count == 0:
        saturation_score = min(0.95, read_ratio + 0.3)
    elif cluster_count > 0:
        saturation_score = min(0.85, read_ratio + 0.1)
    else:
        saturation_score = read_ratio * 0.5

    updates["clusters"] = new_clusters
    updates["contradictions"] = new_contradictions
    updates["gaps"] = new_gaps
    updates["saturation_score"] = saturation_score
    updates["current_cost_usd"] = cost
    updates["errors"] = errors
    updates["messages"] = [{
        "role": "assistant",
        "content": (
            f"Analysis complete: {len(new_clusters)} clusters, "
            f"{len(new_contradictions)} contradictions, {len(new_gaps)} gaps. "
            f"Saturation: {saturation_score:.2f}."
        ),
    }]

    return updates


async def generate_hypotheses(state: GraphState) -> dict[str, Any]:
    """
    Generate innovation hypotheses from gaps, contradictions, and clusters.
    """
    updates: dict[str, Any] = {
        "current_step": "generate_hypotheses",
    }
    errors: list[str] = list(state.errors)
    cost = state.current_cost_usd

    gateway = get_gateway()

    try:
        innovation_system = get_system_prompt(PromptName.INNOVATION_GENERATION)
        innovation_user = (
            f"Research topic: {state.topic}\n\n"
            f"## Research Gaps\n{json.dumps(state.gaps[:10], indent=2, default=str)}\n\n"
            f"## Contradictions\n{json.dumps(state.contradictions[:10], indent=2, default=str)}\n\n"
            f"## Clusters\n{json.dumps(state.clusters[:10], indent=2, default=str)}\n\n"
            f"Papers read: {state.papers_read}\n"
            f"Generate candidate innovation hypotheses based on the above analysis.\n"
        )

        hyp_result = await gateway.chat_json(
            messages=[
                {"role": "system", "content": innovation_system},
                {"role": "user", "content": innovation_user},
            ],
            tier=ModelTier.HIGH,
            schema=INNOVATION_CARD_SCHEMA,
        )
        cost += _estimate_cost(hyp_result, ModelTier.HIGH) if isinstance(hyp_result, dict) and "usage" in hyp_result else 0.01

        new_hypotheses: list[dict[str, Any]] = []
        if isinstance(hyp_result, list):
            new_hypotheses = hyp_result
        elif isinstance(hyp_result, dict):
            if "hypotheses" in hyp_result:
                new_hypotheses = hyp_result["hypotheses"]
            else:
                # Single hypothesis returned
                new_hypotheses = [hyp_result]

        # Assign IDs to new hypotheses
        for idx, h in enumerate(new_hypotheses):
            if "id" not in h:
                h["id"] = f"hyp-{state.iteration_count}-{idx}"
            h["status"] = "pending"

        all_hypotheses = list(state.hypotheses) + new_hypotheses

        updates["hypotheses"] = all_hypotheses
        logger.info("generate_hypotheses.done", new_count=len(new_hypotheses), total=len(all_hypotheses))

    except Exception as exc:
        logger.error("generate_hypotheses.failed", error=str(exc))
        errors.append(f"Hypothesis generation failed: {exc}")

    updates["current_cost_usd"] = cost
    updates["errors"] = errors
    updates["messages"] = [{
        "role": "assistant",
        "content": f"Generated {len(updates.get('hypotheses', state.hypotheses)) - len(state.hypotheses)} new hypotheses.",
    }]

    return updates


async def verify_hypotheses(state: GraphState) -> dict[str, Any]:
    """
    Verify hypotheses with the VERIFIER prompt, updating status per hypothesis.
    """
    updates: dict[str, Any] = {
        "current_step": "verify_hypotheses",
    }
    errors: list[str] = list(state.errors)
    cost = state.current_cost_usd

    gateway = get_gateway()

    # Only verify pending hypotheses
    pending = [h for h in state.hypotheses if h.get("status") == "pending"]
    if not pending:
        updates["iteration_count"] = state.iteration_count + 1
        updates["messages"] = [{
            "role": "assistant",
            "content": "No pending hypotheses to verify.",
        }]
        return updates

    verified_ids: list[str] = list(state.verified_hypothesis_ids)
    rejected_ids: list[str] = list(state.rejected_hypothesis_ids)
    updated_hypotheses: list[dict[str, Any]] = list(state.hypotheses)

    verifier_system = get_system_prompt(PromptName.VERIFIER)

    for hyp in pending:
        hyp_id = hyp.get("id", "unknown")
        try:
            verifier_user = (
                f"Research topic: {state.topic}\n\n"
                f"## Hypothesis to Verify\n"
                f"Title: {hyp.get('title', '')}\n"
                f"Statement: {hyp.get('statement', '')}\n"
                f"Type: {hyp.get('type', '')}\n"
                f"Why now: {hyp.get('why_now', '')}\n"
                f"Novelty score: {hyp.get('novelty_score', 'N/A')}\n"
                f"Feasibility score: {hyp.get('feasibility_score', 'N/A')}\n\n"
                f"## Context\n"
                f"Papers read: {state.papers_read}\n"
                f"Clusters: {json.dumps(state.clusters[:5], default=str)}\n"
                f"Gaps: {json.dumps(state.gaps[:5], default=str)}\n"
            )

            ver_result = await gateway.chat_json(
                messages=[
                    {"role": "system", "content": verifier_system},
                    {"role": "user", "content": verifier_user},
                ],
                tier=ModelTier.HIGH,
                schema=VERIFIER_OUTPUT_SCHEMA,
            )
            cost += _estimate_cost(ver_result, ModelTier.HIGH) if isinstance(ver_result, dict) and "usage" in ver_result else 0.01

            verdict = ver_result.get("verdict", "hold") if isinstance(ver_result, dict) else "hold"
            rationale = ver_result.get("rationale", "") if isinstance(ver_result, dict) else ""

            # Find and update the hypothesis in-place (new list, immutable pattern)
            updated_hypotheses = [
                {
                    **h,
                    "status": (
                        "verified" if verdict == "finalize"
                        else "rejected" if verdict == "reject"
                        else "hold"
                    ),
                    "verification_rationale": rationale,
                    "verification_verdict": verdict,
                }
                if h.get("id") == hyp_id
                else h
                for h in updated_hypotheses
            ]

            if verdict == "finalize":
                verified_ids.append(hyp_id)
            elif verdict == "reject":
                rejected_ids.append(hyp_id)

            logger.info("verify_hypotheses.result", hyp_id=hyp_id, verdict=verdict)

        except Exception as exc:
            logger.error("verify_hypotheses.failed", hyp_id=hyp_id, error=str(exc))
            errors.append(f"Verification failed for {hyp_id}: {exc}")

    updates["hypotheses"] = updated_hypotheses
    updates["verified_hypothesis_ids"] = verified_ids
    updates["rejected_hypothesis_ids"] = rejected_ids
    updates["iteration_count"] = state.iteration_count + 1
    updates["current_cost_usd"] = cost
    updates["errors"] = errors
    updates["messages"] = [{
        "role": "assistant",
        "content": (
            f"Verified {len(pending)} hypotheses. "
            f"Finalized: {len(verified_ids) - len(state.verified_hypothesis_ids)}, "
            f"Rejected: {len(rejected_ids) - len(state.rejected_hypothesis_ids)}. "
            f"Iteration {state.iteration_count + 1}."
        ),
    }]

    return updates


async def compile_output(state: GraphState) -> dict[str, Any]:
    """
    Compile final research report via LLM.
    """
    updates: dict[str, Any] = {
        "current_step": "compile_output",
        "should_stop": True,
        "stop_reason": "completed",
    }
    errors: list[str] = list(state.errors)
    cost = state.current_cost_usd

    gateway = get_gateway()

    try:
        report_system = get_system_prompt(PromptName.REPORT_GENERATION)

        # Build comprehensive context for the report
        verified_hyps = [h for h in state.hypotheses if h.get("status") == "verified"]
        rejected_hyps = [h for h in state.hypotheses if h.get("status") == "rejected"]

        report_user = (
            f"# Research Report Request\n\n"
            f"## Topic\n{state.topic}\n\n"
            f"## Goal\n{state.goal_type}\n\n"
            f"## Statistics\n"
            f"- Papers discovered: {state.papers_discovered}\n"
            f"- Papers read in depth: {state.papers_read}\n"
            f"- Iterations: {state.iteration_count}\n"
            f"- Total cost: ${state.current_cost_usd:.2f}\n\n"
            f"## Research Clusters\n{json.dumps(state.clusters, indent=2, default=str)}\n\n"
            f"## Contradictions\n{json.dumps(state.contradictions, indent=2, default=str)}\n\n"
            f"## Research Gaps\n{json.dumps(state.gaps, indent=2, default=str)}\n\n"
            f"## Verified Hypotheses\n{json.dumps(verified_hyps, indent=2, default=str)}\n\n"
            f"## Rejected Hypotheses\n{json.dumps(rejected_hyps, indent=2, default=str)}\n\n"
            f"## Keywords\n{', '.join(state.keywords)}\n\n"
            f"Generate a comprehensive research report in Markdown format.\n"
        )

        report_result = await gateway.chat(
            messages=[
                {"role": "system", "content": report_system},
                {"role": "user", "content": report_user},
            ],
            tier=ModelTier.HIGH,
            max_tokens=8192,
        )

        cost += _estimate_cost(report_result, ModelTier.HIGH) if isinstance(report_result, dict) and "usage" in report_result else 0.02

        report_markdown = report_result.get("content", "") if isinstance(report_result, dict) else ""

        updates["report_markdown"] = report_markdown
        logger.info("compile_output.done", report_length=len(report_markdown))

    except Exception as exc:
        logger.error("compile_output.report_failed", error=str(exc))
        errors.append(f"Report generation failed: {exc}")
        # Fallback: generate a basic summary
        updates["report_markdown"] = (
            f"# Research Report: {state.topic}\n\n"
            f"*Report generation failed. Below is a summary of findings.*\n\n"
            f"## Statistics\n"
            f"- Papers discovered: {state.papers_discovered}\n"
            f"- Papers read: {state.papers_read}\n"
            f"- Iterations: {state.iteration_count}\n"
            f"- Clusters: {len(state.clusters)}\n"
            f"- Contradictions: {len(state.contradictions)}\n"
            f"- Gaps: {len(state.gaps)}\n"
            f"- Hypotheses: {len(state.hypotheses)} "
            f"({len(state.verified_hypothesis_ids)} verified, {len(state.rejected_hypothesis_ids)} rejected)\n\n"
            f"## Errors\n" + "\n".join(f"- {e}" for e in errors) + "\n"
        )

    updates["current_cost_usd"] = cost
    updates["errors"] = errors
    updates["messages"] = [{
        "role": "assistant",
        "content": f"Report compiled ({len(updates.get('report_markdown', ''))} chars).",
    }]

    return updates


def check_should_continue(state: GraphState) -> Literal["continue", "pause", "stop"]:
    """
    Check if the workflow should continue, pause, or stop.
    """
    if state.should_stop:
        return "stop"

    if state.should_pause:
        return "pause"

    # Budget checks
    if state.current_cost_usd >= state.max_cost_usd:
        return "pause"

    if state.papers_read >= state.max_fulltext_reads:
        return "pause"

    # Saturation check
    if state.saturation_score > 0.9:
        return "stop"

    # Iteration limit
    if state.iteration_count >= state.max_iterations:
        return "stop"

    return "continue"


# ============================================
# Graph Construction
# ============================================


def create_research_graph():
    """
    Create the research workflow graph.
    """
    # Create the graph
    workflow = StateGraph(GraphState)

    # Add nodes
    workflow.add_node("plan_research", plan_research)
    workflow.add_node("ingest_seeds", ingest_seeds)
    workflow.add_node("search_sources", search_sources)
    workflow.add_node("rank_candidates", rank_candidates)
    workflow.add_node("deep_read", deep_read)
    workflow.add_node("analyze_content", analyze_content)
    workflow.add_node("generate_hypotheses", generate_hypotheses)
    workflow.add_node("verify_hypotheses", verify_hypotheses)
    workflow.add_node("compile_output", compile_output)

    # Set entry point
    workflow.set_entry_point("plan_research")

    # Add edges
    workflow.add_edge("plan_research", "ingest_seeds")
    workflow.add_edge("ingest_seeds", "search_sources")
    workflow.add_edge("search_sources", "rank_candidates")

    # Conditional edge from rank_candidates
    workflow.add_conditional_edges(
        "rank_candidates",
        check_should_continue,
        {
            "continue": "deep_read",
            "pause": END,
            "stop": "compile_output",
        },
    )

    workflow.add_edge("deep_read", "analyze_content")
    workflow.add_edge("analyze_content", "generate_hypotheses")
    workflow.add_edge("generate_hypotheses", "verify_hypotheses")

    # Conditional edge from verify_hypotheses
    workflow.add_conditional_edges(
        "verify_hypotheses",
        lambda s: "continue" if check_should_continue(s) == "continue" else "stop",
        {
            "continue": "search_sources",  # Loop back for more
            "stop": "compile_output",
        },
    )

    workflow.add_edge("compile_output", END)

    return workflow


async def create_checkpointer(database_url: str | None = None):
    """
    Create a checkpointer for state persistence.
    """
    if database_url:
        # Use PostgreSQL for production
        checkpointer = PostgresSaver.from_conn_string(database_url)
        await checkpointer.setup()
        return checkpointer
    else:
        # Use in-memory for development
        return MemorySaver()


def compile_research_graph(checkpointer=None):
    """
    Compile the research graph with optional checkpointer.
    """
    workflow = create_research_graph()

    return workflow.compile(
        checkpointer=checkpointer,
        interrupt_before=[],  # Can add nodes to interrupt before
        interrupt_after=[],   # Can add nodes to interrupt after
    )


# ============================================
# Workflow Runner
# ============================================


class ResearchWorkflowRunner:
    """
    Runner for research workflows.
    """

    def __init__(self, database_url: str | None = None):
        self.database_url = database_url
        self.checkpointer = None
        self.graph = None

    async def initialize(self):
        """Initialize the workflow runner."""
        self.checkpointer = await create_checkpointer(self.database_url)
        self.graph = compile_research_graph(self.checkpointer)

    async def start_run(
        self,
        run_id: UUID,
        topic: str,
        keywords: list[str] | None = None,
        seed_paper_ids: list[str] | None = None,
        **kwargs,
    ) -> GraphState:
        """
        Start a new research run.
        """
        initial_state = GraphState(
            run_id=run_id,
            thread_id=str(run_id),
            topic=topic,
            keywords=keywords or [],
            seed_paper_ids=seed_paper_ids or [],
            **kwargs,
        )

        config = {
            "configurable": {
                "thread_id": str(run_id),
            }
        }

        # Run until first interrupt or completion
        result = await self.graph.ainvoke(
            initial_state.model_dump(),
            config=config,
        )

        return GraphState(**result)

    async def resume_run(self, run_id: UUID, patch: dict[str, Any] | None = None) -> GraphState:
        """
        Resume a paused research run.
        """
        config = {
            "configurable": {
                "thread_id": str(run_id),
            }
        }

        # Get current state
        current_state = await self.graph.aget_state(config)

        if current_state is None:
            raise ValueError(f"Run {run_id} not found")

        # Apply patch if provided
        if patch:
            # Update state with patch
            pass

        # Resume execution
        result = await self.graph.ainvoke(None, config=config)

        return GraphState(**result)

    async def get_state(self, run_id: UUID) -> GraphState | None:
        """
        Get the current state of a run.
        """
        config = {
            "configurable": {
                "thread_id": str(run_id),
            }
        }

        state = await self.graph.aget_state(config)

        if state is None:
            return None

        return GraphState(**state.values)

    async def pause_run(self, run_id: UUID) -> bool:
        """
        Request a pause for a running run.
        """
        # This sets a flag that will be checked at the next conditional edge
        config = {
            "configurable": {
                "thread_id": str(run_id),
            }
        }

        current_state = await self.graph.aget_state(config)

        if current_state is None:
            return False

        # Update state to request pause
        await self.graph.aupdate_state(
            config,
            {"should_pause": True, "pause_reason": "user_requested"},
        )

        return True
