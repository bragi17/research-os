"""Health and status API routes."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from structlog import get_logger

import apps.api.database as db
from apps.api.auth import get_current_user
from apps.api.tenancy import WorkspaceContext

logger = get_logger(__name__)
router = APIRouter()


@router.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy", "service": "research-os-api"}


@router.get("/api/v1/status")
async def get_system_status(
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Get system status and metrics."""
    ctx = WorkspaceContext.from_user(user)
    try:
        total = await db.count_runs(workspace_id=ctx.workspace_id)
        by_status = await db.count_runs_by_status(workspace_id=ctx.workspace_id)
    except Exception as exc:
        logger.error("status_query_failed", error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to query system status") from exc

    all_statuses = ["queued", "running", "paused", "completed", "failed", "cancelled"]
    return {
        "version": "0.1.0",
        "runs_total": total,
        "runs_by_status": {status: by_status.get(status, 0) for status in all_statuses},
    }
