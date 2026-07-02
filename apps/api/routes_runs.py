"""Research run lifecycle API routes."""

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from structlog import get_logger

import apps.api.database as db
from apps.api.auth import get_current_user
from apps.api.redis_queue import enqueue_run, publish_event
from apps.api.tenancy import WorkspaceContext
from libs.schemas.run import (
    CreateRunRequest,
    PauseRequest,
    ResumeRequest,
    RunResponse,
    RunStatus,
    Severity,
)

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/runs", tags=["runs"])


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _same_id(left: Any, right: Any) -> bool:
    return str(left) == str(right)


async def _require_project_access(
    project_id: UUID | None,
    user: dict[str, Any],
) -> None:
    if project_id is None:
        return
    try:
        project = await db.get_project(project_id)
    except Exception as exc:
        logger.error("get_project_failed", project_id=str(project_id), error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to retrieve project") from exc
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    owner_user_id = project.get("owner_user_id")
    if owner_user_id is None or not _same_id(owner_user_id, user["id"]):
        raise HTTPException(status_code=403, detail="Project access denied")


@router.post("", response_model=RunResponse, status_code=201)
async def create_run(
    request: CreateRunRequest,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Create a new research run."""
    ctx = WorkspaceContext.from_user(user)
    await _require_project_access(request.project_id, user)

    run_id = uuid4()
    now = _utcnow()

    run_data = {
        "id": run_id,
        "title": request.title,
        "topic": request.topic,
        "status": RunStatus.QUEUED.value,
        "goal_type": request.goal_type.value,
        "autonomy_mode": request.autonomy_mode.value,
        "budget_json": request.budget.model_dump(),
        "policy_json": request.policy.model_dump(),
        "progress_pct": 0,
        "current_step": None,
        "started_at": None,
        "completed_at": None,
        "created_at": now,
        "updated_at": now,
        "workspace_id": ctx.workspace_id,
        "created_by": ctx.user_id,
        "project_id": request.project_id,
    }

    try:
        row = await db.create_run(run_data)
    except Exception as exc:
        logger.error("create_run_failed", error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to create run") from exc

    try:
        await db.create_event(
            run_id=run_id,
            event_type="run.created",
            severity=Severity.INFO.value,
            payload={"title": request.title, "topic": request.topic[:100]},
        )
    except Exception as exc:
        logger.warning("create_event_failed", run_id=str(run_id), error=str(exc))

    logger.info("run_created", run_id=str(run_id), title=request.title)
    return row


@router.get("", response_model=list[RunResponse])
async def list_runs(
    status: RunStatus | None = Query(None, description="Filter by status"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: dict[str, Any] = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """List research runs with optional filtering."""
    ctx = WorkspaceContext.from_user(user)
    try:
        status_value = status.value if status else None
        return await db.list_runs(
            status=status_value,
            limit=limit,
            offset=offset,
            workspace_id=ctx.workspace_id,
        )
    except Exception as exc:
        logger.error("list_runs_failed", error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to list runs") from exc


@router.get("/{run_id}", response_model=RunResponse)
async def get_run(
    run_id: UUID,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Get details of a specific research run."""
    ctx = WorkspaceContext.from_user(user)
    try:
        row = await db.get_run(run_id, workspace_id=ctx.workspace_id)
    except Exception as exc:
        logger.error("get_run_failed", run_id=str(run_id), error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to get run") from exc

    if row is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return row


@router.get("/{run_id}/children", response_model=list[RunResponse])
async def get_run_children(
    run_id: UUID,
    mode: str | None = Query(None, description="Filter child runs by mode"),
    user: dict[str, Any] = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """List child runs for a parent run within the current workspace."""
    ctx = WorkspaceContext.from_user(user)
    try:
        parent = await db.get_run(run_id, workspace_id=ctx.workspace_id)
        if parent is None:
            raise HTTPException(status_code=404, detail="Run not found")
        children = await db.list_child_runs(run_id, mode=mode)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("list_run_children_failed", run_id=str(run_id), error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to list run children") from exc

    return [
        child for child in children
        if str(child.get("workspace_id")) == str(ctx.workspace_id)
    ]


@router.patch("/{run_id}")
async def patch_run(
    run_id: UUID,
    body: dict[str, Any],
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Update run fields."""
    ctx = WorkspaceContext.from_user(user)
    allowed = {"title"}
    updates = {key: value for key, value in body.items() if key in allowed}
    if not updates:
        raise HTTPException(status_code=400, detail="No valid fields to update")

    try:
        run = await db.get_run(run_id, workspace_id=ctx.workspace_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found")
        updates["updated_at"] = _utcnow()
        result = await db.update_run(run_id, updates)
        if result is None:
            raise HTTPException(status_code=404, detail="Run not found")
        return result
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("patch_run_failed", error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to update run") from exc


@router.delete("/{run_id}")
async def delete_run(
    run_id: UUID,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, str]:
    """Delete a research run and its related rows."""
    ctx = WorkspaceContext.from_user(user)
    try:
        run = await db.get_run(run_id, workspace_id=ctx.workspace_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found")
        pool = await db.get_pool()
        await pool.execute("DELETE FROM run_event WHERE run_id = $1", run_id)
        await pool.execute("DELETE FROM pain_point WHERE run_id = $1", run_id)
        await pool.execute("DELETE FROM reading_path WHERE run_id = $1", run_id)
        await pool.execute("DELETE FROM idea_card WHERE run_id = $1", run_id)
        await pool.execute("DELETE FROM research_run WHERE id = $1", run_id)
        return {"status": "deleted", "run_id": str(run_id)}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("delete_run_failed", error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to delete run") from exc


@router.post("/{run_id}/start")
async def start_run(
    run_id: UUID,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Start a queued research run."""
    ctx = WorkspaceContext.from_user(user)
    try:
        run = await db.get_run(run_id, workspace_id=ctx.workspace_id)
    except Exception as exc:
        logger.error("start_run_get_failed", run_id=str(run_id), error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to retrieve run") from exc

    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if run["status"] not in [RunStatus.QUEUED.value, RunStatus.PAUSED.value]:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot start run in status: {run['status']}",
        )

    enqueued = await enqueue_run(run_id, run)
    if not enqueued:
        try:
            await db.create_event(
                run_id=run_id,
                event_type="run.enqueue_failed",
                severity=Severity.ERROR.value,
                payload={"reason": "queue_unavailable"},
            )
        except Exception as exc:
            logger.warning("create_event_failed", run_id=str(run_id), error=str(exc))
        logger.warning("run_enqueue_failed", run_id=str(run_id))
        raise HTTPException(status_code=503, detail="Failed to enqueue run")

    now = _utcnow()
    try:
        await db.update_run(run_id, {
            "status": RunStatus.QUEUED.value,
            "pause_reason": None,
            "updated_at": now,
        })
    except Exception as exc:
        logger.error("start_run_update_failed", run_id=str(run_id), error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to update run") from exc

    try:
        await db.create_event(
            run_id=run_id,
            event_type="run.enqueued",
            severity=Severity.INFO.value,
            payload={"enqueued": enqueued},
        )
        await publish_event(run_id, {
            "event_type": "run.enqueued",
            "severity": "info",
            "payload": {"enqueued": enqueued},
            "timestamp": now.isoformat(),
        })
    except Exception as exc:
        logger.warning("create_event_failed", run_id=str(run_id), error=str(exc))

    logger.info("run_enqueued", run_id=str(run_id), enqueued=enqueued)
    return {"status": "queued", "run_id": str(run_id), "enqueued": enqueued}


@router.post("/{run_id}/pause")
async def pause_run(
    run_id: UUID,
    request: PauseRequest,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Pause a running research run."""
    ctx = WorkspaceContext.from_user(user)
    try:
        run = await db.get_run(run_id, workspace_id=ctx.workspace_id)
    except Exception as exc:
        logger.error("pause_run_get_failed", run_id=str(run_id), error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to retrieve run") from exc

    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if run["status"] != RunStatus.RUNNING.value:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot pause run in status: {run['status']}",
        )

    now = _utcnow()
    pause_reason = f"user_{request.mode}_pause"
    try:
        await db.update_run(run_id, {
            "status": RunStatus.PAUSED.value,
            "pause_reason": pause_reason,
            "updated_at": now,
        })
    except Exception as exc:
        logger.error("pause_run_update_failed", run_id=str(run_id), error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to update run") from exc

    try:
        await db.create_event(
            run_id=run_id,
            event_type="run.paused",
            severity=Severity.INFO.value,
            payload={"mode": request.mode},
        )
    except Exception as exc:
        logger.warning("create_event_failed", run_id=str(run_id), error=str(exc))

    logger.info("run_paused", run_id=str(run_id), mode=request.mode)
    return {"status": "paused", "run_id": str(run_id), "mode": request.mode}


@router.post("/{run_id}/resume")
async def resume_run(
    run_id: UUID,
    request: ResumeRequest,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Resume a paused research run."""
    ctx = WorkspaceContext.from_user(user)
    try:
        run = await db.get_run(run_id, workspace_id=ctx.workspace_id)
    except Exception as exc:
        logger.error("resume_run_get_failed", run_id=str(run_id), error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to retrieve run") from exc

    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if run["status"] != RunStatus.PAUSED.value:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot resume run in status: {run['status']}",
        )

    now = _utcnow()
    try:
        await db.update_run(run_id, {
            "status": RunStatus.RUNNING.value,
            "pause_reason": None,
            "updated_at": now,
        })
    except Exception as exc:
        logger.error("resume_run_update_failed", run_id=str(run_id), error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to update run") from exc

    patch_applied = request.patch or {}
    try:
        await db.create_event(
            run_id=run_id,
            event_type="run.resumed",
            severity=Severity.INFO.value,
            payload={"patch_applied": bool(patch_applied)},
        )
    except Exception as exc:
        logger.warning("create_event_failed", run_id=str(run_id), error=str(exc))

    logger.info("run_resumed", run_id=str(run_id), patch=bool(request.patch))
    return {"status": "resumed", "run_id": str(run_id), "patch_applied": patch_applied}


@router.post("/{run_id}/cancel")
async def cancel_run(
    run_id: UUID,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Cancel a research run."""
    ctx = WorkspaceContext.from_user(user)
    try:
        run = await db.get_run(run_id, workspace_id=ctx.workspace_id)
    except Exception as exc:
        logger.error("cancel_run_get_failed", run_id=str(run_id), error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to retrieve run") from exc

    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    terminal = {RunStatus.COMPLETED.value, RunStatus.CANCELLED.value, RunStatus.FAILED.value}
    if run["status"] in terminal:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel run in status: {run['status']}",
        )

    now = _utcnow()
    try:
        await db.update_run(run_id, {
            "status": RunStatus.CANCELLED.value,
            "updated_at": now,
            "completed_at": now,
        })
    except Exception as exc:
        logger.error("cancel_run_update_failed", run_id=str(run_id), error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to update run") from exc

    try:
        await db.create_event(
            run_id=run_id,
            event_type="run.cancelled",
            severity=Severity.INFO.value,
            payload={},
        )
    except Exception as exc:
        logger.warning("create_event_failed", run_id=str(run_id), error=str(exc))

    logger.info("run_cancelled", run_id=str(run_id))
    return {"status": "cancelled", "run_id": str(run_id)}
