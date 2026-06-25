"""Queue status API routes."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from structlog import get_logger

import apps.api.database as db
from apps.api.auth import get_current_user
from apps.api.redis_queue import get_queue_length, get_redis
from apps.api.tenancy import WorkspaceContext

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/queue", tags=["queue"])


@router.get("/status")
async def get_queue_status(
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Get the current task queue status."""
    ctx = WorkspaceContext.from_user(user)
    redis_available = get_redis() is not None
    queue_length = await get_queue_length()

    try:
        by_status = await db.count_runs_by_status(workspace_id=ctx.workspace_id)
    except Exception as exc:
        logger.error("queue_status_runs_failed", error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to query run status")

    return {
        "redis_available": redis_available,
        "queue_length": queue_length,
        "active_runs": by_status.get("running", 0),
        "queued_runs": by_status.get("queued", 0),
        "paused_runs": by_status.get("paused", 0),
    }
