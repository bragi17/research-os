"""Tests for services.library.tools_embedding — embedding tool wrappers."""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_embed_paper_chunks_empty() -> None:
    from services.library.tools_embedding import embed_paper_chunks

    result = await embed_paper_chunks([])
    assert result == []


@pytest.mark.asyncio
async def test_embed_paper_chunks_calls_embed_texts() -> None:
    mock_svc = MagicMock()
    mock_svc.embed_texts = AsyncMock(return_value=[[0.1, 0.2], [0.3, 0.4]])

    with patch(
        "services.library.tools_embedding.get_embedding_service",
        return_value=mock_svc,
    ):
        from services.library.tools_embedding import embed_paper_chunks

        result = await embed_paper_chunks(["hello", "world"])

    assert result == [[0.1, 0.2], [0.3, 0.4]]
    mock_svc.embed_texts.assert_awaited_once_with(
        ["hello", "world"], dimension=1024
    )


@pytest.mark.asyncio
async def test_rerank_papers_empty() -> None:
    from services.library.tools_embedding import rerank_papers

    result = await rerank_papers(query="test", documents=[])
    assert result == []


@pytest.mark.asyncio
async def test_rerank_papers_calls_svc_rerank() -> None:
    expected: list[dict[str, Any]] = [
        {"index": 1, "relevance_score": 0.9, "document": {"text": "doc B"}},
        {"index": 0, "relevance_score": 0.5, "document": {"text": "doc A"}},
    ]
    mock_svc = MagicMock()
    mock_svc.rerank = AsyncMock(return_value=expected)

    with patch(
        "services.library.tools_embedding.get_embedding_service",
        return_value=mock_svc,
    ):
        from services.library.tools_embedding import rerank_papers

        result = await rerank_papers(
            query="quantum computing",
            documents=["doc A", "doc B"],
            top_n=2,
        )

    assert result == expected
    mock_svc.rerank.assert_awaited_once_with(
        query="quantum computing",
        documents=["doc A", "doc B"],
        top_n=2,
    )
