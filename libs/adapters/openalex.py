"""
Research OS - OpenAlex Adapter

Adapter for OpenAlex API - comprehensive open academic graph.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any

import httpx
from pydantic import BaseModel, Field
from structlog import get_logger

logger = get_logger(__name__)

OPENALEX_API_BASE = "https://api.openalex.org"


class OpenAlexWorkType(str, Enum):
    """OpenAlex work types."""

    ARTICLE = "article"
    BOOK = "book"
    BOOK_CHAPTER = "book-chapter"
    DISSERTATION = "dissertation"
    EDITORIAL = "editorial"
    LETTER = "letter"
    PARATEXT = "paratext"
    PEER_REVIEW = "peer-review"
    REPORT = "report"
    STANDARD = "standard"
    THESIS = "thesis"
    DATASET = "dataset"


class OpenAlexWork(BaseModel):
    """OpenAlex work data."""

    id: str = Field(..., alias="id")  # OpenAlex ID (URL format)
    doi: str | None = None
    title: str | None = None
    display_name: str | None = Field(None, alias="display_name")
    publication_year: int | None = Field(None, alias="publication_year")
    publication_date: str | None = Field(None, alias="publication_date")
    type: str | None = None
    cited_by_count: int = Field(default=0, alias="cited_by_count")
    cited_by_api_url: str | None = Field(None, alias="cited_by_api_url")
    ids: dict[str, str] = Field(default_factory=dict)
    authorships: list[dict[str, Any]] = Field(default_factory=list)
    primary_location: dict[str, Any] | None = Field(None, alias="primary_location")
    locations: list[dict[str, Any]] = Field(default_factory=list)
    best_oa_location: dict[str, Any] | None = Field(None, alias="best_oa_location")
    keywords: list[dict[str, Any]] = Field(default_factory=list)
    concepts: list[dict[str, Any]] = Field(default_factory=list)
    referenced_works: list[str] = Field(default_factory=list, alias="referenced_works")
    related_works: list[str] = Field(default_factory=list, alias="related_works")
    counts_by_year: list[dict[str, int]] = Field(default_factory=list, alias="counts_by_year")
    abstract_inverted_index: dict[str, list[int]] | None = Field(None, alias="abstract_inverted_index")

    class Config:
        populate_by_name = True

    @property
    def openalex_id(self) -> str:
        """Extract the short OpenAlex ID (W123456789)."""
        if self.id:
            return self.id.split("/")[-1]
        return ""

    @property
    def abstract(self) -> str | None:
        """Reconstruct abstract from inverted index."""
        if not self.abstract_inverted_index:
            return None

        # Reconstruct from inverted index
        positions = []
        for word, indices in self.abstract_inverted_index.items():
            for idx in indices:
                positions.append((idx, word))

        positions.sort(key=lambda x: x[0])
        return " ".join(word for _, word in positions)

    @property
    def is_oa(self) -> bool:
        """Check if the work has an open access version."""
        return self.best_oa_location is not None

    @property
    def oa_url(self) -> str | None:
        """Get the best OA URL."""
        if self.best_oa_location:
            return self.best_oa_location.get("pdf_url") or self.best_oa_location.get("landing_page_url")
        return None

    @property
    def authors(self) -> list[str]:
        """Get list of author names."""
        names = []
        for authorship in self.authorships:
            author = authorship.get("author", {})
            if author and author.get("display_name"):
                names.append(author["display_name"])
        return names

    @property
    def venue(self) -> str | None:
        """Get venue name."""
        if self.primary_location:
            source = self.primary_location.get("source", {})
            if source:
                return source.get("display_name")
        return None


@dataclass
class OpenAlexConfig:
    """Configuration for OpenAlex API."""

    email: str | None = None  # For polite pool access
    base_url: str = OPENALEX_API_BASE
    requests_per_second: float = 10.0  # Polite pool rate
    max_results_per_query: int = 200


class OpenAlexAdapter:
    """
    Adapter for OpenAlex API.

    Features:
    - Email-based polite pool access
    - Rate limiting
    - Response caching
    - Full text search
    - Entity expansion
    """

    def __init__(
        self,
        email: str | None = None,
        config: OpenAlexConfig | None = None,
    ):
        self.config = config or OpenAlexConfig(email=email)
        self._client: httpx.AsyncClient | None = None
        self._last_request_time: float = 0
        self._cache: dict[str, tuple[Any, float]] = {}

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            headers = {"User-Agent": f"ResearchOS/0.1.0 (mailto:{self.config.email or 'anonymous'})"}
            self._client = httpx.AsyncClient(
                base_url=self.config.base_url,
                headers=headers,
                timeout=httpx.Timeout(30.0),
                follow_redirects=True,
            )
        return self._client

    async def _rate_limit(self) -> None:
        """Apply rate limiting."""
        min_interval = 1.0 / self.config.requests_per_second
        elapsed = time.time() - self._last_request_time
        if elapsed < min_interval:
            await asyncio.sleep(min_interval - elapsed)
        self._last_request_time = time.time()

    async def _request(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
        use_cache: bool = True,
    ) -> dict[str, Any]:
        """Make a rate-limited request to OpenAlex."""
        cache_key = hashlib.sha256(
            json.dumps({"endpoint": endpoint, "params": params or {}}, sort_keys=True).encode()
        ).hexdigest()

        if use_cache:
            cached = self._cache.get(cache_key)
            if cached and time.time() - cached[1] < 86400:  # 24 hour cache
                return cached[0]

        await self._rate_limit()

        client = await self._get_client()
        response = await client.get(endpoint, params=params)

        if response.status_code == 200:
            data = response.json()
            if use_cache:
                self._cache[cache_key] = (data, time.time())
            return data

        raise ValueError(f"OpenAlex API error: {response.status_code}")

    async def search_works(
        self,
        query: str,
        filters: dict[str, Any] | None = None,
        sort: str | None = None,
        page: int = 1,
        per_page: int = 200,
        select: list[str] | None = None,
        mailto: str | None = None,
    ) -> dict[str, Any]:
        """
        Search for works.

        Args:
            query: Search query
            filters: Filter parameters (e.g., {"publication_year": "2020-2024"})
            sort: Sort field (e.g., "cited_by_count:desc")
            page: Page number
            per_page: Results per page (max 200)
            select: Fields to return
            mailto: Email for large page sizes
        """
        params = {
            "search": query,
            "page": page,
            "per_page": min(per_page, 200),
        }

        if filters:
            filter_parts = []
            for key, value in filters.items():
                if isinstance(value, list):
                    filter_parts.append(f"{key}:{'|'.join(str(v) for v in value)}")
                else:
                    filter_parts.append(f"{key}:{value}")
            params["filter"] = ",".join(filter_parts)

        if sort:
            params["sort"] = sort

        if select:
            params["select"] = ",".join(select)

        if mailto or self.config.email:
            params["mailto"] = mailto or self.config.email

        return await self._request("/works", params=params)

    async def get_work(self, work_id: str, select: list[str] | None = None) -> OpenAlexWork:
        """
        Get a single work by ID.

        Args:
            work_id: OpenAlex ID (W123456789), DOI, or URL
            select: Fields to return
        """
        params = {}
        if select:
            params["select"] = ",".join(select)

        # Normalize ID
        if work_id.startswith("10."):
            work_id = f"doi:{work_id}"
        elif work_id.startswith("W") and len(work_id) == 10:
            work_id = f"https://openalex.org/{work_id}"

        data = await self._request(f"/works/{work_id}", params=params)
        return OpenAlexWork(**data)

    async def get_works_batch(
        self,
        work_ids: list[str],
        select: list[str] | None = None,
    ) -> list[OpenAlexWork]:
        """
        Get multiple works in a single request.

        Uses the filter endpoint with openalex_id.
        """
        if not work_ids:
            return []

        # Normalize IDs
        normalized_ids = []
        for wid in work_ids:
            if wid.startswith("10."):
                normalized_ids.append(f"doi:{wid}")
            elif wid.startswith("W") and len(wid) == 10:
                normalized_ids.append(f"https://openalex.org/{wid}")
            else:
                normalized_ids.append(wid)

        params = {
            "filter": f"openalex_id:{'|'.join(normalized_ids)}",
            "per_page": len(work_ids),
        }

        if select:
            params["select"] = ",".join(select)

        data = await self._request("/works", params=params)
        return [OpenAlexWork(**w) for w in data.get("results", [])]

    async def get_referenced_works(self, work_id: str) -> list[OpenAlexWork]:
        """Get works referenced by a given work."""
        work = await self.get_work(work_id, select=["referenced_works"])
        if not work.referenced_works:
            return []

        return await self.get_works_batch(work.referenced_works[:50])

    async def get_related_works(self, work_id: str) -> list[OpenAlexWork]:
        """Get works related to a given work."""
        work = await self.get_work(work_id, select=["related_works"])
        if not work.related_works:
            return []

        return await self.get_works_batch(work.related_works[:20])

    async def get_citing_works(
        self,
        work_id: str,
        page: int = 1,
        per_page: int = 100,
    ) -> dict[str, Any]:
        """Get works that cite a given work."""
        params = {
            "filter": f"cites:{work_id}",
            "page": page,
            "per_page": per_page,
            "sort": "publication_year:desc",
        }

        return await self._request("/works", params=params)

    async def get_author(self, author_id: str) -> dict[str, Any]:
        """Get author by ID."""
        return await self._request(f"/authors/{author_id}")

    async def get_concept(self, concept_id: str) -> dict[str, Any]:
        """Get concept by ID."""
        return await self._request(f"/concepts/{concept_id}")

    async def get_venue(self, venue_id: str) -> dict[str, Any]:
        """Get venue by ID."""
        return await self._request(f"/venues/{venue_id}")

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
