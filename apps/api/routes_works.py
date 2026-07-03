from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID  # noqa: TC003

from fastapi import APIRouter, Depends, HTTPException, Query

import apps.api.database as db
from apps.api.auth import get_current_user
from apps.api.tenancy import WorkspaceContext
from libs.schemas.work import (
    ArtifactCardCreate,  # noqa: TC001
    ArtifactCardPatch,  # noqa: TC001
    PhaseInputSelectionUpdate,  # noqa: TC001
    WorkCreate,  # noqa: TC001
)

router = APIRouter(prefix="/api/v1/works", tags=["works"])

VALID_PHASES = {"atlas", "frontier", "divergent"}


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
