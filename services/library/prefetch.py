"""
Library prefetch — find relevant papers from library before starting research.
Uses vector search + rerank to match library papers to the research query.
"""
from __future__ import annotations
from typing import Any
from structlog import get_logger

logger = get_logger(__name__)


async def library_prefetch(
    topic: str,
    keywords: list[str],
    limit: int = 10,
) -> list[dict[str, Any]]:
    from services.library.tools_embedding import embed_paper_chunks, rerank_papers
    from services.library.tools_db import search_library_vectors, count_library_papers

    paper_count = await count_library_papers()
    if paper_count == 0:
        return []

    query_text = f"{topic} {' '.join(keywords)}"
    try:
        vectors = await embed_paper_chunks([query_text])
    except Exception as exc:
        logger.debug("library_prefetch.embed_failed", error=str(exc))
        return []

    if not vectors:
        return []

    candidates = await search_library_vectors(vectors[0], limit=limit * 3)
    if not candidates:
        return []

    titles = [c.get("title", "") for c in candidates]
    try:
        reranked = await rerank_papers(query_text, titles, top_n=limit)
    except Exception:
        # Fallback: return top candidates without reranking
        return candidates[:limit]

    results = []
    for r in reranked:
        idx = r.get("index", 0)
        if idx < len(candidates):
            paper = dict(candidates[idx])
            paper["relevance_score"] = r.get("relevance_score", 0)
            paper["source"] = "library"
            results.append(paper)

    logger.info("library_prefetch.done", matched=len(results), library_size=paper_count)
    return results
