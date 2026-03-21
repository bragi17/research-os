"""
Research OS - Divergent Mode (Mode C): Cross-Domain Innovation

7-stage LangGraph StateGraph for generating novel research ideas
by borrowing methods from other domains.
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
    _normalize_title,
    check_should_continue,
    generate_llm_json,
    search_academic_sources,
)
from libs.prompts.templates import PromptName, get_system_prompt

logger = get_logger(__name__)

# Re-export for runner
DivergentState = ModeGraphState

# ---------------------------------------------------------------------------
# Divergent-specific system prompts
# ---------------------------------------------------------------------------

_NORMALIZE_PAIN_SYSTEM = """\
You are a Problem Abstraction Agent. For each pain point, generate a \
problem signature that abstracts away domain-specific details to enable \
cross-domain matching.

For EACH pain point, produce a problem signature with these keys:
- task: the abstract task type (e.g. "classification", "segmentation", "ranking")
- input_modality: what kind of data is consumed (e.g. "image", "text", "tabular", "graph")
- label_regime: supervision model (e.g. "fully supervised", "semi-supervised", "self-supervised", "unsupervised")
- failure_modes: list of documented or expected failure modes
- objective: the high-level optimisation target
- constraints: practical constraints (data size, latency, compute, privacy, etc.)
- abstract_keywords: domain-agnostic keywords suitable for cross-domain search

Output MUST be valid JSON with keys:
- problem_signatures: [{
    original_statement: str,
    task: str,
    input_modality: str,
    label_regime: str,
    failure_modes: [str],
    objective: str,
    constraints: [str],
    abstract_keywords: [str]
  }]
- domain_context: str
"""

_ANALOGICAL_RETRIEVAL_SYSTEM = """\
You are a Cross-Domain Analogical Search Agent.

Given problem signatures (already abstracted from their original domain), \
generate search queries that look for similar problems and solutions in \
OTHER domains. IMPORTANT: do NOT include the original sub-field keywords. \
Instead, focus on:
- Similar data conditions (modality, scale, noise profile)
- Similar supervision settings (label regime, annotation cost)
- Similar evaluation targets (metrics, objectives)

The goal is to find methods from distant fields that solved structurally \
similar problems.

Output MUST be valid JSON with keys:
- queries: [{query: str, target_domain: str, source: str, intent: str}]
- search_strategy: str
"""

_METHOD_TRANSFER_SYSTEM = """\
You are a Method Transfer Evaluator. For each candidate method from an \
external domain, assess its transfer potential to the target research area.

For EACH method, produce an object with:
- external_method: str (name of the method)
- source_domain: str (domain the method originates from)
- target_pain_point: str (which pain point it addresses)
- core_mechanism: str (the fundamental algorithmic / conceptual mechanism)
- transfer_feasibility: float (0-1, likelihood of successful transfer)
- failed_assumptions: [str] (assumptions of the original method that would NOT hold in the target domain)
- required_modifications: [str] (modules or components that need replacement/adaptation)
- rationale: str

Output MUST be valid JSON: an array of these objects.
"""

_FEASIBILITY_SYSTEM = """\
You are a Research Feasibility Reviewer. For each innovation idea, assess \
practical feasibility along concrete dimensions.

For EACH idea, produce an object with:
- idea_title: str
- data_available: bool (can the required data be obtained?)
- compute_reasonable: bool (can experiments run on typical academic hardware?)
- experiment_designable: bool (is there a clear experimental protocol?)
- estimated_weeks: int (estimated calendar weeks for a first experiment)
- critical_risks: [str] (top risks that could block execution)
- overall_feasibility: float (0-1)
- go_no_go: "go" | "conditional" | "no_go"
- rationale: str

Output MUST be valid JSON: an array of these objects.
"""

_IDEA_PORTFOLIO_SYSTEM = """\
You are a Research Idea Portfolio Manager.

Given feasibility-assessed idea cards with novelty, feasibility, and evidence \
scores, produce a final portfolio recommendation.

Output MUST be valid JSON with keys:
- ranked_ideas: [{
    rank: int,
    title: str,
    composite_score: float,
    novelty: float,
    feasibility: float,
    evidence: float,
    impact_potential: str,
    one_line_pitch: str
  }]
- portfolio_summary: str
- recommended_next_steps: [str]
"""

# Maximum number of failed assumptions before filtering out a transfer candidate
_MAX_FAILED_ASSUMPTIONS = 3


# ---------------------------------------------------------------------------
# Node functions
# ---------------------------------------------------------------------------


async def normalize_pain_package(state: ModeGraphState) -> dict[str, Any]:
    """Stage 1: Read pain-point package from context bundle, generate problem signatures."""
    updates: dict[str, Any] = {"current_stage": "plan", "current_step": "normalize_pain_package"}
    errors: list[str] = list(state.errors)
    cost = state.current_cost_usd

    gateway = get_gateway()

    pain_package = state.context_bundle.get("pain_point_package", {})
    pain_points_raw = state.pain_points or pain_package.get("pain_points", [])

    user_content = (
        f"Research topic: {state.topic}\n"
        f"Pain points:\n{json.dumps(pain_points_raw[:15], default=str)}\n"
        f"Context: {pain_package.get('context', '')}\n"
    )

    result, delta, errs = await generate_llm_json(
        _NORMALIZE_PAIN_SYSTEM, user_content, gateway, ModelTier.HIGH
    )
    cost += delta
    errors.extend(errs)

    signatures: list[dict[str, Any]] = []
    if isinstance(result, dict):
        signatures = result.get("problem_signatures", [])

    # Enrich pain_points with their signatures for downstream consumption
    enriched_pain_points: list[dict[str, Any]] = []
    for idx, pp in enumerate(pain_points_raw[:15]):
        sig = signatures[idx] if idx < len(signatures) else {}
        if isinstance(pp, dict):
            enriched = {**pp, "signature": sig}
        else:
            enriched = {"statement": str(pp), "signature": sig}
        enriched_pain_points.append(enriched)

    # Store signatures and enriched pain points in context_bundle
    updated_bundle = dict(state.context_bundle)
    updated_bundle["problem_signatures"] = signatures
    updated_bundle["domain_context"] = (
        result.get("domain_context", "") if isinstance(result, dict) else ""
    )

    updates["pain_points"] = enriched_pain_points
    updates["context_bundle"] = updated_bundle
    updates["current_cost_usd"] = cost
    updates["errors"] = errors
    updates["messages"] = [
        {"role": "assistant", "content": f"Normalized {len(signatures)} problem signatures."}
    ]

    logger.info("normalize_pain_package.done", signatures=len(signatures))
    return updates


async def analogical_retrieval(state: ModeGraphState) -> dict[str, Any]:
    """Stage 2: Search OTHER domains for similar problems using abstract signatures.

    Intentionally omits original sub-field keywords to enable cross-domain discovery.
    Focuses on similar data conditions, supervision settings, and evaluation targets.
    """
    updates: dict[str, Any] = {"current_stage": "search", "current_step": "analogical_retrieval"}
    errors: list[str] = list(state.errors)
    cost = state.current_cost_usd

    gateway = get_gateway()

    signatures = state.context_bundle.get("problem_signatures", [])

    # Instruct LLM to generate BROAD cross-domain queries
    user_content = (
        f"Research topic (for context only -- do NOT use its sub-field keywords "
        f"in queries): {state.topic}\n\n"
        f"Problem signatures:\n{json.dumps(signatures[:10], default=str)}\n\n"
        f"Generate search queries targeting OTHER domains that face structurally "
        f"similar problems. Focus on:\n"
        f"- Similar data conditions (modality, scale, noise)\n"
        f"- Similar supervision settings (label regime, annotation cost)\n"
        f"- Similar evaluation targets (metrics, objectives)\n"
    )

    result, delta, errs = await generate_llm_json(
        _ANALOGICAL_RETRIEVAL_SYSTEM, user_content, gateway, ModelTier.MEDIUM
    )
    cost += delta
    errors.extend(errs)

    queries: list[dict[str, Any]] = []
    if isinstance(result, dict):
        for q in result.get("queries", []):
            queries.append({
                "query": q.get("query", ""),
                "type": q.get("intent", "analogical"),
                "source": q.get("source", "both"),
                "priority": 1,
            })

    # Fallback: use abstract_keywords from signatures (NOT domain-specific keywords)
    if not queries:
        for sig in signatures[:5]:
            for kw in sig.get("abstract_keywords", [])[:2]:
                queries.append({
                    "query": kw,
                    "type": "analogical",
                    "source": "both",
                    "priority": 2,
                })

    existing_titles = {_normalize_title(pid) for pid in state.candidate_paper_ids}

    new_candidates, executed, search_errors, _titles = await search_academic_sources(
        topic=state.topic,
        queries=queries[:8],
        existing_titles=existing_titles,
    )
    errors.extend(search_errors)

    updates["candidate_paper_ids"] = list(state.candidate_paper_ids) + new_candidates
    updates["executed_queries"] = list(state.executed_queries) + executed
    updates["papers_discovered"] = state.papers_discovered + len(new_candidates)
    updates["current_cost_usd"] = cost
    updates["errors"] = errors
    updates["messages"] = [
        {"role": "assistant", "content": f"Analogical retrieval found {len(new_candidates)} cross-domain papers."}
    ]

    logger.info("analogical_retrieval.done", new=len(new_candidates))
    return updates


async def method_transfer_screening(state: ModeGraphState) -> dict[str, Any]:
    """Stage 3: Evaluate transfer potential of cross-domain methods.

    Assesses core mechanism, transfer feasibility, failed assumptions,
    and required modifications. Filters out methods with too many failed
    assumptions (> _MAX_FAILED_ASSUMPTIONS).
    """
    updates: dict[str, Any] = {"current_stage": "analyze", "current_step": "method_transfer_screening"}
    errors: list[str] = list(state.errors)
    cost = state.current_cost_usd

    gateway = get_gateway()

    signatures = state.context_bundle.get("problem_signatures", [])

    user_content = (
        f"Target research topic: {state.topic}\n"
        f"Problem signatures:\n{json.dumps(signatures[:10], default=str)}\n"
        f"Cross-domain paper IDs found: {', '.join(state.candidate_paper_ids[:30])}\n\n"
        f"For each candidate method from these external papers, assess:\n"
        f"- core_mechanism: the fundamental algorithmic/conceptual mechanism\n"
        f"- transfer_feasibility (0-1): can it transfer to the target domain?\n"
        f"- failed_assumptions: which assumptions would NOT hold in the target?\n"
        f"- required_modifications: what modules need replacement?\n"
    )

    result, delta, errs = await generate_llm_json(
        _METHOD_TRANSFER_SYSTEM, user_content, gateway, ModelTier.HIGH
    )
    cost += delta
    errors.extend(errs)

    raw_transfers: list[dict[str, Any]] = []
    if isinstance(result, list):
        raw_transfers = result
    elif isinstance(result, dict) and "transfers" in result:
        raw_transfers = result["transfers"]

    # Filter out methods with too many failed assumptions
    transfers: list[dict[str, Any]] = []
    filtered_count = 0
    for t in raw_transfers:
        failed = t.get("failed_assumptions", [])
        if len(failed) > _MAX_FAILED_ASSUMPTIONS:
            filtered_count += 1
            continue
        transfers.append(t)

    if filtered_count > 0:
        logger.info(
            "method_transfer_screening.filtered",
            removed=filtered_count,
            reason=f">{_MAX_FAILED_ASSUMPTIONS} failed assumptions",
        )

    # Store in context_bundle
    updated_bundle = dict(state.context_bundle)
    updated_bundle["method_transfers"] = transfers

    updates["context_bundle"] = updated_bundle
    updates["current_cost_usd"] = cost
    updates["errors"] = errors
    updates["messages"] = [
        {
            "role": "assistant",
            "content": (
                f"Screened {len(raw_transfers)} methods, "
                f"kept {len(transfers)} viable transfer candidates "
                f"(filtered {filtered_count})."
            ),
        }
    ]

    logger.info(
        "method_transfer_screening.done",
        total=len(raw_transfers),
        kept=len(transfers),
        filtered=filtered_count,
    )
    return updates


async def idea_composition(state: ModeGraphState) -> dict[str, Any]:
    """Stage 4: Generate innovation idea cards.

    Uses the INNOVATION_GENERATION prompt from templates.py.
    Combines pain points with their signatures and transfer candidates
    into structured idea cards.
    """
    updates: dict[str, Any] = {"current_stage": "synthesize", "current_step": "idea_composition"}
    errors: list[str] = list(state.errors)
    cost = state.current_cost_usd

    gateway = get_gateway()

    transfers = state.context_bundle.get("method_transfers", [])
    signatures = state.context_bundle.get("problem_signatures", [])
    pain_points = state.pain_points or state.context_bundle.get(
        "pain_point_package", {}
    ).get("pain_points", [])

    # Use INNOVATION_GENERATION prompt from templates.py as the base system prompt
    innovation_system = get_system_prompt(PromptName.INNOVATION_GENERATION)

    # Augment with idea card structure instructions
    system_prompt = (
        f"{innovation_system}\n\n"
        f"## Additional Output Requirements for Idea Cards\n"
        f"Each idea card MUST be a JSON object with these keys:\n"
        f"- title: str (concise idea title)\n"
        f"- problem_statement: str (the pain point being addressed)\n"
        f"- borrowed_method: str (the method being transferred)\n"
        f"- source_domain: str (where the method comes from)\n"
        f"- mechanism_of_transfer: str (how the method applies to the target)\n"
        f"- expected_benefit: str (what improvement is expected)\n"
        f"- risks: [str] (potential failure modes)\n"
        f"- required_experiments: [str] (experiments needed to validate)\n"
        f"- novelty_score: float (0-1)\n"
        f"- feasibility_score: float (0-1)\n\n"
        f"Output MUST be a JSON array of idea card objects."
    )

    user_content = (
        f"Research topic: {state.topic}\n\n"
        f"## Pain Points (with problem signatures)\n"
        f"{json.dumps(pain_points[:10], default=str)}\n\n"
        f"## Problem Signatures\n"
        f"{json.dumps(signatures[:10], default=str)}\n\n"
        f"## Viable Transfer Candidates\n"
        f"{json.dumps(transfers[:10], default=str)}\n\n"
        f"Generate idea cards that combine pain points with transferable methods.\n"
    )

    result, delta, errs = await generate_llm_json(
        system_prompt, user_content, gateway, ModelTier.HIGH
    )
    cost += delta
    errors.extend(errs)

    idea_cards: list[dict[str, Any]] = []
    if isinstance(result, list):
        idea_cards = result
    elif isinstance(result, dict) and "ideas" in result:
        idea_cards = result["ideas"]

    # Assign IDs and initial status; score novelty and feasibility defaults
    for idx, card in enumerate(idea_cards):
        card["id"] = f"idea-{idx}"
        card["status"] = "candidate"
        card["prior_art_check_status"] = "pending"
        # Ensure numeric scores exist
        card.setdefault("novelty_score", 0.5)
        card.setdefault("feasibility_score", 0.5)

    updates["idea_cards"] = idea_cards
    updates["current_cost_usd"] = cost
    updates["errors"] = errors
    updates["messages"] = [
        {"role": "assistant", "content": f"Composed {len(idea_cards)} idea cards."}
    ]

    logger.info("idea_composition.done", ideas=len(idea_cards))
    return updates


async def prior_art_check(state: ModeGraphState) -> dict[str, Any]:
    """Stage 5: Search for existing similar work.

    For each idea card, searches S2 for papers with similar title/method
    combinations. Uses the VERIFIER prompt from templates.py to assess
    novelty. Flags high-risk ideas where prior art is found.
    """
    updates: dict[str, Any] = {"current_stage": "analyze", "current_step": "prior_art_check"}
    errors: list[str] = list(state.errors)
    cost = state.current_cost_usd

    gateway = get_gateway()

    # Build search queries from idea card titles and borrowed methods
    search_queries: list[dict[str, Any]] = []
    for card in state.idea_cards[:10]:
        title = card.get("title", "")
        method = card.get("borrowed_method", "")
        query_text = f"{title} {method}".strip()
        if query_text:
            search_queries.append({
                "query": query_text,
                "type": "prior_art",
                "source": "both",
                "priority": 1,
            })

    # Search S2 + OpenAlex for similar papers
    existing_titles = {_normalize_title(pid) for pid in state.candidate_paper_ids}
    prior_art_papers: list[str] = []
    if search_queries:
        found, _executed, search_errors, _t = await search_academic_sources(
            topic=state.topic,
            queries=search_queries[:10],
            existing_titles=existing_titles,
        )
        prior_art_papers = found
        errors.extend(search_errors)

    # Use VERIFIER prompt from templates.py to assess novelty
    verifier_system = get_system_prompt(PromptName.VERIFIER)

    user_content = (
        f"Research topic: {state.topic}\n\n"
        f"## Idea Cards to Verify\n"
        f"{json.dumps(state.idea_cards[:10], default=str)}\n\n"
        f"## Prior Art Papers Found (IDs)\n"
        f"{json.dumps(prior_art_papers[:20], default=str)}\n\n"
        f"For EACH idea card, assess whether substantially similar work "
        f"already exists. Output MUST be valid JSON: an array of objects with:\n"
        f"- idea_title: str\n"
        f"- verdict: \"reject\" | \"hold\" | \"finalize\" | \"continue_search\"\n"
        f"- prior_art_found: bool\n"
        f"- similar_works: [{{title: str, similarity_reason: str}}]\n"
        f"- adjusted_novelty_score: float (0-1)\n"
        f"- rationale: str\n"
    )

    result, delta, errs = await generate_llm_json(
        verifier_system, user_content, gateway, ModelTier.HIGH
    )
    cost += delta
    errors.extend(errs)

    checks: list[dict[str, Any]] = []
    if isinstance(result, list):
        checks = result
    elif isinstance(result, dict) and "checks" in result:
        checks = result["checks"]

    # Update idea cards with prior art status
    check_map = {c.get("idea_title", ""): c for c in checks}
    updated_cards: list[dict[str, Any]] = []
    for card in state.idea_cards:
        title = card.get("title", "")
        check = check_map.get(title, {})
        prior_art_found = check.get("prior_art_found", False)
        updated_card = {
            **card,
            "prior_art_check_status": "high_risk" if prior_art_found else "checked",
            "prior_art_found": prior_art_found,
            "prior_art_details": check.get("similar_works", []),
            "novelty_score": check.get(
                "adjusted_novelty_score",
                card.get("novelty_score", 0.5),
            ),
        }
        updated_cards.append(updated_card)

    updates["idea_cards"] = updated_cards
    updates["current_cost_usd"] = cost
    updates["errors"] = errors
    updates["messages"] = [
        {"role": "assistant", "content": f"Prior art check completed for {len(checks)} ideas."}
    ]

    logger.info("prior_art_check.done", checked=len(checks))
    return updates


async def feasibility_review(state: ModeGraphState) -> dict[str, Any]:
    """Stage 6: Assess practical feasibility.

    Evaluates data availability, compute requirements, experiment design
    feasibility, and timeline estimate. Updates feasibility scores.
    """
    updates: dict[str, Any] = {"current_stage": "analyze", "current_step": "feasibility_review"}
    errors: list[str] = list(state.errors)
    cost = state.current_cost_usd

    gateway = get_gateway()

    # Only assess ideas that survived prior art check (not flagged high-risk)
    viable_ideas = [
        c for c in state.idea_cards
        if not c.get("prior_art_found", False)
    ]

    user_content = (
        f"Research topic: {state.topic}\n\n"
        f"## Viable Idea Cards (passed prior art check)\n"
        f"{json.dumps(viable_ideas[:10], default=str)}\n\n"
        f"For each idea, assess:\n"
        f"- data_available (bool): can the required data be obtained?\n"
        f"- compute_reasonable (bool): can it run on typical academic hardware?\n"
        f"- experiment_designable (bool): is there a clear experimental protocol?\n"
        f"- estimated_weeks (int): calendar weeks for a first experiment\n"
        f"- critical_risks: top risks that could block execution\n"
    )

    result, delta, errs = await generate_llm_json(
        _FEASIBILITY_SYSTEM, user_content, gateway, ModelTier.HIGH
    )
    cost += delta
    errors.extend(errs)

    assessments: list[dict[str, Any]] = []
    if isinstance(result, list):
        assessments = result
    elif isinstance(result, dict) and "assessments" in result:
        assessments = result["assessments"]

    # Merge feasibility into idea cards
    assess_map = {a.get("idea_title", ""): a for a in assessments}
    updated_cards: list[dict[str, Any]] = []
    for card in state.idea_cards:
        title = card.get("title", "")
        assessment = assess_map.get(title, {})
        updated_card = {
            **card,
            "feasibility_score": assessment.get(
                "overall_feasibility",
                card.get("feasibility_score", 0.5),
            ),
            "data_available": assessment.get("data_available", None),
            "compute_reasonable": assessment.get("compute_reasonable", None),
            "experiment_designable": assessment.get("experiment_designable", None),
            "estimated_weeks": assessment.get("estimated_weeks", None),
            "critical_risks": assessment.get("critical_risks", []),
            "go_no_go": assessment.get("go_no_go", "conditional"),
            "recommended_first_experiment": assessment.get(
                "recommended_first_experiment", ""
            ),
        }
        updated_cards.append(updated_card)

    updates["idea_cards"] = updated_cards
    updates["current_cost_usd"] = cost
    updates["errors"] = errors
    updates["messages"] = [
        {"role": "assistant", "content": f"Feasibility reviewed for {len(assessments)} ideas."}
    ]

    logger.info("feasibility_review.done", assessed=len(assessments))
    return updates


def _compute_composite_score(card: dict[str, Any]) -> float:
    """Compute composite score: novelty * 0.4 + feasibility * 0.3 + evidence * 0.3."""
    novelty = float(card.get("novelty_score", 0.5))
    feasibility = float(card.get("feasibility_score", 0.5))
    # Evidence score: derived from prior art status and number of supporting details
    evidence = _compute_evidence_score(card)
    return round(novelty * 0.4 + feasibility * 0.3 + evidence * 0.3, 4)


def _compute_evidence_score(card: dict[str, Any]) -> float:
    """Derive an evidence score from prior art check and experiment details.

    Higher score if: no prior art found, has required experiments, has
    mechanism of transfer documented.
    """
    score = 0.5  # baseline

    # Boost if prior art check passed cleanly
    if not card.get("prior_art_found", False):
        score += 0.15

    # Boost if required experiments are specified
    experiments = card.get("required_experiments", [])
    if experiments:
        score += min(0.15, 0.05 * len(experiments))

    # Boost if mechanism of transfer is documented
    if card.get("mechanism_of_transfer"):
        score += 0.1

    # Boost if go_no_go is positive
    if card.get("go_no_go") == "go":
        score += 0.1

    return min(1.0, score)


async def idea_portfolio(state: ModeGraphState) -> dict[str, Any]:
    """Stage 7: Rank and finalize idea cards.

    Sorts by composite score (novelty * 0.4 + feasibility * 0.3 + evidence * 0.3).
    Generates summary report_markdown. Builds context_bundle with final
    idea cards for Mode X or Mode B re-check. Sets should_stop = True.
    """
    updates: dict[str, Any] = {
        "current_stage": "output",
        "current_step": "idea_portfolio",
        "should_stop": True,
        "stop_reason": "completed",
    }
    errors: list[str] = list(state.errors)
    cost = state.current_cost_usd

    gateway = get_gateway()

    # Compute composite scores locally
    scored_cards: list[dict[str, Any]] = []
    for card in state.idea_cards:
        evidence = _compute_evidence_score(card)
        composite = _compute_composite_score(card)
        scored_card = {
            **card,
            "evidence_score": round(evidence, 4),
            "composite_score": composite,
        }
        scored_cards.append(scored_card)

    # Sort by composite score descending
    scored_cards.sort(key=lambda c: c.get("composite_score", 0), reverse=True)

    # Assign final ranks
    for rank, card in enumerate(scored_cards, start=1):
        card["rank"] = rank

    # Use LLM to generate portfolio summary and next steps
    user_content = (
        f"Research topic: {state.topic}\n\n"
        f"## Ranked Idea Cards (by composite score)\n"
        f"{json.dumps(scored_cards[:10], default=str)}\n\n"
        f"Generate a portfolio summary and recommended next steps.\n"
    )

    result, delta, errs = await generate_llm_json(
        _IDEA_PORTFOLIO_SYSTEM, user_content, gateway, ModelTier.HIGH
    )
    cost += delta
    errors.extend(errs)

    summary = ""
    next_steps: list[str] = []
    if isinstance(result, dict):
        summary = result.get("portfolio_summary", "")
        next_steps = result.get("recommended_next_steps", [])

    # Build Markdown report
    lines = [f"# Innovation Portfolio: {state.topic}\n"]
    if summary:
        lines.append(f"{summary}\n")
    lines.append("## Ranked Ideas\n")
    for card in scored_cards:
        lines.append(
            f"### {card.get('rank', '?')}. {card.get('title', 'Untitled')}\n"
            f"- **Composite Score**: {card.get('composite_score', 'N/A')}\n"
            f"- **Novelty**: {card.get('novelty_score', 'N/A')}\n"
            f"- **Feasibility**: {card.get('feasibility_score', 'N/A')}\n"
            f"- **Evidence**: {card.get('evidence_score', 'N/A')}\n"
            f"- **Problem**: {card.get('problem_statement', '')}\n"
            f"- **Borrowed Method**: {card.get('borrowed_method', '')}\n"
            f"- **Source Domain**: {card.get('source_domain', '')}\n"
            f"- **Mechanism**: {card.get('mechanism_of_transfer', '')}\n"
            f"- **Expected Benefit**: {card.get('expected_benefit', '')}\n"
            f"- **Go/No-Go**: {card.get('go_no_go', 'N/A')}\n"
        )
        risks = card.get("risks", [])
        if risks:
            lines.append(f"- **Risks**: {', '.join(str(r) for r in risks)}\n")
        experiments = card.get("required_experiments", [])
        if experiments:
            lines.append(f"- **Required Experiments**: {', '.join(str(e) for e in experiments)}\n")
        lines.append("")

    if next_steps:
        lines.append("\n## Recommended Next Steps\n")
        for step in next_steps:
            lines.append(f"- {step}\n")

    report = "\n".join(lines)

    # Build context_bundle for Mode X or Mode B re-check
    updated_bundle = dict(state.context_bundle)
    updated_bundle["final_idea_cards"] = scored_cards
    updated_bundle["portfolio_summary"] = summary
    updated_bundle["recommended_next_steps"] = next_steps

    updates["idea_cards"] = scored_cards
    updates["context_bundle"] = updated_bundle
    updates["report_markdown"] = report
    updates["current_cost_usd"] = cost
    updates["errors"] = errors
    updates["messages"] = [
        {"role": "assistant", "content": f"Idea portfolio compiled ({len(report)} chars, {len(scored_cards)} ideas)."}
    ]

    logger.info(
        "idea_portfolio.done",
        report_len=len(report),
        ideas=len(scored_cards),
    )
    return updates


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------


def create_divergent_graph() -> StateGraph:
    """Create the 7-stage Divergent (Mode C) LangGraph StateGraph."""
    workflow = StateGraph(ModeGraphState)

    workflow.add_node("normalize_pain_package", normalize_pain_package)
    workflow.add_node("analogical_retrieval", analogical_retrieval)
    workflow.add_node("method_transfer_screening", method_transfer_screening)
    workflow.add_node("idea_composition", idea_composition)
    workflow.add_node("prior_art_check", prior_art_check)
    workflow.add_node("feasibility_review", feasibility_review)
    workflow.add_node("idea_portfolio", idea_portfolio)

    workflow.set_entry_point("normalize_pain_package")

    workflow.add_edge("normalize_pain_package", "analogical_retrieval")

    # Check after retrieval
    workflow.add_conditional_edges(
        "analogical_retrieval",
        check_should_continue,
        {
            "continue": "method_transfer_screening",
            "pause": END,
            "stop": "idea_portfolio",
        },
    )

    workflow.add_edge("method_transfer_screening", "idea_composition")
    workflow.add_edge("idea_composition", "prior_art_check")
    workflow.add_edge("prior_art_check", "feasibility_review")

    # Check after feasibility — could loop back for more retrieval
    workflow.add_conditional_edges(
        "feasibility_review",
        check_should_continue,
        {
            "continue": "idea_portfolio",
            "pause": END,
            "stop": "idea_portfolio",
        },
    )

    workflow.add_edge("idea_portfolio", END)

    return workflow


def compile_divergent_graph(checkpointer=None):
    """Compile the Divergent graph with an optional checkpointer."""
    workflow = create_divergent_graph()
    return workflow.compile(checkpointer=checkpointer or MemorySaver())
