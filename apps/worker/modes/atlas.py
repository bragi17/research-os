"""
Research OS - Atlas Mode (Mode A): Field Onboarding

8-stage LangGraph StateGraph for newcomers to a research field.
Produces a one-page atlas, taxonomy, reading path, and mind map.
"""

from __future__ import annotations

import json
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

logger = get_logger(__name__)

# Re-export the state for the runner
AtlasState = ModeGraphState

# ---------------------------------------------------------------------------
# System prompts specific to Atlas mode
# ---------------------------------------------------------------------------

_ATLAS_PLAN_SYSTEM = """\
You are a Research Atlas Planning Agent.

Given a research topic, identify:
1. The domain boundaries (what is in scope vs. out of scope)
2. Key sub-directions within the field
3. Aliases and alternate names for the domain
4. Foundational concepts a newcomer must understand
5. Retrieval plan: queries for classic (highly-cited) papers, recent surveys, \
and pedagogical resources

Output MUST be valid JSON with keys:
- domain_boundaries: {in_scope: [str], out_of_scope: [str]}
- sub_directions: [{name: str, description: str}]
- aliases: [str]  (alternate names for the domain)
- foundational_concepts: [str]
- queries: [{query: str, intent: "classical"|"recent"|"pedagogical"|"survey", \
source: "both"|"semantic_scholar"|"openalex", min_citation_count: int|null}]
"""

_TIMELINE_SYSTEM = """\
You are a Research Timeline Curator. Given a list of papers with years and \
citation counts, construct a research timeline showing the evolution of this \
field.

Output MUST be valid JSON with key "timeline": an array of objects with keys:
- year: int
- title: str
- paper_id: str
- significance: str  (1-2 sentences explaining why this is a milestone)
- phase: "foundational" | "growth" | "current_frontier"

Order chronologically. Include at least one entry per phase. The "foundational" \
phase covers seminal works, "growth" covers the period of rapid adoption and \
method diversification, and "current_frontier" covers the most recent advances.
"""

_TAXONOMY_SYSTEM = """\
You are a Research Taxonomy Builder. Given papers in a research field, generate \
classification views: by_method, by_task, by_modality. Each view is a tree with \
{label, children, representative_papers}.

Output MUST be valid JSON with keys:
- root_label: str  (the field name)
- views: {
    by_method: {label: str, children: [{label: str, description: str, \
representative_papers: [str], children: [...]}]},
    by_task: {label: str, children: [{label: str, description: str, \
representative_papers: [str], children: [...]}]},
    by_modality: {label: str, children: [{label: str, description: str, \
representative_papers: [str], children: [...]}]}
  }
- classification_dimensions: ["by_method", "by_task", "by_modality"]
- mindmap: {center: str, branches: [{label: str, children: [{label: str}]}]}
"""

_READING_PATH_SYSTEM = """\
You are a Research Pedagogy Advisor. Generate a structured reading path for a \
beginner entering this field. Order papers from foundational to advanced.

Output MUST be valid JSON with keys:
- learning_goals: [{phase: "foundation"|"intermediate"|"advanced", \
goals: [str]}]
- reading_path: array of {
    paper_id: str,
    paper_title: str,
    reason: str  (why read this paper at this point),
    difficulty: "beginner" | "intermediate" | "advanced",
    suggested_week: int  (1-4),
    prerequisites: [str]  (paper_ids that should be read first)
  }
"""

_ATLAS_SYNTHESIS_SYSTEM = """\
You are a Research Atlas Synthesis Agent.

Given the taxonomy, timeline, reading path, and paper summaries, generate:
1. A one-page atlas overview in Markdown with sections: Domain Overview, \
Timeline, Taxonomy, Key Papers, and Recommended Reading Path
2. A mind map JSON structure for frontend rendering
3. Suggested entry points for Mode B (Focused Gap Analysis)

Output MUST be valid JSON with keys:
- atlas_markdown: str  (Markdown with sections: ## Domain Overview, \
## Timeline, ## Taxonomy, ## Key Papers, ## Reading Path)
- mindmap: {center: str, branches: [{label: str, children: [{label: str}]}]}
- mode_b_entry_points: [{topic: str, reason: str, keywords: [str]}]
"""


# ---------------------------------------------------------------------------
# Node functions
# ---------------------------------------------------------------------------


async def plan_atlas(state: ModeGraphState) -> dict[str, Any]:
    """Stage 1: Identify domain boundaries, sub-directions, plan retrieval.

    Uses the PLANNER prompt to decompose the domain into boundaries,
    sub-directions, aliases, and generates search queries for classical,
    recent, and pedagogical papers.
    """
    updates: dict[str, Any] = {"current_stage": "plan", "current_step": "plan_atlas"}
    errors: list[str] = list(state.errors)
    cost = state.current_cost_usd

    try:
        gateway = get_gateway()

        user_content = (
            f"Research topic: {state.topic}\n"
            f"Keywords: {', '.join(state.keywords) if state.keywords else 'none'}\n"
            f"Exclude: {', '.join(state.exclude_keywords) if state.exclude_keywords else 'none'}\n"
        )

        result, delta, errs = await generate_llm_json(
            _ATLAS_PLAN_SYSTEM, user_content, gateway, ModelTier.HIGH
        )
        cost += delta
        errors.extend(errs)

        queries: list[dict[str, Any]] = []
        context_bundle = dict(state.context_bundle)

        if isinstance(result, dict):
            # Extract queries from LLM response
            for q in result.get("queries", []):
                queries.append({
                    "query": q.get("query", ""),
                    "type": q.get("intent", "primary"),
                    "source": q.get("source", "both"),
                    "priority": 1,
                    "min_citation_count": q.get("min_citation_count"),
                })

            # Store domain info
            updates["domain_id"] = json.dumps(result.get("domain_boundaries", {}))

            # Persist sub-directions, aliases, and foundational concepts
            # in context_bundle for downstream nodes
            context_bundle["sub_directions"] = result.get("sub_directions", [])
            context_bundle["aliases"] = result.get("aliases", [])
            context_bundle["foundational_concepts"] = result.get(
                "foundational_concepts", []
            )
            context_bundle["domain_boundaries"] = result.get(
                "domain_boundaries", {}
            )

        updates["context_bundle"] = context_bundle

        # Fallback queries when LLM returns none
        if not queries:
            queries.append({
                "query": state.topic,
                "type": "classical",
                "source": "both",
                "priority": 1,
                "min_citation_count": 100,
            })
            queries.append({
                "query": f"{state.topic} survey",
                "type": "survey",
                "source": "both",
                "priority": 1,
            })
            queries.append({
                "query": f"{state.topic} recent advances",
                "type": "recent",
                "source": "both",
                "priority": 2,
            })

        updates["pending_queries"] = queries
        updates["current_cost_usd"] = cost
        updates["errors"] = errors
        updates["messages"] = [
            {
                "role": "assistant",
                "content": f"Atlas plan created with {len(queries)} queries.",
            }
        ]

        logger.info("plan_atlas.done", queries=len(queries))

    except Exception as exc:
        logger.error("plan_atlas.error", error=str(exc))
        errors.append(f"plan_atlas failed: {exc}")
        # Provide minimal fallback queries so the pipeline can continue
        updates["pending_queries"] = [
            {"query": state.topic, "type": "primary", "source": "both", "priority": 1},
            {"query": f"{state.topic} survey", "type": "survey", "source": "both", "priority": 1},
        ]
        updates["current_cost_usd"] = cost
        updates["errors"] = errors
        updates["messages"] = [
            {"role": "assistant", "content": "Atlas plan created with fallback queries (LLM error)."}
        ]

    return updates


async def retrieve_classics(state: ModeGraphState) -> dict[str, Any]:
    """Stage 2: Search S2 + OpenAlex for high-citation foundational papers.

    Searches for classical highly-cited papers and recent (3-5 year)
    representative papers. Deduplicates results by normalized title.
    """
    updates: dict[str, Any] = {"current_stage": "search", "current_step": "retrieve_classics"}
    errors: list[str] = list(state.errors)

    try:
        # Process up to 6 queries per batch
        queries_to_run = list(state.pending_queries[:6])
        remaining = list(state.pending_queries[6:])

        # Ensure we have queries targeting high-citation classics
        has_classical = any(
            q.get("type") in ("classical", "primary") for q in queries_to_run
        )
        if not has_classical and state.topic:
            queries_to_run.insert(0, {
                "query": state.topic,
                "type": "classical",
                "source": "both",
                "priority": 1,
                "min_citation_count": 50,
            })

        # Ensure we have queries targeting recent papers (3-5 years)
        has_recent = any(q.get("type") == "recent" for q in queries_to_run)
        if not has_recent and state.topic:
            queries_to_run.append({
                "query": f"{state.topic} 2022 2023 2024 2025",
                "type": "recent",
                "source": "both",
                "priority": 2,
            })

        existing_titles = {_normalize_title(pid) for pid in state.candidate_paper_ids}

        new_candidates, executed, search_errors = await search_academic_sources(
            topic=state.topic,
            queries=queries_to_run,
            keywords=state.keywords,
            existing_titles=existing_titles,
        )
        errors.extend(search_errors)

        # Deduplicate new candidates by normalized title against existing
        deduped_candidates: list[str] = []
        seen_titles = set(existing_titles)
        for pid in new_candidates:
            norm = _normalize_title(pid)
            if norm not in seen_titles:
                seen_titles.add(norm)
                deduped_candidates.append(pid)

        updates["candidate_paper_ids"] = list(state.candidate_paper_ids) + deduped_candidates
        updates["executed_queries"] = list(state.executed_queries) + executed
        updates["pending_queries"] = remaining
        updates["papers_discovered"] = state.papers_discovered + len(deduped_candidates)
        updates["errors"] = errors
        updates["messages"] = [
            {
                "role": "assistant",
                "content": (
                    f"Retrieved {len(deduped_candidates)} classic/representative papers "
                    f"({len(executed)} queries executed, {len(remaining)} remaining)."
                ),
            }
        ]

        logger.info(
            "retrieve_classics.done",
            new=len(deduped_candidates),
            executed=len(executed),
            remaining=len(remaining),
        )

    except Exception as exc:
        logger.error("retrieve_classics.error", error=str(exc))
        errors.append(f"retrieve_classics failed: {exc}")
        updates["errors"] = errors
        updates["messages"] = [
            {"role": "assistant", "content": f"Retrieval encountered an error: {exc}"}
        ]

    return updates


async def build_timeline(state: ModeGraphState) -> dict[str, Any]:
    """Stage 3: Construct research timeline with phases.

    Calls LLM to generate a timeline with foundational, growth, and
    current_frontier phases based on discovered paper IDs.
    """
    updates: dict[str, Any] = {"current_stage": "analyze", "current_step": "build_timeline"}
    errors: list[str] = list(state.errors)
    cost = state.current_cost_usd

    try:
        gateway = get_gateway()

        paper_list_text = "\n".join(
            f"- {pid}" for pid in state.candidate_paper_ids[:50]
        )

        # Include domain context from planning stage if available
        domain_context = ""
        sub_directions = state.context_bundle.get("sub_directions", [])
        if sub_directions:
            direction_names = [d.get("name", "") for d in sub_directions if isinstance(d, dict)]
            domain_context = f"Sub-directions: {', '.join(direction_names)}\n"

        user_content = (
            f"Research topic: {state.topic}\n"
            f"{domain_context}"
            f"Candidate papers (IDs):\n{paper_list_text}\n\n"
            f"Build a research timeline for the field with phases: "
            f"foundational, growth, current_frontier.\n"
        )

        result, delta, errs = await generate_llm_json(
            _TIMELINE_SYSTEM, user_content, gateway, ModelTier.MEDIUM
        )
        cost += delta
        errors.extend(errs)

        timeline: list[dict[str, Any]] = []
        if isinstance(result, list):
            timeline = result
        elif isinstance(result, dict):
            # Handle both {timeline: [...]} and direct array
            timeline = result.get("timeline", [])

        # Ensure each entry has the required phase field
        for entry in timeline:
            if "phase" not in entry:
                year = entry.get("year", 0)
                if isinstance(year, int):
                    if year < 2015:
                        entry["phase"] = "foundational"
                    elif year < 2022:
                        entry["phase"] = "growth"
                    else:
                        entry["phase"] = "current_frontier"
                else:
                    entry["phase"] = "growth"

        updates["timeline_data"] = timeline
        updates["current_cost_usd"] = cost
        updates["errors"] = errors
        updates["messages"] = [
            {
                "role": "assistant",
                "content": f"Built timeline with {len(timeline)} entries.",
            }
        ]

        logger.info("build_timeline.done", entries=len(timeline))

    except Exception as exc:
        logger.error("build_timeline.error", error=str(exc))
        errors.append(f"build_timeline failed: {exc}")
        updates["timeline_data"] = []
        updates["current_cost_usd"] = cost
        updates["errors"] = errors
        updates["messages"] = [
            {"role": "assistant", "content": f"Timeline build failed: {exc}"}
        ]

    return updates


async def build_taxonomy(state: ModeGraphState) -> dict[str, Any]:
    """Stage 4: Generate 2-3 classification tree views (by method, task, modality).

    Calls LLM to produce a multi-view taxonomy and a mindmap JSON for
    frontend rendering.
    """
    updates: dict[str, Any] = {"current_stage": "analyze", "current_step": "build_taxonomy"}
    errors: list[str] = list(state.errors)
    cost = state.current_cost_usd

    try:
        gateway = get_gateway()

        # Build rich context for taxonomy generation
        timeline_summary = json.dumps(state.timeline_data[:20], default=str)
        paper_ids_text = ", ".join(state.candidate_paper_ids[:30])

        # Include sub-directions if available
        sub_dir_text = ""
        sub_directions = state.context_bundle.get("sub_directions", [])
        if sub_directions:
            sub_dir_text = f"Sub-directions:\n{json.dumps(sub_directions, default=str)}\n"

        user_content = (
            f"Research topic: {state.topic}\n"
            f"{sub_dir_text}"
            f"Timeline entries: {timeline_summary}\n"
            f"Candidate paper IDs: {paper_ids_text}\n\n"
            f"Generate a hierarchical taxonomy with views: by_method, by_task, "
            f"by_modality. Also produce a mindmap JSON for visualization.\n"
        )

        result, delta, errs = await generate_llm_json(
            _TAXONOMY_SYSTEM, user_content, gateway, ModelTier.HIGH
        )
        cost += delta
        errors.extend(errs)

        taxonomy: dict[str, Any] = {}
        mindmap: dict[str, Any] = {}

        if isinstance(result, dict):
            taxonomy = result
            # Extract mindmap from taxonomy result (LLM generates it inline)
            mindmap = result.get("mindmap", {})

            # If LLM did not produce a mindmap, construct one from taxonomy views
            if not mindmap and result.get("views"):
                branches: list[dict[str, Any]] = []
                for view_key in ("by_method", "by_task", "by_modality"):
                    view = result.get("views", {}).get(view_key, {})
                    if isinstance(view, dict) and view.get("children"):
                        branch_children = [
                            {"label": child.get("label", "unknown")}
                            for child in view["children"]
                            if isinstance(child, dict)
                        ]
                        branches.append({
                            "label": view.get("label", view_key),
                            "children": branch_children,
                        })
                mindmap = {
                    "center": result.get("root_label", state.topic),
                    "branches": branches,
                }

        updates["taxonomy_tree"] = taxonomy
        updates["mindmap_json"] = mindmap
        updates["current_cost_usd"] = cost
        updates["errors"] = errors
        updates["messages"] = [
            {
                "role": "assistant",
                "content": f"Taxonomy built: {taxonomy.get('root_label', 'unknown')}.",
            }
        ]

        logger.info(
            "build_taxonomy.done",
            root=taxonomy.get("root_label", "n/a"),
            has_mindmap=bool(mindmap),
        )

    except Exception as exc:
        logger.error("build_taxonomy.error", error=str(exc))
        errors.append(f"build_taxonomy failed: {exc}")
        updates["taxonomy_tree"] = {}
        updates["mindmap_json"] = {}
        updates["current_cost_usd"] = cost
        updates["errors"] = errors
        updates["messages"] = [
            {"role": "assistant", "content": f"Taxonomy build failed: {exc}"}
        ]

    return updates


async def read_representatives(state: ModeGraphState) -> dict[str, Any]:
    """Stage 5: Deep read 1-3 papers per taxonomy branch.

    Uses resolve_and_read_paper() from base.py for each selected paper.
    Extracts: problem, method, innovation, datasets, limitations.
    Tracks cost throughout.
    """
    updates: dict[str, Any] = {"current_stage": "read", "current_step": "read_representatives"}
    errors: list[str] = list(state.errors)
    cost = state.current_cost_usd

    try:
        gateway = get_gateway()

        # Select representative papers (up to budget)
        already_read = set(state.read_paper_ids)
        budget = max(0, state.max_fulltext_reads - state.papers_read)

        # Prioritize papers that appear in taxonomy branches
        branch_paper_ids: list[str] = []
        views = state.taxonomy_tree.get("views", {})
        for view_key in ("by_method", "by_task", "by_modality"):
            view = views.get(view_key, {})
            if isinstance(view, dict):
                _collect_branch_papers(view, branch_paper_ids)

        # Deduplicate while preserving order; branch papers first
        ordered_candidates: list[str] = []
        seen: set[str] = set()
        for pid in branch_paper_ids:
            if pid not in seen and pid not in already_read:
                seen.add(pid)
                ordered_candidates.append(pid)
        for pid in state.candidate_paper_ids:
            if pid not in seen and pid not in already_read:
                seen.add(pid)
                ordered_candidates.append(pid)

        to_read = ordered_candidates[: min(budget, 8)]

        newly_read: list[str] = []
        summaries: list[dict[str, Any]] = []

        for pid in to_read:
            try:
                summary, claims, delta, read_errors = await resolve_and_read_paper(
                    pid, gateway
                )
                cost += delta
                errors.extend(read_errors)
                if summary:
                    # Ensure structured fields are present
                    enriched = {
                        "paper_id": pid,
                        "problem": summary.get("problem", "unknown"),
                        "method": summary.get("method", "unknown"),
                        "innovation": summary.get(
                            "innovation",
                            summary.get("reusable_components", "unknown"),
                        ),
                        "datasets": (
                            summary.get("experimental_setup", {}).get("datasets", [])
                            if isinstance(summary.get("experimental_setup"), dict)
                            else []
                        ),
                        "limitations": summary.get("limitations", []),
                        "title": summary.get("title", pid),
                        "year": summary.get("year"),
                        "venue": summary.get("venue"),
                    }
                    summaries.append(enriched)
                    newly_read.append(pid)
            except Exception as read_exc:
                logger.error(
                    "read_representatives.paper_error",
                    pid=pid,
                    error=str(read_exc),
                )
                errors.append(f"Failed to read paper {pid}: {read_exc}")

        # Store summaries in context_bundle for downstream use
        context_bundle = dict(state.context_bundle)
        existing_summaries = context_bundle.get("paper_summaries", [])
        context_bundle["paper_summaries"] = existing_summaries + summaries
        updates["context_bundle"] = context_bundle

        updates["read_paper_ids"] = list(state.read_paper_ids) + newly_read
        updates["papers_read"] = state.papers_read + len(newly_read)
        updates["current_cost_usd"] = cost
        updates["errors"] = errors
        updates["messages"] = [
            {
                "role": "assistant",
                "content": (
                    f"Read {len(newly_read)} representative papers. "
                    f"Extracted structured summaries for each."
                ),
            }
        ]

        logger.info(
            "read_representatives.done",
            read=len(newly_read),
            total_cost=round(cost, 4),
        )

    except Exception as exc:
        logger.error("read_representatives.error", error=str(exc))
        errors.append(f"read_representatives failed: {exc}")
        updates["current_cost_usd"] = cost
        updates["errors"] = errors
        updates["messages"] = [
            {"role": "assistant", "content": f"Reading representatives failed: {exc}"}
        ]

    return updates


def _collect_branch_papers(
    node: dict[str, Any], out: list[str]
) -> None:
    """Recursively collect representative_papers from taxonomy tree nodes."""
    if not isinstance(node, dict):
        return
    for pid in node.get("representative_papers", []):
        if isinstance(pid, str) and pid:
            out.append(pid)
    for pid in node.get("paper_ids", []):
        if isinstance(pid, str) and pid:
            out.append(pid)
    for child in node.get("children", []):
        _collect_branch_papers(child, out)


async def extract_figures(state: ModeGraphState) -> dict[str, Any]:
    """Stage 6: Extract key figures from representative papers (placeholder).

    Figure extraction is not yet implemented. This node logs the pending
    status and tracks which papers need figure extraction for future
    processing.
    """
    updates: dict[str, Any] = {"current_stage": "analyze", "current_step": "extract_figures"}
    errors: list[str] = list(state.errors)

    try:
        # Track paper IDs that have been read for future figure extraction
        existing_figure_pids = {
            f.get("paper_id") for f in state.figures if isinstance(f, dict)
        }
        figures: list[dict[str, Any]] = list(state.figures)

        for pid in state.read_paper_ids:
            if pid not in existing_figure_pids:
                figures.append({
                    "paper_id": pid,
                    "figure_ids": [],
                    "status": "pending",
                    "note": "Figure extraction not yet implemented",
                })

        updates["figures"] = figures
        updates["errors"] = errors
        updates["messages"] = [
            {
                "role": "assistant",
                "content": (
                    f"Tracked {len(state.read_paper_ids)} papers for figure "
                    f"extraction (pending implementation)."
                ),
            }
        ]

        logger.info(
            "extract_figures.pending",
            papers_tracked=len(state.read_paper_ids),
            total_figures=len(figures),
        )

    except Exception as exc:
        logger.error("extract_figures.error", error=str(exc))
        errors.append(f"extract_figures failed: {exc}")
        updates["errors"] = errors
        updates["messages"] = [
            {"role": "assistant", "content": f"Figure extraction tracking failed: {exc}"}
        ]

    return updates


async def generate_reading_path(state: ModeGraphState) -> dict[str, Any]:
    """Stage 7: Create ordered learning path with difficulty and weekly schedule.

    Uses timeline, taxonomy, and representative paper summaries to generate
    an ordered reading path with prerequisites and learning goals per phase.
    """
    updates: dict[str, Any] = {
        "current_stage": "synthesize",
        "current_step": "generate_reading_path",
    }
    errors: list[str] = list(state.errors)
    cost = state.current_cost_usd

    try:
        gateway = get_gateway()

        # Build rich context for reading path generation
        taxonomy_text = json.dumps(state.taxonomy_tree, default=str)[:4000]
        timeline_text = json.dumps(state.timeline_data[:15], default=str)

        # Include paper summaries if available
        summaries = state.context_bundle.get("paper_summaries", [])
        summaries_text = ""
        if summaries:
            brief_summaries = [
                {
                    "paper_id": s.get("paper_id", ""),
                    "title": s.get("title", ""),
                    "problem": s.get("problem", "")[:200],
                    "method": s.get("method", "")[:200],
                }
                for s in summaries[:15]
            ]
            summaries_text = f"Paper summaries:\n{json.dumps(brief_summaries, default=str)}\n"

        user_content = (
            f"Research topic: {state.topic}\n"
            f"Taxonomy: {taxonomy_text}\n"
            f"Timeline: {timeline_text}\n"
            f"{summaries_text}"
            f"Papers read: {', '.join(state.read_paper_ids[:20])}\n\n"
            f"Create an ordered reading path for a newcomer with learning goals "
            f"per phase and a weekly schedule (weeks 1-4).\n"
        )

        result, delta, errs = await generate_llm_json(
            _READING_PATH_SYSTEM, user_content, gateway, ModelTier.MEDIUM
        )
        cost += delta
        errors.extend(errs)

        reading_path: list[dict[str, Any]] = []
        learning_goals: list[dict[str, Any]] = []

        if isinstance(result, list):
            reading_path = result
        elif isinstance(result, dict):
            reading_path = result.get("reading_path", [])
            learning_goals = result.get("learning_goals", [])

        # Ensure each entry has suggested_week and prerequisites
        for entry in reading_path:
            if "suggested_week" not in entry:
                difficulty = entry.get("difficulty", "intermediate")
                if difficulty == "beginner":
                    entry["suggested_week"] = 1
                elif difficulty == "intermediate":
                    entry["suggested_week"] = 2
                else:
                    entry["suggested_week"] = 3
            if "prerequisites" not in entry:
                entry["prerequisites"] = []

        # Store learning goals in context_bundle
        if learning_goals:
            context_bundle = dict(state.context_bundle)
            context_bundle["learning_goals"] = learning_goals
            updates["context_bundle"] = context_bundle

        updates["reading_path"] = reading_path
        updates["current_cost_usd"] = cost
        updates["errors"] = errors
        updates["messages"] = [
            {
                "role": "assistant",
                "content": f"Generated reading path with {len(reading_path)} entries.",
            }
        ]

        logger.info("generate_reading_path.done", entries=len(reading_path))

    except Exception as exc:
        logger.error("generate_reading_path.error", error=str(exc))
        errors.append(f"generate_reading_path failed: {exc}")
        updates["reading_path"] = []
        updates["current_cost_usd"] = cost
        updates["errors"] = errors
        updates["messages"] = [
            {"role": "assistant", "content": f"Reading path generation failed: {exc}"}
        ]

    return updates


async def synthesize_atlas(state: ModeGraphState) -> dict[str, Any]:
    """Stage 8: Generate final atlas output.

    Calls LLM with atlas-specific synthesis prompt to produce:
    - report_markdown: atlas format with domain overview, timeline, taxonomy,
      key papers, and reading path
    - mindmap_json: for frontend rendering
    - context_bundle: for potential Mode B continuation
    Sets should_stop = True.
    """
    updates: dict[str, Any] = {
        "current_stage": "output",
        "current_step": "synthesize_atlas",
        "should_stop": True,
        "stop_reason": "completed",
    }
    errors: list[str] = list(state.errors)
    cost = state.current_cost_usd

    try:
        gateway = get_gateway()

        # Build comprehensive context for synthesis
        taxonomy_text = json.dumps(state.taxonomy_tree, default=str)[:3000]
        timeline_text = json.dumps(state.timeline_data[:15], default=str)
        reading_path_text = json.dumps(state.reading_path[:15], default=str)

        # Include paper summaries for richer synthesis
        summaries = state.context_bundle.get("paper_summaries", [])
        summaries_text = ""
        if summaries:
            brief = [
                {
                    "title": s.get("title", ""),
                    "problem": s.get("problem", "")[:150],
                    "method": s.get("method", "")[:150],
                    "year": s.get("year"),
                }
                for s in summaries[:10]
            ]
            summaries_text = f"## Paper Summaries\n{json.dumps(brief, default=str)}\n\n"

        # Include domain context
        domain_context = ""
        foundational_concepts = state.context_bundle.get("foundational_concepts", [])
        if foundational_concepts:
            domain_context = (
                f"Foundational concepts: {', '.join(foundational_concepts)}\n"
            )

        user_content = (
            f"Research topic: {state.topic}\n"
            f"{domain_context}\n"
            f"## Taxonomy\n{taxonomy_text}\n\n"
            f"## Timeline\n{timeline_text}\n\n"
            f"## Reading Path\n{reading_path_text}\n\n"
            f"{summaries_text}"
            f"Papers read: {state.papers_read}\n"
            f"Papers discovered: {state.papers_discovered}\n\n"
            f"Generate the atlas synthesis with sections: Domain Overview, "
            f"Timeline, Taxonomy, Key Papers, and Reading Path.\n"
        )

        result, delta, errs = await generate_llm_json(
            _ATLAS_SYNTHESIS_SYSTEM, user_content, gateway, ModelTier.HIGH
        )
        cost += delta
        errors.extend(errs)

        if isinstance(result, dict):
            updates["report_markdown"] = result.get("atlas_markdown", "")
            updates["mindmap_json"] = result.get("mindmap", state.mindmap_json)

            # Build context_bundle for Mode B continuation
            context_bundle = {
                "source_mode": "atlas",
                "topic": state.topic,
                "mode_b_entry_points": result.get("mode_b_entry_points", []),
                "taxonomy": state.taxonomy_tree,
                "reading_path": state.reading_path,
                "timeline": state.timeline_data,
                "papers_discovered": state.papers_discovered,
                "papers_read": state.papers_read,
                "read_paper_ids": list(state.read_paper_ids),
                "candidate_paper_ids": list(state.candidate_paper_ids),
                "paper_summaries": state.context_bundle.get("paper_summaries", []),
                "foundational_concepts": state.context_bundle.get(
                    "foundational_concepts", []
                ),
                "sub_directions": state.context_bundle.get("sub_directions", []),
            }
            updates["context_bundle"] = context_bundle
        else:
            # Fallback when LLM fails to produce structured output
            updates["report_markdown"] = (
                f"# Atlas: {state.topic}\n\n"
                f"Papers discovered: {state.papers_discovered}\n"
                f"Papers read: {state.papers_read}\n\n"
                f"## Timeline\n"
                f"{_format_timeline_fallback(state.timeline_data)}\n\n"
                f"## Reading Path\n"
                f"{_format_reading_path_fallback(state.reading_path)}\n"
            )

        updates["current_cost_usd"] = cost
        updates["errors"] = errors
        updates["messages"] = [
            {
                "role": "assistant",
                "content": (
                    f"Atlas synthesized "
                    f"({len(updates.get('report_markdown', ''))} chars)."
                ),
            }
        ]

        logger.info(
            "synthesize_atlas.done",
            report_len=len(updates.get("report_markdown", "")),
        )

    except Exception as exc:
        logger.error("synthesize_atlas.error", error=str(exc))
        errors.append(f"synthesize_atlas failed: {exc}")
        updates["report_markdown"] = (
            f"# Atlas: {state.topic}\n\n"
            f"Synthesis failed: {exc}\n\n"
            f"Papers discovered: {state.papers_discovered}\n"
            f"Papers read: {state.papers_read}\n"
        )
        updates["current_cost_usd"] = cost
        updates["errors"] = errors
        updates["messages"] = [
            {"role": "assistant", "content": f"Atlas synthesis failed: {exc}"}
        ]

    return updates


def _format_timeline_fallback(
    timeline: list[dict[str, Any]],
) -> str:
    """Format timeline data as Markdown when LLM synthesis fails."""
    if not timeline:
        return "No timeline data available."
    lines: list[str] = []
    for entry in timeline[:20]:
        year = entry.get("year", "?")
        title = entry.get("title", "Unknown")
        phase = entry.get("phase", "")
        sig = entry.get("significance", "")
        phase_tag = f" [{phase}]" if phase else ""
        lines.append(f"- **{year}**{phase_tag}: {title} — {sig}")
    return "\n".join(lines)


def _format_reading_path_fallback(
    reading_path: list[dict[str, Any]],
) -> str:
    """Format reading path as Markdown when LLM synthesis fails."""
    if not reading_path:
        return "No reading path available."
    lines: list[str] = []
    for entry in reading_path[:20]:
        title = entry.get("paper_title", entry.get("title", "Unknown"))
        difficulty = entry.get("difficulty", "?")
        week = entry.get("suggested_week", "?")
        reason = entry.get("reason", "")
        lines.append(f"- **Week {week}** ({difficulty}): {title} — {reason}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------


def create_atlas_graph() -> StateGraph:
    """Create the 8-stage Atlas (Mode A) LangGraph StateGraph."""
    workflow = StateGraph(ModeGraphState)

    # Add nodes
    workflow.add_node("plan_atlas", plan_atlas)
    workflow.add_node("retrieve_classics", retrieve_classics)
    workflow.add_node("build_timeline", build_timeline)
    workflow.add_node("build_taxonomy", build_taxonomy)
    workflow.add_node("read_representatives", read_representatives)
    workflow.add_node("extract_figures", extract_figures)
    workflow.add_node("generate_reading_path", generate_reading_path)
    workflow.add_node("synthesize_atlas", synthesize_atlas)

    # Entry point
    workflow.set_entry_point("plan_atlas")

    # Edges
    workflow.add_edge("plan_atlas", "retrieve_classics")

    # Conditional after retrieval — check budget/pause
    workflow.add_conditional_edges(
        "retrieve_classics",
        check_should_continue,
        {
            "continue": "build_timeline",
            "pause": END,
            "stop": "synthesize_atlas",
        },
    )

    workflow.add_edge("build_timeline", "build_taxonomy")
    workflow.add_edge("build_taxonomy", "read_representatives")

    # Conditional after reading — check budget
    workflow.add_conditional_edges(
        "read_representatives",
        check_should_continue,
        {
            "continue": "extract_figures",
            "pause": END,
            "stop": "synthesize_atlas",
        },
    )

    workflow.add_edge("extract_figures", "generate_reading_path")
    workflow.add_edge("generate_reading_path", "synthesize_atlas")
    workflow.add_edge("synthesize_atlas", END)

    return workflow


def compile_atlas_graph(checkpointer=None):
    """Compile the Atlas graph with an optional checkpointer."""
    workflow = create_atlas_graph()
    return workflow.compile(checkpointer=checkpointer or MemorySaver())
