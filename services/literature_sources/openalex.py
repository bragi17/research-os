"""OpenAlex literature source wrapper."""

from __future__ import annotations

from typing import Any

from libs.adapters.openalex import OpenAlexAdapter
from libs.schemas.literature import LiteratureCandidate, LiteratureSource
from services.literature_errors import SourceRequestError
from services.literature_sources.base import SourceSearchResult, compact_raw, parse_year


class OpenAlexSource:
    source = LiteratureSource.OPENALEX

    def __init__(
        self,
        options: dict[str, object] | None = None,
        **dependencies: object,
    ) -> None:
        self.options = dict(options or {})
        self.email = dependencies.get("email") or self.options.get("email")
        self.api_key = dependencies.get("api_key") or self.options.get("api_key")
        self.api_keys = dependencies.get("api_keys") or self.options.get("api_keys")
        self.source_key_pool = dependencies.get("source_key_pool")
        self.adapter_class = dependencies.get("adapter_class", OpenAlexAdapter)

    async def search(self, query: str, limit: int = 50) -> SourceSearchResult:
        adapter = self.adapter_class(
            email=str(self.email) if self.email else None,
            api_key=str(self.api_key) if self.api_key else None,
            api_keys=list(self.api_keys) if isinstance(self.api_keys, (list, tuple)) else None,
            source_key_pool=self.source_key_pool,
        )
        try:
            data = await adapter.search_works(query, per_page=limit)
        except SourceRequestError as exc:
            return SourceSearchResult(
                source=self.source,
                errors=[exc.to_report_error(query)],
            )
        finally:
            close = getattr(adapter, "close", None)
            if close is not None:
                await close()

        works = data.get("results", []) if isinstance(data, dict) else []
        return SourceSearchResult(
            source=self.source,
            candidates=[
                candidate
                for work in works[:limit]
                if (candidate := self._candidate(work)) is not None
            ],
        )

    async def close(self) -> None:
        return None

    def _candidate(self, work: object) -> LiteratureCandidate | None:
        if not isinstance(work, dict):
            return None
        title = str(work.get("title") or work.get("display_name") or "").strip()
        openalex_url = str(work.get("id") or "").strip()
        openalex_id = openalex_url.rsplit("/", 1)[-1] if openalex_url else ""
        if not title or not openalex_id:
            return None

        ids = work.get("ids") if isinstance(work.get("ids"), dict) else {}
        doi = work.get("doi") or ids.get("doi")
        url = self._best_url(work) or openalex_url
        return LiteratureCandidate(
            candidate_id=f"OPENALEX:{openalex_id}",
            title=title,
            source=self.source,
            doi=self._clean_doi(doi),
            openalex_id=openalex_id,
            url=url,
            abstract=self._abstract(work.get("abstract_inverted_index")),
            year=parse_year(work.get("publication_year") or work.get("publication_date")),
            venue=self._venue(work),
            authors=self._authors(work.get("authorships")),
            raw=compact_raw(dict(work)),
        )

    def _authors(self, value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        authors: list[str] = []
        for authorship in value:
            if not isinstance(authorship, dict):
                continue
            author = authorship.get("author")
            if isinstance(author, dict) and author.get("display_name"):
                authors.append(str(author["display_name"]))
        return authors

    def _venue(self, work: dict[str, Any]) -> str | None:
        location = work.get("primary_location")
        if not isinstance(location, dict):
            return None
        source = location.get("source")
        if not isinstance(source, dict):
            return None
        return self._clean_optional(source.get("display_name"))

    def _best_url(self, work: dict[str, Any]) -> str | None:
        for key in ("best_oa_location", "primary_location"):
            location = work.get(key)
            if not isinstance(location, dict):
                continue
            value = location.get("pdf_url") or location.get("landing_page_url")
            if value:
                return str(value)
        return None

    def _abstract(self, inverted_index: object) -> str | None:
        if not isinstance(inverted_index, dict):
            return None
        positions: list[tuple[int, str]] = []
        for word, indices in inverted_index.items():
            if not isinstance(indices, list):
                continue
            for index in indices:
                if isinstance(index, int):
                    positions.append((index, str(word)))
        if not positions:
            return None
        return " ".join(word for _, word in sorted(positions))

    def _clean_doi(self, value: object) -> str | None:
        text = self._clean_optional(value)
        if text is None:
            return None
        return text.removeprefix("https://doi.org/")

    def _clean_optional(self, value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None
