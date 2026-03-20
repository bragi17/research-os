"""
Research OS - Frontier Mode (Mode B): Focused Gap Analysis

7-stage LangGraph StateGraph for deep sub-field analysis.
Closest to the v1 workflow -- reuses search, read, and analysis logic.
Produces comparison matrix, pain-point package, and frontier overview.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Literal

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from structlog import get_logger

from apps.worker.llm_gateway import ModelTier, get_gateway
from apps.worker.modes.base import (
    ModeGraphState,
    _estimate_cost,
    _normalize_title,
    check_should_continue,
    extract_claims,
    generate_llm_json,
    resolve_and_read_paper,
    search_academic_sources,
)
from libs.adapters.semantic_scholar import SemanticScholarAdapter
from libs.prompts.templates import (
    CLAIM_OUTPUT_SCHEMA,
    GAP_OUTPUT_SCHEMA,
    PLANNER_OUTPUT_SCHEMA,
    PromptName,
    get_schema,
    get_system_prompt,
)

logger = get_logger(__name__)

# Re-export for runner
FrontierState = ModeGraphState

# ---------------------------------------------------------------------------
# Frontier-specific system prompts (inline per task spec)
# ---------------------------------------------------------------------------

_SCOPE_SYSTEM = """\
You are a Research Scope Guard. Define precise boundaries for this sub-field.

Given a research topic, seed papers, keywords, and optional context from a
previous Atlas run, output a detailed scope definition that will constrain
all subsequent retrieval and analysis stages.

Your boundaries must be STRICT: only papers that match the venue whitelist,
address the listed benchmarks, or appear in the citation chain of seed papers
should be included.

Output MUST be valid JSON with keys:
- definition: str  (1-2 paragraph sub-field definition)
- exclusions: [str]  (explicit exclusion criteria)
- venue_whitelist: [str]  (top conferences/journals, e.g. "NeurIPS", "ACL")
- benchmark_list: [str]  (key benchmarks/datasets for this sub-field)
- query_templates: [{query: str, intent: str, source: str, min_citation_count: int|null}]
"""

_SCOPE_PRUNING_SYSTEM = """\
You are a Relevance Filter. Given paper titles/abstracts and the sub-field
definition, score each paper 0-1 for relevance.

Remove papers below 0.4. Ensure method diversity: if all remaining papers
use only one approach, flag this as a warning.

Output MUST be valid JSON with keys:
- scores: [{paper_id: str, title: str, relevance: float, keep: bool, reason: str}]
- method_groups: [{method: str, paper_ids: [str]}]
- warnings: [str]
"""

_COMPARISON_SYSTEM = """\
You are a Method Comparator. Create a structured comparison matrix from
these paper summaries.

Output MUST be valid JSON with keys:
- methods: [{name: str, problem_solved: str, key_innovation: str, \
datasets: [str], metrics: [str], results: str, limitations: str}]
- benchmark_panel: [{dataset: str, entries: [{method: str, scores: str}]}]
"""

_PAIN_MINING_SYSTEM = """\
You are a Research Pain Point Miner. From these paper summaries and
limitations, extract structured pain points.

Categorize each pain point into exactly one of these types:
- generalization: the method fails to generalize across domains/tasks
- efficiency: computational or data efficiency bottlenecks
- data_requirement: needs data that is scarce, expensive, or biased
- evaluation_gap: metrics or benchmarks are inadequate
- assumption_limitation: relies on assumptions that do not hold in practice

Output MUST be valid JSON with keys:
- pain_points: [{statement: str, pain_type: str, severity_score: float, \
novelty_potential: float, supporting_papers: [str], counter_evidence: str|null}]
- future_work: [{direction: str, motivation: str, difficulty: str, \
related_pain_ids: [int]}]
"""

_FRONTIER_SUMMARY_SYSTEM = """\
You are a Frontier Summary Agent.

Given the comparison matrix, pain points, gaps, and paper summaries,
generate a comprehensive frontier overview suitable for guiding new research.

Include:
1. Method landscape: what approaches exist, how they relate
2. Benchmark status: which benchmarks are saturated vs. open
3. Entry point suggestions: concrete starting points for new researchers
4. Pain-point package: structured data for Mode C (Divergent Innovation)

Output MUST be valid JSON with keys:
- frontier_markdown: str  (comprehensive Markdown overview with sections)
- key_findings: [str]
- method_landscape: str  (narrative summary of method families)
- benchmark_status: [{name: str, status: str, best_score: str|null}]
- entry_points: [{suggestion: str, rationale: str, difficulty: str}]
- pain_point_package: {pain_points: [...], context: str, topic: str}
- mode_c_suggestions: [{topic: str, pain_ids: [int], rationale: str}]
"""


# ---------------------------------------------------------------------------
# Node functions
# ---------------------------------------------------------------------------


async def scope_definition(state: ModeGraphState) -> dict[str, Any]:
    """Stage 1: Define sub-field boundaries, venue whitelist, constraints."""
    updates: dict[str, Any] = {"current_stage": "plan", "current_step": "scope_definition"}
    errors: list[str] = list(state.errors)
    cost = state.current_cost_usd

    gateway = get_gateway()

    # Build rich context from prior runs, seed papers, and constraints
    context_text = ""
    if state.context_bundle:
        context_text = (
            f"\nContext from previous run:\n"
            f"{json.dumps(state.context_bundle, default=str)[:3000]}\n"
        )

    seed_text = ""
    if state.seed_paper_ids:
        seed_text = (
            f"\nSeed paper IDs: {', '.join(state.seed_paper_ids[:20])}\n"
            f"Use these as anchors for citation-chain search.\n"
        )

    user_content = (
        f"Research topic: {state.topic}\n"
        f"Keywords: {', '.join(state.keywords) if state.keywords else 'none'}\n"
        f"Exclude: {', '.join(state.exclude_keywords) if state.exclude_keywords else 'none'}\n"
        f"Max papers budget: {state.max_papers}\n"
        f"{seed_text}"
        f"{context_text}"
    )

    result, delta, errs = await generate_llm_json(
        _SCOPE_SYSTEM, user_content, gateway, ModelTier.HIGH
    )
    cost += delta
    errors.extend(errs)

    # Parse scope result and build queries
    queries: list[dict[str, Any]] = []
    scope_info: dict[str, Any] = {}

    if isinstance(result, dict):
        scope_info = {
            "definition": result.get("definition", ""),
            "exclusions": result.get("exclusions", []),
            "venue_whitelist": result.get("venue_whitelist", []),
            "benchmark_list": result.get("benchmark_list", []),
        }

        for q in result.get("query_templates", []):
            queries.append({
                "query": q.get("query", ""),
                "type": q.get("intent", "primary"),
                "source": q.get("source", "both"),
                "priority": 1,
                "min_citation_count": q.get("min_citation_count"),
            })

    # Fallback queries if LLM produced none
    if not queries:
        queries.append({
            "query": state.topic,
            "type": "primary",
            "source": "both",
            "priority": 1,
        })
        for kw in state.keywords[:3]:
            queries.append({
                "query": f"{state.topic} {kw}",
                "type": "keyword",
                "source": "both",
                "priority": 2,
            })

    # Store scope info in context_bundle for downstream nodes
    context_bundle = dict(state.context_bundle) if state.context_bundle else {}
    context_bundle["scope"] = scope_info

    updates["pending_queries"] = queries
    updates["context_bundle"] = context_bundle
    updates["current_cost_usd"] = cost
    updates["errors"] = errors
    updates["messages"] = [
        {"role": "assistant", "content": (
            f"Scope defined with {len(queries)} queries. "
            f"Venues: {len(scope_info.get('venue_whitelist', []))}, "
            f"Benchmarks: {len(scope_info.get('benchmark_list', []))}."
        )}
    ]

    logger.info(
        "scope_definition.done",
        queries=len(queries),
        venues=len(scope_info.get("venue_whitelist", [])),
    )
    return updates


async def candidate_retrieval(state: ModeGraphState) -> dict[str, Any]:
    """Stage 2: Search with STRONG constraints (citation chain + benchmark + venue)."""
    updates: dict[str, Any] = {"current_stage": "search", "current_step": "candidate_retrieval"}
    errors: list[str] = list(state.errors)

    queries_to_run = state.pending_queries[:5]
    remaining = state.pending_queries[5:]

    existing_titles = {_normalize_title(pid) for pid in state.candidate_paper_ids}
    existing_ids = set(state.candidate_paper_ids)

    # --- Standard search via base.py ---
    new_candidates, executed, search_errors = await search_academic_sources(
        topic=state.topic,
        queries=queries_to_run,
        keywords=state.keywords,
        existing_titles=existing_titles,
    )
    errors.extend(search_errors)

    # --- Citation chain expansion for seed papers ---
    # Only run on the first iteration to avoid repeated expansion
    chain_candidates: list[str] = []
    if state.seed_paper_ids and state.iteration_count == 0:
        s2 = SemanticScholarAdapter(api_key=os.getenv("S2_API_KEY"))
        try:
            for seed_id in state.seed_paper_ids[:5]:
                # Skip OA/DOI identifiers for S2 citation lookup
                if seed_id.startswith("OA:") or seed_id.startswith("10."):
                    continue
                try:
                    # Fetch papers that cite this seed
                    cit_result = await s2.get_citations(
                        paper_id=seed_id,
                        limit=30,
                        fields=["paperId", "title", "year", "venue"],
                    )
                    for edge in cit_result.get("data", []):
                        citing = edge.get("citingPaper", {})
                        pid = citing.get("paperId", "")
                        title = citing.get("title", "")
                        if pid and pid not in existing_ids:
                            norm = _normalize_title(title)
                            if norm and norm not in existing_titles:
                                existing_titles.add(norm)
                                existing_ids.add(pid)
                                chain_candidates.append(pid)
                except Exception as exc:
                    logger.debug(
                        "candidate_retrieval.citations_failed",
                        seed_id=seed_id,
                        error=str(exc),
                    )

                try:
                    # Fetch papers referenced by this seed
                    ref_result = await s2.get_references(
                        paper_id=seed_id,
                        limit=30,
                        fields=["paperId", "title", "year", "venue"],
                    )
                    for edge in ref_result.get("data", []):
                        cited = edge.get("citedPaper", {})
                        pid = cited.get("paperId", "")
                        title = cited.get("title", "")
                        if pid and pid not in existing_ids:
                            norm = _normalize_title(title)
                            if norm and norm not in existing_titles:
                                existing_titles.add(norm)
                                existing_ids.add(pid)
                                chain_candidates.append(pid)
                except Exception as exc:
                    logger.debug(
                        "candidate_retrieval.references_failed",
                        seed_id=seed_id,
                        error=str(exc),
                    )
        finally:
            await s2.close()

    # --- Venue filtering ---
    # If scope defines a venue whitelist, filter candidates that we can check
    scope = state.context_bundle.get("scope", {}) if state.context_bundle else {}
    venue_whitelist = scope.get("venue_whitelist", [])
    # Note: full venue filtering requires metadata lookup; here we log intent
    # and defer strict filtering to scope_pruning where LLM evaluates relevance
    if venue_whitelist:
        logger.info(
            "candidate_retrieval.venue_whitelist_active",
            venues=venue_whitelist[:5],
        )

    all_new = new_candidates + chain_candidates
    total_discovered = state.papers_discovered + len(all_new)

    updates["candidate_paper_ids"] = list(state.candidate_paper_ids) + all_new
    updates["executed_queries"] = list(state.executed_queries) + executed
    updates["pending_queries"] = remaining
    updates["papers_discovered"] = total_discovered
    updates["iteration_count"] = state.iteration_count + 1
    updates["errors"] = errors
    updates["messages"] = [
        {"role": "assistant", "content": (
            f"Retrieved {len(new_candidates)} from search + "
            f"{len(chain_candidates)} from citation chain. "
            f"Total candidates: {len(state.candidate_paper_ids) + len(all_new)}."
        )}
    ]

    logger.info(
        "candidate_retrieval.done",
        search=len(new_candidates),
        chain=len(chain_candidates),
        total=len(state.candidate_paper_ids) + len(all_new),
    )
    return updates


async def scope_pruning(state: ModeGraphState) -> dict[str, Any]:
    """Stage 3: Remove off-topic papers via LLM relevance scoring, enforce method diversity."""
    updates: dict[str, Any] = {"current_stage": "analyze", "current_step": "scope_pruning"}
    errors: list[str] = list(state.errors)
    warnings: list[str] = list(state.warnings)
    cost = state.current_cost_usd

    gateway = get_gateway()

    all_candidates = list(state.candidate_paper_ids)

    # Extract scope info for LLM context
    scope = state.context_bundle.get("scope", {}) if state.context_bundle else {}
    definition = scope.get("definition", state.topic)
    venue_whitelist = scope.get("venue_whitelist", [])
    exclusions = scope.get("exclusions", [])

    # --- LLM-based relevance scoring (batch candidates) ---
    # Process in batches to stay within context limits
    batch_size = 30
    scored_candidates: list[tuple[str, float]] = []

    candidates_to_score = all_candidates[:120]  # Cap at 120 for cost control

    for batch_start in range(0, len(candidates_to_score), batch_size):
        batch = candidates_to_score[batch_start : batch_start + batch_size]

        paper_list_text = "\n".join(
            f"- {pid}" for pid in batch
        )

        pruning_user = (
            f"Sub-field definition: {definition}\n"
            f"Venue whitelist: {', '.join(venue_whitelist) if venue_whitelist else 'not specified'}\n"
            f"Exclusion criteria: {', '.join(exclusions) if exclusions else 'none'}\n\n"
            f"Paper IDs to evaluate:\n{paper_list_text}\n\n"
            f"Score each paper for relevance to the sub-field. "
            f"Use paper IDs as identifiers. For papers you cannot identify "
            f"by ID alone, assign a neutral score of 0.5.\n"
        )

        result, delta, errs = await generate_llm_json(
            _SCOPE_PRUNING_SYSTEM, pruning_user, gateway, ModelTier.MEDIUM
        )
        cost += delta
        errors.extend(errs)

        if isinstance(result, dict):
            scores_list = result.get("scores", [])
            method_groups = result.get("method_groups", [])
            batch_warnings = result.get("warnings", [])
            warnings.extend(batch_warnings)

            # Build a map of paper_id -> relevance
            score_map: dict[str, float] = {}
            for entry in scores_list:
                pid = entry.get("paper_id", "")
                rel = entry.get("relevance", 0.5)
                keep = entry.get("keep", rel >= 0.4)
                if pid and keep:
                    score_map[pid] = rel

            for pid in batch:
                score = score_map.get(pid, 0.5)
                if score >= 0.4:
                    scored_candidates.append((pid, score))
        else:
            # Fallback: keep all in this batch with neutral score
            for pid in batch:
                scored_candidates.append((pid, 0.5))

    # Also keep any candidates that were not scored (beyond 120 cap)
    scored_ids = {pid for pid, _ in scored_candidates}
    for pid in all_candidates[120:]:
        if pid not in scored_ids:
            scored_candidates.append((pid, 0.5))

    # Sort by relevance score descending
    scored_candidates.sort(key=lambda x: x[1], reverse=True)

    # Cap at max_papers
    max_keep = min(len(scored_candidates), state.max_papers)
    pruned = [pid for pid, _ in scored_candidates[:max_keep]]

    # Warn if too few candidates remain
    if len(pruned) < 5:
        warnings.append(
            f"Only {len(pruned)} candidates survived pruning. "
            f"Consider broadening the scope or adding seed papers."
        )

    # --- Source diversity: interleave S2 and OA papers ---
    s2_papers = [p for p in pruned if not p.startswith("OA:")]
    oa_papers = [p for p in pruned if p.startswith("OA:")]
    diverse_pruned: list[str] = []
    s2_iter = iter(s2_papers)
    oa_iter = iter(oa_papers)
    while len(diverse_pruned) < max_keep:
        added = False
        try:
            diverse_pruned.append(next(s2_iter))
            added = True
        except StopIteration:
            pass
        if len(diverse_pruned) >= max_keep:
            break
        try:
            diverse_pruned.append(next(oa_iter))
            added = True
        except StopIteration:
            pass
        if not added:
            break

    # Select top-K for deep reading
    already_read = set(state.read_paper_ids)
    budget = max(0, state.max_fulltext_reads - state.papers_read)
    to_read = [pid for pid in diverse_pruned if pid not in already_read][
        : min(budget, 10)
    ]

    updates["candidate_paper_ids"] = diverse_pruned
    updates["selected_paper_ids"] = to_read
    updates["warnings"] = warnings
    updates["current_cost_usd"] = cost
    updates["errors"] = errors
    updates["messages"] = [
        {"role": "assistant", "content": (
            f"Pruned {len(all_candidates)} to {len(diverse_pruned)} candidates "
            f"(LLM relevance filter). Selected {len(to_read)} for reading."
            + (f" Warnings: {'; '.join(warnings)}" if warnings else "")
        )}
    ]

    logger.info(
        "scope_pruning.done",
        original=len(all_candidates),
        kept=len(diverse_pruned),
        selected=len(to_read),
    )
    return updates


async def deep_reading(state: ModeGraphState) -> dict[str, Any]:
    """Stage 4: Structured reading of top-K papers with claim extraction."""
    updates: dict[str, Any] = {"current_stage": "read", "current_step": "deep_reading"}
    errors: list[str] = list(state.errors)
    cost = state.current_cost_usd

    gateway = get_gateway()

    papers_to_read = [
        pid for pid in state.selected_paper_ids if pid not in state.read_paper_ids
    ]
    if not papers_to_read:
        updates["messages"] = [
            {"role": "assistant", "content": "No papers selected for deep reading."}
        ]
        return updates

    newly_read: list[str] = []
    summaries: list[dict[str, Any]] = []
    all_claims: list[dict[str, Any]] = []

    for pid in papers_to_read:
        summary, claims, delta, read_errors = await resolve_and_read_paper(
            pid, gateway
        )
        cost += delta
        errors.extend(read_errors)

        if summary:
            newly_read.append(pid)
            summaries.append(summary)

        if claims:
            all_claims.extend(claims)

    # Store summaries in context_bundle for comparison_build and pain_mining
    context_bundle = dict(state.context_bundle) if state.context_bundle else {}
    existing_summaries = context_bundle.get("paper_summaries", [])
    context_bundle["paper_summaries"] = existing_summaries + summaries
    existing_claims = context_bundle.get("claims", [])
    context_bundle["claims"] = existing_claims + all_claims

    updates["read_paper_ids"] = list(state.read_paper_ids) + newly_read
    updates["papers_read"] = state.papers_read + len(newly_read)
    updates["current_cost_usd"] = cost
    updates["context_bundle"] = context_bundle
    updates["errors"] = errors
    updates["messages"] = [
        {"role": "assistant", "content": (
            f"Deep read {len(newly_read)} papers, extracted "
            f"{len(all_claims)} claims. Total read: "
            f"{state.papers_read + len(newly_read)}."
        )}
    ]

    logger.info(
        "deep_reading.done",
        read=len(newly_read),
        summaries=len(summaries),
        claims=len(all_claims),
    )
    return updates


async def comparison_build(state: ModeGraphState) -> dict[str, Any]:
    """Stage 5: Generate method comparison matrix and benchmark panel."""
    updates: dict[str, Any] = {
        "current_stage": "analyze",
        "current_step": "comparison_build",
    }
    errors: list[str] = list(state.errors)
    cost = state.current_cost_usd

    gateway = get_gateway()

    # Gather paper summaries from context_bundle
    summaries = (
        state.context_bundle.get("paper_summaries", [])
        if state.context_bundle
        else []
    )
    summaries_text = json.dumps(summaries[:20], default=str)[:6000]

    scope = state.context_bundle.get("scope", {}) if state.context_bundle else {}
    benchmarks = scope.get("benchmark_list", [])

    user_content = (
        f"Research topic: {state.topic}\n"
        f"Papers read: {state.papers_read}\n"
        f"Paper IDs: {', '.join(state.read_paper_ids[:30])}\n"
        f"Keywords: {', '.join(state.keywords)}\n"
        f"Benchmarks of interest: {', '.join(benchmarks) if benchmarks else 'not specified'}\n\n"
        f"## Paper Summaries\n{summaries_text}\n\n"
        f"Build a method comparison matrix with columns: method_name, "
        f"problem_solved, key_innovation, datasets, metrics, results, "
        f"limitations. Also build a benchmark panel: dataset -> method -> score.\n"
    )

    result, delta, errs = await generate_llm_json(
        _COMPARISON_SYSTEM, user_content, gateway, ModelTier.HIGH
    )
    cost += delta
    errors.extend(errs)

    matrix: list[dict[str, Any]] = []
    if isinstance(result, dict):
        methods = result.get("methods", [])
        benchmark_panel = result.get("benchmark_panel", [])
        matrix = [{
            "methods": methods,
            "benchmark_panel": benchmark_panel,
        }]
    elif isinstance(result, list):
        matrix = result

    # Also store in context_bundle for downstream
    context_bundle = dict(state.context_bundle) if state.context_bundle else {}
    context_bundle["comparison_matrix"] = matrix

    updates["comparison_matrix"] = matrix
    updates["context_bundle"] = context_bundle
    updates["current_cost_usd"] = cost
    updates["errors"] = errors
    updates["messages"] = [
        {"role": "assistant", "content": (
            f"Comparison matrix built: "
            f"{len(matrix[0].get('methods', [])) if matrix and isinstance(matrix[0], dict) else 0} methods, "
            f"{len(matrix[0].get('benchmark_panel', [])) if matrix and isinstance(matrix[0], dict) else 0} benchmarks."
        )}
    ]

    logger.info("comparison_build.done", methods=len(matrix))
    return updates


async def pain_mining(state: ModeGraphState) -> dict[str, Any]:
    """Stage 6: Extract and aggregate pain points with categorization."""
    updates: dict[str, Any] = {
        "current_stage": "analyze",
        "current_step": "pain_mining",
    }
    errors: list[str] = list(state.errors)
    cost = state.current_cost_usd

    gateway = get_gateway()

    # --- Gap analysis (reusing v1 prompt) ---
    gap_system = get_system_prompt(PromptName.GAP_ANALYSIS)
    gap_user = (
        f"Research topic: {state.topic}\n"
        f"Papers read: {state.papers_read}\n"
        f"Read paper IDs: {', '.join(state.read_paper_ids[:20])}\n"
        f"Existing clusters: {json.dumps(state.clusters[:5], default=str)}\n"
        f"Identify research gaps.\n"
    )

    gap_result, gap_delta, gap_errs = await generate_llm_json(
        gap_system, gap_user, gateway, ModelTier.MEDIUM, GAP_OUTPUT_SCHEMA
    )
    cost += gap_delta
    errors.extend(gap_errs)

    new_gaps: list[dict[str, Any]] = []
    if isinstance(gap_result, list):
        new_gaps = gap_result
    elif isinstance(gap_result, dict) and "gaps" in gap_result:
        new_gaps = gap_result["gaps"]

    # --- Pain point mining with categorized types ---
    summaries = (
        state.context_bundle.get("paper_summaries", [])
        if state.context_bundle
        else []
    )
    summaries_text = json.dumps(summaries[:15], default=str)[:4000]

    pain_user = (
        f"Research topic: {state.topic}\n"
        f"Papers read: {state.papers_read}\n"
        f"Read paper IDs: {', '.join(state.read_paper_ids[:20])}\n\n"
        f"## Paper Summaries\n{summaries_text}\n\n"
        f"## Gaps Found\n{json.dumps(new_gaps[:10], default=str)}\n\n"
        f"## Comparison Matrix\n{json.dumps(state.comparison_matrix[:2], default=str)[:2000]}\n\n"
        f"Extract pain points categorized as: generalization, efficiency, "
        f"data_requirement, evaluation_gap, assumption_limitation.\n"
        f"Score severity (0-1) and novelty potential (0-1).\n"
        f"Also identify future work directions.\n"
    )

    pain_result, pain_delta, pain_errs = await generate_llm_json(
        _PAIN_MINING_SYSTEM, pain_user, gateway, ModelTier.HIGH
    )
    cost += pain_delta
    errors.extend(pain_errs)

    pain_points: list[dict[str, Any]] = []
    future_work: list[dict[str, Any]] = []

    if isinstance(pain_result, dict):
        raw_pains = pain_result.get("pain_points", [])
        if isinstance(raw_pains, list):
            pain_points = raw_pains
        future_work = pain_result.get("future_work", [])
    elif isinstance(pain_result, list):
        pain_points = pain_result

    # Validate pain_type categories
    valid_types = {
        "generalization",
        "efficiency",
        "data_requirement",
        "evaluation_gap",
        "assumption_limitation",
        # Also accept v1 types gracefully
        "limitation",
        "scalability",
        "data_gap",
        "theory_gap",
    }
    for pp in pain_points:
        if pp.get("pain_type") not in valid_types:
            pp["pain_type"] = "generalization"
        # Ensure scores are floats in [0, 1]
        for key in ("severity_score", "novelty_potential"):
            val = pp.get(key, 0.5)
            try:
                pp[key] = max(0.0, min(1.0, float(val)))
            except (TypeError, ValueError):
                pp[key] = 0.5

    # Store future_work in context_bundle
    context_bundle = dict(state.context_bundle) if state.context_bundle else {}
    context_bundle["future_work"] = future_work
    context_bundle["pain_points"] = pain_points

    # --- Saturation heuristic ---
    papers_read = state.papers_read
    max_reads = max(state.max_fulltext_reads, 1)
    read_ratio = papers_read / max_reads
    gap_count = len(new_gaps)

    if gap_count == 0 and papers_read > 5:
        saturation = min(0.95, read_ratio + 0.3)
    elif gap_count > 0:
        saturation = min(0.85, read_ratio + 0.1)
    else:
        saturation = read_ratio * 0.5

    updates["gaps"] = new_gaps
    updates["pain_points"] = pain_points
    updates["context_bundle"] = context_bundle
    updates["saturation_score"] = saturation
    updates["current_cost_usd"] = cost
    updates["errors"] = errors
    updates["messages"] = [
        {"role": "assistant", "content": (
            f"Mined {len(pain_points)} pain points "
            f"({', '.join(set(pp.get('pain_type', '?') for pp in pain_points))}), "
            f"{len(new_gaps)} gaps, {len(future_work)} future work items. "
            f"Saturation: {saturation:.2f}."
        )}
    ]

    logger.info(
        "pain_mining.done",
        pains=len(pain_points),
        gaps=len(new_gaps),
        future_work=len(future_work),
        saturation=saturation,
    )
    return updates


async def frontier_summary(state: ModeGraphState) -> dict[str, Any]:
    """Stage 7: Generate frontier overview + pain-point package for Mode C."""
    updates: dict[str, Any] = {
        "current_stage": "output",
        "current_step": "frontier_summary",
        "should_stop": True,
        "stop_reason": "completed",
    }
    errors: list[str] = list(state.errors)
    cost = state.current_cost_usd

    gateway = get_gateway()

    # Gather all context for the summary
    summaries = (
        state.context_bundle.get("paper_summaries", [])
        if state.context_bundle
        else []
    )
    future_work = (
        state.context_bundle.get("future_work", [])
        if state.context_bundle
        else []
    )
    scope = state.context_bundle.get("scope", {}) if state.context_bundle else {}

    user_content = (
        f"Research topic: {state.topic}\n\n"
        f"## Scope Definition\n{json.dumps(scope, default=str)[:1000]}\n\n"
        f"## Comparison Matrix\n{json.dumps(state.comparison_matrix[:3], default=str)[:2000]}\n\n"
        f"## Pain Points ({len(state.pain_points)})\n"
        f"{json.dumps(state.pain_points[:15], default=str)[:3000]}\n\n"
        f"## Gaps ({len(state.gaps)})\n{json.dumps(state.gaps[:10], default=str)}\n\n"
        f"## Future Work Directions\n{json.dumps(future_work[:10], default=str)}\n\n"
        f"## Paper Summaries (sample)\n{json.dumps(summaries[:5], default=str)[:2000]}\n\n"
        f"## Statistics\n"
        f"Papers discovered: {state.papers_discovered}\n"
        f"Papers read: {state.papers_read}\n"
        f"Cost: ${state.current_cost_usd:.2f}\n\n"
        f"Generate a comprehensive frontier summary including method landscape, "
        f"benchmark status, entry points for new researchers, and a pain-point "
        f"package for Mode C.\n"
    )

    result, delta, errs = await generate_llm_json(
        _FRONTIER_SUMMARY_SYSTEM, user_content, gateway, ModelTier.HIGH
    )
    cost += delta
    errors.extend(errs)

    if isinstance(result, dict):
        frontier_md = result.get("frontier_markdown", "")
        key_findings = result.get("key_findings", [])
        method_landscape = result.get("method_landscape", "")
        benchmark_status = result.get("benchmark_status", [])
        entry_points = result.get("entry_points", [])
        pain_point_package = result.get("pain_point_package", {})
        mode_c_suggestions = result.get("mode_c_suggestions", [])

        # Ensure pain_point_package has required fields
        if not isinstance(pain_point_package, dict):
            pain_point_package = {}
        pain_point_package.setdefault("pain_points", state.pain_points)
        pain_point_package.setdefault("context", method_landscape)
        pain_point_package.setdefault("topic", state.topic)

        updates["report_markdown"] = frontier_md

        # Build comprehensive context_bundle for Mode C consumption
        updates["context_bundle"] = {
            "source_mode": "frontier",
            "topic": state.topic,
            "scope": scope,
            "pain_point_package": pain_point_package,
            "mode_c_suggestions": mode_c_suggestions,
            "comparison_matrix": state.comparison_matrix,
            "benchmark_status": benchmark_status,
            "entry_points": entry_points,
            "gaps": state.gaps,
            "key_findings": key_findings,
            "method_landscape": method_landscape,
            "future_work": future_work,
            "papers_discovered": state.papers_discovered,
            "papers_read": state.papers_read,
        }
    else:
        # Fallback report
        updates["report_markdown"] = (
            f"# Frontier Analysis: {state.topic}\n\n"
            f"## Overview\n"
            f"Papers discovered: {state.papers_discovered}\n"
            f"Papers read in depth: {state.papers_read}\n\n"
            f"## Pain Points ({len(state.pain_points)})\n"
            + "\n".join(
                f"- [{pp.get('pain_type', '?')}] {pp.get('statement', 'N/A')} "
                f"(severity: {pp.get('severity_score', '?')}, "
                f"novelty: {pp.get('novelty_potential', '?')})"
                for pp in state.pain_points[:10]
            )
            + f"\n\n## Gaps ({len(state.gaps)})\n"
            + "\n".join(
                f"- {g.get('description', g.get('gap', 'N/A'))}"
                for g in state.gaps[:10]
            )
            + "\n"
        )
        updates["context_bundle"] = {
            "source_mode": "frontier",
            "topic": state.topic,
            "pain_point_package": {
                "pain_points": state.pain_points,
                "context": state.topic,
                "topic": state.topic,
            },
            "comparison_matrix": state.comparison_matrix,
            "gaps": state.gaps,
        }

    updates["current_cost_usd"] = cost
    updates["errors"] = errors
    updates["messages"] = [
        {"role": "assistant", "content": (
            f"Frontier summary compiled "
            f"({len(updates.get('report_markdown', ''))} chars). "
            f"Pain-point package ready for Mode C."
        )}
    ]

    logger.info(
        "frontier_summary.done",
        report_len=len(updates.get("report_markdown", "")),
    )
    return updates


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------


def create_frontier_graph() -> StateGraph:
    """Create the 7-stage Frontier (Mode B) LangGraph StateGraph."""
    workflow = StateGraph(ModeGraphState)

    workflow.add_node("scope_definition", scope_definition)
    workflow.add_node("candidate_retrieval", candidate_retrieval)
    workflow.add_node("scope_pruning", scope_pruning)
    workflow.add_node("deep_reading", deep_reading)
    workflow.add_node("comparison_build", comparison_build)
    workflow.add_node("pain_mining", pain_mining)
    workflow.add_node("frontier_summary", frontier_summary)

    workflow.set_entry_point("scope_definition")

    workflow.add_edge("scope_definition", "candidate_retrieval")

    # Check after retrieval
    workflow.add_conditional_edges(
        "candidate_retrieval",
        check_should_continue,
        {
            "continue": "scope_pruning",
            "pause": END,
            "stop": "frontier_summary",
        },
    )

    workflow.add_edge("scope_pruning", "deep_reading")

    # Check after deep reading
    workflow.add_conditional_edges(
        "deep_reading",
        check_should_continue,
        {
            "continue": "comparison_build",
            "pause": END,
            "stop": "frontier_summary",
        },
    )

    workflow.add_edge("comparison_build", "pain_mining")

    # Check after pain mining -- can loop back for more reading
    workflow.add_conditional_edges(
        "pain_mining",
        lambda s: (
            "continue"
            if check_should_continue(s) == "continue"
            and s.iteration_count < s.max_iterations
            else "stop"
        ),
        {
            "continue": "candidate_retrieval",
            "stop": "frontier_summary",
        },
    )

    workflow.add_edge("frontier_summary", END)

    return workflow


def compile_frontier_graph(checkpointer=None):
    """Compile the Frontier graph with an optional checkpointer."""
    workflow = create_frontier_graph()
    return workflow.compile(checkpointer=checkpointer or MemorySaver())
