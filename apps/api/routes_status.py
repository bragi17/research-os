"""Health and status API routes."""

from typing import Any

from fastapi import APIRouter, HTTPException
from structlog import get_logger

import apps.api.database as db

logger = get_logger(__name__)
router = APIRouter()


@router.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy", "service": "research-os-api"}


@router.get("/api/v1/status")
async def get_system_status() -> dict[str, Any]:
    """Get system status and metrics."""
    try:
        total = await db.count_runs()
        by_status = await db.count_runs_by_status()
    except Exception as exc:
        logger.error("status_query_failed", error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to query system status")

    all_statuses = ["queued", "running", "paused", "completed", "failed", "cancelled"]
    return {
        "version": "0.1.0",
        "runs_total": total,
        "runs_by_status": {status: by_status.get(status, 0) for status in all_statuses},
    }
