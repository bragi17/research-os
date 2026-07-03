"""Persistence helpers for worker run results and workspace outputs."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from structlog import get_logger

from services.research_memory import persist_run_memory

logger = get_logger(__name__)

MemoryPersister = Callable[[Any], Awaitable[list[dict[str, Any]]]]
ArtifactCardCreator = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
PhaseExecutionUpdater = Callable[[UUID | str, dict[str, Any]], Awaitable[Any]]


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


def _coerce_text(value: Any, *, max_len: int | None = None) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return text[:max_len] if max_len is not None else text


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _coerce_uuid(value: UUID | str) -> UUID | str:
    if isinstance(value, UUID):
        return value
    return UUID(str(value))


def _has_state_key(state: Any, key: str) -> bool:
    if isinstance(state, dict):
        return key in state
    return hasattr(state, key)


def _state_value(state: Any, key: str, default: Any = None) -> Any:
    if isinstance(state, dict):
        return state.get(key, default)
    return getattr(state, key, default)


def _state_mapping(state: Any, key: str) -> dict[str, Any]:
    value = _state_value(state, key, {})
    return value if isinstance(value, dict) else {}


def _set_state_value(state: Any, key: str, value: Any) -> None:
    if isinstance(state, dict):
        state[key] = value
    else:
        setattr(state, key, value)


def _items_from_value(value: Any) -> list[Any]:
    return list(value) if isinstance(value, (list, tuple)) else []


def _state_items(state: Any, key: str) -> list[Any]:
    return _items_from_value(_state_value(state, key, []))


def _state_or_context_items(state: Any, key: str) -> list[Any]:
    if _has_state_key(state, key):
        return _state_items(state, key)
    return _items_from_value(_state_mapping(state, "context_bundle").get(key, []))


def _artifact_title(*values: Any, fallback: str) -> str:
    for value in values:
        title = _coerce_text(value, max_len=500)
        if title:
            return title
    return fallback[:500]


def _artifact_card_payload(
    *,
    work_id: UUID | str,
    phase: str,
    artifact_type: str,
    title: str,
    body: Any,
    payload: dict[str, Any],
    source_execution_id: UUID | str,
) -> dict[str, Any]:
    return {
        "work_id": work_id,
        "phase": phase,
        "artifact_type": artifact_type,
        "title": title,
        "body": body,
        "payload": payload,
        "source_execution_id": source_execution_id,
        "edit_source": "ai",
    }


def _artifact_cards_from_state(
    *,
    work_id: UUID | str,
    phase: str,
    source_execution_id: UUID | str,
    state: Any,
) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    phase = _coerce_text(phase).lower()

    if phase == "atlas":
        for item in _state_or_context_items(state, "sub_directions"):
            if not isinstance(item, dict):
                continue
            cards.append(
                _artifact_card_payload(
                    work_id=work_id,
                    phase="atlas",
                    artifact_type="atlas_direction",
                    title=_artifact_title(
                        item.get("name"),
                        item.get("title"),
                        item.get("label"),
                        fallback="Atlas direction",
                    ),
                    body=item.get("description"),
                    payload=item,
                    source_execution_id=source_execution_id,
                )
            )

    if phase == "frontier":
        for item in _state_items(state, "gaps"):
            if not isinstance(item, dict):
                continue
            cards.append(
                _artifact_card_payload(
                    work_id=work_id,
                    phase="frontier",
                    artifact_type="frontier_gap",
                    title=_artifact_title(
                        item.get("description"),
                        item.get("title"),
                        fallback="Frontier gap",
                    ),
                    body=item.get("potential_impact"),
                    payload=item,
                    source_execution_id=source_execution_id,
                )
            )
        for item in _state_items(state, "pain_points"):
            if not isinstance(item, dict):
                continue
            cards.append(
                _artifact_card_payload(
                    work_id=work_id,
                    phase="frontier",
                    artifact_type="frontier_pain_point",
                    title=_artifact_title(
                        item.get("statement"),
                        item.get("description"),
                        fallback="Pain point",
                    ),
                    body=item.get("pain_type"),
                    payload=item,
                    source_execution_id=source_execution_id,
                )
            )

    if phase == "divergent":
        for item in _state_items(state, "idea_cards"):
            if not isinstance(item, dict):
                continue
            cards.append(
                _artifact_card_payload(
                    work_id=work_id,
                    phase="divergent",
                    artifact_type="divergent_idea",
                    title=_artifact_title(
                        item.get("title"),
                        fallback="Innovation idea",
                    ),
                    body=item.get("problem_statement"),
                    payload=item,
                    source_execution_id=source_execution_id,
                )
            )

    return cards


def _extract_arxiv_id(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    lower = text.lower()
    for prefix in ("arxiv:", "arxiv/"):
        if lower.startswith(prefix):
            return text[len(prefix):].strip() or None
    if lower.startswith("arxiv.org/abs/"):
        return text.rsplit("/", 1)[-1].strip() or None
    if lower.startswith("https://arxiv.org/abs/") or lower.startswith("http://arxiv.org/abs/"):
        return text.rsplit("/", 1)[-1].strip() or None
    return text if any(char.isdigit() for char in text) and "." in text else None


def _paper_summary_arxiv_id(summary: dict[str, Any]) -> str | None:
    for key in ("arxiv_id", "paper_id", "candidate_id", "id"):
        arxiv_id = _extract_arxiv_id(summary.get(key))
        if arxiv_id:
            return arxiv_id
    return None


def _paper_summary_doi(summary: dict[str, Any]) -> str | None:
    for key in ("doi", "canonical_doi"):
        value = _coerce_text(summary.get(key))
        if value:
            return value
    return None


async def persist_results(
    run_id: UUID,
    state: Any,
    *,
    work_id: UUID | str | None = None,
    phase_execution_id: UUID | str | None = None,
    memory_persister: MemoryPersister | None = None,
    log: Any | None = None,
) -> None:
    """Persist workflow results to database-backed storage."""
    from apps.api.database import (
        create_artifact_card,
        create_context_bundle,
        create_idea_card,
        create_pain_point,
        update_phase_execution,
    )

    log = logger if log is None else log
    memory_persister = persist_run_memory if memory_persister is None else memory_persister
    output_bundle_id: Any | None = None

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
        output_bundle_id = await _persist_context_bundle(
            run_id,
            state,
            create_context_bundle=create_context_bundle,
            log=log,
        )
        await _persist_work_artifact_cards(
            work_id=work_id,
            phase_execution_id=phase_execution_id,
            state=state,
            output_bundle_id=output_bundle_id,
            create_artifact_card=create_artifact_card,
            update_phase_execution=update_phase_execution,
            log=log,
        )
        await _persist_research_memory(
            run_id,
            state,
            memory_persister=memory_persister,
            log=log,
        )

        log.info(
            "worker.results_persisted",
            run_id=str(run_id),
            pain_points=len(_state_items(state, "pain_points")),
            idea_cards=saved_ideas,
            has_comparison=bool(_state_items(state, "comparison_matrix")),
        )
    except Exception as exc:
        log.error("worker.persist_results_failed", error=str(exc))
        if phase_execution_id:
            await _mark_phase_execution_failed(
                phase_execution_id,
                update_phase_execution=update_phase_execution,
                log=log,
                error=exc,
                output_bundle_id=output_bundle_id,
            )


def _collect_pain_items(state: Any) -> list[dict[str, Any]]:
    all_pain_items = [
        item for item in _state_items(state, "pain_points") if isinstance(item, dict)
    ]
    for gap in _state_items(state, "gaps"):
        if not isinstance(gap, dict):
            continue
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
    context_bundle = _state_mapping(state, "context_bundle")
    paper_summaries = context_bundle.get("paper_summaries", [])
    if paper_summaries:
        try:
            from apps.api.database import get_pool
            pool = await get_pool()
            from uuid import uuid4 as _uuid4
            persisted_ids: list[str] = []
            failed = 0
            for ps in paper_summaries:
                if not isinstance(ps, dict):
                    continue
                title = _coerce_text(ps.get("title") or ps.get("paper_title"), max_len=500)
                if not title:
                    continue
                paper_id = _uuid4()
                arxiv_id = _paper_summary_arxiv_id(ps)
                doi = _paper_summary_doi(ps)
                metadata_json = json.loads(
                    json.dumps({**ps, "source_run_id": str(run_id)}, default=str)
                )
                try:
                    result = await pool.execute("""
                        INSERT INTO paper (id, canonical_title, normalized_title, doi, arxiv_id,
                            abstract, publication_year, venue, has_fulltext, fulltext_status,
                            metadata_json)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, TRUE, 'analyzed',
                            $9)
                        ON CONFLICT DO NOTHING
                    """,
                        paper_id,
                        title,
                        title.lower().strip()[:500],
                        doi,
                        arxiv_id,
                        _coerce_text(ps.get("abstract") or ps.get("summary"), max_len=2000),
                        ps.get("year"),
                        _coerce_text(ps.get("venue")),
                        metadata_json,
                    )
                    if result.endswith(" 1"):
                        persisted_ids.append(str(paper_id))
                except Exception as exc:
                    failed += 1
                    log.warning(
                        "worker.paper_persist_failed",
                        title=title[:80],
                        arxiv_id=arxiv_id,
                        error=str(exc),
                    )
            if persisted_ids:
                context_bundle = dict(context_bundle)
                context_bundle["selected_paper_ids"] = persisted_ids
                _set_state_value(state, "context_bundle", context_bundle)
            log.info(
                "worker.papers_persisted",
                count=len(persisted_ids),
                failed=failed,
            )
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
    for idea_card in _state_items(state, "idea_cards"):
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
) -> Any | None:
    bundle_data = _state_mapping(state, "context_bundle")
    if not bundle_data:
        return None
    try:
        report_text = _coerce_text(_state_value(state, "report_markdown"), max_len=5000)
        summary_text = bundle_data.get("summary_text") or report_text
        benchmark_data = {
            "comparison_matrix": _state_items(state, "comparison_matrix"),
            "gaps": _state_items(state, "gaps"),
            "pain_points_count": len(_state_items(state, "pain_points")),
            "papers_read": _state_value(state, "papers_read", 0) or 0,
            "papers_discovered": _state_value(state, "papers_discovered", 0) or 0,
        }
        for field in (
            "summary_text",
            "key_findings",
            "method_landscape",
            "benchmark_status",
            "entry_points",
            "mode_c_suggestions",
            "future_work",
            "pain_point_package",
            "paper_summaries",
        ):
            if field in bundle_data:
                benchmark_data[field] = bundle_data[field]
        bundle = await create_context_bundle({
            "source_run_id": str(run_id),
            "source_mode": _coerce_text(_state_value(state, "mode")) or "frontier",
            "summary_text": summary_text,
            "selected_paper_ids": bundle_data.get("selected_paper_ids", []),
            "benchmark_data": benchmark_data,
            "mindmap_json": bundle_data.get("mindmap_json", {}),
        })
        from apps.api.database import update_run
        await update_run(run_id, {"output_bundle_id": bundle["id"]})
        return bundle["id"]
    except Exception as exc:
        log.debug("persist_bundle_failed", error=str(exc))
        return None


async def _update_phase_execution_safely(
    phase_execution_id: UUID | str,
    updates: dict[str, Any],
    *,
    update_phase_execution: PhaseExecutionUpdater,
    log: Any,
) -> None:
    try:
        await update_phase_execution(_coerce_uuid(phase_execution_id), updates)
    except Exception as exc:
        log.warning(
            "worker.phase_execution_update_failed",
            phase_execution_id=str(phase_execution_id),
            error=str(exc),
        )


async def _mark_phase_execution_failed(
    phase_execution_id: UUID | str,
    *,
    update_phase_execution: PhaseExecutionUpdater,
    log: Any,
    error: Exception,
    output_bundle_id: Any | None = None,
) -> None:
    now = _utcnow()
    updates: dict[str, Any] = {
        "status": "failed",
        "error_message": str(error)[:500],
        "completed_at": now,
        "updated_at": now,
    }
    if output_bundle_id is not None:
        updates["output_bundle_id"] = output_bundle_id
    await _update_phase_execution_safely(
        phase_execution_id,
        updates,
        update_phase_execution=update_phase_execution,
        log=log,
    )


async def _persist_work_artifact_cards(
    *,
    work_id: UUID | str | None,
    phase_execution_id: UUID | str | None,
    state: Any,
    output_bundle_id: Any | None,
    create_artifact_card: ArtifactCardCreator,
    update_phase_execution: PhaseExecutionUpdater,
    log: Any,
) -> int:
    if not work_id or not phase_execution_id:
        return 0

    phase = _coerce_text(_state_value(state, "mode") or _state_value(state, "phase"))
    try:
        normalized_work_id = _coerce_uuid(work_id)
        normalized_phase_execution_id = _coerce_uuid(phase_execution_id)
        cards = _artifact_cards_from_state(
            work_id=normalized_work_id,
            phase=phase,
            source_execution_id=normalized_phase_execution_id,
            state=state,
        )
        for card in cards:
            await create_artifact_card(card)
    except Exception as exc:
        log.warning(
            "worker.artifact_card_extraction_failed",
            work_id=str(work_id),
            phase_execution_id=str(phase_execution_id),
            phase=phase,
            error=str(exc),
        )
        await _mark_phase_execution_failed(
            phase_execution_id,
            update_phase_execution=update_phase_execution,
            log=log,
            error=exc,
            output_bundle_id=output_bundle_id,
        )
        return 0

    now = _utcnow()
    updates: dict[str, Any] = {
        "status": "completed",
        "error_message": None,
        "completed_at": now,
        "updated_at": now,
    }
    if output_bundle_id is not None:
        updates["output_bundle_id"] = output_bundle_id
    await _update_phase_execution_safely(
        normalized_phase_execution_id,
        updates,
        update_phase_execution=update_phase_execution,
        log=log,
    )
    log.info(
        "worker.artifact_cards_persisted",
        work_id=str(normalized_work_id),
        phase_execution_id=str(normalized_phase_execution_id),
        phase=phase,
        count=len(cards),
    )
    return len(cards)


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
