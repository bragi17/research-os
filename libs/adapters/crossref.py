"""
Research OS - Crossref Adapter

Adapter for Crossref REST API - DOI metadata and citation data.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from typing import Any

import httpx
from pydantic import BaseModel, Field
from structlog import get_logger

logger = get_logger(__name__)

CROSSREF_API_BASE = "https://api.crossref.org"


class CrossrefWork(BaseModel):
    """Crossref work data."""

    doi: str | None = None
    title: list[str] | None = None
    author: list[dict[str, Any]] = Field(default_factory=list)
    abstract: str | None = None
    published_print: dict[str, Any] | None = Field(None, alias="published-print")
    published_online: dict[str, Any] | None = Field(None, alias="published-online")
    created: dict[str, Any] | None = None
    container_title: list[str] | None = Field(None, alias="container-title")
    publisher: str | None = None
    volume: str | None = None
    issue: str | None = None
    page: str | None = None
    article_number: str | None = Field(None, alias="article-number")
    type: str | None = None
    subtype: str | None = None
    is_referenced_by_count: int = Field(default=0, alias="is-referenced-by-count")
    references_count: int = Field(default=0, alias="references-count")
    reference: list[dict[str, Any]] = Field(default_factory=list)
    subject: list[str] = Field(default_factory=list)
    license: list[dict[str, Any]] = Field(default_factory=list)
    link: list[dict[str, Any]] = Field(default_factory=list)
    issn: list[str] = Field(default_factory=list)
    url: str | None = None

    class Config:
        populate_by_name = True

    @property
    def display_title(self) -> str | None:
        """Get the first title."""
        if self.title:
            return self.title[0]
        return None

    @property
    def publication_year(self) -> int | None:
        """Extract publication year."""
        for source in [self.published_print, self.published_online]:
            if source and "date-parts" in source:
                parts = source["date-parts"]
                if parts and parts[0]:
                    return parts[0][0]
        if self.created and "date-parts" in self.created:
            parts = self.created["date-parts"]
            if parts and parts[0]:
                return parts[0][0]
        return None

    @property
    def authors(self) -> list[str]:
        """Get list of author names."""
        names = []
        for author in self.author:
            given = author.get("given", "")
            family = author.get("family", "")
            if given and family:
                names.append(f"{given} {family}")
            elif family:
                names.append(family)
        return names

    @property
    def venue(self) -> str | None:
        """Get venue name."""
        if self.container_title:
            return self.container_title[0]
        return None

    @property
    def pdf_url(self) -> str | None:
        """Get PDF URL if available."""
        for link in self.link:
            if link.get("content-type") == "application/pdf":
                return link.get("URL")
        return None


class CrossrefAdapter:
    """
    Adapter for Crossref REST API.

    Features:
    - DOI metadata lookup
    - Citation data
    - Reference extraction
    - Polite pool access
    """

    def __init__(
        self,
        email: str | None = None,
        base_url: str = CROSSREF_API_BASE,
        requests_per_second: float = 50.0,  # Polite pool rate
    ):
        self.email = email
        self.base_url = base_url
        self.requests_per_second = requests_per_second
        self._client: httpx.AsyncClient | None = None
        self._last_request_time: float = 0
        self._cache: dict[str, tuple[Any, float]] = {}

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            headers = {
                "User-Agent": f"ResearchOS/0.1.0 (mailto:{self.email or 'anonymous'})",
            }
            if self.email:
                headers["mailto"] = self.email

            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers=headers,
                timeout=httpx.Timeout(30.0),
            )
        return self._client

    async def _rate_limit(self) -> None:
        """Apply rate limiting."""
        min_interval = 1.0 / self.requests_per_second
        elapsed = time.time() - self._last_request_time
        if elapsed < min_interval:
            await asyncio.sleep(min_interval - elapsed)
        self._last_request_time = time.time()

    async def _request(self, endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Make a rate-limited request to Crossref."""
        cache_key = hashlib.sha256(
            json.dumps({"endpoint": endpoint, "params": params or {}}, sort_keys=True).encode()
        ).hexdigest()

        cached = self._cache.get(cache_key)
        if cached and time.time() - cached[1] < 86400:
            return cached[0]

        await self._rate_limit()

        client = await self._get_client()
        response = await client.get(endpoint, params=params)

        if response.status_code == 200:
            data = response.json()
            self._cache[cache_key] = (data, time.time())
            return data

        if response.status_code == 404:
            raise ValueError(f"Resource not found: {endpoint}")

        raise ValueError(f"Crossref API error: {response.status_code}")

    async def get_work(self, doi: str) -> CrossrefWork:
        """
        Get work metadata by DOI.

        Args:
            doi: DOI (with or without "https://doi.org/" prefix)
        """
        # Normalize DOI
        doi = doi.strip()
        if doi.startswith("https://doi.org/"):
            doi = doi[16:]
        elif doi.startswith("http://doi.org/"):
            doi = doi[15:]
        elif doi.startswith("doi:"):
            doi = doi[4:].strip()

        data = await self._request(f"/works/{doi}")
        return CrossrefWork(**data.get("message", {}))

    async def get_works_batch(self, dois: list[str]) -> list[CrossrefWork]:
        """
        Get multiple works by DOI.

        Note: Crossref doesn't have a true batch endpoint,
        so we make individual requests with rate limiting.
        """
        works = []
        for doi in dois:
            try:
                work = await self.get_work(doi)
                works.append(work)
            except ValueError:
                logger.warning("crossref_doi_not_found", doi=doi)
        return works

    async def search_works(
        self,
        query: str | None = None,
        query_title: str | None = None,
        query_author: str | None = None,
        query_bibliographic: str | None = None,
        filter_params: dict[str, Any] | None = None,
        rows: int = 20,
        offset: int = 0,
        sort: str = "score",
        order: str = "desc",
        select: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Search for works.

        Args:
            query: General query
            query_title: Title-specific query
            query_author: Author-specific query
            query_bibliographic: Bibliographic query
            filter_params: Filter parameters (e.g., {"from-pub-date": "2020"})
            rows: Number of results (max 1000)
            offset: Result offset
            sort: Sort field (score, published, deposited, etc.)
            order: Sort order (asc, desc)
            select: Fields to return
        """
        params = {
            "rows": min(rows, 1000),
            "offset": offset,
            "sort": sort,
            "order": order,
        }

        if query:
            params["query"] = query
        if query_title:
            params["query.title"] = query_title
        if query_author:
            params["query.author"] = query_author
        if query_bibliographic:
            params["query.bibliographic"] = query_bibliographic

        if filter_params:
            filter_parts = []
            for key, value in filter_params.items():
                if isinstance(value, list):
                    filter_parts.append(f"{key}:{','.join(str(v) for v in value)}")
                else:
                    filter_parts.append(f"{key}:{value}")
            params["filter"] = ",".join(filter_parts)

        if select:
            params["select"] = ",".join(select)

        return await self._request("/works", params=params)

    async def get_works_by_author(
        self,
        orcid: str | None = None,
        author_email: str | None = None,
        rows: int = 100,
    ) -> dict[str, Any]:
        """Get works by author identifier."""
        filter_params = {}
        if orcid:
            filter_params["orcid"] = orcid
        if author_email:
            filter_params["author_email"] = author_email

        if not filter_params:
            raise ValueError("Either orcid or author_email must be provided")

        return await self.search_works(filter_params=filter_params, rows=rows)

    async def get_citing_works(self, doi: str, rows: int = 1000) -> dict[str, Any]:
        """
        Get works that cite a given DOI.

        Note: This uses the "cited-by" feature which requires member access.
        """
        filter_params = {"references": doi}
        return await self.search_works(filter_params=filter_params, rows=rows)

    async def resolve_doi(self, doi: str) -> str | None:
        """Resolve a DOI to its URL."""
        try:
            work = await self.get_work(doi)
            return work.url or f"https://doi.org/{doi}"
        except ValueError:
            return None

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
