"""
Research OS - V2 Mode-Aware API Routes

FastAPI APIRouter providing v2 endpoints for multi-mode research runs.
Adds mode selection, run spawning, pain points, idea cards, figures,
reading paths, context bundles, and generated output endpoints.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from structlog import get_logger

from apps.api.auth import get_current_user

from apps.api.database import (
    create_context_bundle,
    create_event,
    create_run as db_create_run,
    get_context_bundle,
    get_reading_path,
    get_run as db_get_run,
    list_figures_by_run,
    list_idea_cards,
    list_pain_points,
    update_run as db_update_run,
)
from libs.schemas.multimode import ResearchMode, SpawnRunRequest

logger = get_logger(__name__)

# Redis configuration (shared with main module)
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
REDIS_EVENTS_CHANNEL = "research_os:events"

router = APIRouter(prefix="/api/v1", tags=["v1-multimode"])


# ---------------------------------------------------------------------------
# Request / Response Models
# ---------------------------------------------------------------------------


class CreateRunV2Request(BaseModel):
    """Request body for creating a v2 mode-aware run."""

    title: str = Field(..., min_length=3)
    topic: str = Field(..., min_length=10)
    mode: ResearchMode = Field(default=ResearchMode.INTAKE)
    keywords: list[str] = Field(default_factory=list)
    seed_papers: list[str] = Field(default_factory=list)
    constraints: dict[str, Any] = Field(default_factory=dict)
    parent_run_id: UUID | None = None
    context_bundle_id: UUID | None = None


class UserActionRequest(BaseModel):
    """Request body for the unified user-action endpoint."""

    payload: dict[str, Any] = Field(default_factory=dict)


VALID_ACTIONS = frozenset({
    "pin_paper",
    "exclude_paper",
    "tighten_scope",
    "expand_scope",
    "switch_mode",
    "request_more_figures",
    "send_to_mode_c",
    "recheck_prior_art",
})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_redis():
    """Return the Redis connection from the main module, or None."""
    try:
        from apps.api.main import _redis
        return _redis
    except Exception:
        return None


async def _publish_event(run_id: UUID, event_data: dict[str, Any]) -> None:
    """Publish an event to Redis pub/sub channel."""
    redis = await _get_redis()
    if redis is None:
        return
    try:
        channel = f"{REDIS_EVENTS_CHANNEL}:{run_id}"
        await redis.publish(channel, json.dumps(event_data, default=str))
    except Exception as exc:
        logger.warning("publish_event_failed", run_id=str(run_id), error=str(exc))


async def _require_run(run_id: UUID) -> dict[str, Any]:
    """Fetch a run or raise 404."""
    try:
        run = await db_get_run(run_id)
    except Exception as exc:
        logger.error("get_run_failed", run_id=str(run_id), error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to retrieve run")
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


# ---------------------------------------------------------------------------
# 1. POST /api/v2/runs  -- create run WITH mode
# ---------------------------------------------------------------------------


@router.post("/runs/multimode", status_code=201)
async def create_run_v2(
    request: CreateRunV2Request,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Create a new research run with an explicit research mode."""
    run_id = uuid4()
    now = datetime.utcnow()

    run_data: dict[str, Any] = {
        "id": run_id,
        "title": request.title,
        "topic": request.topic,
        "status": "queued",
        "goal_type": "survey_plus_innovations",
        "autonomy_mode": "default_autonomous",
        "budget_json": {},
        "policy_json": {"keywords": request.keywords, "seed_papers": request.seed_papers},
        "progress_pct": 0,
        "current_step": None,
        "started_at": None,
        "completed_at": None,
        "created_at": now,
        "updated_at": now,
        "workspace_id": user["workspace_id"],
        "created_by": user["id"],
        # v2 multi-mode columns
        "mode": request.mode.value,
        "parent_run_id": request.parent_run_id,
        "context_bundle_id": request.context_bundle_id,
        "current_stage": "init",
    }

    try:
        row = await db_create_run(run_data)
    except Exception as exc:
        logger.error("create_run_v2_failed", error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to create run")

    # Emit initial event
    try:
        await create_event(
            run_id=run_id,
            event_type="run.created",
            severity="info",
            payload={
                "title": request.title,
                "mode": request.mode.value,
                "parent_run_id": str(request.parent_run_id) if request.parent_run_id else None,
            },
        )
    except Exception as exc:
        logger.warning("create_event_failed", run_id=str(run_id), error=str(exc))

    logger.info("run_v2_created", run_id=str(run_id), mode=request.mode.value)

    # Merge mode into response even if DB doesn't return it
    result = dict(row)
    result.setdefault("mode", request.mode.value)
    result.setdefault("parent_run_id", request.parent_run_id)
    result.setdefault("context_bundle_id", request.context_bundle_id)
    result.setdefault("current_stage", "init")
    return result


# ---------------------------------------------------------------------------
# 2. POST /api/v2/runs/{run_id}/spawn  -- spawn child run from parent
# ---------------------------------------------------------------------------


@router.post("/runs/{run_id}/spawn", status_code=201)
async def spawn_run(
    run_id: UUID,
    request: SpawnRunRequest,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Spawn a child run from an existing parent run."""
    parent = await _require_run(run_id)

    child_id = uuid4()
    now = datetime.utcnow()

    child_data: dict[str, Any] = {
        "id": child_id,
        "title": f"[{request.target_mode.value}] child of {parent.get('title', 'unknown')}",
        "topic": parent.get("topic", ""),
        "status": "queued",
        "goal_type": parent.get("goal_type", "survey_plus_innovations"),
        "autonomy_mode": parent.get("autonomy_mode", "default_autonomous"),
        "budget_json": parent.get("budget_json", {}),
        "policy_json": parent.get("policy_json", {}),
        "progress_pct": 0,
        "current_step": None,
        "started_at": None,
        "completed_at": None,
        "created_at": now,
        "updated_at": now,
        "workspace_id": user["workspace_id"],
        "created_by": user["id"],
        # v2 multi-mode columns
        "mode": request.target_mode.value,
        "parent_run_id": run_id,
        "context_bundle_id": request.context_bundle_id,
        "current_stage": "init",
    }

    try:
        row = await db_create_run(child_data)
    except Exception as exc:
        logger.error("spawn_run_failed", parent_id=str(run_id), error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to spawn child run")

    # Record event on parent
    try:
        await create_event(
            run_id=run_id,
            event_type="run.child_spawned",
            severity="info",
            payload={
                "child_run_id": str(child_id),
                "target_mode": request.target_mode.value,
            },
        )
    except Exception as exc:
        logger.warning("create_event_failed", run_id=str(run_id), error=str(exc))

    logger.info(
        "run_spawned",
        parent_id=str(run_id),
        child_id=str(child_id),
        target_mode=request.target_mode.value,
    )

    result = dict(row)
    result.setdefault("mode", request.target_mode.value)
    result.setdefault("parent_run_id", run_id)
    result.setdefault("context_bundle_id", request.context_bundle_id)
    result.setdefault("current_stage", "init")
    return result


# ---------------------------------------------------------------------------
# 3. GET /api/v2/runs/{run_id}/pain-points
# ---------------------------------------------------------------------------


@router.get("/runs/{run_id}/pain-points")
async def get_pain_points(
    run_id: UUID,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """List pain points identified for a run."""
    await _require_run(run_id)
    try:
        items = await list_pain_points(run_id, limit=limit, offset=offset)
    except Exception as exc:
        logger.error("list_pain_points_failed", run_id=str(run_id), error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to list pain points")
    return {"run_id": str(run_id), "items": items}


# ---------------------------------------------------------------------------
# 4. GET /api/v2/runs/{run_id}/idea-cards
# ---------------------------------------------------------------------------


@router.get("/runs/{run_id}/idea-cards")
async def get_idea_cards(
    run_id: UUID,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """List idea cards generated for a run."""
    await _require_run(run_id)
    try:
        items = await list_idea_cards(run_id, limit=limit, offset=offset)
    except Exception as exc:
        logger.error("list_idea_cards_failed", run_id=str(run_id), error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to list idea cards")
    return {"run_id": str(run_id), "items": items}


# ---------------------------------------------------------------------------
# 5. GET /api/v2/runs/{run_id}/figures
# ---------------------------------------------------------------------------


@router.get("/runs/{run_id}/figures")
async def get_figures(
    run_id: UUID,
    limit: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    """List extracted figures for a run."""
    await _require_run(run_id)
    try:
        items = await list_figures_by_run(run_id, limit=limit)
    except Exception as exc:
        logger.error("list_figures_failed", run_id=str(run_id), error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to list figures")
    return {"run_id": str(run_id), "items": items}


# ---------------------------------------------------------------------------
# 6. GET /api/v2/runs/{run_id}/reading-path
# ---------------------------------------------------------------------------


@router.get("/runs/{run_id}/reading-path")
async def get_run_reading_path(run_id: UUID) -> dict[str, Any]:
    """Get the reading path generated for a run."""
    await _require_run(run_id)
    try:
        path = await get_reading_path(run_id)
    except Exception as exc:
        logger.error("get_reading_path_failed", run_id=str(run_id), error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to get reading path")
    return {"run_id": str(run_id), "reading_path": path}


# ---------------------------------------------------------------------------
# 7. GET /api/v2/runs/{run_id}/context-bundle
# ---------------------------------------------------------------------------


@router.get("/runs/{run_id}/context-bundle")
async def get_run_context_bundle(run_id: UUID) -> dict[str, Any]:
    """Get the output context bundle for a run."""
    run = await _require_run(run_id)
    bundle_id = run.get("output_bundle_id") or run.get("context_bundle_id")
    if bundle_id is None:
        return {"run_id": str(run_id), "context_bundle": None}
    try:
        bundle = await get_context_bundle(bundle_id)
    except Exception as exc:
        logger.error("get_context_bundle_failed", run_id=str(run_id), error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to get context bundle")
    return {"run_id": str(run_id), "context_bundle": bundle}


# ---------------------------------------------------------------------------
# 8-11. Generated output endpoints (timeline, taxonomy, comparison, mindmap)
#
# These are generated by the workflow and stored in the context_bundle's
# JSONB fields or as run output. For now we pull from the context_bundle
# mindmap_json / benchmark_data or return empty structures.
# ---------------------------------------------------------------------------


async def _get_bundle_for_run(run_id: UUID) -> dict[str, Any] | None:
    """Fetch the output context bundle for a run, if available."""
    run = await _require_run(run_id)
    bundle_id = run.get("output_bundle_id") or run.get("context_bundle_id")
    if bundle_id is None:
        return None
    try:
        return await get_context_bundle(bundle_id)
    except Exception:
        return None


@router.get("/runs/{run_id}/timeline")
async def get_run_timeline(run_id: UUID) -> dict[str, Any]:
    """Get timeline data for a run."""
    bundle = await _get_bundle_for_run(run_id)
    timeline_data: dict[str, Any] = {}
    if bundle is not None:
        benchmark = bundle.get("benchmark_data")
        if isinstance(benchmark, dict):
            timeline_data = benchmark.get("timeline", {})
    return {"run_id": str(run_id), "timeline": timeline_data}


@router.get("/runs/{run_id}/taxonomy")
async def get_run_taxonomy(run_id: UUID) -> dict[str, Any]:
    """Get taxonomy tree data for a run."""
    bundle = await _get_bundle_for_run(run_id)
    taxonomy_data: dict[str, Any] = {}
    if bundle is not None:
        benchmark = bundle.get("benchmark_data")
        if isinstance(benchmark, dict):
            taxonomy_data = benchmark.get("taxonomy", {})
    return {"run_id": str(run_id), "taxonomy": taxonomy_data}


@router.get("/runs/{run_id}/comparison")
async def get_run_comparison(run_id: UUID) -> dict[str, Any]:
    """Get comparison matrix data for a run."""
    bundle = await _get_bundle_for_run(run_id)
    comparison_data: dict[str, Any] = {}
    if bundle is not None:
        benchmark = bundle.get("benchmark_data")
        if isinstance(benchmark, dict):
            comparison_data = benchmark.get("comparison", {})
    return {"run_id": str(run_id), "comparison": comparison_data}


@router.get("/runs/{run_id}/mindmap")
async def get_run_mindmap(run_id: UUID) -> dict[str, Any]:
    """Get mind map JSON for a run."""
    bundle = await _get_bundle_for_run(run_id)
    mindmap_data: dict[str, Any] = {}
    if bundle is not None:
        mindmap = bundle.get("mindmap_json")
        if isinstance(mindmap, dict):
            mindmap_data = mindmap
    return {"run_id": str(run_id), "mindmap": mindmap_data}


# ---------------------------------------------------------------------------
# 12. POST /api/v2/runs/{run_id}/actions/{action}  -- unified user action
# ---------------------------------------------------------------------------


@router.post("/runs/{run_id}/actions/{action}")
async def perform_action(
    run_id: UUID,
    action: str,
    request: UserActionRequest,
) -> dict[str, Any]:
    """
    Unified user-action endpoint.

    Records the action as a run_event with type ``user.action.<action_name>``
    and publishes it to Redis so the worker can pick it up on its next iteration.

    Valid actions: pin_paper, exclude_paper, tighten_scope, expand_scope,
    switch_mode, request_more_figures, send_to_mode_c, recheck_prior_art.
    """
    if action not in VALID_ACTIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid action: {action}. Must be one of: {', '.join(sorted(VALID_ACTIONS))}",
        )

    await _require_run(run_id)

    event_type = f"user.action.{action}"
    now = datetime.utcnow()

    try:
        await create_event(
            run_id=run_id,
            event_type=event_type,
            severity="info",
            payload=request.payload,
        )
    except Exception as exc:
        logger.error("create_action_event_failed", run_id=str(run_id), error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to record action")

    # Publish to Redis for the worker
    await _publish_event(run_id, {
        "event_type": event_type,
        "payload": request.payload,
        "timestamp": now.isoformat(),
    })

    # Handle switch_mode specially: update the run's mode column
    if action == "switch_mode" and "target_mode" in request.payload:
        try:
            await db_update_run(run_id, {
                "mode": request.payload["target_mode"],
                "updated_at": now,
            })
        except Exception as exc:
            logger.warning("switch_mode_update_failed", run_id=str(run_id), error=str(exc))

    logger.info("user_action_recorded", run_id=str(run_id), action=action)

    return {
        "run_id": str(run_id),
        "action": action,
        "status": "recorded",
    }
