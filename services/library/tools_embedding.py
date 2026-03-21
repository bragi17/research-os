"""
Embedding tool wrappers for Paper Library.
Thin deterministic wrappers around EmbeddingService.
No LLM calls — only vector operations.
"""
from __future__ import annotations

from typing import Any

from services.embedding import get_embedding_service


async def embed_paper_chunks(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    svc = get_embedding_service()
    return await svc.embed_texts(texts, dimension=1024)


async def rerank_papers(
    query: str,
    documents: list[str],
    top_n: int | None = None,
) -> list[dict[str, Any]]:
    if not documents:
        return []
    svc = get_embedding_service()
    return await svc.rerank(query=query, documents=documents, top_n=top_n)
