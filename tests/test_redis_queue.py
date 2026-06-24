"""Tests for Redis queue payload shaping."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest


class FakeRedis:
    def __init__(self) -> None:
        self.items: list[tuple[str, str]] = []

    async def lpush(self, key: str, value: str) -> None:
        self.items.append((key, value))


@pytest.mark.asyncio
async def test_enqueue_run_includes_library_pool_ids():
    from apps.api import redis_queue

    redis = FakeRedis()
    redis_queue.set_redis(redis)
    run_id = uuid4()

    try:
        enqueued = await redis_queue.enqueue_run(
            run_id,
            {
                "topic": "3D anomaly detection",
                "goal_type": "survey_plus_innovations",
                "mode": "frontier",
                "policy_json": {
                    "keywords": ["point cloud"],
                    "seed_papers": ["2505.24431"],
                    "library_pool_ids": ["11111111-1111-1111-1111-111111111111"],
                },
                "budget_json": {"max_fulltext_reads": 10},
            },
        )
    finally:
        redis_queue.set_redis(None)

    assert enqueued is True
    payload = json.loads(redis.items[0][1])
    assert payload["library_pool_ids"] == ["11111111-1111-1111-1111-111111111111"]
