"""Semantic Scholar literature source wrapper."""

from __future__ import annotations

from libs.adapters.semantic_scholar import RateLimitConfig, SemanticScholarAdapter
from libs.schemas.literature import (
    LiteratureCandidate,
    LiteratureErrorKind,
    LiteratureSource,
)
from services.literature_errors import SourceRequestError
from services.literature_sources.base import SourceSearchResult, compact_raw, parse_year
from services.source_key_pool import NoAvailableSourceKey


class SemanticScholarSource:
    source = LiteratureSource.SEMANTIC_SCHOLAR

    def __init__(
        self,
        options: dict[str, object] | None = None,
        **dependencies: object,
    ) -> None:
        self.options = dict(options or {})
        self.key_pool = self._dependency(
            dependencies,
            "source_key_pool",
            "key_pool",
            "pool",
        )
        self.adapter_class = dependencies.get(
            "adapter_class",
            SemanticScholarAdapter,
        )

    async def search(self, query: str, limit: int = 50) -> SourceSearchResult:
        if not hasattr(self.key_pool, "acquire"):
            return SourceSearchResult(
                source=self.source,
                unavailable_reason="Semantic Scholar API key pool is not configured",
            )

        try:
            lease = await self.key_pool.acquire()
        except NoAvailableSourceKey as exc:
            return SourceSearchResult(source=self.source, unavailable_reason=str(exc))

        adapter = self.adapter_class(
            api_key=lease.secret,
            rate_limit=RateLimitConfig(burst_capacity=1),
        )
        try:
            data = await adapter.search_papers(query, limit=limit)
        except SourceRequestError as exc:
            if exc.kind is LiteratureErrorKind.RATE_LIMITED:
                self.key_pool.record_rate_limit(lease, exc.retry_after_seconds)
            elif exc.kind is LiteratureErrorKind.CREDENTIAL_ERROR:
                self.key_pool.record_credential_error(lease)
            return SourceSearchResult(
                source=self.source,
                errors=[exc.to_report_error(query)],
            )
        finally:
            close = getattr(adapter, "close", None)
            if close is not None:
                await close()

        papers = data.get("data", []) if isinstance(data, dict) else []
        return SourceSearchResult(
            source=self.source,
            candidates=[
                candidate
                for paper in papers[:limit]
                if (candidate := self._candidate(paper)) is not None
            ],
        )

    async def close(self) -> None:
        return None

    def _candidate(self, paper: object) -> LiteratureCandidate | None:
        if not isinstance(paper, dict):
            return None
        title = str(paper.get("title") or "").strip()
        paper_id = paper.get("paperId") or paper.get("paper_id")
        if not title or not paper_id:
            return None

        external_ids = paper.get("externalIds") or paper.get("external_ids") or {}
        if not isinstance(external_ids, dict):
            external_ids = {}
        open_access_pdf = paper.get("openAccessPdf") or {}
        if not isinstance(open_access_pdf, dict):
            open_access_pdf = {}

        return LiteratureCandidate(
            candidate_id=f"S2:{paper_id}",
            title=title,
            source=self.source,
            doi=self._clean_optional(external_ids.get("DOI")),
            arxiv_id=self._clean_optional(external_ids.get("ArXiv")),
            s2_id=str(paper_id),
            url=self._clean_optional(paper.get("url") or open_access_pdf.get("url")),
            abstract=self._clean_optional(paper.get("abstract")),
            year=parse_year(paper.get("year") or paper.get("publicationDate")),
            venue=self._clean_optional(paper.get("venue")),
            authors=self._authors(paper.get("authors")),
            raw=compact_raw(dict(paper)),
        )

    def _authors(self, value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        authors: list[str] = []
        for author in value:
            if isinstance(author, dict) and author.get("name"):
                authors.append(str(author["name"]))
            elif isinstance(author, str):
                authors.append(author)
        return authors

    def _clean_optional(self, value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def _dependency(
        self,
        dependencies: dict[str, object],
        *names: str,
    ) -> object | None:
        for name in names:
            if name in dependencies:
                return dependencies[name]
        return None
