"""Persistence helpers for worker run results and workspace outputs."""

from __future__ import annotations

import json
from contextlib import suppress
from typing import Any, Awaitable, Callable
from uuid import UUID

from structlog import get_logger

from services.research_memory import persist_run_memory

logger = get_logger(__name__)

MemoryPersister = Callable[[Any], Awaitable[list[dict[str, Any]]]]


def _listify_idea_value(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item is not None and str(item)]
    if isinstance(value, (tuple, set)):
        return [str(item) for item in value if item is not None and str(item)]
    normalized = str(value)
    return [normalized] if normalized else []


def _normalize_idea_card_payload(idea_card: dict[str, Any]) -> dict[str, Any]:
    payload = dict(idea_card)
    if "borrowed_methods" not in payload and payload.get("borrowed_method"):
        payload["borrowed_methods"] = _listify_idea_value(
            payload.get("borrowed_method")
        )
    if "source_domains" not in payload and payload.get("source_domain"):
        payload["source_domains"] = _listify_idea_value(
            payload.get("source_domain")
        )
    return payload


async def persist_results(
    run_id: UUID,
    state: Any,
    *,
    memory_persister: MemoryPersister | None = None,
    log: Any | None = None,
) -> None:
    """Persist workflow results to database-backed storage."""
    from apps.api.database import (
        create_context_bundle,
        create_idea_card,
        create_pain_point,
    )

    log = logger if log is None else log
    memory_persister = persist_run_memory if memory_persister is None else memory_persister

    try:
        all_pain_items = _collect_pain_items(state)

        await _persist_pain_points(
            run_id,
            all_pain_items,
            create_pain_point=create_pain_point,
        )
        await _persist_paper_summaries(run_id, state, log=log)
        saved_ideas = await _persist_idea_cards(
            run_id,
            state,
            create_idea_card=create_idea_card,
            log=log,
        )
        await _persist_context_bundle(
            run_id,
            state,
            create_context_bundle=create_context_bundle,
            log=log,
        )
        await _persist_research_memory(
            run_id,
            state,
            memory_persister=memory_persister,
            log=log,
        )

        log.info("worker.results_persisted", run_id=str(run_id),
                 pain_points=len(state.pain_points or []),
                 idea_cards=saved_ideas,
                 has_comparison=bool(state.comparison_matrix))
    except Exception as exc:
        log.error("worker.persist_results_failed", error=str(exc))


def _collect_pain_items(state: Any) -> list[dict[str, Any]]:
    all_pain_items = list(state.pain_points or [])
    for gap in (state.gaps or []):
        all_pain_items.append({
            "statement": gap.get("description", ""),
            "pain_type": gap.get("gap_type", "method"),
            "severity_score": 0.8 if gap.get("significance") == "high" else 0.5,
            "novelty_potential": 0.7,
        })
    return all_pain_items


async def _persist_pain_points(
    run_id: UUID,
    pain_items: list[dict[str, Any]],
    *,
    create_pain_point: Callable[[UUID, dict[str, Any]], Awaitable[Any]],
) -> None:
    for pp in pain_items:
        try:
            statement = (
                pp.get("statement")
                or pp.get("description")
                or pp.get("problem")
                or pp.get("text")
                or ""
            )
            if not statement:
                continue
            await create_pain_point(run_id, {
                "statement": statement,
                "pain_type": pp.get("pain_type", pp.get("type", pp.get("gap_type", "generalization"))),
                "severity_score": float(pp.get("severity_score", pp.get("severity", 0.5))),
                "novelty_potential": float(pp.get("novelty_potential", pp.get("novelty", 0.5))),
            })
        except Exception:
            pass


async def _persist_paper_summaries(
    run_id: UUID,
    state: Any,
    *,
    log: Any,
) -> None:
    paper_summaries = (state.context_bundle or {}).get("paper_summaries", [])
    if paper_summaries:
        try:
            from apps.api.database import get_pool
            pool = await get_pool()
            from uuid import uuid4 as _uuid4
            for ps in paper_summaries:
                if not isinstance(ps, dict):
                    continue
                title = ps.get("title", ps.get("paper_title", ""))
                if not title:
                    continue
                paper_id = _uuid4()
                with suppress(Exception):
                    await pool.execute("""
                        INSERT INTO paper (id, canonical_title, normalized_title, abstract,
                            publication_year, venue, metadata_json)
                        VALUES ($1, $2, $3, $4, $5, $6, $7)
                        ON CONFLICT DO NOTHING
                    """,
                        paper_id,
                        title[:500],
                        title.lower().strip()[:500],
                        ps.get("abstract", ps.get("summary", ""))[:2000],
                        ps.get("year"),
                        ps.get("venue", ""),
                        json.dumps({**ps, "source_run_id": str(run_id)}, default=str)[:5000],
                    )
            log.info("worker.papers_persisted", count=len(paper_summaries))
        except Exception as exc:
            log.debug("persist_papers_failed", error=str(exc))


async def _persist_idea_cards(
    run_id: UUID,
    state: Any,
    *,
    create_idea_card: Callable[[UUID, dict[str, Any]], Awaitable[Any]],
    log: Any,
) -> int:
    saved_ideas = 0
    for idea_card in getattr(state, "idea_cards", []) or []:
        if not isinstance(idea_card, dict):
            continue
        payload = _normalize_idea_card_payload(idea_card)
        if not payload.get("title"):
            continue
        try:
            await create_idea_card(run_id, payload)
            saved_ideas += 1
        except Exception as exc:
            log.warning(
                "persist_idea_card_failed",
                run_id=str(run_id),
                title=str(payload.get("title", ""))[:120],
                error=str(exc),
            )
    return saved_ideas


async def _persist_context_bundle(
    run_id: UUID,
    state: Any,
    *,
    create_context_bundle: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]],
    log: Any,
) -> None:
    bundle_data = state.context_bundle or {}
    if bundle_data:
        try:
            bundle = await create_context_bundle({
                "source_run_id": str(run_id),
                "source_mode": state.mode or "frontier",
                "summary_text": state.report_markdown[:5000] if state.report_markdown else "",
                "benchmark_data": {
                    "comparison_matrix": state.comparison_matrix or [],
                    "gaps": state.gaps or [],
                    "pain_points_count": len(state.pain_points or []),
                    "papers_read": state.papers_read,
                    "papers_discovered": state.papers_discovered,
                    "paper_summaries": (state.context_bundle or {}).get("paper_summaries", []),
                },
                "mindmap_json": bundle_data.get("mindmap_json", {}),
            })
            from apps.api.database import update_run
            await update_run(run_id, {"output_bundle_id": bundle["id"]})
        except Exception as exc:
            log.debug("persist_bundle_failed", error=str(exc))


async def _persist_research_memory(
    run_id: UUID,
    state: Any,
    *,
    memory_persister: MemoryPersister,
    log: Any,
) -> None:
    try:
        await memory_persister(state)
    except Exception as exc:
        log.warning(
            "research_memory.persist_failed",
            run_id=str(run_id),
            error=str(exc),
        )


def write_workspace_outputs(
    run_id: UUID,
    run: dict[str, Any],
    state: Any,
    *,
    log: Any | None = None,
) -> None:
    """Write run outputs into the configured experiment workspace."""

    log = logger if log is None else log
    policy = run.get("policy_json") if isinstance(run, dict) else {}
    workspace = policy.get("experiment_workspace") if isinstance(policy, dict) else None
    if not isinstance(workspace, dict):
        return
    raw_path = workspace.get("path") or workspace.get("relative_path")
    if not raw_path:
        return

    try:
        from apps.worker.production.workspaces import (
            resolve_path_reference,
            workspace_base,
        )

        workspace_path = resolve_path_reference(
            workspace_base(),
            raw_path,
            field_name="experiment_workspace",
        )
        workspace_path.mkdir(parents=True, exist_ok=True)

        report = getattr(state, "report_markdown", "") or ""
        if report:
            (workspace_path / "report.md").write_text(report, encoding="utf-8")

        _write_json_file(workspace_path, "context_bundle.json", getattr(state, "context_bundle", {}) or {})
        _write_json_file(workspace_path, "idea_cards.json", getattr(state, "idea_cards", []) or [])
        context_bundle = getattr(state, "context_bundle", {}) or {}
        paper_summaries = getattr(state, "paper_summaries", []) or context_bundle.get("paper_summaries", [])
        _write_json_file(workspace_path, "paper_summaries.json", paper_summaries)
        _write_json_file(
            workspace_path,
            "run_state.json",
            {
                "run_id": str(run_id),
                "title": run.get("title"),
                "topic": getattr(state, "topic", None),
                "mode": getattr(state, "mode", None),
                "current_step": getattr(state, "current_step", None),
                "papers_discovered": getattr(state, "papers_discovered", 0),
                "papers_read": getattr(state, "papers_read", 0),
                "current_cost_usd": getattr(state, "current_cost_usd", 0.0),
                "export_urls": getattr(state, "export_urls", []) or [],
                "experiment_workspace": workspace,
            },
        )
        from apps.worker.production.research_completion import (
            write_research_completion_package,
        )

        write_research_completion_package(
            workspace_path,
            run_id=run_id,
            title=str(run.get("title") or getattr(state, "topic", "Research Run")),
            state=state,
        )
    except Exception as exc:
        log.warning(
            "worker.workspace_outputs_failed",
            run_id=str(run_id),
            error=str(exc),
        )


def _write_json_file(workspace_path: Any, filename: str, payload: Any) -> None:
    (workspace_path / filename).write_text(
        json.dumps(payload, default=str, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
