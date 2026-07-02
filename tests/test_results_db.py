from __future__ import annotations

from uuid import uuid4

import pytest

from apps.api.db import results


class _FakeCountPool:
    def __init__(self, metadata_count: int, cluster_count: int = 0) -> None:
        self.metadata_count = metadata_count
        self.cluster_count = cluster_count
        self.queries: list[str] = []

    async def fetchrow(self, query: str, *args):
        self.queries.append(query)
        if "metadata_json->>'source_run_id'" in query:
            return {"cnt": self.metadata_count}
        return {"cnt": self.cluster_count}


@pytest.mark.asyncio
async def test_count_papers_by_run_prefers_metadata_source_run(monkeypatch) -> None:
    pool = _FakeCountPool(metadata_count=3, cluster_count=0)

    async def fake_get_pool():
        return pool

    monkeypatch.setattr(results.db_pool, "get_pool", fake_get_pool)

    assert await results.count_papers_by_run(uuid4()) == 3
    assert len(pool.queries) == 1


@pytest.mark.asyncio
async def test_count_papers_by_run_falls_back_to_clusters(monkeypatch) -> None:
    pool = _FakeCountPool(metadata_count=0, cluster_count=2)

    async def fake_get_pool():
        return pool

    monkeypatch.setattr(results.db_pool, "get_pool", fake_get_pool)

    assert await results.count_papers_by_run(uuid4()) == 2
    assert len(pool.queries) == 2
