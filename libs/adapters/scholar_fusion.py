"""
Research OS - Scholar Fusion Layer

Unified layer for combining data from multiple academic sources.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from structlog import get_logger

from libs.adapters.semantic_scholar import SemanticScholarAdapter, S2Paper
from libs.adapters.openalex import OpenAlexAdapter, OpenAlexWork
from libs.adapters.crossref import CrossrefAdapter, CrossrefWork
from libs.adapters.unpaywall import UnpaywallAdapter, UnpaywallWork

logger = get_logger(__name__)


class Source(str, Enum):
    """Academic data sources."""

    SEMANTIC_SCHOLAR = "semantic_scholar"
    OPENALEX = "openalex"
    CROSSREF = "crossref"
    UNPAYWALL = "unpaywall"


@dataclass
class FusedPaper:
    """
    A paper with data fused from multiple sources.

    This is the canonical paper record used within Research OS.
    """

    # Identity
    id: UUID = field(default_factory=uuid4)
    canonical_title: str = ""
    normalized_title: str = ""

    # External IDs
    doi: str | None = None
    arxiv_id: str | None = None
    pmid: str | None = None
    s2_paper_id: str | None = None
    s2_corpus_id: int | None = None
    openalex_id: str | None = None

    # Basic metadata
    abstract: str | None = None
    year: int | None = None
    publication_date: str | None = None
    venue: str | None = None
    publisher: str | None = None

    # Authors
    authors: list[dict[str, str]] = field(default_factory=list)

    # Citation counts
    citation_count: int = 0
    influential_citation_count: int = 0
    reference_count: int = 0

    # OA status
    is_oa: bool = False
    oa_url: str | None = None
    pdf_url: str | None = None
    oa_license: str | None = None
    oa_status: str | None = None

    # Source tracking
    sources: list[str] = field(default_factory=list)
    source_records: dict[str, Any] = field(default_factory=dict)

    # Quality indicators
    source_trust_score: float = 0.0
    is_retracted: bool = False

    # Timestamps
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for database storage."""
        return {
            "id": str(self.id),
            "canonical_title": self.canonical_title,
            "normalized_title": self.normalized_title,
            "doi": self.doi,
            "arxiv_id": self.arxiv_id,
            "pmid": self.pmid,
            "s2_paper_id": self.s2_paper_id,
            "s2_corpus_id": self.s2_corpus_id,
            "openalex_id": self.openalex_id,
            "abstract": self.abstract,
            "year": self.year,
            "publication_date": self.publication_date,
            "venue": self.venue,
            "publisher": self.publisher,
            "authors": self.authors,
            "citation_count": self.citation_count,
            "influential_citation_count": self.influential_citation_count,
            "reference_count": self.reference_count,
            "is_oa": self.is_oa,
            "oa_url": self.oa_url,
            "pdf_url": self.pdf_url,
            "oa_license": self.oa_license,
            "oa_status": self.oa_status,
            "sources": self.sources,
            "source_trust_score": self.source_trust_score,
            "is_retracted": self.is_retracted,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


class ScholarFusionService:
    """
    Service for fusing data from multiple academic sources.

    Features:
    - Unified paper identity resolution
    - Cross-source deduplication
    - OA enrichment
    - Source priority handling
    """

    def __init__(
        self,
        s2_api_key: str | None = None,
        openalex_email: str | None = None,
        crossref_email: str | None = None,
        unpaywall_email: str | None = None,
    ):
        self.s2 = SemanticScholarAdapter(api_key=s2_api_key)
        self.openalex = OpenAlexAdapter(email=openalex_email)
        self.crossref = CrossrefAdapter(email=crossref_email)
        self.unpaywall = UnpaywallAdapter(email=unpaywall_email) if unpaywall_email else None

    def _normalize_title(self, title: str) -> str:
        """Normalize title for deduplication."""
        if not title:
            return ""
        # Lowercase, remove punctuation, collapse whitespace
        normalized = title.lower()
        normalized = "".join(c if c.isalnum() or c.isspace() else " " for c in normalized)
        normalized = " ".join(normalized.split())
        return normalized

    def _fuse_from_s2(self, paper: S2Paper) -> dict[str, Any]:
        """Extract data from Semantic Scholar paper."""
        return {
            "s2_paper_id": paper.paper_id,
            "s2_corpus_id": paper.corpus_id,
            "doi": paper.doi,
            "title": paper.title,
            "abstract": paper.abstract,
            "year": paper.year,
            "venue": paper.venue,
            "citation_count": paper.citation_count,
            "influential_citation_count": paper.influential_citation_count,
            "reference_count": paper.reference_count,
            "is_oa": paper.is_open_access,
            "oa_url": paper.open_access_pdf.get("url") if paper.open_access_pdf else None,
            "authors": [
                {
                    "first_name": a.get("name", "").split()[0] if a.get("name") else "",
                    "last_name": " ".join(a.get("name", "").split()[1:]) if a.get("name") else "",
                }
                for a in paper.authors
            ],
        }

    def _fuse_from_openalex(self, work: OpenAlexWork) -> dict[str, Any]:
        """Extract data from OpenAlex work."""
        return {
            "openalex_id": work.openalex_id,
            "doi": work.doi,
            "title": work.display_name or work.title,
            "abstract": work.abstract,
            "year": work.publication_year,
            "venue": work.venue,
            "citation_count": work.cited_by_count,
            "is_oa": work.is_oa,
            "oa_url": work.oa_url,
            "authors": [{"name": name} for name in work.authors],
        }

    def _fuse_from_crossref(self, work: CrossrefWork) -> dict[str, Any]:
        """Extract data from Crossref work."""
        return {
            "doi": work.doi,
            "title": work.display_title,
            "abstract": work.abstract,
            "year": work.publication_year,
            "venue": work.venue,
            "publisher": work.publisher,
            "citation_count": work.is_referenced_by_count,
            "reference_count": work.references_count,
            "pdf_url": work.pdf_url,
            "authors": [{"name": name} for name in work.authors],
        }

    def _fuse_from_unpaywall(self, work: UnpaywallWork) -> dict[str, Any]:
        """Extract data from Unpaywall work."""
        return {
            "doi": work.doi,
            "title": work.title,
            "year": work.year,
            "venue": work.journal_name,
            "publisher": work.publisher,
            "is_oa": work.is_oa,
            "oa_url": work.landing_page_url,
            "pdf_url": work.pdf_url,
            "oa_status": work.oa_status.value if work.oa_status else None,
            "oa_license": work.best_oa_location.license if work.best_oa_location else None,
        }

    def _merge_papers(
        self,
        papers: list[tuple[Source, Any]],
        primary_source: Source = Source.SEMANTIC_SCHOLAR,
    ) -> FusedPaper:
        """
        Merge data from multiple sources into a single FusedPaper.

        Priority order:
        1. Primary source
        2. S2 for citations
        3. Unpaywall for OA info
        4. Crossref for metadata
        5. OpenAlex as fallback
        """
        fused = FusedPaper()

        # Sort by priority
        priority_order = [
            primary_source,
            Source.SEMANTIC_SCHOLAR,
            Source.UNPAYWALL,
            Source.CROSSREF,
            Source.OPENALEX,
        ]

        # Remove duplicates while preserving priority order
        seen = set()
        sorted_papers = []
        for source in priority_order:
            for s, paper in papers:
                if s == source and s not in seen:
                    sorted_papers.append((s, paper))
                    seen.add(s)

        # Add remaining sources
        for s, paper in papers:
            if s not in seen:
                sorted_papers.append((s, paper))

        # Merge data
        for source, paper in sorted_papers:
            fused.sources.append(source.value)

            if source == Source.SEMANTIC_SCHOLAR:
                data = self._fuse_from_s2(paper)
                fused.source_records["s2"] = paper.model_dump()
            elif source == Source.OPENALEX:
                data = self._fuse_from_openalex(paper)
                fused.source_records["openalex"] = paper.model_dump()
            elif source == Source.CROSSREF:
                data = self._fuse_from_crossref(paper)
                fused.source_records["crossref"] = paper.model_dump()
            elif source == Source.UNPAYWALL:
                data = self._fuse_from_unpaywall(paper)
                fused.source_records["unpaywall"] = paper.model_dump()
            else:
                continue

            # Merge fields (don't overwrite if already set)
            if data.get("doi") and not fused.doi:
                fused.doi = data["doi"]
            if data.get("s2_paper_id") and not fused.s2_paper_id:
                fused.s2_paper_id = data["s2_paper_id"]
            if data.get("s2_corpus_id") and not fused.s2_corpus_id:
                fused.s2_corpus_id = data["s2_corpus_id"]
            if data.get("openalex_id") and not fused.openalex_id:
                fused.openalex_id = data["openalex_id"]
            if data.get("title") and not fused.canonical_title:
                fused.canonical_title = data["title"]
            if data.get("abstract") and not fused.abstract:
                fused.abstract = data["abstract"]
            if data.get("year") and not fused.year:
                fused.year = data["year"]
            if data.get("venue") and not fused.venue:
                fused.venue = data["venue"]
            if data.get("publisher") and not fused.publisher:
                fused.publisher = data["publisher"]
            if data.get("citation_count"):
                fused.citation_count = max(fused.citation_count, data["citation_count"])
            if data.get("influential_citation_count"):
                fused.influential_citation_count = max(
                    fused.influential_citation_count,
                    data["influential_citation_count"],
                )
            if data.get("reference_count"):
                fused.reference_count = max(fused.reference_count, data["reference_count"])
            if data.get("is_oa"):
                fused.is_oa = True
            if data.get("oa_url") and not fused.oa_url:
                fused.oa_url = data["oa_url"]
            if data.get("pdf_url") and not fused.pdf_url:
                fused.pdf_url = data["pdf_url"]
            if data.get("oa_license") and not fused.oa_license:
                fused.oa_license = data["oa_license"]
            if data.get("oa_status") and not fused.oa_status:
                fused.oa_status = data["oa_status"]
            if data.get("authors") and not fused.authors:
                fused.authors = data["authors"]

        # Normalize title
        fused.normalized_title = self._normalize_title(fused.canonical_title)

        # Calculate trust score
        fused.source_trust_score = min(len(fused.sources) * 0.25, 1.0)

        return fused

    async def resolve_paper(
        self,
        doi: str | None = None,
        title: str | None = None,
        s2_id: str | None = None,
        openalex_id: str | None = None,
    ) -> FusedPaper | None:
        """
        Resolve a paper from multiple sources.

        Args:
            doi: DOI identifier
            title: Paper title
            s2_id: Semantic Scholar paper ID
            openalex_id: OpenAlex ID

        Returns:
            FusedPaper with combined data from all sources
        """
        papers: list[tuple[Source, Any]] = []

        # Fetch from each source in parallel
        tasks = []

        if doi:
            tasks.append(self._fetch_s2_by_doi(doi))
            tasks.append(self._fetch_openalex_by_doi(doi))
            tasks.append(self._fetch_crossref_by_doi(doi))
            if self.unpaywall:
                tasks.append(self._fetch_unpaywall_by_doi(doi))

        if s2_id:
            tasks.append(self._fetch_s2_by_id(s2_id))

        if openalex_id:
            tasks.append(self._fetch_openalex_by_id(openalex_id))

        if title and not doi:
            tasks.append(self._fetch_s2_by_title(title))

        if not tasks:
            return None

        # Execute all fetches
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, tuple) and len(result) == 2:
                source, paper = result
                if paper:
                    papers.append((source, paper))

        if not papers:
            return None

        return self._merge_papers(papers)

    async def _fetch_s2_by_doi(self, doi: str) -> tuple[Source, S2Paper | None]:
        """Fetch S2 paper by DOI."""
        try:
            paper = await self.s2.get_paper(doi)
            return (Source.SEMANTIC_SCHOLAR, paper)
        except Exception as e:
            logger.debug("s2_fetch_failed", doi=doi, error=str(e))
            return (Source.SEMANTIC_SCHOLAR, None)

    async def _fetch_s2_by_id(self, s2_id: str) -> tuple[Source, S2Paper | None]:
        """Fetch S2 paper by ID."""
        try:
            paper = await self.s2.get_paper(s2_id)
            return (Source.SEMANTIC_SCHOLAR, paper)
        except Exception as e:
            logger.debug("s2_fetch_failed", s2_id=s2_id, error=str(e))
            return (Source.SEMANTIC_SCHOLAR, None)

    async def _fetch_s2_by_title(self, title: str) -> tuple[Source, S2Paper | None]:
        """Fetch S2 paper by title match."""
        try:
            result = await self.s2.match_paper(title)
            if result.get("paperId"):
                paper = await self.s2.get_paper(result["paperId"])
                return (Source.SEMANTIC_SCHOLAR, paper)
        except Exception as e:
            logger.debug("s2_title_match_failed", title=title[:50], error=str(e))
        return (Source.SEMANTIC_SCHOLAR, None)

    async def _fetch_openalex_by_doi(self, doi: str) -> tuple[Source, OpenAlexWork | None]:
        """Fetch OpenAlex work by DOI."""
        try:
            work = await self.openalex.get_work(doi)
            return (Source.OPENALEX, work)
        except Exception as e:
            logger.debug("openalex_fetch_failed", doi=doi, error=str(e))
            return (Source.OPENALEX, None)

    async def _fetch_openalex_by_id(self, openalex_id: str) -> tuple[Source, OpenAlexWork | None]:
        """Fetch OpenAlex work by ID."""
        try:
            work = await self.openalex.get_work(openalex_id)
            return (Source.OPENALEX, work)
        except Exception as e:
            logger.debug("openalex_fetch_failed", openalex_id=openalex_id, error=str(e))
            return (Source.OPENALEX, None)

    async def _fetch_crossref_by_doi(self, doi: str) -> tuple[Source, CrossrefWork | None]:
        """Fetch Crossref work by DOI."""
        try:
            work = await self.crossref.get_work(doi)
            return (Source.CROSSREF, work)
        except Exception as e:
            logger.debug("crossref_fetch_failed", doi=doi, error=str(e))
            return (Source.CROSSREF, None)

    async def _fetch_unpaywall_by_doi(self, doi: str) -> tuple[Source, UnpaywallWork | None]:
        """Fetch Unpaywall work by DOI."""
        if not self.unpaywall:
            return (Source.UNPAYWALL, None)
        try:
            work = await self.unpaywall.get_work(doi)
            return (Source.UNPAYWALL, work)
        except Exception as e:
            logger.debug("unpaywall_fetch_failed", doi=doi, error=str(e))
            return (Source.UNPAYWALL, None)

    async def close(self) -> None:
        """Close all adapters."""
        await self.s2.close()
        await self.openalex.close()
        await self.crossref.close()
        if self.unpaywall:
            await self.unpaywall.close()
