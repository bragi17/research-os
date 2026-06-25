"""Web search literature source wrapper."""

from __future__ import annotations

from typing import Any

import httpx

from libs.schemas.literature import (
    LiteratureCandidate,
    LiteratureErrorKind,
    LiteratureSource,
    LiteratureSourceError,
)
from services.literature_errors import SourceRequestError
from services.literature_sources.base import SourceSearchResult, compact_raw, parse_year


class WebSearchSource:
    source = LiteratureSource.WEB_SEARCH

    def __init__(
        self,
        options: dict[str, object] | None = None,
        **dependencies: object,
    ) -> None:
        self.options = dict(options or {})
        self.provider = str(self.options.get("provider") or "").casefold()
        self.api_key = dependencies.get("api_key") or self.options.get("api_key")
        self._client = dependencies.get("client")
        self._owns_client = self._client is None

    async def search(self, query: str, limit: int = 50) -> SourceSearchResult:
        if self.provider not in {"tavily", "exa", "serpapi"}:
            return SourceSearchResult(
                source=self.source,
                unavailable_reason="Web search provider is not configured",
            )
        if not self.api_key:
            return SourceSearchResult(
                source=self.source,
                unavailable_reason=f"{self.provider} API key is not configured",
            )

        try:
            records = await self._search_provider(query, limit)
        except SourceRequestError as exc:
            return SourceSearchResult(
                source=self.source,
                errors=[exc.to_report_error(query)],
            )
        except httpx.RequestError as exc:
            return SourceSearchResult(
                source=self.source,
                errors=[
                    LiteratureSourceError(
                        source=self.source,
                        kind=LiteratureErrorKind.TRANSIENT_ERROR,
                        message=f"Web search request failed: {exc}",
                        query=query,
                    )
                ],
            )

        return SourceSearchResult(
            source=self.source,
            candidates=[
                candidate
                for index, record in enumerate(records[:limit])
                if (candidate := self._candidate(record, index)) is not None
            ],
        )

    async def close(self) -> None:
        close = getattr(self._client, "aclose", None)
        if self._owns_client and close is not None:
            await close()
        return None

    async def _search_provider(self, query: str, limit: int) -> list[dict[str, Any]]:
        if self.provider == "tavily":
            return await self._search_tavily(query, limit)
        if self.provider == "exa":
            return await self._search_exa(query, limit)
        return await self._search_serpapi(query, limit)

    async def _search_tavily(self, query: str, limit: int) -> list[dict[str, Any]]:
        response = await self._client_or_create().post(
            "https://api.tavily.com/search",
            json={
                "api_key": str(self.api_key),
                "query": query,
                "max_results": min(limit, 20),
                "include_answer": False,
            },
        )
        data = self._checked_json(response)
        results = data.get("results", []) if isinstance(data, dict) else []
        return [dict(result) for result in results if isinstance(result, dict)]

    async def _search_exa(self, query: str, limit: int) -> list[dict[str, Any]]:
        response = await self._client_or_create().post(
            "https://api.exa.ai/search",
            headers={"x-api-key": str(self.api_key)},
            json={"query": query, "numResults": min(limit, 25), "contents": {"text": True}},
        )
        data = self._checked_json(response)
        results = data.get("results", []) if isinstance(data, dict) else []
        return [dict(result) for result in results if isinstance(result, dict)]

    async def _search_serpapi(self, query: str, limit: int) -> list[dict[str, Any]]:
        response = await self._client_or_create().get(
            "https://serpapi.com/search.json",
            params={"engine": "google_scholar", "q": query, "api_key": str(self.api_key)},
        )
        data = self._checked_json(response)
        results = data.get("organic_results", []) if isinstance(data, dict) else []
        return [dict(result) for result in results[:limit] if isinstance(result, dict)]

    def _checked_json(self, response: httpx.Response) -> Any:
        if response.status_code == 401 or response.status_code == 403:
            raise SourceRequestError(
                source=self.source,
                kind=LiteratureErrorKind.CREDENTIAL_ERROR,
                message="Web search credentials were rejected",
                status_code=response.status_code,
            )
        if response.status_code == 429:
            raise SourceRequestError(
                source=self.source,
                kind=LiteratureErrorKind.RATE_LIMITED,
                message="Web search rate limit exceeded",
                status_code=response.status_code,
            )
        if response.status_code >= 500:
            raise SourceRequestError(
                source=self.source,
                kind=LiteratureErrorKind.TRANSIENT_ERROR,
                message=f"Web search transient error: {response.status_code}",
                status_code=response.status_code,
            )
        response.raise_for_status()
        return response.json()

    def _candidate(self, record: dict[str, Any], index: int) -> LiteratureCandidate | None:
        title = str(record.get("title") or record.get("name") or "").strip()
        if not title:
            return None
        url = record.get("url") or record.get("link")
        abstract = record.get("content") or record.get("snippet") or record.get("text")
        return LiteratureCandidate(
            candidate_id=f"WEB:{self.provider}:{url or index}",
            title=title,
            source=self.source,
            url=str(url).strip() if url else None,
            abstract=str(abstract).strip() if abstract else None,
            year=parse_year(record.get("publishedDate") or record.get("year")),
            authors=self._authors(record),
            raw=compact_raw(dict(record)),
        )

    def _authors(self, record: dict[str, Any]) -> list[str]:
        value = record.get("authors") or record.get("author")
        if isinstance(value, str):
            return [value]
        if isinstance(value, list):
            return [str(author) for author in value if author]
        publication_info = record.get("publication_info")
        if isinstance(publication_info, dict) and publication_info.get("authors"):
            authors = publication_info["authors"]
            if isinstance(authors, list):
                return [
                    str(author.get("name") if isinstance(author, dict) else author)
                    for author in authors
                ]
        return []

    def _client_or_create(self) -> Any:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(30.0))
        return self._client
