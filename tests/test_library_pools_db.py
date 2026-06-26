"""Tests for Paper Library pool database helpers."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


def _make_pool(fetchrow_return: Any = None, fetch_return: Any = None) -> AsyncMock:
    pool = AsyncMock()
    pool.fetchrow = AsyncMock(return_value=fetchrow_return)
    pool.fetch = AsyncMock(return_value=fetch_return or [])
    pool.execute = AsyncMock(return_value="DELETE 1")

    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=fetchrow_return)
    conn.fetch = AsyncMock(return_value=fetch_return or [])
    conn.execute = AsyncMock(return_value="DELETE 1")

    tx = AsyncMock()
    tx.__aenter__ = AsyncMock(return_value=None)
    tx.__aexit__ = AsyncMock(return_value=False)
    conn.transaction = MagicMock(return_value=tx)

    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool.acquire = MagicMock(return_value=ctx)
    return pool


@pytest.mark.asyncio
async def test_create_library_pool_inserts_custom_pool():
    pool_id = uuid4()
    expected = {"id": pool_id, "name": "Geometry", "kind": "custom", "paper_count": 0}
    pool = _make_pool(fetchrow_return=MagicMock())

    with (
        patch("services.library.pools_db.get_pool", AsyncMock(return_value=pool)),
        patch("services.library.pools_db._record_to_dict", return_value=expected),
    ):
        from services.library.pools_db import create_library_pool

        result = await create_library_pool("Geometry", description="3D papers")

    assert result == expected
    sql = pool.fetchrow.call_args[0][0]
    assert "INSERT INTO library_pool" in sql
    assert pool.fetchrow.call_args[0][1] == "Geometry"
    assert pool.fetchrow.call_args[0][3] == "custom"


@pytest.mark.asyncio
async def test_assign_paper_to_pools_uses_default_pool_when_empty():
    default_id = uuid4()
    paper_id = uuid4()
    pool = _make_pool(fetchrow_return={"id": default_id})

    with patch("services.library.pools_db.get_pool", AsyncMock(return_value=pool)):
        from services.library.pools_db import assign_paper_to_pools

        assigned = await assign_paper_to_pools(paper_id, [])

    assert assigned == [default_id]
    assert pool.fetchrow.call_args[0][1] == "default"
    sql = pool.execute.call_args[0][0]
    assert "INSERT INTO library_pool_paper" in sql


@pytest.mark.asyncio
async def test_update_library_pool_rejects_unknown_fields():
    pool = _make_pool()

    with patch("services.library.pools_db.get_pool", AsyncMock(return_value=pool)):
        from services.library.pools_db import update_library_pool

        with pytest.raises(ValueError, match="Invalid column names"):
            await update_library_pool(uuid4(), {"name": "Geometry", "kind": "default"})

    pool.fetchrow.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_pool_without_deleting_papers_moves_orphans_to_unassigned():
    pool_id = uuid4()
    unassigned_id = uuid4()
    orphan_id = uuid4()
    pool = _make_pool(
        fetchrow_return={"id": pool_id, "kind": "custom"},
        fetch_return=[{"library_paper_id": orphan_id}],
    )
    conn = pool.acquire.return_value.__aenter__.return_value
    conn.fetchrow.side_effect = [
        {"id": pool_id, "kind": "custom"},
        {"id": unassigned_id},
    ]
    conn.fetch.return_value = [{"library_paper_id": orphan_id}]

    with patch("services.library.pools_db.get_pool", AsyncMock(return_value=pool)):
        from services.library.pools_db import delete_library_pool

        result = await delete_library_pool(pool_id, delete_papers=False)

    assert result["status"] == "deleted"
    assert result["moved_to_unassigned"] == 1
    executed_sql = "\n".join(call.args[0] for call in conn.execute.call_args_list)
    assert "INSERT INTO library_pool_paper" in executed_sql
    assert "DELETE FROM library_pool" in executed_sql


@pytest.mark.asyncio
async def test_delete_pool_with_delete_papers_deletes_library_papers():
    pool_id = uuid4()
    pool = _make_pool(fetchrow_return={"id": pool_id, "kind": "custom"})
    conn = pool.acquire.return_value.__aenter__.return_value
    conn.fetchrow.return_value = {"id": pool_id, "kind": "custom"}

    with patch("services.library.pools_db.get_pool", AsyncMock(return_value=pool)):
        from services.library.pools_db import delete_library_pool

        result = await delete_library_pool(pool_id, delete_papers=True)

    assert result["status"] == "deleted"
    executed_sql = "\n".join(call.args[0] for call in conn.execute.call_args_list)
    assert "DELETE FROM library_paper" in executed_sql
    assert "DELETE FROM library_pool" in executed_sql


@pytest.mark.asyncio
async def test_move_library_paper_removes_source_membership_and_adds_target():
    paper_id = uuid4()
    source_id = uuid4()
    target_id = uuid4()
    pool = _make_pool()

    with patch("services.library.pools_db.get_pool", AsyncMock(return_value=pool)):
        from services.library.pools_db import move_library_paper

        result = await move_library_paper(paper_id, source_id, target_id)

    assert result == {"status": "moved", "paper_id": str(paper_id)}
    executed_sql = "\n".join(call.args[0] for call in pool.execute.call_args_list)
    assert "INSERT INTO library_pool_paper" in executed_sql
    assert "DELETE FROM library_pool_paper" in executed_sql
