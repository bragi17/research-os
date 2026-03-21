"""
Research OS - Shared Mode Graph Utilities

Shared state definition, helper functions, and reusable node logic
extracted from the v1 graph_state.py for use across all mode-specific graphs.
"""

from __future__ import annotations

import json
import os
import re
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from langgraph.graph import END
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field
from structlog import get_logger

from apps.worker.llm_gateway import LLMGateway, ModelTier, get_gateway
from libs.adapters.openalex import OpenAlexAdapter
from libs.adapters.semantic_scholar import SemanticScholarAdapter
from libs.adapters.scholar_fusion import ScholarFusionService
from libs.prompts.templates import (
    CLAIM_OUTPUT_SCHEMA,
    PAPER_SUMMARY_SCHEMA,
    PromptName,
    get_system_prompt,
)
from services.parser import detect_arxiv_id, parse_paper

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Cost estimation
# ---------------------------------------------------------------------------

_COST_PER_1K_INPUT = {
    ModelTier.HIGH: 0.005,
    ModelTier.MEDIUM: 0.00015,
    ModelTier.LOW: 0.00008,
}
_COST_PER_1K_OUTPUT = {
    ModelTier.HIGH: 0.015,
    ModelTier.MEDIUM: 0.0006,
    ModelTier.LOW: 0.0004,
}


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


# ---------------------------------------------------------------------------
# Title normalization
# ---------------------------------------------------------------------------


def _normalize_title(title: str) -> str:
    """Normalize a paper title for deduplication."""
    if not title:
        return ""
    normalized = title.lower()
    normalized = "".join(c if c.isalnum() or c.isspace() else " " for c in normalized)
    return " ".join(normalized.split())


# ---------------------------------------------------------------------------
# Progress event emitter — writes fine-grained actions to run_event table
# ---------------------------------------------------------------------------


async def emit_progress(
    run_id: UUID | str,
    stage: str,
    action: str,
    detail: str = "",
    severity: str = "info",
    meta: dict[str, Any] | None = None,
) -> None:
    """
    Emit a fine-grained progress event to the database.

    Examples:
        emit_progress(run_id, "candidate_retrieval", "searching",
                      "Querying Semantic Scholar for '3D anomaly detection'")
        emit_progress(run_id, "candidate_retrieval", "result",
                      "Found 50 papers from Semantic Scholar")
        emit_progress(run_id, "deep_reading", "reading",
                      "Reading paper: 'PointAD: A Framework for...'")
    """
    try:
        from apps.api.database import create_event
        payload: dict[str, Any] = {
            "stage": stage,
            "action": action,
            "message": detail,
        }
        if meta:
            payload.update(meta)
        await create_event(
            run_id=run_id if isinstance(run_id, UUID) else UUID(str(run_id)),
            event_type=f"progress.{stage}.{action}",
            severity=severity,
            payload=payload,
        )
    except Exception as exc:
        logger.debug("emit_progress_failed", error=str(exc))


# ---------------------------------------------------------------------------
# Shared ModeGraphState
# ---------------------------------------------------------------------------


class ModeGraphState(BaseModel):
    """
    Shared state for all mode-specific LangGraph workflows.

    Extends the v1 GraphState with v2 fields for multi-mode support.
    """

    # Core identification
    run_id: UUID = Field(default_factory=uuid4)
    thread_id: str = ""
    mode: str = "atlas"
    current_stage: str = "plan"

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

    # Messages (for LLM interactions — accepts AIMessage, HumanMessage, or dicts)
    messages: Annotated[list[Any], add_messages] = Field(
        default_factory=list
    )

    # Outputs
    report_markdown: str = ""
    export_urls: list[str] = Field(default_factory=list)

    # Errors and warnings
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    # ---- V2 additions ----
    domain_id: str | None = None
    pain_points: list[dict[str, Any]] = Field(default_factory=list)
    idea_cards: list[dict[str, Any]] = Field(default_factory=list)
    timeline_data: list[dict[str, Any]] = Field(default_factory=list)
    taxonomy_tree: dict[str, Any] = Field(default_factory=dict)
    reading_path: list[dict[str, Any]] = Field(default_factory=list)
    comparison_matrix: list[dict[str, Any]] = Field(default_factory=list)
    context_bundle: dict[str, Any] = Field(default_factory=dict)
    mindmap_json: dict[str, Any] = Field(default_factory=dict)
    figures: list[dict[str, Any]] = Field(default_factory=list)

    class Config:
        arbitrary_types_allowed = True


# ---------------------------------------------------------------------------
# Shared conditional edge: check_should_continue
# ---------------------------------------------------------------------------


def check_should_continue(
    state: ModeGraphState,
) -> Literal["continue", "pause", "stop"]:
    """Determine whether the graph should continue, pause, or stop."""
    if state.should_stop:
        return "stop"
    if state.should_pause:
        return "pause"
    # max_cost check removed — we display token usage instead of limiting
    if state.papers_read >= state.max_fulltext_reads:
        return "pause"
    if state.saturation_score > 0.9:
        return "stop"
    if state.iteration_count >= state.max_iterations:
        return "stop"
    return "continue"


# ---------------------------------------------------------------------------
# Shared reusable async helpers
# ---------------------------------------------------------------------------


async def search_academic_sources(
    topic: str,
    queries: list[dict[str, Any]],
    keywords: list[str] | None = None,
    existing_titles: set[str] | None = None,
) -> tuple[list[str], list[str], list[str], dict[str, str]]:
    """
    Unified search across Semantic Scholar and OpenAlex.

    Returns:
        (new_candidate_ids, executed_query_texts, error_messages, id_to_title_map)
    """
    s2 = SemanticScholarAdapter(api_key=os.getenv("S2_API_KEY"))
    oa = OpenAlexAdapter(email=os.getenv("OPENALEX_EMAIL"))

    executed: list[str] = []
    new_candidates: list[str] = []
    errors: list[str] = []
    id_to_title: dict[str, str] = {}
    seen_titles: set[str] = set(existing_titles or set())

    try:
        for query_spec in queries:
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
                                id_to_title[pid] = title

                    logger.info(
                        "search_academic.s2_done",
                        query=query_text[:60],
                        results=len(s2_result.get("data", [])),
                    )
                except Exception as exc:
                    logger.error(
                        "search_academic.s2_failed",
                        query=query_text[:60],
                        error=str(exc),
                    )
                    errors.append(f"S2 search failed for '{query_text[:40]}': {exc}")

            # --- OpenAlex ---
            if source in ("both", "openalex"):
                try:
                    oa_result = await oa.search_works(query=query_text, per_page=50)
                    for work in oa_result.get("results", []):
                        title = (
                            work.get("display_name") or work.get("title", "")
                        )
                        norm = _normalize_title(title)
                        if norm and norm not in seen_titles:
                            seen_titles.add(norm)
                            oa_id = (
                                work.get("id", "").split("/")[-1]
                                if work.get("id")
                                else ""
                            )
                            if oa_id:
                                new_candidates.append(f"OA:{oa_id}")
                                id_to_title[f"OA:{oa_id}"] = title

                    logger.info(
                        "search_academic.oa_done",
                        query=query_text[:60],
                        results=len(oa_result.get("results", [])),
                    )
                except Exception as exc:
                    logger.error(
                        "search_academic.oa_failed",
                        query=query_text[:60],
                        error=str(exc),
                    )
                    errors.append(
                        f"OpenAlex search failed for '{query_text[:40]}': {exc}"
                    )
    finally:
        await s2.close()
        await oa.close()

    return new_candidates, executed, errors, id_to_title


async def resolve_and_read_paper(
    pid: str,
    gateway: LLMGateway,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], float, list[str]]:
    """
    Resolve paper metadata, parse LaTeX/GROBID if available, summarize via LLM,
    and extract claims.

    Returns:
        (summary_dict | None, claims_list, cost_delta, error_messages)
    """
    errors: list[str] = []
    cost = 0.0

    fusion = ScholarFusionService(
        s2_api_key=os.getenv("S2_API_KEY"),
        openalex_email=os.getenv("OPENALEX_EMAIL"),
        crossref_email=os.getenv("CROSSREF_EMAIL"),
        unpaywall_email=os.getenv("UNPAYWALL_EMAIL"),
    )

    summary: dict[str, Any] | None = None
    claims: list[dict[str, Any]] = []

    try:
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
            return None, [], cost, errors

        paper_title = fused.canonical_title or pid
        paper_text = fused.abstract or ""
        parsed_sections_text = ""

        # Try to find arXiv ID from multiple sources (LaTeX parsing priority)
        arxiv_id = detect_arxiv_id(pid)
        if not arxiv_id:
            arxiv_id = getattr(fused, "arxiv_id", None)
        if not arxiv_id:
            fused_doi = getattr(fused, "doi", None)
            if fused_doi:
                arxiv_id = detect_arxiv_id(fused_doi)
        if not arxiv_id:
            # Try extracting from S2 externalIds
            ext_ids = getattr(fused, "external_ids", None) or {}
            if isinstance(ext_ids, dict) and ext_ids.get("ArXiv"):
                arxiv_id = str(ext_ids["ArXiv"])

        if arxiv_id:
            try:
                parsed = await parse_paper(arxiv_id)
                if parsed.parse_quality != "low" and parsed.sections:
                    section_texts = []
                    for sec in parsed.sections:
                        sec_header = f"## {sec.title}" if sec.title else ""
                        sec_body = (
                            "\n".join(sec.paragraphs) if sec.paragraphs else ""
                        )
                        if sec_header or sec_body:
                            section_texts.append(f"{sec_header}\n{sec_body}")
                    parsed_sections_text = "\n\n".join(section_texts)
                    if parsed.abstract:
                        paper_text = parsed.abstract
                    if parsed.title:
                        paper_title = parsed.title
                    logger.info(
                        "resolve_and_read.latex_parsed",
                        pid=pid,
                        sections=len(parsed.sections),
                    )
            except Exception as exc:
                logger.debug(
                    "resolve_and_read.latex_fallback", pid=pid, error=str(exc)
                )

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
                summary_result["title"] = paper_title
                summary_result["year"] = fused.year
                summary_result["venue"] = fused.venue
                summary = summary_result
                cost += (
                    _estimate_cost(summary_result, ModelTier.HIGH)
                    if "usage" in summary_result
                    else 0.01
                )
        except Exception as exc:
            logger.error(
                "resolve_and_read.summary_failed", pid=pid, error=str(exc)
            )
            errors.append(f"Summary LLM failed for {pid}: {exc}")

        # ---- Claim Extraction ----
        claims, claim_cost, claim_errors = await extract_claims(
            paper_title, full_paper_content, gateway
        )
        cost += claim_cost
        for c in claims:
            c["source_paper_id"] = pid
        errors.extend(claim_errors)

        # ── Paper Tagging (Level 1) ──
        try:
            from apps.worker.agents.paper_tag_agent import PaperTagAgent
            tag_agent = PaperTagAgent(gateway=gateway)
            tag_result = await tag_agent.run(
                paper_text=full_paper_content,
                metadata={
                    "title": paper_title,
                    "year": getattr(fused, "year", None),
                    "venue": getattr(fused, "venue", None),
                },
            )
            if summary and isinstance(summary, dict):
                summary["paper_tags"] = tag_result.model_dump()
        except Exception as exc:
            logger.debug("paper_tag_skipped", pid=pid, error=str(exc))

        logger.info(
            "resolve_and_read.done", pid=pid, title=paper_title[:60]
        )
    except Exception as exc:
        logger.error("resolve_and_read.error", pid=pid, error=str(exc))
        errors.append(f"Resolve/read failed for {pid}: {exc}")
    finally:
        await fusion.close()

    return summary, claims, cost, errors


async def extract_claims(
    paper_title: str,
    paper_text: str,
    gateway: LLMGateway,
) -> tuple[list[dict[str, Any]], float, list[str]]:
    """
    Extract structured claims from paper text via LLM.

    Returns:
        (claims_list, cost_delta, error_messages)
    """
    cost = 0.0
    errors: list[str] = []
    all_claims: list[dict[str, Any]] = []

    try:
        claim_system = get_system_prompt(PromptName.CLAIM_EXTRACTION)
        claim_user = (
            f"Paper: {paper_title}\nText chunk:\n{paper_text[:8000]}\n"
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
            all_claims.extend(claim_result)
        elif isinstance(claim_result, dict) and "claims" in claim_result:
            all_claims.extend(claim_result["claims"])

        cost += (
            _estimate_cost(claim_result, ModelTier.MEDIUM)
            if isinstance(claim_result, dict) and "usage" in claim_result
            else 0.003
        )
    except Exception as exc:
        logger.error(
            "extract_claims.failed", title=paper_title[:60], error=str(exc)
        )
        errors.append(f"Claim extraction failed for {paper_title[:40]}: {exc}")

    return all_claims, cost, errors


async def generate_llm_json(
    system_prompt: str,
    user_content: str,
    gateway: LLMGateway,
    tier: ModelTier = ModelTier.MEDIUM,
    schema: dict[str, Any] | None = None,
) -> tuple[dict[str, Any] | list, float, list[str]]:
    """
    Wrapper for gateway.chat_json with standardised error handling.

    Returns:
        (parsed_result, cost_delta, error_messages)
    """
    cost = 0.0
    errors: list[str] = []

    try:
        result = await gateway.chat_json(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            tier=tier,
            schema=schema,
        )
        cost += (
            _estimate_cost(result, tier)
            if isinstance(result, dict) and "usage" in result
            else 0.005
        )
        return result, cost, errors
    except Exception as exc:
        logger.error("generate_llm_json.failed", error=str(exc))
        errors.append(f"LLM JSON call failed: {exc}")
        return {}, cost, errors


async def rerank_search_results(
    query: str,
    paper_titles: list[str],
    paper_ids: list[str],
    top_n: int = 50,
) -> list[str]:
    """
    Rerank paper candidates by relevance using Tongyi gte-rerank-v2.

    Args:
        query: The research topic or search query.
        paper_titles: Parallel list of paper titles to score.
        paper_ids: Parallel list of paper IDs (same order as titles).
        top_n: Maximum number of results to return.

    Returns:
        Reranked list of paper IDs (most relevant first).
        Falls back to original order on failure.
    """
    from services.embedding import get_embedding_service

    if not paper_titles:
        return paper_ids

    try:
        svc = get_embedding_service()
        results = await svc.rerank(
            query=query,
            documents=paper_titles,
            top_n=top_n,
        )
        reranked_ids = [
            paper_ids[r["index"]]
            for r in results
            if r["index"] < len(paper_ids)
        ]
        return reranked_ids
    except Exception as exc:
        logger.warning("rerank_failed_using_original_order", error=str(exc))
        return paper_ids


def _create_fusion_service() -> ScholarFusionService:
    """Create a ScholarFusionService with env-based credentials."""
    return ScholarFusionService(
        s2_api_key=os.getenv("S2_API_KEY"),
        openalex_email=os.getenv("OPENALEX_EMAIL"),
        crossref_email=os.getenv("CROSSREF_EMAIL"),
        unpaywall_email=os.getenv("UNPAYWALL_EMAIL"),
    )
