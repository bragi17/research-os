"""Project-level research memory extraction and persistence."""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from apps.api.database import (
    list_research_memory_items,
    upsert_research_memory_item,
)
from apps.worker.modes.base import ModeGraphState


def _uuid(value: object) -> UUID | None:
    if value in (None, ""):
        return None
    return UUID(str(value))


def _stable_key(*parts: object) -> str:
    raw = " ".join(str(part or "") for part in parts).lower()
    key = re.sub(r"[^a-z0-9:./-]+", "-", raw).strip("-")
    return key[:180] or "memory-item"


def _paper_summaries_from_state(state: ModeGraphState) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    summaries.extend(state.paper_summaries or [])
    summaries.extend((state.context_bundle or {}).get("paper_summaries", []) or [])
    return [summary for summary in summaries if isinstance(summary, dict)]


def memory_items_from_state(state: ModeGraphState) -> list[dict[str, Any]]:
    """Convert one mode state into memory ledger item payloads."""
    project_id = _uuid(state.project_id)
    if project_id is None:
        return []
    run_id = _uuid(state.run_id)
    items: list[dict[str, Any]] = []

    for paper in _paper_summaries_from_state(state):
        paper_id = paper.get("paper_id") or paper.get("id") or paper.get("title")
        title = paper.get("title") or paper.get("paper_title") or str(paper_id)
        items.append(
            {
                "project_id": project_id,
                "source_run_id": run_id,
                "item_type": "paper",
                "stable_key": _stable_key("paper", paper_id),
                "title": title,
                "status": "seen",
                "summary_text": paper.get("summary") or paper.get("tl_dr"),
                "payload_json": dict(paper),
            }
        )

    for gap in (state.pain_points or []) + (state.gaps or []):
        if not isinstance(gap, dict):
            continue
        title = (
            gap.get("title")
            or gap.get("pain_point")
            or gap.get("description")
            or gap.get("statement")
        )
        items.append(
            {
                "project_id": project_id,
                "source_run_id": run_id,
                "item_type": "gap",
                "stable_key": _stable_key("gap", title),
                "title": title,
                "status": gap.get("severity") or gap.get("gap_type") or "observed",
                "summary_text": gap.get("description") or gap.get("statement"),
                "payload_json": dict(gap),
            }
        )

    for idea in state.idea_cards or []:
        if not isinstance(idea, dict):
            continue
        quality = str(
            idea.get("quality_verdict") or idea.get("status") or "hold"
        ).strip().lower()
        item_type = "failed_idea" if quality == "reject" else "idea"
        title = idea.get("title") or "Untitled idea"
        items.append(
            {
                "project_id": project_id,
                "source_run_id": run_id,
                "item_type": item_type,
                "stable_key": idea.get("dedup_key")
                or _stable_key("idea", title, idea.get("problem_statement")),
                "title": title,
                "status": quality,
                "summary_text": (
                    idea.get("problem_statement")
                    or idea.get("strongest_objection")
                ),
                "payload_json": dict(idea),
            }
        )

    for claim in state.claims or []:
        if not isinstance(claim, dict):
            continue
        text = claim.get("claim") or claim.get("text")
        items.append(
            {
                "project_id": project_id,
                "source_run_id": run_id,
                "item_type": "claim",
                "stable_key": _stable_key("claim", text),
                "title": text,
                "status": claim.get("status") or "draft",
                "summary_text": text,
                "payload_json": dict(claim),
            }
        )

    for experiment in state.experiments or []:
        if not isinstance(experiment, dict):
            continue
        title = experiment.get("title") or experiment.get("name")
        items.append(
            {
                "project_id": project_id,
                "source_run_id": run_id,
                "item_type": "experiment",
                "stable_key": _stable_key("experiment", title),
                "title": title,
                "status": experiment.get("status") or "planned",
                "summary_text": experiment.get("summary") or experiment.get("rationale"),
                "payload_json": dict(experiment),
            }
        )

    return items


async def persist_run_memory(state: ModeGraphState) -> list[dict[str, Any]]:
    """Persist extracted memory items for one completed run."""
    saved: list[dict[str, Any]] = []
    for item in memory_items_from_state(state):
        saved.append(await upsert_research_memory_item(item))
    return saved


async def load_failed_idea_memory(
    project_id: object,
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Load failed idea memory for prompt-time avoidance."""
    resolved_project_id = _uuid(project_id)
    if resolved_project_id is None:
        return []
    return await list_research_memory_items(
        resolved_project_id,
        item_type="failed_idea",
        limit=limit,
    )
