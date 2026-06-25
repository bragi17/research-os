"""Research OS local library literature source."""

from __future__ import annotations

from typing import Any

from libs.schemas.literature import LiteratureCandidate, LiteratureSource
from services.library import tools_db
from services.literature_sources.base import (
    SourceSearchResult,
    coerce_list,
    compact_raw,
    has_token_overlap,
    parse_year,
)


class LocalLibrarySource:
    source = LiteratureSource.LOCAL_LIBRARY

    def __init__(
        self,
        options: dict[str, object] | None = None,
        **dependencies: object,
    ) -> None:
        self.options = dict(options or {})

    async def search(self, query: str, limit: int = 50) -> SourceSearchResult:
        papers = await tools_db.list_library_papers(limit=200)
        candidates: list[LiteratureCandidate] = []
        for paper in papers:
            if not has_token_overlap(
                query,
                paper.get("title"),
                paper.get("keywords"),
                paper.get("methods"),
                paper.get("innovation_points"),
                paper.get("summary_json"),
            ):
                continue
            title = str(paper.get("title") or "").strip()
            if not title:
                continue
            candidates.append(self._candidate(paper))
            if len(candidates) >= limit:
                break
        return SourceSearchResult(source=self.source, candidates=candidates)

    async def close(self) -> None:
        return None

    def _candidate(self, paper: dict[str, Any]) -> LiteratureCandidate:
        return LiteratureCandidate(
            candidate_id=f"LOCAL:{paper['id']}",
            title=str(paper.get("title") or ""),
            source=self.source,
            doi=str(paper["doi"]).strip() if paper.get("doi") else None,
            arxiv_id=str(paper["arxiv_id"]).strip() if paper.get("arxiv_id") else None,
            url=str(paper["url"]).strip() if paper.get("url") else None,
            abstract=str(paper["abstract"]).strip() if paper.get("abstract") else None,
            year=parse_year(paper.get("year") or paper.get("publication_year")),
            venue=str(paper["venue"]).strip() if paper.get("venue") else None,
            authors=coerce_list(paper.get("authors")),
            raw=compact_raw(dict(paper)),
        )
