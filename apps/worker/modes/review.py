"""
Research OS - Review Mode (Mode X): Synthesis & Review

Simple 3-stage LangGraph StateGraph for loading a context bundle from
a parent run, applying user refinement instructions, and exporting
final outputs (Markdown, JSON, BibTeX).
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
    check_should_continue,
    emit_progress,
    generate_llm_json,
)
from libs.prompts.templates import PromptName, get_system_prompt

logger = get_logger(__name__)

# Re-export for runner
ReviewState = ModeGraphState

# ---------------------------------------------------------------------------
# Review-specific system prompts
# ---------------------------------------------------------------------------

_REFINE_SYSTEM = """\
You are a Research Report Refinement Agent.

Given an existing research report/context and user refinement instructions,
produce an improved version. Follow the user instructions precisely.

Output MUST be valid JSON with keys:
- refined_markdown: str  (the refined report in Markdown)
- changes_made: [str]  (list of changes applied)
- suggestions: [str]  (additional improvement suggestions)
"""

_EXPORT_SYSTEM = """\
You are a Research Export Agent.

Given a refined research report, generate export-ready outputs:
1. A clean Markdown report
2. A structured JSON summary
3. A BibTeX bibliography for all cited papers

Output MUST be valid JSON with keys:
- markdown_report: str
- json_summary: {
    topic: str,
    key_findings: [str],
    papers_count: int,
    recommendations: [str]
  }
- bibtex: str  (valid BibTeX entries)
"""


# ---------------------------------------------------------------------------
# Node functions
# ---------------------------------------------------------------------------


async def load_context(state: ModeGraphState) -> dict[str, Any]:
    """Stage 1: Load context bundle from parent run."""
    await emit_progress(state.run_id, "load_context", "start", "Loading context from parent run")
    updates: dict[str, Any] = {"current_stage": "plan", "current_step": "load_context"}
    errors: list[str] = list(state.errors)

    bundle = state.context_bundle
    if not bundle:
        errors.append("No context bundle provided for review mode.")
        updates["errors"] = errors
        updates["messages"] = [
            {"role": "assistant", "content": "No context bundle found. Review mode requires input from a previous run."}
        ]
        logger.warning("load_context.no_bundle")
        return updates

    source_mode = bundle.get("source_mode", "unknown")

    # Populate state from bundle if a parent report exists
    if "report_markdown" not in bundle and state.report_markdown:
        pass  # Report already in state
    elif "report_markdown" in bundle:
        updates["report_markdown"] = bundle["report_markdown"]

    # Carry over pain points if available
    if "pain_point_package" in bundle:
        pp = bundle["pain_point_package"]
        if isinstance(pp, dict) and "pain_points" in pp:
            updates["pain_points"] = pp["pain_points"]

    updates["errors"] = errors
    updates["messages"] = [
        {"role": "assistant", "content": f"Loaded context bundle from {source_mode} mode."}
    ]

    logger.info("load_context.done", source_mode=source_mode)
    await emit_progress(state.run_id, "load_context", "done", f"Loaded context from {source_mode} mode")
    return updates


async def refine_output(state: ModeGraphState) -> dict[str, Any]:
    """Stage 2: Apply user refinement instructions."""
    await emit_progress(state.run_id, "refine_output", "start", "Applying refinement instructions")
    updates: dict[str, Any] = {"current_stage": "synthesize", "current_step": "refine_output"}
    errors: list[str] = list(state.errors)
    cost = state.current_cost_usd

    gateway = get_gateway()

    existing_report = state.report_markdown
    if not existing_report:
        # Try to build a basic report from context
        existing_report = (
            f"# Research Summary: {state.topic}\n\n"
            f"Papers discovered: {state.papers_discovered}\n"
            f"Papers read: {state.papers_read}\n"
            f"Pain points: {len(state.pain_points)}\n"
            f"Idea cards: {len(state.idea_cards)}\n"
        )

    # Gather user instructions from messages (last user message)
    user_instructions = "Refine and improve this report for clarity and completeness."
    for msg in reversed(state.messages):
        if isinstance(msg, dict) and msg.get("role") == "user":
            user_instructions = msg.get("content", user_instructions)
            break

    user_content = (
        f"## Existing Report\n{existing_report[:8000]}\n\n"
        f"## Context Bundle\n{json.dumps(state.context_bundle, default=str)[:4000]}\n\n"
        f"## User Instructions\n{user_instructions}\n"
    )

    result, delta, errs = await generate_llm_json(
        _REFINE_SYSTEM, user_content, gateway, ModelTier.HIGH
    )
    cost += delta
    errors.extend(errs)

    if isinstance(result, dict):
        updates["report_markdown"] = result.get("refined_markdown", existing_report)
    else:
        updates["report_markdown"] = existing_report

    updates["current_cost_usd"] = cost
    updates["errors"] = errors
    updates["messages"] = [
        {"role": "assistant", "content": "Report refined."}
    ]

    logger.info("refine_output.done", report_len=len(updates.get("report_markdown", "")))
    await emit_progress(state.run_id, "refine_output", "done", f"Report refined ({len(updates.get('report_markdown', ''))} chars)")
    return updates


async def export_results(state: ModeGraphState) -> dict[str, Any]:
    """Stage 3: Generate final exports (Markdown, JSON, BibTeX)."""
    await emit_progress(state.run_id, "export_results", "start", "Generating final exports")
    updates: dict[str, Any] = {
        "current_stage": "output",
        "current_step": "export_results",
        "should_stop": True,
        "stop_reason": "completed",
    }
    errors: list[str] = list(state.errors)
    cost = state.current_cost_usd

    gateway = get_gateway()

    user_content = (
        f"## Report to Export\n{state.report_markdown[:10000]}\n\n"
        f"Topic: {state.topic}\n"
        f"Papers read: {', '.join(state.read_paper_ids[:30])}\n"
    )

    result, delta, errs = await generate_llm_json(
        _EXPORT_SYSTEM, user_content, gateway, ModelTier.MEDIUM
    )
    cost += delta
    errors.extend(errs)

    export_urls: list[str] = []
    if isinstance(result, dict):
        # In production, these would be written to storage; here we note them
        md_report = result.get("markdown_report", state.report_markdown)
        updates["report_markdown"] = md_report

        # Store JSON summary and BibTeX in context_bundle
        updated_bundle = dict(state.context_bundle)
        updated_bundle["json_summary"] = result.get("json_summary", {})
        updated_bundle["bibtex"] = result.get("bibtex", "")
        updates["context_bundle"] = updated_bundle

        export_urls.append("report.md")
        export_urls.append("summary.json")
        export_urls.append("references.bib")

    updates["export_urls"] = export_urls
    updates["current_cost_usd"] = cost
    updates["errors"] = errors
    updates["messages"] = [
        {"role": "assistant", "content": f"Exports generated: {', '.join(export_urls)}."}
    ]

    logger.info("export_results.done", exports=len(export_urls))
    await emit_progress(state.run_id, "export_results", "done", f"Exported {len(export_urls)} files")
    return updates


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------


def create_review_graph() -> StateGraph:
    """Create the 3-stage Review (Mode X) LangGraph StateGraph."""
    workflow = StateGraph(ModeGraphState)

    workflow.add_node("load_context", load_context)
    workflow.add_node("refine_output", refine_output)
    workflow.add_node("export_results", export_results)

    workflow.set_entry_point("load_context")

    # Conditional after load — can pause if no context
    workflow.add_conditional_edges(
        "load_context",
        check_should_continue,
        {
            "continue": "refine_output",
            "pause": END,
            "stop": "export_results",
        },
    )

    workflow.add_edge("refine_output", "export_results")
    workflow.add_edge("export_results", END)

    return workflow


def compile_review_graph(checkpointer=None):
    """Compile the Review graph with an optional checkpointer."""
    workflow = create_review_graph()
    return workflow.compile(checkpointer=checkpointer or MemorySaver())
