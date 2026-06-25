"""Zotero export literature source."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from libs.schemas.literature import LiteratureCandidate, LiteratureSource
from services.literature_sources.base import (
    SourceSearchResult,
    compact_raw,
    has_token_overlap,
    parse_year,
)


class ZoteroSource:
    source = LiteratureSource.ZOTERO

    def __init__(
        self,
        options: dict[str, object] | None = None,
        **dependencies: object,
    ) -> None:
        self.options = dict(options or {})

    async def search(self, query: str, limit: int = 50) -> SourceSearchResult:
        path_value = self.options.get("path")
        if not path_value:
            return SourceSearchResult(
                source=self.source,
                unavailable_reason="Zotero export path is not configured",
            )

        path = Path(str(path_value)).expanduser()
        if not path.exists():
            return SourceSearchResult(
                source=self.source,
                unavailable_reason=f"Zotero export path does not exist: {path}",
            )

        items = self._read_bib(path) if path.suffix.casefold() == ".bib" else self._read_json(path)
        candidates: list[LiteratureCandidate] = []
        for item in items:
            title = str(item.get("title") or "").strip()
            if not title:
                continue
            body = json.dumps(item, ensure_ascii=False, default=str)
            if not has_token_overlap(query, title, body):
                continue
            candidates.append(self._candidate(item, len(candidates)))
            if len(candidates) >= limit:
                break

        return SourceSearchResult(source=self.source, candidates=candidates)

    async def close(self) -> None:
        return None

    def _read_json(self, path: Path) -> list[dict[str, Any]]:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data = data.get("items", [])
        if not isinstance(data, list):
            return []

        items: list[dict[str, Any]] = []
        for entry in data:
            if isinstance(entry, dict):
                payload = entry.get("data") if isinstance(entry.get("data"), dict) else entry
                items.append(dict(payload))
        return items

    def _read_bib(self, path: Path) -> list[dict[str, Any]]:
        text = path.read_text(encoding="utf-8")
        entries = re.findall(r"@\w+\s*\{.*?(?=\n@\w+\s*\{|\Z)", text, flags=re.DOTALL)
        return [self._parse_bib_entry(entry) for entry in entries]

    def _parse_bib_entry(self, entry: str) -> dict[str, Any]:
        fields: dict[str, Any] = {}
        for name in ("title", "doi", "year", "url"):
            match = re.search(
                rf"\b{name}\s*=\s*(?:\{{(?P<brace>.*?)\}}|\"(?P<quote>.*?)\")",
                entry,
                flags=re.IGNORECASE | re.DOTALL,
            )
            if match:
                fields[name] = (match.group("brace") or match.group("quote") or "").strip()
        fields["raw_bib"] = entry
        return fields

    def _candidate(self, item: dict[str, Any], index: int) -> LiteratureCandidate:
        title = str(item.get("title") or "").strip()
        doi = item.get("DOI") or item.get("doi")
        url = item.get("url")
        authors = self._authors(item.get("creators") or item.get("author"))
        candidate_id = f"ZOTERO:{doi or item.get('key') or index}"
        return LiteratureCandidate(
            candidate_id=str(candidate_id),
            title=title,
            source=self.source,
            doi=str(doi).strip() if doi else None,
            url=str(url).strip() if url else None,
            year=parse_year(item.get("date") or item.get("year")),
            authors=authors,
            raw=compact_raw(dict(item)),
        )

    def _authors(self, creators: object) -> list[str]:
        if isinstance(creators, str):
            return [creators]
        if not isinstance(creators, list):
            return []

        authors: list[str] = []
        for creator in creators:
            if not isinstance(creator, dict):
                continue
            name = creator.get("name")
            if not name:
                name = " ".join(
                    str(part)
                    for part in (creator.get("firstName"), creator.get("lastName"))
                    if part
                )
            if name:
                authors.append(str(name))
        return authors
