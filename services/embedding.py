"""
Research OS - Embedding & Rerank Service

Uses Tongyi/DashScope models:
- text-embedding-v4: text embeddings (OpenAI-compatible endpoint)
- qwen3-vl-embedding: multimodal embeddings (text + image + video)
- gte-rerank-v2: document reranking for RAG
"""

from __future__ import annotations

import os
from typing import Any

import httpx
from structlog import get_logger

logger = get_logger(__name__)

DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
DASHSCOPE_EMBEDDING_URL = (
    "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings"
)
DASHSCOPE_MULTIMODAL_URL = (
    "https://dashscope.aliyuncs.com/api/v1/services/embeddings/"
    "multimodal-embedding/multimodal-embedding"
)
DASHSCOPE_RERANK_URL = (
    "https://dashscope.aliyuncs.com/api/v1/services/rerank/"
    "text-rerank/text-rerank"
)

# Model selection
TEXT_EMBEDDING_MODEL = "text-embedding-v4"
TEXT_EMBEDDING_DIMENSION = 1024
MULTIMODAL_EMBEDDING_MODEL = "qwen3-vl-embedding"
MULTIMODAL_EMBEDDING_DIMENSION = 1024
RERANK_MODEL = "gte-rerank-v2"

# Batching limits
MAX_TEXTS_PER_BATCH = 10


class EmbeddingService:
    """
    Unified embedding and rerank service using Tongyi/DashScope.

    Supports:
    - Text embeddings via text-embedding-v4 (OpenAI-compatible)
    - Multimodal embeddings via qwen3-vl-embedding (text + image + video)
    - Document reranking via gte-rerank-v2
    """

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or DASHSCOPE_API_KEY
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(60.0))
        return self._client

    # ------------------------------------------------------------------
    # Text Embedding (OpenAI-compatible endpoint)
    # ------------------------------------------------------------------

    async def embed_texts(
        self,
        texts: list[str],
        model: str = TEXT_EMBEDDING_MODEL,
        dimension: int = TEXT_EMBEDDING_DIMENSION,
    ) -> list[list[float]]:
        """
        Generate text embeddings using text-embedding-v4.

        Uses the OpenAI-compatible endpoint.
        Handles batching automatically (max 10 texts per request).

        Args:
            texts: List of texts to embed (max 8192 tokens each).
            model: Embedding model name.
            dimension: Output embedding dimension (64-2048, default 1024).

        Returns:
            List of embedding vectors, one per input text.
        """
        if not texts:
            return []

        all_embeddings: list[list[float]] = []

        for i in range(0, len(texts), MAX_TEXTS_PER_BATCH):
            batch = texts[i : i + MAX_TEXTS_PER_BATCH]
            client = await self._get_client()

            response = await client.post(
                DASHSCOPE_EMBEDDING_URL,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "input": batch,
                    "dimensions": dimension,
                    "encoding_format": "float",
                },
            )

            if response.status_code != 200:
                logger.error(
                    "embedding_failed",
                    status=response.status_code,
                    body=response.text[:200],
                )
                raise ValueError(
                    f"Embedding API error: {response.status_code}"
                )

            data = response.json()
            # OpenAI-compatible format: sort by index to preserve order
            batch_embeddings = [
                item["embedding"]
                for item in sorted(data["data"], key=lambda x: x["index"])
            ]
            all_embeddings.extend(batch_embeddings)

            logger.debug(
                "embedding_batch_done",
                batch_size=len(batch),
                total=len(all_embeddings),
            )

        return all_embeddings

    # ------------------------------------------------------------------
    # Multimodal Embedding (DashScope native endpoint)
    # ------------------------------------------------------------------

    async def embed_multimodal(
        self,
        contents: list[dict[str, str]],
        model: str = MULTIMODAL_EMBEDDING_MODEL,
        dimension: int = MULTIMODAL_EMBEDDING_DIMENSION,
    ) -> list[list[float]]:
        """
        Generate multimodal embeddings using qwen3-vl-embedding.

        Args:
            contents: List of content items, each a dict with one key:
                      {"text": "..."} or {"image": "url"} or {"video": "url"}
            model: Multimodal model name.
            dimension: Output embedding dimension.

        Returns:
            List of embedding vectors.
        """
        if not contents:
            return []

        client = await self._get_client()

        response = await client.post(
            DASHSCOPE_MULTIMODAL_URL,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "input": {"contents": contents},
                "parameters": {"dimension": dimension},
            },
        )

        if response.status_code != 200:
            logger.error(
                "multimodal_embedding_failed",
                status=response.status_code,
                body=response.text[:200],
            )
            raise ValueError(
                f"Multimodal embedding API error: {response.status_code}"
            )

        data = response.json()
        embeddings = [
            item["embedding"]
            for item in sorted(
                data["output"]["embeddings"], key=lambda x: x["index"]
            )
        ]

        logger.debug(
            "multimodal_embedding_done",
            count=len(embeddings),
            dimension=dimension,
        )
        return embeddings

    # ------------------------------------------------------------------
    # Rerank
    # ------------------------------------------------------------------

    async def rerank(
        self,
        query: str,
        documents: list[str],
        model: str = RERANK_MODEL,
        top_n: int | None = None,
        return_documents: bool = True,
    ) -> list[dict[str, Any]]:
        """
        Rerank documents by relevance to query using gte-rerank-v2.

        Args:
            query: Search query.
            documents: List of document texts to rerank (up to 30000).
            model: Rerank model name.
            top_n: Return top N results (default: all).
            return_documents: Include document text in response.

        Returns:
            List of results sorted by relevance_score descending:
            [{"index": int, "relevance_score": float, "document": {"text": str}}]
        """
        if not documents:
            return []

        client = await self._get_client()

        params: dict[str, Any] = {"return_documents": return_documents}
        if top_n is not None:
            params["top_n"] = top_n

        response = await client.post(
            DASHSCOPE_RERANK_URL,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "query": query,
                "documents": documents,
                "parameters": params,
            },
        )

        if response.status_code != 200:
            logger.error(
                "rerank_failed",
                status=response.status_code,
                body=response.text[:200],
            )
            raise ValueError(f"Rerank API error: {response.status_code}")

        data = response.json()
        results: list[dict[str, Any]] = data["output"]["results"]

        logger.debug(
            "rerank_done",
            query_len=len(query),
            docs=len(documents),
            returned=len(results),
        )
        return results

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_service: EmbeddingService | None = None


def get_embedding_service() -> EmbeddingService:
    """Get or create the embedding service singleton."""
    global _service
    if _service is None:
        _service = EmbeddingService()
    return _service
