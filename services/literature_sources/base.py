"""Shared interfaces for literature sources."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Protocol

from libs.schemas.literature import (
    LiteratureCandidate,
    LiteratureSource,
    LiteratureSourceError,
)

DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s\"'<>]+)", re.IGNORECASE)
ARXIV_RE = re.compile(
    r"\b(?:arxiv:)?((?:\d{4}\.\d{4,5})|(?:[a-z-]+(?:\.[A-Z]{2})?/\d{7}))\b",
    re.IGNORECASE,
)


def normalize_title_key(title: str | None) -> str:
    return " ".join((title or "").casefold().split())


def candidate_key(candidate: LiteratureCandidate) -> str:
    if candidate.doi:
        doi = normalize_doi(candidate.doi)
        if doi:
            return f"doi:{doi}"
    if candidate.arxiv_id:
        arxiv_id = normalize_arxiv_id(candidate.arxiv_id)
        if arxiv_id:
            return f"arxiv:{arxiv_id}"
    if candidate.s2_id:
        return f"s2:{candidate.s2_id}"
    if candidate.openalex_id:
        return f"openalex:{candidate.openalex_id}"
    return f"title:{normalize_title_key(candidate.title)}"


def parse_year(value: object) -> int | None:
    if value is None:
        return None
    match = re.search(r"(19|20)\d{2}", str(value))
    return int(match.group(0)) if match else None


def normalize_doi(value: str | None) -> str:
    doi = (value or "").strip().casefold()
    for prefix in (
        "https://doi.org/",
        "http://doi.org/",
        "https://dx.doi.org/",
        "http://dx.doi.org/",
    ):
        if doi.startswith(prefix):
            doi = doi.removeprefix(prefix)
            break
    return doi.strip().rstrip(".,;)")


def normalize_arxiv_id(value: str | None) -> str:
    arxiv_id = (value or "").strip().casefold()
    if arxiv_id.startswith("arxiv:"):
        arxiv_id = arxiv_id.removeprefix("arxiv:").strip()
    return re.sub(r"v\d+\Z", "", arxiv_id)


def query_tokens(query: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", query.casefold())
        if len(token) > 1
    }


def has_token_overlap(query: str, *values: object) -> bool:
    tokens = query_tokens(query)
    if not tokens:
        return True
    text = " ".join(_flatten_text(value) for value in values).casefold()
    haystack = set(re.findall(r"[a-z0-9]+", text))
    return bool(tokens & haystack)


def first_doi(text: str) -> str | None:
    match = DOI_RE.search(text)
    if match is None:
        return None
    return match.group(1).rstrip(".,;)")


def first_arxiv_id(text: str) -> str | None:
    match = ARXIV_RE.search(text)
    if match is None:
        return None
    return match.group(1)


def coerce_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, Iterable):
        return [str(item) for item in value if str(item)]
    return [str(value)]


def compact_raw(raw: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in raw.items() if value not in (None, "", [], {})}


def _flatten_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        return " ".join(_flatten_text(item) for item in value.values())
    if isinstance(value, str):
        return value
    if isinstance(value, Iterable):
        return " ".join(_flatten_text(item) for item in value)
    return str(value)


@dataclass
class SourceSearchResult:
    source: LiteratureSource
    candidates: list[LiteratureCandidate] = field(default_factory=list)
    errors: list[LiteratureSourceError] = field(default_factory=list)
    unavailable_reason: str | None = None


class LiteratureSourceAdapter(Protocol):
    source: LiteratureSource

    async def search(self, query: str, limit: int = 50) -> SourceSearchResult:
        ...

    async def close(self) -> None:
        ...
