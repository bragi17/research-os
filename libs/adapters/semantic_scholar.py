"""
Research OS - Semantic Scholar Adapter

Adapter for Semantic Scholar API integration.
Supports paper search, recommendations, citations, references, and batch operations.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any
from uuid import uuid4

import httpx
from pydantic import BaseModel, Field
from structlog import get_logger

logger = get_logger(__name__)

# API Configuration
S2_API_BASE = "https://api.semanticscholar.org"
S2_GRAPH_BASE = f"{S2_API_BASE}/graph/v1"
S2_RECOMMENDATIONS_BASE = f"{S2_API_BASE}/recommendations/v1"
S2_DATASETS_BASE = f"{S2_API_BASE}/datasets/v1"


class S2Endpoint(str, Enum):
    """Semantic Scholar API endpoints."""

    PAPER_SEARCH = "paper/search"
    PAPER_SEARCH_BULK = "paper/search/bulk"
    PAPER_SEARCH_MATCH = "paper/search/match"
    PAPER_GET = "paper/{paper_id}"
    PAPER_BATCH = "paper/batch"
    PAPER_CITATIONS = "paper/{paper_id}/citations"
    PAPER_REFERENCES = "paper/{paper_id}/references"
    RECOMMENDATIONS = "papers"
    RECOMMENDATIONS_FOR_PAPER = "papers/forpaper/{paper_id}"
    SNIPPET_SEARCH = "snippet/search"
    DATASET_RELEASE = "release/{release_id}"
    DATASET_LATEST = "release/latest"
    DATASET_DOWNLOAD = "release/{release_id}/dataset/{dataset}"
    DATASET_DIFFS = "diffs/{start}/to/{end}/{dataset}"


@dataclass
class RateLimitConfig:
    """Rate limiting configuration."""

    requests_per_second: float = 1.0
    burst_capacity: int = 5
    retry_attempts: int = 3
    retry_base_delay: float = 1.0
    retry_max_delay: float = 60.0


class S2Paper(BaseModel):
    """Semantic Scholar paper data."""

    paper_id: str = Field(..., alias="paperId")
    corpus_id: int | None = Field(None, alias="corpusId")
    title: str
    abstract: str | None = None
    year: int | None = None
    publication_date: str | None = Field(None, alias="publicationDate")
    venue: str | None = None
    publication_venue: dict[str, Any] | None = Field(None, alias="publicationVenue")
    authors: list[dict[str, Any]] = Field(default_factory=list)
    citation_count: int = Field(default=0, alias="citationCount")
    influential_citation_count: int = Field(default=0, alias="influentialCitationCount")
    reference_count: int = Field(default=0, alias="referenceCount")
    is_open_access: bool = Field(default=False, alias="isOpenAccess")
    open_access_pdf: dict[str, Any] | None = Field(None, alias="openAccessPdf")
    fields_of_study: list[str] = Field(default_factory=list, alias="fieldsOfStudy")
    s2_fields_of_study: list[dict[str, Any]] = Field(default_factory=list, alias="s2FieldsOfStudy")
    tldr: dict[str, Any] | None = None
    external_ids: dict[str, Any] | None = Field(None, alias="externalIds")
    embedding: dict[str, Any] | None = None

    class Config:
        populate_by_name = True


class S2CitationEdge(BaseModel):
    """A citation edge with context."""

    paper_id: str = Field(..., alias="paperId")
    title: str | None = None
    year: int | None = None
    authors: list[dict[str, Any]] = Field(default_factory=list)
    contexts: list[str] = Field(default_factory=list)
    intents: list[str] = Field(default_factory=list)
    is_influential: bool = Field(default=False, alias="isInfluential")
    abstract: str | None = None

    class Config:
        populate_by_name = True


class S2Snippet(BaseModel):
    """A snippet from snippet search."""

    paper_id: str = Field(..., alias="paperId")
    title: str | None = None
    abstract: str | None = None
    snippet_text: str = Field(..., alias="snippet")
    section: str | None = None
    sentence_spans: list[list[int]] = Field(default_factory=list, alias="sentenceSpans")
    score: float = Field(default=0.0)

    class Config:
        populate_by_name = True


class SemanticScholarAdapter:
    """
    Adapter for Semantic Scholar API.

    Features:
    - Rate limiting with token bucket
    - Automatic retries with exponential backoff
    - Response caching
    - Batch request aggregation
    """

    def __init__(
        self,
        api_key: str | None = None,
        rate_limit: RateLimitConfig | None = None,
        cache_ttl_seconds: int = 86400,
    ):
        self.api_key = api_key
        self.rate_limit = rate_limit or RateLimitConfig()
        self.cache_ttl = cache_ttl_seconds

        # Token bucket state
        self._tokens = self.rate_limit.burst_capacity
        self._last_refill = time.monotonic()

        # Simple in-memory cache
        self._cache: dict[str, tuple[Any, float]] = {}

        # HTTP client
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            headers = {"User-Agent": "ResearchOS/0.1.0"}
            if self.api_key:
                headers["x-api-key"] = self.api_key

            self._client = httpx.AsyncClient(
                base_url=S2_GRAPH_BASE,
                headers=headers,
                timeout=httpx.Timeout(30.0, connect=10.0),
                follow_redirects=True,
            )
        return self._client

    def _get_cache_key(self, endpoint: str, params: dict[str, Any] | None = None) -> str:
        """Generate cache key for a request."""
        key_data = {"endpoint": endpoint, "params": params or {}}
        return hashlib.sha256(json.dumps(key_data, sort_keys=True).encode()).hexdigest()

    async def _acquire_token(self) -> None:
        """Acquire a rate limit token."""
        now = time.monotonic()
        elapsed = now - self._last_refill

        # Refill tokens
        self._tokens = min(
            self.rate_limit.burst_capacity,
            self._tokens + elapsed * self.rate_limit.requests_per_second,
        )
        self._last_refill = now

        if self._tokens < 1:
            wait_time = (1 - self._tokens) / self.rate_limit.requests_per_second
            logger.debug("rate_limit_wait", wait_seconds=wait_time)
            await asyncio.sleep(wait_time)
            self._tokens = 0
        else:
            self._tokens -= 1

    async def _request_with_retry(
        self,
        method: str,
        url: str,
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
        use_cache: bool = True,
    ) -> dict[str, Any]:
        """Make a request with retry logic."""
        cache_key = self._get_cache_key(url, params)

        # Check cache
        if use_cache:
            cached = self._cache.get(cache_key)
            if cached and time.time() - cached[1] < self.cache_ttl:
                logger.debug("cache_hit", key=cache_key[:16])
                return cached[0]

        client = await self._get_client()
        last_error = None

        for attempt in range(self.rate_limit.retry_attempts):
            await self._acquire_token()

            try:
                if method.upper() == "GET":
                    response = await client.get(url, params=params)
                else:
                    response = await client.post(url, params=params, json=json_data)

                if response.status_code == 200:
                    data = response.json()
                    if use_cache:
                        self._cache[cache_key] = (data, time.time())
                    return data

                elif response.status_code == 429:
                    # Rate limited - exponential backoff
                    delay = min(
                        self.rate_limit.retry_base_delay * (2**attempt),
                        self.rate_limit.retry_max_delay,
                    )
                    logger.warning("rate_limited", attempt=attempt, delay=delay)
                    await asyncio.sleep(delay)
                    continue

                elif response.status_code == 404:
                    raise ValueError(f"Resource not found: {url}")

                elif response.status_code >= 500:
                    # Server error - retry
                    delay = min(
                        self.rate_limit.retry_base_delay * (2**attempt),
                        self.rate_limit.retry_max_delay,
                    )
                    logger.warning(
                        "server_error",
                        status=response.status_code,
                        attempt=attempt,
                        delay=delay,
                    )
                    await asyncio.sleep(delay)
                    continue

                else:
                    raise ValueError(f"API error: {response.status_code} - {response.text}")

            except httpx.TimeoutException as e:
                last_error = e
                logger.warning("timeout", attempt=attempt, error=str(e))
                await asyncio.sleep(self.rate_limit.retry_base_delay * (2**attempt))

            except httpx.RequestError as e:
                last_error = e
                logger.warning("request_error", attempt=attempt, error=str(e))
                await asyncio.sleep(self.rate_limit.retry_base_delay * (2**attempt))

        raise RuntimeError(f"Failed after {self.rate_limit.retry_attempts} attempts: {last_error}")

    # ============================================
    # Paper Search Methods
    # ============================================

    async def search_papers(
        self,
        query: str,
        limit: int = 100,
        offset: int = 0,
        fields: list[str] | None = None,
        year: str | None = None,
        publication_types: list[str] | None = None,
        venue: list[str] | None = None,
        fields_of_study: list[str] | None = None,
        open_access_pdf: bool | None = None,
        min_citation_count: int | None = None,
    ) -> dict[str, Any]:
        """
        Search for papers using relevance ranking.

        Best for: Small-scale high-quality results, front-end instant search.
        Max results: 1,000
        """
        if fields is None:
            fields = [
                "paperId", "corpusId", "title", "abstract", "year",
                "publicationDate", "venue", "publicationVenue", "authors",
                "citationCount", "influentialCitationCount", "referenceCount",
                "isOpenAccess", "openAccessPdf", "fieldsOfStudy", "s2FieldsOfStudy",
                "tldr", "externalIds", "embedding.specter_v2",
            ]

        params = {
            "query": query,
            "limit": min(limit, 100),
            "offset": offset,
            "fields": ",".join(fields),
        }

        if year:
            params["year"] = year
        if publication_types:
            params["publicationTypes"] = ",".join(publication_types)
        if venue:
            params["venue"] = ",".join(venue)
        if fields_of_study:
            params["fieldsOfStudy"] = ",".join(fields_of_study)
        if open_access_pdf is not None:
            params["openAccessPdf"] = str(open_access_pdf).lower()
        if min_citation_count is not None:
            params["minCitationCount"] = min_citation_count

        return await self._request_with_retry("GET", "paper/search", params=params)

    async def bulk_search_papers(
        self,
        query: str,
        limit: int = 1000,
        token: str | None = None,
        year: str | None = None,
        publication_types: list[str] | None = None,
        fields_of_study: list[str] | None = None,
        open_access_pdf: bool | None = None,
        min_citation_count: int | None = None,
    ) -> dict[str, Any]:
        """
        Bulk search for papers using boolean query syntax.

        Best for: Large-scale retrieval, backend batch processing.
        Max results: 10,000,000

        Query syntax:
        - `+` AND
        - `|` OR
        - `-` NOT
        - `"..."` phrase
        - `*` prefix
        - `(...)` grouping
        - `~N` fuzzy/phrase slop
        """
        fields = [
            "paperId", "corpusId", "title", "abstract", "year",
            "publicationDate", "venue", "authors",
            "citationCount", "influentialCitationCount", "referenceCount",
            "isOpenAccess", "openAccessPdf", "fieldsOfStudy",
            "tldr", "externalIds",
        ]

        params = {
            "query": query,
            "limit": min(limit, 1000),
            "fields": ",".join(fields),
        }

        if token:
            params["token"] = token
        if year:
            params["year"] = year
        if publication_types:
            params["publicationTypes"] = ",".join(publication_types)
        if fields_of_study:
            params["fieldsOfStudy"] = ",".join(fields_of_study)
        if open_access_pdf is not None:
            params["openAccessPdf"] = str(open_access_pdf).lower()
        if min_citation_count is not None:
            params["minCitationCount"] = min_citation_count

        return await self._request_with_retry("GET", "paper/search/bulk", params=params)

    async def match_paper(
        self,
        query: str,
        year: str | None = None,
    ) -> dict[str, Any]:
        """
        Find the closest paper match by title.

        Best for: Seed paper normalization, DOI/title resolution.
        """
        params = {"query": query, "fields": "paperId,corpusId,title,year,externalIds"}
        if year:
            params["year"] = year

        return await self._request_with_retry("GET", "paper/search/match", params=params)

    # ============================================
    # Paper Retrieval Methods
    # ============================================

    async def get_paper(
        self,
        paper_id: str,
        fields: list[str] | None = None,
    ) -> S2Paper:
        """
        Get details for a single paper.

        paper_id can be: paperId, DOI, ARXIV, CorpusId, MAG, ACL, PMID, PMCID, URL
        """
        if fields is None:
            fields = [
                "paperId", "corpusId", "title", "abstract", "year",
                "publicationDate", "venue", "publicationVenue", "authors",
                "citationCount", "influentialCitationCount", "referenceCount",
                "isOpenAccess", "openAccessPdf", "fieldsOfStudy", "s2FieldsOfStudy",
                "tldr", "externalIds", "embedding.specter_v2",
            ]

        params = {"fields": ",".join(fields)}
        data = await self._request_with_retry(
            "GET", f"paper/{paper_id}", params=params
        )
        return S2Paper(**data)

    async def batch_get_papers(
        self,
        paper_ids: list[str],
        fields: list[str] | None = None,
    ) -> list[S2Paper]:
        """
        Get details for multiple papers in a single request.

        Max: 500 paper IDs per request.
        Max response size: 10MB.
        """
        if len(paper_ids) > 500:
            raise ValueError("Maximum 500 paper IDs per batch request")

        if fields is None:
            fields = [
                "paperId", "corpusId", "title", "abstract", "year",
                "publicationDate", "venue", "publicationVenue", "authors",
                "citationCount", "influentialCitationCount", "referenceCount",
                "isOpenAccess", "openAccessPdf", "fieldsOfStudy",
                "tldr", "externalIds",
            ]

        data = await self._request_with_retry(
            "POST",
            "paper/batch",
            params={"fields": ",".join(fields)},
            json_data={"ids": paper_ids},
        )

        return [S2Paper(**p) for p in data if p is not None]

    # ============================================
    # Citation Graph Methods
    # ============================================

    async def get_citations(
        self,
        paper_id: str,
        limit: int = 1000,
        offset: int = 0,
        fields: list[str] | None = None,
        year: str | None = None,
        requires_intent: bool | None = None,
    ) -> dict[str, Any]:
        """
        Get papers that cite this paper.

        Returns citation edges with contexts, intents, and isInfluential.
        """
        if fields is None:
            fields = [
                "paperId", "title", "year", "authors", "abstract",
                "contexts", "intents", "isInfluential",
            ]

        params = {
            "limit": min(limit, 1000),
            "offset": offset,
            "fields": ",".join(fields),
        }

        if year:
            params["year"] = year
        if requires_intent is not None:
            params["requiresIntent"] = str(requires_intent).lower()

        return await self._request_with_retry(
            "GET", f"paper/{paper_id}/citations", params=params
        )

    async def get_references(
        self,
        paper_id: str,
        limit: int = 1000,
        offset: int = 0,
        fields: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Get papers cited by this paper.

        Returns reference edges with contexts, intents, and isInfluential.
        """
        if fields is None:
            fields = [
                "paperId", "title", "year", "authors", "abstract",
                "contexts", "intents", "isInfluential",
            ]

        params = {
            "limit": min(limit, 1000),
            "offset": offset,
            "fields": ",".join(fields),
        }

        return await self._request_with_retry(
            "GET", f"paper/{paper_id}/references", params=params
        )

    # ============================================
    # Recommendations Methods
    # ============================================

    async def get_recommendations(
        self,
        positive_paper_ids: list[str],
        negative_paper_ids: list[str] | None = None,
        limit: int = 100,
        fields: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Get paper recommendations based on positive/negative seeds.

        Max: 500 results, 5 positive seeds, 3 negative seeds recommended.
        """
        if fields is None:
            fields = [
                "paperId", "corpusId", "title", "abstract", "year",
                "venue", "authors", "citationCount", "isOpenAccess",
            ]

        # Use recommendations base URL
        client = await self._get_client()
        url = f"{S2_RECOMMENDATIONS_BASE}/papers"

        await self._acquire_token()

        response = await client.post(
            url,
            params={"fields": ",".join(fields)},
            json={
                "positivePaperIds": positive_paper_ids,
                "negativePaperIds": negative_paper_ids or [],
                "limit": min(limit, 500),
            },
        )

        if response.status_code == 200:
            return response.json()
        elif response.status_code == 429:
            raise RuntimeError("Rate limited")
        else:
            raise ValueError(f"API error: {response.status_code}")

    async def get_recommendations_for_paper(
        self,
        paper_id: str,
        limit: int = 100,
        from_pool: str = "all-cs",  # "recent" or "all-cs"
        fields: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Get recommendations for a single paper.
        """
        if fields is None:
            fields = [
                "paperId", "corpusId", "title", "abstract", "year",
                "venue", "authors", "citationCount", "isOpenAccess",
            ]

        client = await self._get_client()
        url = f"{S2_RECOMMENDATIONS_BASE}/papers/forpaper/{paper_id}"

        await self._acquire_token()

        response = await client.get(
            url,
            params={
                "limit": min(limit, 500),
                "from": from_pool,
                "fields": ",".join(fields),
            },
        )

        if response.status_code == 200:
            return response.json()
        elif response.status_code == 429:
            raise RuntimeError("Rate limited")
        else:
            raise ValueError(f"API error: {response.status_code}")

    # ============================================
    # Snippet Search Method
    # ============================================

    async def search_snippets(
        self,
        query: str,
        limit: int = 10,
        paper_ids: list[str] | None = None,
    ) -> list[S2Snippet]:
        """
        Search for text snippets in paper full-text.

        Returns ~500 word snippets with section and sentence spans.
        Best for: Evidence probing, quick validation, fallback when PDF unavailable.
        """
        params = {
            "query": query,
            "limit": min(limit, 1000),
        }

        if paper_ids:
            params["paperIds"] = ",".join(paper_ids[:100])

        data = await self._request_with_retry("GET", "snippet/search", params=params)

        # Note: snippet search endpoint may be at different path
        return [S2Snippet(**s) for s in data.get("data", [])]

    # ============================================
    # Dataset Methods
    # ============================================

    async def get_latest_release(self) -> dict[str, Any]:
        """Get the latest dataset release information."""
        client = await self._get_client()
        url = f"{S2_DATASETS_BASE}/release/latest"

        await self._acquire_token()
        response = await client.get(url)

        if response.status_code == 200:
            return response.json()
        raise ValueError(f"API error: {response.status_code}")

    async def get_dataset_download_url(
        self,
        release_id: str,
        dataset_name: str,
    ) -> str:
        """Get download URL for a specific dataset."""
        client = await self._get_client()
        url = f"{S2_DATASETS_BASE}/release/{release_id}/dataset/{dataset_name}"

        await self._acquire_token()
        response = await client.get(url)

        if response.status_code == 200:
            data = response.json()
            return data["downloadLink"]
        raise ValueError(f"API error: {response.status_code}")

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None


# ============================================
# Helper Functions
# ============================================


def build_bulk_query(
    terms: list[str],
    exclude_terms: list[str] | None = None,
    phrase: bool = False,
) -> str:
    """
    Build a bulk search query string.

    Example:
        build_bulk_query(["retrieval augmented generation", "benchmark"], ["survey"])
        # Returns: '"retrieval augmented generation" + benchmark -survey'
    """
    parts = []

    for term in terms:
        if " " in term or phrase:
            parts.append(f'"{term}"')
        else:
            parts.append(term)

    query = " + ".join(parts)

    if exclude_terms:
        for term in exclude_terms:
            query += f' -"{term}"' if " " in term else f" -{term}"

    return query
