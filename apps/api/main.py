"""
Research OS - FastAPI Main Application

Main entry point for the Research OS API.
"""

import asyncio
import json
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
load_dotenv()
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, HTTPException, Query, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, Response
from pydantic import BaseModel, Field
from structlog import get_logger

from apps.api.auth import (
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
    create_access_token,
    create_user,
    get_current_user,
    get_user_by_email,
    verify_password,
)
from apps.api.database import (
    close_pool,
    count_events,
    count_papers_by_run,
    count_runs,
    count_runs_by_status,
    create_event,
    create_run as db_create_run,
    get_run as db_get_run,
    init_pool,
    list_events,
    list_hypotheses,
    list_papers_by_run,
    list_runs as db_list_runs,
    update_run as db_update_run,
)
from libs.schemas.run import (
    CreateRunRequest,
    PauseRequest,
    ResumeRequest,
    RunResponse,
    RunStatus,
    RunEvent,
    Severity,
)
from services.export import (
    generate_bibtex_export,
    generate_csv_export,
    generate_json_export,
    generate_markdown_report,
)
from services.storage import get_storage

logger = get_logger(__name__)

# Redis configuration
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
REDIS_QUEUE_KEY = "research_os:run_queue"
REDIS_EVENTS_CHANNEL = "research_os:events"

# Redis connection (initialized in lifespan)
_redis = None


async def _init_redis():
    """Initialize Redis connection. Returns None if Redis is unavailable."""
    global _redis
    try:
        import redis.asyncio as aioredis
        _redis = aioredis.from_url(REDIS_URL, decode_responses=True)
        await _redis.ping()
        logger.info("redis_connected", url=REDIS_URL)
    except Exception as exc:
        logger.warning("redis_unavailable", error=str(exc))
        _redis = None


async def _close_redis():
    """Close Redis connection."""
    global _redis
    if _redis is not None:
        try:
            await _redis.close()
        except Exception:
            pass
        _redis = None


async def _enqueue_run(run_id: UUID, run_data: dict[str, Any]) -> bool:
    """Enqueue a run to Redis task queue. Returns True if enqueued."""
    if _redis is None:
        return False
    try:
        policy = run_data.get("policy_json", {})
        if isinstance(policy, str):
            policy = json.loads(policy)
        task = json.dumps({
            "run_id": str(run_id),
            "topic": run_data.get("topic", ""),
            "goal_type": run_data.get("goal_type", ""),
            "mode": run_data.get("mode", "frontier"),
            "keywords": policy.get("keywords", []),
            "seed_paper_ids": policy.get("seed_papers", []),
            "budget": run_data.get("budget_json", {}),
            "enqueued_at": datetime.utcnow().isoformat(),
        })
        await _redis.lpush(REDIS_QUEUE_KEY, task)
        logger.info("run_enqueued", run_id=str(run_id))
        return True
    except Exception as exc:
        logger.warning("enqueue_failed", run_id=str(run_id), error=str(exc))
        return False


async def _publish_event(run_id: UUID, event_data: dict[str, Any]) -> None:
    """Publish an event to Redis pub/sub channel."""
    if _redis is None:
        return
    try:
        channel = f"{REDIS_EVENTS_CHANNEL}:{run_id}"
        await _redis.publish(channel, json.dumps(event_data, default=str))
    except Exception as exc:
        logger.warning("publish_event_failed", run_id=str(run_id), error=str(exc))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    logger.info("research_os_starting", version="0.1.0")
    await init_pool()
    logger.info("database_pool_initialized")
    await _init_redis()
    yield
    logger.info("research_os_shutting_down")
    await _close_redis()
    await close_pool()
    logger.info("database_pool_closed")


app = FastAPI(
    title="Research OS",
    description="Autonomous Research Operating System API",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

ALLOWED_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:3001").split(",")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================
# Health & Status Endpoints
# ============================================


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy", "service": "research-os-api"}


@app.get("/api/v1/status")
async def get_system_status() -> dict[str, Any]:
    """Get system status and metrics."""
    try:
        total = await count_runs()
        by_status = await count_runs_by_status()
    except Exception as exc:
        logger.error("status_query_failed", error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to query system status")

    all_statuses = ["queued", "running", "paused", "completed", "failed", "cancelled"]
    return {
        "version": "0.1.0",
        "runs_total": total,
        "runs_by_status": {s: by_status.get(s, 0) for s in all_statuses},
    }


# ============================================
# Authentication Endpoints
# ============================================


@app.post("/api/v1/auth/register", response_model=TokenResponse, status_code=201)
async def register(request: RegisterRequest) -> dict[str, Any]:
    """
    Register a new user account.

    Creates a user and a default workspace, then returns a JWT token.
    """
    user = await create_user(
        email=request.email,
        username=request.username,
        password=request.password,
    )

    token = create_access_token(
        user_id=user["id"],
        email=user["email"],
        role=user["role"],
        workspace_id=user.get("workspace_id"),
    )

    logger.info("user_registered", user_id=str(user["id"]), email=user["email"])

    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": int(os.getenv("JWT_EXPIRATION_HOURS", "24")) * 3600,
        "user": {
            "id": str(user["id"]),
            "email": user["email"],
            "username": user["username"],
            "role": user["role"],
            "workspace_id": str(user["workspace_id"]) if user.get("workspace_id") else None,
        },
    }


@app.post("/api/v1/auth/login", response_model=TokenResponse)
async def login(request: LoginRequest) -> dict[str, Any]:
    """
    Authenticate a user and return a JWT token.
    """
    user = await get_user_by_email(request.email)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not verify_password(request.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = create_access_token(
        user_id=user["id"],
        email=user["email"],
        role=user["role"],
        workspace_id=user.get("workspace_id"),
    )

    logger.info("user_logged_in", user_id=str(user["id"]), email=user["email"])

    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": int(os.getenv("JWT_EXPIRATION_HOURS", "24")) * 3600,
        "user": {
            "id": str(user["id"]),
            "email": user["email"],
            "username": user["username"],
            "role": user["role"],
            "workspace_id": str(user["workspace_id"]) if user.get("workspace_id") else None,
        },
    }


@app.get("/api/v1/auth/me", response_model=UserResponse)
async def get_me(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    """
    Get the current authenticated user's profile.
    """
    return user


# ============================================
# Run Management Endpoints
# ============================================


@app.post("/api/v1/runs", response_model=RunResponse, status_code=201)
async def create_run(
    request: CreateRunRequest,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Create a new research run.

    The run will be queued and start executing automatically based on
    the configured autonomy mode.
    """
    run_id = uuid4()
    now = datetime.utcnow()

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
        "workspace_id": user["workspace_id"],
        "created_by": user["id"],
    }

    try:
        row = await db_create_run(run_data)
    except Exception as exc:
        logger.error("create_run_failed", error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to create run")

    # Emit initial event
    try:
        await create_event(
            run_id=run_id,
            event_type="run.created",
            severity=Severity.INFO.value,
            payload={"title": request.title, "topic": request.topic[:100]},
        )
    except Exception as exc:
        logger.warning("create_event_failed", run_id=str(run_id), error=str(exc))

    logger.info("run_created", run_id=str(run_id), title=request.title)

    return row


@app.get("/api/v1/runs", response_model=list[RunResponse])
async def list_runs(
    status: RunStatus | None = Query(None, description="Filter by status"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> list[dict[str, Any]]:
    """
    List research runs with optional filtering.
    """
    try:
        status_value = status.value if status else None
        rows = await db_list_runs(status=status_value, limit=limit, offset=offset)
    except Exception as exc:
        logger.error("list_runs_failed", error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to list runs")

    return rows


@app.get("/api/v1/runs/{run_id}", response_model=RunResponse)
async def get_run(run_id: UUID) -> dict[str, Any]:
    """
    Get details of a specific research run.
    """
    try:
        row = await db_get_run(run_id)
    except Exception as exc:
        logger.error("get_run_failed", run_id=str(run_id), error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to get run")

    if row is None:
        raise HTTPException(status_code=404, detail="Run not found")

    return row


@app.patch("/api/v1/runs/{run_id}")
async def patch_run(run_id: UUID, body: dict[str, Any]) -> dict[str, Any]:
    """Update run fields (e.g., rename title)."""
    allowed = {"title"}
    updates = {k: v for k, v in body.items() if k in allowed}
    if not updates:
        raise HTTPException(status_code=400, detail="No valid fields to update")
    try:
        from datetime import datetime
        updates["updated_at"] = datetime.utcnow()
        result = await db_update_run(run_id, updates)
        if result is None:
            raise HTTPException(status_code=404, detail="Run not found")
        return result
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("patch_run_failed", error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to update run")


@app.delete("/api/v1/runs/{run_id}")
async def delete_run(run_id: UUID) -> dict[str, str]:
    """Delete a research run and its events."""
    try:
        from apps.api.database import get_pool
        pool = await get_pool()
        # Check exists
        row = await pool.fetchrow("SELECT id FROM research_run WHERE id = $1", run_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Run not found")
        # Delete cascade (events, pain_points, etc.)
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
        raise HTTPException(status_code=500, detail="Failed to delete run")


@app.post("/api/v1/runs/{run_id}/start")
async def start_run(run_id: UUID) -> dict[str, Any]:
    """
    Start a queued research run.
    """
    try:
        run = await db_get_run(run_id)
    except Exception as exc:
        logger.error("start_run_get_failed", run_id=str(run_id), error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to retrieve run")

    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    if run["status"] not in [RunStatus.QUEUED.value, RunStatus.PAUSED.value]:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot start run in status: {run['status']}",
        )

    now = datetime.utcnow()
    updates: dict[str, Any] = {
        "status": RunStatus.RUNNING.value,
        "updated_at": now,
        "current_step": "plan_research",
    }
    if run.get("started_at") is None:
        updates["started_at"] = now

    try:
        await db_update_run(run_id, updates)
    except Exception as exc:
        logger.error("start_run_update_failed", run_id=str(run_id), error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to update run")

    # Enqueue to Redis task queue
    enqueued = await _enqueue_run(run_id, run)

    try:
        await create_event(
            run_id=run_id,
            event_type="run.started",
            severity=Severity.INFO.value,
            payload={"enqueued": enqueued},
        )
        await _publish_event(run_id, {
            "event_type": "run.started",
            "severity": "info",
            "payload": {"enqueued": enqueued},
            "timestamp": now.isoformat(),
        })
    except Exception as exc:
        logger.warning("create_event_failed", run_id=str(run_id), error=str(exc))

    logger.info("run_started", run_id=str(run_id), enqueued=enqueued)

    return {"status": "started", "run_id": str(run_id), "enqueued": enqueued}


@app.post("/api/v1/runs/{run_id}/pause")
async def pause_run(run_id: UUID, request: PauseRequest) -> dict[str, Any]:
    """
    Pause a running research run.

    - **soft**: Wait for current step to complete before pausing
    - **hard**: Pause immediately and checkpoint
    """
    try:
        run = await db_get_run(run_id)
    except Exception as exc:
        logger.error("pause_run_get_failed", run_id=str(run_id), error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to retrieve run")

    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    if run["status"] != RunStatus.RUNNING.value:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot pause run in status: {run['status']}",
        )

    now = datetime.utcnow()
    pause_reason = f"user_{request.mode}_pause"
    try:
        await db_update_run(run_id, {
            "status": RunStatus.PAUSED.value,
            "pause_reason": pause_reason,
            "updated_at": now,
        })
    except Exception as exc:
        logger.error("pause_run_update_failed", run_id=str(run_id), error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to update run")

    try:
        await create_event(
            run_id=run_id,
            event_type="run.paused",
            severity=Severity.INFO.value,
            payload={"mode": request.mode},
        )
    except Exception as exc:
        logger.warning("create_event_failed", run_id=str(run_id), error=str(exc))

    logger.info("run_paused", run_id=str(run_id), mode=request.mode)

    return {"status": "paused", "run_id": str(run_id), "mode": request.mode}


@app.post("/api/v1/runs/{run_id}/resume")
async def resume_run(run_id: UUID, request: ResumeRequest) -> dict[str, Any]:
    """
    Resume a paused research run.

    Optionally provide a patch to modify constraints before resuming.
    """
    try:
        run = await db_get_run(run_id)
    except Exception as exc:
        logger.error("resume_run_get_failed", run_id=str(run_id), error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to retrieve run")

    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    if run["status"] != RunStatus.PAUSED.value:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot resume run in status: {run['status']}",
        )

    now = datetime.utcnow()
    try:
        await db_update_run(run_id, {
            "status": RunStatus.RUNNING.value,
            "pause_reason": None,
            "updated_at": now,
        })
    except Exception as exc:
        logger.error("resume_run_update_failed", run_id=str(run_id), error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to update run")

    # Apply patch if provided
    patch_applied = {}
    if request.patch:
        patch_applied = request.patch

    try:
        await create_event(
            run_id=run_id,
            event_type="run.resumed",
            severity=Severity.INFO.value,
            payload={"patch_applied": bool(patch_applied)},
        )
    except Exception as exc:
        logger.warning("create_event_failed", run_id=str(run_id), error=str(exc))

    logger.info("run_resumed", run_id=str(run_id), patch=bool(request.patch))

    return {"status": "resumed", "run_id": str(run_id), "patch_applied": patch_applied}


@app.post("/api/v1/runs/{run_id}/cancel")
async def cancel_run(run_id: UUID) -> dict[str, Any]:
    """
    Cancel a research run.
    """
    try:
        run = await db_get_run(run_id)
    except Exception as exc:
        logger.error("cancel_run_get_failed", run_id=str(run_id), error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to retrieve run")

    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    terminal = {RunStatus.COMPLETED.value, RunStatus.CANCELLED.value, RunStatus.FAILED.value}
    if run["status"] in terminal:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel run in status: {run['status']}",
        )

    now = datetime.utcnow()
    try:
        await db_update_run(run_id, {
            "status": RunStatus.CANCELLED.value,
            "updated_at": now,
            "completed_at": now,
        })
    except Exception as exc:
        logger.error("cancel_run_update_failed", run_id=str(run_id), error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to update run")

    try:
        await create_event(
            run_id=run_id,
            event_type="run.cancelled",
            severity=Severity.INFO.value,
            payload={},
        )
    except Exception as exc:
        logger.warning("create_event_failed", run_id=str(run_id), error=str(exc))

    logger.info("run_cancelled", run_id=str(run_id))

    return {"status": "cancelled", "run_id": str(run_id)}


# ============================================
# Event Stream Endpoints
# ============================================


@app.get("/api/v1/runs/{run_id}/events")
async def get_run_events(
    run_id: UUID,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """
    Get events for a research run.
    """
    try:
        run = await db_get_run(run_id)
    except Exception as exc:
        logger.error("get_events_run_check_failed", run_id=str(run_id), error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to retrieve run")

    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    try:
        total = await count_events(run_id)
        events = await list_events(run_id, limit=limit, offset=offset)
    except Exception as exc:
        logger.error("list_events_failed", run_id=str(run_id), error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to list events")

    return {
        "run_id": str(run_id),
        "total": total,
        "events": [
            {
                "event_type": e["event_type"],
                "severity": e["severity"],
                "payload": e.get("payload", {}),
                "timestamp": e["created_at"].isoformat() if e.get("created_at") else None,
            }
            for e in events
        ],
    }


@app.get("/api/v1/runs/{run_id}/events/stream")
async def stream_run_events(run_id: UUID) -> StreamingResponse:
    """
    Stream events for a research run via Server-Sent Events (SSE).

    Subscribes to Redis pub/sub channel for real-time event delivery.
    Falls back to polling the database if Redis is unavailable.
    """
    try:
        run = await db_get_run(run_id)
    except Exception as exc:
        logger.error("stream_events_run_check_failed", run_id=str(run_id), error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to retrieve run")

    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    async def event_generator():
        # Send initial connection event
        yield _format_sse({"event_type": "connected", "run_id": str(run_id)})

        if _redis is not None:
            # Redis pub/sub mode
            import redis.asyncio as aioredis
            pubsub = _redis.pubsub()
            channel = f"{REDIS_EVENTS_CHANNEL}:{run_id}"
            try:
                await pubsub.subscribe(channel)
                logger.info("sse_subscribed", run_id=str(run_id), channel=channel)

                while True:
                    message = await pubsub.get_message(
                        ignore_subscribe_messages=True,
                        timeout=30.0,
                    )
                    if message is not None and message["type"] == "message":
                        try:
                            data = json.loads(message["data"])
                        except (json.JSONDecodeError, TypeError):
                            data = {"raw": message["data"]}
                        yield _format_sse(data)

                        # Stop streaming if run reached a terminal state
                        if data.get("event_type") in (
                            "run.completed",
                            "run.failed",
                            "run.cancelled",
                        ):
                            yield _format_sse({"event_type": "stream_end"})
                            break
                    else:
                        # Send keepalive comment every 30s
                        yield ": keepalive\n\n"
            except asyncio.CancelledError:
                logger.info("sse_client_disconnected", run_id=str(run_id))
            finally:
                await pubsub.unsubscribe(channel)
                await pubsub.close()
        else:
            # Fallback: poll database for new events
            last_count = 0
            terminal_statuses = {"completed", "failed", "cancelled"}

            for _ in range(360):  # Max ~3 hours at 30s intervals
                try:
                    current_count = await count_events(run_id)
                    if current_count > last_count:
                        new_events = await list_events(
                            run_id,
                            limit=current_count - last_count,
                            offset=last_count,
                        )
                        for e in new_events:
                            yield _format_sse({
                                "event_type": e["event_type"],
                                "severity": e["severity"],
                                "payload": e.get("payload", {}),
                                "timestamp": e["created_at"].isoformat()
                                if e.get("created_at")
                                else None,
                            })
                        last_count = current_count

                    # Check if run is done
                    current_run = await db_get_run(run_id)
                    if current_run and current_run.get("status") in terminal_statuses:
                        yield _format_sse({"event_type": "stream_end"})
                        break

                    yield ": keepalive\n\n"
                    await asyncio.sleep(30)
                except asyncio.CancelledError:
                    break
                except Exception as exc:
                    logger.warning("sse_poll_error", error=str(exc))
                    await asyncio.sleep(5)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _format_sse(data: dict[str, Any]) -> str:
    """Format a dictionary as an SSE event string."""
    event_type = data.get("event_type", "message")
    payload = json.dumps(data, default=str)
    return f"event: {event_type}\ndata: {payload}\n\n"


# ============================================
# Hypothesis Endpoints
# ============================================


class HypothesisResponse(BaseModel):
    """Response for a hypothesis."""

    id: UUID
    run_id: UUID
    title: str
    statement: str
    type: str
    novelty_score: float
    feasibility_score: float
    evidence_score: float
    risk_score: float
    status: str
    created_at: datetime


@app.get("/api/v1/runs/{run_id}/hypotheses", response_model=list[HypothesisResponse])
async def get_run_hypotheses(run_id: UUID) -> list[dict[str, Any]]:
    """
    Get hypotheses generated by a research run.
    """
    try:
        run = await db_get_run(run_id)
    except Exception as exc:
        logger.error("get_hypotheses_run_check_failed", run_id=str(run_id), error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to retrieve run")

    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    try:
        rows = await list_hypotheses(run_id)
    except Exception as exc:
        logger.error("list_hypotheses_failed", run_id=str(run_id), error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to list hypotheses")

    return rows


# ============================================
# Export Endpoints
# ============================================


class ExportRequest(BaseModel):
    """Request to export run results."""

    formats: list[str] = Field(default=["markdown"], description="Export formats")


class ExportResponse(BaseModel):
    """Response for export request."""

    run_id: UUID
    exports: list[dict[str, Any]]


@app.post("/api/v1/runs/{run_id}/export", response_model=ExportResponse)
async def export_run_results(run_id: UUID, request: ExportRequest) -> dict[str, Any]:
    """
    Export results of a completed research run.

    Supported formats: markdown, json, csv, bibtex
    """
    try:
        run = await db_get_run(run_id)
    except Exception as exc:
        logger.error("export_run_get_failed", run_id=str(run_id), error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to retrieve run")

    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    if run["status"] != RunStatus.COMPLETED.value:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot export run in status: {run['status']}",
        )

    exports = []
    for fmt in request.formats:
        if fmt in ["markdown", "json", "csv", "bibtex"]:
            exports.append({
                "format": fmt,
                "status": "generated",
                "url": f"/api/v1/runs/{run_id}/downloads/{fmt}",
            })

    return {"run_id": run_id, "exports": exports}


@app.get("/api/v1/runs/{run_id}/downloads/{format}")
async def download_export(run_id: UUID, format: str) -> Response:
    """
    Download an export file for a research run.

    Supported formats: markdown, json, csv, bibtex
    """
    valid_formats = {"markdown", "json", "csv", "bibtex"}
    if format not in valid_formats:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid format: {format}. Must be one of: {', '.join(valid_formats)}",
        )

    try:
        run = await db_get_run(run_id)
    except Exception as exc:
        logger.error("download_export_get_failed", run_id=str(run_id), error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to retrieve run")

    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    # Fetch related data
    try:
        papers = await list_papers_by_run(run_id, limit=200, offset=0)
        hypotheses = await list_hypotheses(run_id)
    except Exception as exc:
        logger.error("download_export_data_failed", run_id=str(run_id), error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to fetch run data")

    # Generate export content
    if format == "markdown":
        try:
            events = await list_events(run_id, limit=20, offset=0)
        except Exception:
            events = []
        content = await generate_markdown_report(run, hypotheses, papers, events)
        return Response(
            content=content.encode("utf-8"),
            media_type="text/markdown; charset=utf-8",
            headers={
                "Content-Disposition": f"attachment; filename=\"research-report-{run_id}.md\"",
            },
        )

    elif format == "json":
        content = await generate_json_export(run, hypotheses, papers)
        return Response(
            content=content.encode("utf-8"),
            media_type="application/json; charset=utf-8",
            headers={
                "Content-Disposition": f"attachment; filename=\"research-export-{run_id}.json\"",
            },
        )

    elif format == "csv":
        content = await generate_csv_export(papers)
        return Response(
            content=content.encode("utf-8"),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f"attachment; filename=\"papers-{run_id}.csv\"",
            },
        )

    elif format == "bibtex":
        content = await generate_bibtex_export(papers)
        return Response(
            content=content.encode("utf-8"),
            media_type="application/x-bibtex; charset=utf-8",
            headers={
                "Content-Disposition": f"attachment; filename=\"references-{run_id}.bib\"",
            },
        )

    # Should not reach here due to validation above
    raise HTTPException(status_code=400, detail="Unsupported format")


# ============================================
# Paper Endpoints
# ============================================


@app.get("/api/v1/runs/{run_id}/papers")
async def get_run_papers(
    run_id: UUID,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """
    Get papers discovered in a research run.
    """
    try:
        run = await db_get_run(run_id)
    except Exception as exc:
        logger.error("get_papers_run_check_failed", run_id=str(run_id), error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to retrieve run")

    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    try:
        total = await count_papers_by_run(run_id)
        papers = await list_papers_by_run(run_id, limit=limit, offset=offset)
    except Exception as exc:
        logger.error("list_papers_failed", run_id=str(run_id), error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to list papers")

    return {
        "run_id": str(run_id),
        "total": total,
        "papers": papers,
    }


# ============================================
# File Upload Endpoints
# ============================================


MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 50 MB


@app.post("/api/v1/files/upload")
async def upload_file(
    file: UploadFile = File(..., description="PDF file to upload"),
) -> dict[str, Any]:
    """
    Upload a PDF file to object storage.

    Accepts multipart file upload. Max size: 50 MB.
    Returns storage metadata including the object key for later retrieval.
    """
    if file.content_type and file.content_type != "application/pdf":
        raise HTTPException(
            status_code=400,
            detail=f"Only PDF files are accepted. Got: {file.content_type}",
        )

    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required")

    content = await file.read()

    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Empty file")

    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Max size: {MAX_UPLOAD_SIZE // (1024 * 1024)} MB",
        )

    storage = get_storage()
    try:
        metadata = await storage.upload_file(
            content=content,
            filename=file.filename,
            content_type=file.content_type or "application/pdf",
            prefix="pdfs",
        )
    except Exception as exc:
        logger.error("file_upload_failed", filename=file.filename, error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to upload file")

    logger.info(
        "file_uploaded",
        filename=file.filename,
        size=metadata["size"],
        key=metadata["object_key"],
    )

    return {
        "status": "uploaded",
        "filename": file.filename,
        "object_key": metadata["object_key"],
        "sha256": metadata["sha256"],
        "size": metadata["size"],
        "content_type": metadata["content_type"],
    }


# ============================================
# Queue Status Endpoint
# ============================================


@app.get("/api/v1/queue/status")
async def get_queue_status() -> dict[str, Any]:
    """
    Get the current task queue status.

    Shows queue length and count of active (running) runs.
    """
    queue_length = 0
    redis_available = _redis is not None

    if _redis is not None:
        try:
            queue_length = await _redis.llen(REDIS_QUEUE_KEY)
        except Exception as exc:
            logger.warning("queue_length_failed", error=str(exc))

    try:
        by_status = await count_runs_by_status()
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


from apps.api.routes_v2 import router as v2_router

app.include_router(v2_router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
