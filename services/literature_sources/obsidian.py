"""Obsidian markdown vault literature source."""

from __future__ import annotations

import re
from pathlib import Path

from libs.schemas.literature import LiteratureCandidate, LiteratureSource
from services.literature_sources.base import (
    SourceSearchResult,
    compact_raw,
    first_arxiv_id,
    first_doi,
    has_token_overlap,
    parse_year,
)


class ObsidianSource:
    source = LiteratureSource.OBSIDIAN

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
                unavailable_reason="Obsidian vault path is not configured",
            )

        path = Path(str(path_value)).expanduser()
        if not path.exists():
            return SourceSearchResult(
                source=self.source,
                unavailable_reason=f"Obsidian vault path does not exist: {path}",
            )

        candidates: list[LiteratureCandidate] = []
        for note in sorted(path.rglob("*.md")):
            text = note.read_text(encoding="utf-8")
            metadata, body = self._split_frontmatter(text)
            title = str(metadata.get("title") or self._first_heading(body) or note.stem).strip()
            if not has_token_overlap(query, title, body):
                continue
            doi = metadata.get("doi") or first_doi(text)
            arxiv_id = metadata.get("arxiv") or metadata.get("arxiv_id") or first_arxiv_id(text)
            candidates.append(
                LiteratureCandidate(
                    candidate_id=f"OBSIDIAN:{note.relative_to(path)}",
                    title=title,
                    source=self.source,
                    doi=str(doi).strip() if doi else None,
                    arxiv_id=str(arxiv_id).strip() if arxiv_id else None,
                    year=parse_year(metadata.get("year") or metadata.get("date")),
                    url=str(metadata["url"]).strip() if metadata.get("url") else None,
                    raw=compact_raw({"path": str(note), "metadata": metadata}),
                )
            )
            if len(candidates) >= limit:
                break

        return SourceSearchResult(source=self.source, candidates=candidates)

    async def close(self) -> None:
        return None

    def _split_frontmatter(self, text: str) -> tuple[dict[str, str], str]:
        if not text.startswith("---\n"):
            return {}, text
        end = text.find("\n---", 4)
        if end == -1:
            return {}, text

        metadata: dict[str, str] = {}
        for line in text[4:end].splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            metadata[key.strip().casefold()] = value.strip().strip("'\"")
        return metadata, text[end + 4 :]

    def _first_heading(self, text: str) -> str | None:
        match = re.search(r"^#\s+(.+)$", text, flags=re.MULTILINE)
        return match.group(1).strip() if match else None
