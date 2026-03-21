"""
Tests for services.library.tools_db — mock-based (no real DB).

Uses unittest.mock.AsyncMock to mock get_pool() and verify SQL interactions.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_record(data: dict[str, Any]) -> MagicMock:
    """Create a MagicMock that behaves like an asyncpg.Record."""
    record = MagicMock()
    record.__iter__ = MagicMock(return_value=iter(data.items()))
    record.__getitem__ = MagicMock(side_effect=lambda k: data[k])
    record.items = MagicMock(return_value=data.items())
    # _record_to_dict calls dict(record), which uses __iter__ on Record.
    # asyncpg.Record supports dict() via __iter__ returning key-value tuples.
    # Our MagicMock's __iter__ already returns items tuples — but dict()
    # on a MagicMock doesn't work the same way.  Patch _record_to_dict instead.
    return record


def _make_pool(
    fetchrow_return: Any = None,
    fetch_return: Any = None,
    execute_return: str = "DELETE 1",
) -> AsyncMock:
    """Build a mock pool that responds to fetchrow / fetch / execute / acquire."""
    pool = AsyncMock()
    pool.fetchrow = AsyncMock(return_value=fetchrow_return)
    pool.fetch = AsyncMock(return_value=fetch_return or [])
    pool.execute = AsyncMock(return_value=execute_return)

    # acquire() context manager — used by insert_library_chunks
    conn = AsyncMock()
    conn.execute = AsyncMock(return_value="INSERT 0 1")

    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool.acquire = MagicMock(return_value=ctx)

    return pool


POOL_PATH = "services.library.tools_db.get_pool"
RECORD_PATH = "services.library.tools_db._record_to_dict"


# ---------------------------------------------------------------------------
# insert_library_paper
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_insert_library_paper_returns_dict():
    expected = {"id": uuid4(), "title": "Attention Is All You Need", "status": "pending"}
    pool = _make_pool(fetchrow_return=MagicMock())

    with patch(POOL_PATH, AsyncMock(return_value=pool)), \
         patch(RECORD_PATH, return_value=expected):
        from services.library.tools_db import insert_library_paper
        result = await insert_library_paper({"title": "Attention Is All You Need"})

    assert result["title"] == "Attention Is All You Need"
    pool.fetchrow.assert_awaited_once()
    call_sql = pool.fetchrow.call_args[0][0]
    assert "INSERT INTO library_paper" in call_sql


# ---------------------------------------------------------------------------
# get_library_paper
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_library_paper_found():
    paper_id = uuid4()
    expected = {"id": paper_id, "title": "BERT"}
    pool = _make_pool(fetchrow_return=MagicMock())

    with patch(POOL_PATH, AsyncMock(return_value=pool)), \
         patch(RECORD_PATH, return_value=expected):
        from services.library.tools_db import get_library_paper
        result = await get_library_paper(paper_id)

    assert result is not None
    assert result["title"] == "BERT"


@pytest.mark.asyncio
async def test_get_library_paper_returns_none_for_missing():
    pool = _make_pool(fetchrow_return=None)

    with patch(POOL_PATH, AsyncMock(return_value=pool)):
        from services.library.tools_db import get_library_paper
        result = await get_library_paper(uuid4())

    assert result is None


# ---------------------------------------------------------------------------
# list_library_papers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_library_papers_no_filters():
    pool = _make_pool(fetch_return=[])

    with patch(POOL_PATH, AsyncMock(return_value=pool)):
        from services.library.tools_db import list_library_papers
        result = await list_library_papers()

    assert result == []
    call_sql = pool.fetch.call_args[0][0]
    assert "SELECT * FROM library_paper" in call_sql
    assert "WHERE" not in call_sql


@pytest.mark.asyncio
async def test_list_library_papers_applies_field_filter():
    pool = _make_pool(fetch_return=[])

    with patch(POOL_PATH, AsyncMock(return_value=pool)):
        from services.library.tools_db import list_library_papers
        await list_library_papers(field="NLP")

    call_sql = pool.fetch.call_args[0][0]
    assert "field = $1" in call_sql
    # First positional arg after SQL should be the field value
    call_args = pool.fetch.call_args[0]
    assert call_args[1] == "NLP"


@pytest.mark.asyncio
async def test_list_library_papers_applies_project_tag_filter():
    pool = _make_pool(fetch_return=[])

    with patch(POOL_PATH, AsyncMock(return_value=pool)):
        from services.library.tools_db import list_library_papers
        await list_library_papers(project_tag="ml-safety")

    call_sql = pool.fetch.call_args[0][0]
    assert "ANY(project_tags)" in call_sql


@pytest.mark.asyncio
async def test_list_library_papers_applies_both_filters():
    pool = _make_pool(fetch_return=[])

    with patch(POOL_PATH, AsyncMock(return_value=pool)):
        from services.library.tools_db import list_library_papers
        await list_library_papers(field="CV", project_tag="autonomous")

    call_sql = pool.fetch.call_args[0][0]
    assert "field = $1" in call_sql
    assert "$2 = ANY(project_tags)" in call_sql


# ---------------------------------------------------------------------------
# delete_library_paper
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_library_paper_returns_true():
    pool = _make_pool(execute_return="DELETE 1")

    with patch(POOL_PATH, AsyncMock(return_value=pool)):
        from services.library.tools_db import delete_library_paper
        result = await delete_library_paper(uuid4())

    assert result is True


@pytest.mark.asyncio
async def test_delete_library_paper_returns_false_when_missing():
    pool = _make_pool(execute_return="DELETE 0")

    with patch(POOL_PATH, AsyncMock(return_value=pool)):
        from services.library.tools_db import delete_library_paper
        result = await delete_library_paper(uuid4())

    assert result is False


# ---------------------------------------------------------------------------
# update_library_paper
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_library_paper_builds_dynamic_set():
    paper_id = uuid4()
    expected = {"id": paper_id, "title": "Updated", "status": "indexed"}
    pool = _make_pool(fetchrow_return=MagicMock())

    with patch(POOL_PATH, AsyncMock(return_value=pool)), \
         patch(RECORD_PATH, return_value=expected):
        from services.library.tools_db import update_library_paper
        result = await update_library_paper(paper_id, {"status": "indexed", "title": "Updated"})

    assert result["status"] == "indexed"
    call_sql = pool.fetchrow.call_args[0][0]
    assert "UPDATE library_paper SET" in call_sql
    assert "RETURNING *" in call_sql


@pytest.mark.asyncio
async def test_update_library_paper_rejects_invalid_columns():
    with patch(POOL_PATH, AsyncMock(return_value=_make_pool())):
        from services.library.tools_db import update_library_paper
        with pytest.raises(ValueError, match="Invalid column names"):
            await update_library_paper(uuid4(), {"hacked_column": "bad"})


@pytest.mark.asyncio
async def test_update_library_paper_empty_updates():
    """Empty updates dict should just return the current row."""
    paper_id = uuid4()
    expected = {"id": paper_id, "title": "Existing"}
    pool = _make_pool(fetchrow_return=MagicMock())

    with patch(POOL_PATH, AsyncMock(return_value=pool)), \
         patch(RECORD_PATH, return_value=expected):
        from services.library.tools_db import update_library_paper
        result = await update_library_paper(paper_id, {})

    assert result["title"] == "Existing"


# ---------------------------------------------------------------------------
# insert_library_chunks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_insert_library_chunks_returns_count():
    pool = _make_pool()

    with patch(POOL_PATH, AsyncMock(return_value=pool)):
        from services.library.tools_db import insert_library_chunks
        chunks = [
            {"text": "chunk one", "section_type": "abstract"},
            {"text": "chunk two", "section_type": "body"},
            {"text": "chunk three", "section_type": "conclusion"},
        ]
        count = await insert_library_chunks(uuid4(), chunks)

    assert count == 3


@pytest.mark.asyncio
async def test_insert_library_chunks_empty_list():
    pool = _make_pool()

    with patch(POOL_PATH, AsyncMock(return_value=pool)):
        from services.library.tools_db import insert_library_chunks
        count = await insert_library_chunks(uuid4(), [])

    assert count == 0


# ---------------------------------------------------------------------------
# search_library_vectors
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_library_vectors_no_field():
    pool = _make_pool(fetch_return=[])

    with patch(POOL_PATH, AsyncMock(return_value=pool)):
        from services.library.tools_db import search_library_vectors
        result = await search_library_vectors([0.1, 0.2, 0.3], limit=10)

    assert result == []
    call_sql = pool.fetch.call_args[0][0]
    assert "<=>" in call_sql
    assert "JOIN library_paper" in call_sql


@pytest.mark.asyncio
async def test_search_library_vectors_with_field():
    pool = _make_pool(fetch_return=[])

    with patch(POOL_PATH, AsyncMock(return_value=pool)):
        from services.library.tools_db import search_library_vectors
        await search_library_vectors([0.1, 0.2], limit=5, field="NLP")

    call_sql = pool.fetch.call_args[0][0]
    assert "lp.field = $2" in call_sql


# ---------------------------------------------------------------------------
# search_library_text
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_library_text_builds_ilike_query():
    pool = _make_pool(fetch_return=[])

    with patch(POOL_PATH, AsyncMock(return_value=pool)):
        from services.library.tools_db import search_library_text
        result = await search_library_text("transformer")

    assert result == []
    call_sql = pool.fetch.call_args[0][0]
    assert "ILIKE" in call_sql
    # Verify pattern wrapping
    call_args = pool.fetch.call_args[0]
    assert call_args[1] == "%transformer%"


# ---------------------------------------------------------------------------
# count functions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_count_library_papers_returns_int():
    row = MagicMock()
    row.__getitem__ = MagicMock(side_effect=lambda k: 42 if k == "cnt" else None)
    pool = _make_pool(fetchrow_return=row)

    with patch(POOL_PATH, AsyncMock(return_value=pool)):
        from services.library.tools_db import count_library_papers
        result = await count_library_papers()

    assert result == 42
    assert isinstance(result, int)


@pytest.mark.asyncio
async def test_count_library_chunks_returns_int():
    row = MagicMock()
    row.__getitem__ = MagicMock(side_effect=lambda k: 100 if k == "cnt" else None)
    pool = _make_pool(fetchrow_return=row)

    with patch(POOL_PATH, AsyncMock(return_value=pool)):
        from services.library.tools_db import count_library_chunks
        result = await count_library_chunks()

    assert result == 100
    assert isinstance(result, int)
