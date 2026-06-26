"""Run event history and Server-Sent Events routes."""

import asyncio
import json
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from structlog import get_logger

import apps.api.database as db
from apps.api.auth import get_current_user
from apps.api.redis_queue import REDIS_EVENTS_CHANNEL, get_redis
from apps.api.tenancy import WorkspaceContext

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/runs", tags=["events"])


@router.get("/{run_id}/events")
async def get_run_events(
    run_id: UUID,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Get events for a research run."""
    ctx = WorkspaceContext.from_user(user)
    try:
        run = await db.get_run(run_id, workspace_id=ctx.workspace_id)
    except Exception as exc:
        logger.error("get_events_run_check_failed", run_id=str(run_id), error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to retrieve run") from exc

    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    try:
        total = await db.count_events(run_id)
        events = await db.list_events(run_id, limit=limit, offset=offset)
    except Exception as exc:
        logger.error("list_events_failed", run_id=str(run_id), error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to list events") from exc

    return {
        "run_id": str(run_id),
        "total": total,
        "events": [
            {
                "event_type": event["event_type"],
                "severity": event["severity"],
                "payload": event.get("payload", {}),
                "timestamp": event["created_at"].isoformat()
                if event.get("created_at")
                else None,
            }
            for event in events
        ],
    }


@router.get("/{run_id}/events/stream")
async def stream_run_events(
    run_id: UUID,
    user: dict[str, Any] = Depends(get_current_user),
) -> StreamingResponse:
    """Stream events for a research run via Server-Sent Events."""
    ctx = WorkspaceContext.from_user(user)
    try:
        run = await db.get_run(run_id, workspace_id=ctx.workspace_id)
    except Exception as exc:
        logger.error("stream_events_run_check_failed", run_id=str(run_id), error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to retrieve run") from exc

    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    async def event_generator():
        yield format_sse({"event_type": "connected", "run_id": str(run_id)})

        redis = get_redis()
        if redis is not None:
            pubsub = redis.pubsub()
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
                        yield format_sse(data)

                        if data.get("event_type") in (
                            "run.completed",
                            "run.failed",
                            "run.cancelled",
                        ):
                            yield format_sse({"event_type": "stream_end"})
                            break
                    else:
                        yield ": keepalive\n\n"
            except asyncio.CancelledError:
                logger.info("sse_client_disconnected", run_id=str(run_id))
            finally:
                await pubsub.unsubscribe(channel)
                await pubsub.close()
        else:
            last_count = 0
            terminal_statuses = {"completed", "failed", "cancelled"}

            for _ in range(360):
                try:
                    current_count = await db.count_events(run_id)
                    if current_count > last_count:
                        new_events = await db.list_events(
                            run_id,
                            limit=current_count - last_count,
                            offset=last_count,
                        )
                        for event in new_events:
                            yield format_sse({
                                "event_type": event["event_type"],
                                "severity": event["severity"],
                                "payload": event.get("payload", {}),
                                "timestamp": event["created_at"].isoformat()
                                if event.get("created_at")
                                else None,
                            })
                        last_count = current_count

                    current_run = await db.get_run(
                        run_id,
                        workspace_id=ctx.workspace_id,
                    )
                    if current_run and current_run.get("status") in terminal_statuses:
                        yield format_sse({"event_type": "stream_end"})
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


def format_sse(data: dict[str, Any]) -> str:
    """Format a dictionary as an SSE event string."""
    event_type = data.get("event_type", "message")
    payload = json.dumps(data, default=str)
    return f"event: {event_type}\ndata: {payload}\n\n"
