"""Redis-backed queue and event helpers for the API process."""

import json
import os
from datetime import datetime
from typing import Any
from uuid import UUID

from structlog import get_logger

logger = get_logger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
REDIS_QUEUE_KEY = "research_os:run_queue"
REDIS_EVENTS_CHANNEL = "research_os:events"

_redis = None


async def init_redis() -> None:
    """Initialize Redis connection. Leaves Redis disabled when unavailable."""
    global _redis
    try:
        import redis.asyncio as aioredis

        _redis = aioredis.from_url(REDIS_URL, decode_responses=True)
        await _redis.ping()
        logger.info("redis_connected", url=REDIS_URL)
    except Exception as exc:
        logger.warning("redis_unavailable", error=str(exc))
        _redis = None


async def close_redis() -> None:
    """Close the API Redis connection."""
    global _redis
    if _redis is not None:
        try:
            await _redis.close()
        except Exception:
            pass
        _redis = None


def get_redis():
    """Return the current API Redis connection, or None."""
    return _redis


def set_redis(redis) -> None:
    """Override the API Redis connection, primarily for tests."""
    global _redis
    _redis = redis


async def enqueue_run(run_id: UUID, run_data: dict[str, Any]) -> bool:
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
            "library_pool_ids": policy.get("library_pool_ids", []),
            "budget": run_data.get("budget_json", {}),
            "enqueued_at": datetime.utcnow().isoformat(),
        })
        await _redis.lpush(REDIS_QUEUE_KEY, task)
        logger.info("run_enqueued", run_id=str(run_id))
        return True
    except Exception as exc:
        logger.warning("enqueue_failed", run_id=str(run_id), error=str(exc))
        return False


async def publish_event(run_id: UUID, event_data: dict[str, Any]) -> None:
    """Publish an event to Redis pub/sub channel."""
    if _redis is None:
        return
    try:
        channel = f"{REDIS_EVENTS_CHANNEL}:{run_id}"
        await _redis.publish(channel, json.dumps(event_data, default=str))
    except Exception as exc:
        logger.warning("publish_event_failed", run_id=str(run_id), error=str(exc))


async def get_queue_length() -> int:
    """Return queue length, or zero if Redis is unavailable/failing."""
    if _redis is None:
        return 0
    try:
        return await _redis.llen(REDIS_QUEUE_KEY)
    except Exception as exc:
        logger.warning("queue_length_failed", error=str(exc))
        return 0
