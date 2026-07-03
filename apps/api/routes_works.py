from __future__ import annotations

import contextlib
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4  # noqa: TC003

from fastapi import APIRouter, Depends, HTTPException, Query

import apps.api.database as db
from apps.api.auth import get_current_user
from apps.api.tenancy import WorkspaceContext
from libs.schemas.work import (
    ArtifactCardCreate,  # noqa: TC001
    ArtifactCardPatch,  # noqa: TC001
    PhaseExecutionCreate,  # noqa: TC001
    PhaseInputSelectionUpdate,  # noqa: TC001
    WorkCreate,  # noqa: TC001
)

router = APIRouter(prefix="/api/v1/works", tags=["works"])

VALID_PHASES = {"atlas", "frontier", "divergent"}
LEGACY_AUTO_SPAWN_POLICY_FLAGS = ("auto_continue", "auto_spawn_next")
ARTIFACT_CONTEXT_FIELDS = (
    "id",
    "work_id",
    "phase",
    "artifact_type",
    "title",
    "body",
    "payload",
    "status",
    "selection_state",
    "source_execution_id",
    "source_card_ids",
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def _get_work_or_404(work_id: UUID, ctx: WorkspaceContext) -> dict[str, Any]:
    work = await db.get_work(work_id, ctx.workspace_id)
    if work is None:
        raise HTTPException(status_code=404, detail="Work not found")
    return work


async def _get_artifact_card_for_work_or_404(
    work_id: UUID,
    card_id: UUID,
) -> dict[str, Any]:
    cards = await db.list_artifact_cards(work_id)
    for card in cards:
        if str(card.get("id")) == str(card_id):
            return card
    raise HTTPException(status_code=404, detail="Artifact card not found")


async def _ensure_artifact_cards_for_work_or_404(
    work_id: UUID,
    card_ids: list[UUID],
) -> None:
    if not card_ids:
        return
    cards = await db.list_artifact_cards(work_id)
    available_ids = {str(card.get("id")) for card in cards}
    if any(str(card_id) not in available_ids for card_id in card_ids):
        raise HTTPException(status_code=404, detail="Artifact card not found")


def _select_artifact_cards_or_404(
    cards: list[dict[str, Any]],
    source_card_ids: list[UUID],
) -> list[dict[str, Any]]:
    if not source_card_ids:
        return cards

    cards_by_id = {str(card.get("id")): card for card in cards}
    selected_cards: list[dict[str, Any]] = []
    for card_id in source_card_ids:
        card = cards_by_id.get(str(card_id))
        if card is None:
            raise HTTPException(status_code=404, detail="Artifact card not found")
        selected_cards.append(card)
    return selected_cards


def _json_safe_value(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, list):
        return [_json_safe_value(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe_value(item) for item in value]
    if isinstance(value, dict):
        return {
            str(key): _json_safe_value(item)
            for key, item in value.items()
        }
    return value


def _artifact_card_for_context(card: dict[str, Any]) -> dict[str, Any]:
    return {
        field: _json_safe_value(card[field])
        for field in ARTIFACT_CONTEXT_FIELDS
        if field in card
    }


def _phase_run_policy(policy: dict[str, Any] | None) -> dict[str, Any]:
    phase_policy = dict(policy or {})
    for flag in LEGACY_AUTO_SPAWN_POLICY_FLAGS:
        if phase_policy.get(flag) is True:
            phase_policy[flag] = False
    return phase_policy


def _context_bundle_from_cards(
    cards: list[dict[str, Any]],
    manual_input: dict[str, Any],
) -> dict[str, Any]:
    context_cards = [_artifact_card_for_context(card) for card in cards]
    bundle: dict[str, Any] = {
        "manual_input": _json_safe_value(manual_input),
        "artifact_cards": context_cards,
    }
    bundle["sub_directions"] = [
        card["payload"]
        for card in context_cards
        if card.get("artifact_type") == "atlas_direction"
    ]
    bundle["gaps"] = [
        card["payload"]
        for card in context_cards
        if card.get("artifact_type") == "frontier_gap"
    ]
    bundle["pain_points"] = [
        card["payload"]
        for card in context_cards
        if card.get("artifact_type") == "frontier_pain_point"
    ]
    bundle["idea_cards"] = [
        card["payload"]
        for card in context_cards
        if card.get("artifact_type") == "divergent_idea"
    ]
    return bundle


async def _mark_phase_enqueue_failed(run_id: UUID, execution_id: UUID) -> None:
    now = _utcnow()
    run_updates = {
        "status": "failed",
        "completed_at": now,
        "updated_at": now,
    }
    execution_updates = {
        "status": "failed",
        "error_message": "Failed to enqueue run",
        "completed_at": now,
        "updated_at": now,
    }
    with contextlib.suppress(Exception):
        await db.update_run(run_id, run_updates)
    with contextlib.suppress(Exception):
        await db.update_phase_execution(execution_id, execution_updates)


async def _mark_run_failed(run_id: UUID) -> None:
    now = _utcnow()
    with contextlib.suppress(Exception):
        await db.update_run(run_id, {
            "status": "failed",
            "completed_at": now,
            "updated_at": now,
        })


async def _mark_phase_enqueued(run_id: UUID, execution_id: UUID) -> dict[str, Any]:
    now = _utcnow()
    try:
        run = await db.update_run(run_id, {
            "status": "queued",
            "completed_at": None,
            "updated_at": now,
        })
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Failed to mark run queued",
        ) from exc
    if run is None:
        raise HTTPException(
            status_code=500,
            detail="Failed to mark run queued",
        )

    try:
        execution = await db.update_phase_execution(execution_id, {
            "status": "queued",
            "error_message": None,
            "completed_at": None,
            "updated_at": now,
        })
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Failed to mark phase execution queued",
        ) from exc

    if execution is None:
        raise HTTPException(
            status_code=500,
            detail="Failed to mark phase execution queued",
        )
    return execution


async def _ensure_phase_execution_for_work_or_404(
    work_id: UUID,
    execution_id: UUID | None,
) -> None:
    if execution_id is None:
        return
    executions = await db.list_phase_executions(work_id)
    if all(str(execution.get("id")) != str(execution_id) for execution in executions):
        raise HTTPException(status_code=404, detail="Phase execution not found")


@router.post("", status_code=201)
async def create_work(
    request: WorkCreate,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    ctx = WorkspaceContext.from_user(user)
    return await db.create_work({
        "workspace_id": ctx.workspace_id,
        "created_by": ctx.user_id,
        "title": request.title,
        "topic": request.topic,
        "project_id": request.project_id,
        "budget_json": request.budget,
        "policy_json": request.policy,
    })


@router.get("")
async def list_works(
    limit: int = Query(100, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    ctx = WorkspaceContext.from_user(user)
    items = await db.list_works(ctx.workspace_id, limit=limit, offset=offset)
    return {"items": items, "total": len(items)}


@router.get("/{work_id}")
async def get_work(
    work_id: UUID,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    ctx = WorkspaceContext.from_user(user)
    return await _get_work_or_404(work_id, ctx)


@router.get("/{work_id}/phases")
async def get_work_phases(
    work_id: UUID,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    ctx = WorkspaceContext.from_user(user)
    await _get_work_or_404(work_id, ctx)
    executions = await db.list_phase_executions(work_id)
    return {"work_id": str(work_id), "executions": executions}


@router.post("/{work_id}/phases/{phase}/executions", status_code=201)
async def start_phase_execution(
    work_id: UUID,
    phase: str,
    request: PhaseExecutionCreate,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    ctx = WorkspaceContext.from_user(user)
    if phase not in VALID_PHASES:
        raise HTTPException(status_code=400, detail="Invalid phase")
    if phase != request.phase:
        raise HTTPException(
            status_code=400,
            detail="Phase path and request body do not match",
        )

    work = await _get_work_or_404(work_id, ctx)
    cards = await db.list_artifact_cards(work_id)
    selected_cards = _select_artifact_cards_or_404(cards, request.source_card_ids)
    if phase != "atlas" and not selected_cards and not request.manual_input:
        raise HTTPException(
            status_code=400,
            detail="Select upstream cards or provide manual input before starting this phase",
        )

    now = _utcnow()
    run_id = uuid4()
    policy_json = _phase_run_policy(work.get("policy_json"))
    try:
        run = await db.create_run({
            "id": run_id,
            "workspace_id": ctx.workspace_id,
            "created_by": ctx.user_id,
            "title": f"{phase.title()}: {work['title']}",
            "topic": work["topic"],
            "status": "failed",
            "goal_type": "survey_plus_innovations",
            "autonomy_mode": "default_autonomous",
            "budget_json": work.get("budget_json") or {},
            "policy_json": policy_json,
            "current_step": None,
            "progress_pct": 0,
            "started_at": None,
            "completed_at": None,
            "created_at": now,
            "updated_at": now,
            "mode": phase,
            "parent_run_id": None,
            "context_bundle_id": None,
            "current_stage": "init",
            "project_id": work.get("project_id"),
        })
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Failed to create run") from exc

    try:
        execution = await db.create_phase_execution({
            "work_id": work_id,
            "phase": phase,
            "execution_kind": request.execution_kind,
            "status": "failed",
            "backing_run_id": run["id"],
            "input_json": {
                "manual_input": request.manual_input,
                "source_card_ids": [
                    str(card_id)
                    for card_id in request.source_card_ids
                ],
            },
        })
    except Exception as exc:
        await _mark_run_failed(run["id"])
        raise HTTPException(
            status_code=500,
            detail="Failed to create phase execution",
        ) from exc

    queue_payload = {
        "project_id": str(work["project_id"]) if work.get("project_id") else None,
        "topic": work["topic"],
        "goal_type": "survey_plus_innovations",
        "mode": phase,
        "keywords": policy_json.get("keywords", []),
        "seed_paper_ids": policy_json.get("seed_papers", []),
        "library_pool_ids": policy_json.get(
            "library_pool_ids",
            [],
        ),
        "budget": work.get("budget_json") or {},
        "work_id": str(work_id),
        "phase_execution_id": str(execution["id"]),
        "context_bundle": _context_bundle_from_cards(
            selected_cards,
            request.manual_input,
        ),
    }
    from apps.worker.task_queue import enqueue_run

    try:
        enqueued = await enqueue_run(run["id"], queue_payload)
    except Exception as exc:
        await _mark_phase_enqueue_failed(run["id"], execution["id"])
        raise HTTPException(status_code=503, detail="Failed to enqueue run") from exc
    if enqueued is False:
        await _mark_phase_enqueue_failed(run["id"], execution["id"])
        raise HTTPException(status_code=503, detail="Failed to enqueue run")
    return await _mark_phase_enqueued(run["id"], execution["id"])


@router.get("/{work_id}/artifact-cards")
async def get_artifact_cards(
    work_id: UUID,
    phase: str | None = Query(None),
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    ctx = WorkspaceContext.from_user(user)
    await _get_work_or_404(work_id, ctx)
    items = await db.list_artifact_cards(work_id, phase=phase)
    return {"items": items, "total": len(items)}


@router.post("/{work_id}/artifact-cards", status_code=201)
async def create_artifact_card(
    work_id: UUID,
    request: ArtifactCardCreate,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    ctx = WorkspaceContext.from_user(user)
    await _get_work_or_404(work_id, ctx)
    await _ensure_artifact_cards_for_work_or_404(work_id, request.source_card_ids)
    await _ensure_phase_execution_for_work_or_404(work_id, request.source_execution_id)
    return await db.create_artifact_card({
        **request.model_dump(),
        "work_id": work_id,
        "created_by": ctx.user_id,
        "edit_source": "user",
    })


@router.patch("/{work_id}/artifact-cards/{card_id}")
async def patch_artifact_card(
    work_id: UUID,
    card_id: UUID,
    request: ArtifactCardPatch,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    ctx = WorkspaceContext.from_user(user)
    await _get_work_or_404(work_id, ctx)

    updates = request.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No valid fields to update")

    await _get_artifact_card_for_work_or_404(work_id, card_id)
    updates["updated_by"] = ctx.user_id
    updates["updated_at"] = _utcnow()
    card = await db.update_artifact_card(card_id, updates)
    if card is None or str(card.get("work_id")) != str(work_id):
        raise HTTPException(status_code=404, detail="Artifact card not found")
    return card


@router.post("/{work_id}/phase-inputs/{phase}")
async def save_phase_inputs(
    work_id: UUID,
    phase: str,
    request: PhaseInputSelectionUpdate,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    ctx = WorkspaceContext.from_user(user)
    await _get_work_or_404(work_id, ctx)
    if phase not in VALID_PHASES:
        raise HTTPException(status_code=400, detail="Invalid phase")
    await _ensure_artifact_cards_for_work_or_404(work_id, request.source_card_ids)

    return await db.upsert_phase_input_selection(
        work_id=work_id,
        target_phase=phase,
        source_card_ids=request.source_card_ids,
        manual_input_json=request.manual_input,
        created_by=ctx.user_id,
    )
