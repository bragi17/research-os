"""Tests for services.library.prefetch — library_prefetch function."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

DB_MODULE = "services.library.tools_db"
EMBED_MODULE = "services.library.tools_embedding"


@pytest.mark.asyncio
async def test_returns_empty_when_library_has_zero_papers():
    """Returns empty list when library has 0 papers."""
    with patch(f"{DB_MODULE}.count_library_papers", new_callable=AsyncMock, return_value=0) as mock_count:
        from services.library.prefetch import library_prefetch
        result = await library_prefetch("quantum computing", ["qubit", "entanglement"])
    assert result == []
    mock_count.assert_awaited_once()


@pytest.mark.asyncio
async def test_returns_papers_with_relevance_score():
    """Returns papers with relevance_score when library has matches."""
    candidates = [
        {"paper_id": "p1", "title": "Paper One"},
        {"paper_id": "p2", "title": "Paper Two"},
        {"paper_id": "p3", "title": "Paper Three"},
    ]
    reranked = [
        {"index": 2, "relevance_score": 0.95},
        {"index": 0, "relevance_score": 0.80},
    ]

    with (
        patch(f"{DB_MODULE}.count_library_papers", new_callable=AsyncMock, return_value=5),
        patch(f"{EMBED_MODULE}.embed_paper_chunks", new_callable=AsyncMock, return_value=[[0.1, 0.2]]),
        patch(f"{DB_MODULE}.search_library_vectors", new_callable=AsyncMock, return_value=candidates),
        patch(f"{EMBED_MODULE}.rerank_papers", new_callable=AsyncMock, return_value=reranked),
    ):
        from services.library.prefetch import library_prefetch
        result = await library_prefetch("deep learning", ["neural", "network"], limit=2)

    assert len(result) == 2
    assert result[0]["paper_id"] == "p3"
    assert result[0]["relevance_score"] == 0.95
    assert result[0]["source"] == "library"
    assert result[1]["paper_id"] == "p1"
    assert result[1]["relevance_score"] == 0.80


@pytest.mark.asyncio
async def test_returns_candidates_without_rerank_on_rerank_failure():
    """Falls back to top candidates when rerank raises an exception."""
    candidates = [
        {"paper_id": "p1", "title": "Paper One"},
        {"paper_id": "p2", "title": "Paper Two"},
        {"paper_id": "p3", "title": "Paper Three"},
    ]

    with (
        patch(f"{DB_MODULE}.count_library_papers", new_callable=AsyncMock, return_value=10),
        patch(f"{EMBED_MODULE}.embed_paper_chunks", new_callable=AsyncMock, return_value=[[0.1, 0.2]]),
        patch(f"{DB_MODULE}.search_library_vectors", new_callable=AsyncMock, return_value=candidates),
        patch(f"{EMBED_MODULE}.rerank_papers", new_callable=AsyncMock, side_effect=RuntimeError("rerank down")),
    ):
        from services.library.prefetch import library_prefetch
        result = await library_prefetch("robotics", ["arm", "grasp"], limit=2)

    assert len(result) == 2
    assert result[0]["paper_id"] == "p1"
    assert result[1]["paper_id"] == "p2"
