"""
Research OS - Unpaywall Adapter

Adapter for Unpaywall REST API - open access location discovery.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from enum import Enum
from typing import Any

import httpx
from pydantic import BaseModel, Field
from structlog import get_logger

logger = get_logger(__name__)

UNPAYWALL_API_BASE = "https://api.unpaywall.org/v2"


class OAStatus(str, Enum):
    """Open access status types."""

    GOLD = "gold"          # Published OA
    HYBRID = "hybrid"      # Hybrid OA
    BRONZE = "bronze"      # Free but without license
    GREEN = "green"        # Self-archived in repository
    CLOSED = "closed"      # Not OA


class OALocation(BaseModel):
    """An open access location."""

    endpoint_id: str | None = Field(None, alias="endpoint_id")
    evidence: str | None = None
    host_type: str | None = Field(None, alias="host_type")  # publisher or repository
    is_best: bool = Field(default=False, alias="is_best")
    license: str | None = None
    license_type: str | None = Field(None, alias="license")  # Same as license, different key
    oa_date: str | None = Field(None, alias="oa_date")
    pmh_id: str | None = Field(None, alias="pmh_id")
    repository_institution: str | None = Field(None, alias="repository_institution")
    updated: str | None = None
    url: str | None = None
    url_for_landing_page: str | None = Field(None, alias="url_for_landing_page")
    url_for_pdf: str | None = Field(None, alias="url_for_pdf")
    version: str | None = None  # publishedVersion, acceptedVersion, etc.

    class Config:
        populate_by_name = True


class UnpaywallWork(BaseModel):
    """Unpaywall work data."""

    doi: str | None = None
    doi_url: str | None = Field(None, alias="doi_url")
    title: str | None = None
    genre: str | None = None
    is_paratext: bool = Field(default=False, alias="is_paratext")
    has_repository_copy: bool = Field(default=False, alias="has_repository_copy")
    is_oa: bool = Field(default=False, alias="is_oa")
    journal_is_in_doaj: bool = Field(default=False, alias="journal_is_in_doaj")
    journal_is_oa: bool = Field(default=False, alias="journal_is_oa")
    journal_name: str | None = Field(None, alias="journal_name")
    oa_locations: list[OALocation] = Field(default_factory=list, alias="oa_locations")
    oa_locations_embargoed: list[OALocation] = Field(default_factory=list, alias="oa_locations_embargoed")
    oa_status: OAStatus | None = Field(None, alias="oa_status")
    published_date: str | None = Field(None, alias="published_date")
    publisher: str | None = None
    title: str | None = None
    updated: str | None = None
    year: int | None = None
    z_authors: list[dict[str, Any]] = Field(default_factory=list, alias="z_authors")

    class Config:
        populate_by_name = True

    @property
    def best_oa_location(self) -> OALocation | None:
        """Get the best OA location."""
        for loc in self.oa_locations:
            if loc.is_best:
                return loc
        return self.oa_locations[0] if self.oa_locations else None

    @property
    def pdf_url(self) -> str | None:
        """Get the best PDF URL."""
        best = self.best_oa_location
        if best:
            return best.url_for_pdf or best.url
        return None

    @property
    def landing_page_url(self) -> str | None:
        """Get the best landing page URL."""
        best = self.best_oa_location
        if best:
            return best.url_for_landing_page or best.url
        return None

    @property
    def authors(self) -> list[str]:
        """Get list of author names."""
        names = []
        for author in self.z_authors:
            given = author.get("given", "")
            family = author.get("family", "")
            if given and family:
                names.append(f"{given} {family}")
            elif family:
                names.append(family)
        return names


class UnpaywallAdapter:
    """
    Adapter for Unpaywall REST API.

    Features:
    - Open access location discovery
    - License detection
    - Repository vs publisher distinction
    - Version identification
    """

    def __init__(
        self,
        email: str,
        base_url: str = UNPAYWALL_API_BASE,
        requests_per_second: float = 1.0,
    ):
        """
        Initialize Unpaywall adapter.

        Args:
            email: Required email for API access
            base_url: API base URL
            requests_per_second: Rate limit
        """
        if not email:
            raise ValueError("Email is required for Unpaywall API")

        self.email = email
        self.base_url = base_url
        self.requests_per_second = requests_per_second
        self._client: httpx.AsyncClient | None = None
        self._last_request_time: float = 0
        self._cache: dict[str, tuple[Any, float]] = {}

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
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

    async def _request(self, doi: str) -> dict[str, Any]:
        """Make a rate-limited request to Unpaywall."""
        cache_key = hashlib.sha256(doi.encode()).hexdigest()

        cached = self._cache.get(cache_key)
        if cached and time.time() - cached[1] < 86400 * 7:  # 7 day cache
            return cached[0]

        await self._rate_limit()

        client = await self._get_client()
        response = await client.get(f"/{doi}", params={"email": self.email})

        if response.status_code == 200:
            data = response.json()
            self._cache[cache_key] = (data, time.time())
            return data

        if response.status_code == 404:
            raise ValueError(f"DOI not found in Unpaywall: {doi}")

        raise ValueError(f"Unpaywall API error: {response.status_code}")

    async def get_work(self, doi: str) -> UnpaywallWork:
        """
        Get OA information for a DOI.

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

        data = await self._request(doi)
        return UnpaywallWork(**data)

    async def get_oa_url(self, doi: str) -> str | None:
        """
        Get the best OA URL for a DOI.

        Returns PDF URL if available, otherwise landing page.
        """
        try:
            work = await self.get_work(doi)
            return work.pdf_url
        except ValueError:
            return None

    async def get_pdf_url(self, doi: str) -> str | None:
        """Get PDF URL specifically."""
        try:
            work = await self.get_work(doi)
            return work.pdf_url
        except ValueError:
            return None

    async def get_license(self, doi: str) -> str | None:
        """Get the OA license for a DOI."""
        try:
            work = await self.get_work(doi)
            best = work.best_oa_location
            return best.license if best else None
        except ValueError:
            return None

    async def is_oa(self, doi: str) -> bool:
        """Check if a DOI has an OA version."""
        try:
            work = await self.get_work(doi)
            return work.is_oa
        except ValueError:
            return False

    async def get_oa_status(self, doi: str) -> OAStatus | None:
        """Get the OA status classification."""
        try:
            work = await self.get_work(doi)
            return work.oa_status
        except ValueError:
            return None

    async def get_repository_locations(self, doi: str) -> list[OALocation]:
        """Get all repository OA locations (not publisher)."""
        try:
            work = await self.get_work(doi)
            return [
                loc
                for loc in work.oa_locations
                if loc.host_type == "repository"
            ]
        except ValueError:
            return []

    async def get_publisher_locations(self, doi: str) -> list[OALocation]:
        """Get all publisher OA locations."""
        try:
            work = await self.get_work(doi)
            return [
                loc
                for loc in work.oa_locations
                if loc.host_type == "publisher"
            ]
        except ValueError:
            return []

    async def batch_check_oa(self, dois: list[str]) -> dict[str, bool]:
        """
        Check OA status for multiple DOIs.

        Returns dict mapping DOI to is_oa boolean.
        """
        results = {}
        for doi in dois:
            try:
                work = await self.get_work(doi)
                results[doi] = work.is_oa
            except ValueError:
                results[doi] = False
        return results

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
