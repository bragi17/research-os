"""
Research OS - Redis Task Queue

Dispatches research run jobs via Redis and provides consumer interface.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any
from uuid import UUID

import redis.asyncio as redis
from structlog import get_logger

logger = get_logger(__name__)

QUEUE_KEY = "research_os:run_queue"
ACTIVE_KEY = "research_os:active_runs"

_redis: redis.Redis | None = None


async def get_redis() -> redis.Redis:
    """Get or create Redis connection."""
    global _redis
    if _redis is None:
        _redis = redis.from_url(
            os.getenv("REDIS_URL", "redis://localhost:6379/0"),
            decode_responses=True,
        )
    return _redis


async def close_redis() -> None:
    """Close Redis connection."""
    global _redis
    if _redis is not None:
        await _redis.close()
        _redis = None


async def enqueue_run(run_id: UUID, payload: dict[str, Any]) -> None:
    """Push a research run job onto the queue."""
    r = await get_redis()
    job = json.dumps({"run_id": str(run_id), **payload})
    await r.rpush(QUEUE_KEY, job)
    logger.info("task_queue.enqueued", run_id=str(run_id))


async def dequeue_run(timeout: int = 5) -> dict[str, Any] | None:
    """Pop the next job from the queue. Blocks up to `timeout` seconds."""
    r = await get_redis()
    result = await r.blpop(QUEUE_KEY, timeout=timeout)
    if result is None:
        return None
    _, raw = result
    return json.loads(raw)


async def mark_active(run_id: UUID) -> None:
    """Mark a run as actively being processed."""
    r = await get_redis()
    await r.sadd(ACTIVE_KEY, str(run_id))


async def mark_inactive(run_id: UUID) -> None:
    """Remove a run from the active set."""
    r = await get_redis()
    await r.srem(ACTIVE_KEY, str(run_id))


async def is_active(run_id: UUID) -> bool:
    """Check if a run is currently being processed."""
    r = await get_redis()
    return await r.sismember(ACTIVE_KEY, str(run_id))


async def get_queue_length() -> int:
    """Get the number of jobs waiting in the queue."""
    r = await get_redis()
    return await r.llen(QUEUE_KEY)


async def publish_event(run_id: UUID, event: dict[str, Any]) -> None:
    """Publish a run event to the Redis pub/sub channel for SSE streaming."""
    r = await get_redis()
    channel = f"research_os:events:{run_id}"
    await r.publish(channel, json.dumps(event))
