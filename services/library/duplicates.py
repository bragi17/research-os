"""Deterministic duplicate detection for Paper Library pools."""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any


_NON_WORD_RE = re.compile(r"[^a-z0-9]+")
_ARXIV_VERSION_RE = re.compile(r"v\d+$", re.IGNORECASE)


def _normalize_title(title: str) -> str:
    lowered = title.lower().replace("&", " and ")
    return _NON_WORD_RE.sub(" ", lowered).strip()


def _normalize_doi(doi: str | None) -> str:
    if not doi:
        return ""
    value = doi.strip().lower()
    value = value.removeprefix("https://doi.org/")
    value = value.removeprefix("http://doi.org/")
    value = value.removeprefix("doi:")
    return value.strip()


def _normalize_arxiv(arxiv_id: str | None) -> str:
    if not arxiv_id:
        return ""
    value = arxiv_id.strip().lower()
    value = value.removeprefix("arxiv:")
    return _ARXIV_VERSION_RE.sub("", value)


def _author_tokens(authors: Any) -> set[str]:
    if not isinstance(authors, list):
        return set()
    tokens: set[str] = set()
    for author in authors:
        if not isinstance(author, str):
            continue
        parts = [part for part in _NON_WORD_RE.split(author.lower()) if part]
        tokens.update(parts)
    return tokens


def _paper_id(paper: dict[str, Any]) -> Any:
    return paper.get("id") or paper.get("paper_id")


def _add_group(
    groups: list[dict[str, Any]],
    seen: set[frozenset[Any]],
    paper_ids: list[Any],
    *,
    reason: str,
    confidence: str,
    score: float,
) -> None:
    key = frozenset(paper_ids)
    if len(key) < 2 or key in seen:
        return
    seen.add(key)
    groups.append({
        "paper_ids": list(paper_ids),
        "reason": reason,
        "confidence": confidence,
        "score": score,
    })


def _group_by_key(
    papers: list[dict[str, Any]],
    key_fn,
    *,
    reason: str,
    seen: set[frozenset[Any]],
) -> list[dict[str, Any]]:
    buckets: dict[str, list[Any]] = {}
    for paper in papers:
        key = key_fn(paper)
        paper_id = _paper_id(paper)
        if key and paper_id:
            buckets.setdefault(key, []).append(paper_id)

    groups: list[dict[str, Any]] = []
    for ids in buckets.values():
        _add_group(
            groups,
            seen,
            ids,
            reason=reason,
            confidence="high",
            score=1.0 if reason in {"same DOI", "same arXiv ID"} else 0.95,
        )
    return groups


def find_duplicate_candidates(papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return deterministic duplicate candidates for a pool of papers.

    The detector intentionally avoids LLM calls. It flags exact DOI/arXiv
    matches, exact normalized-title matches, and high-similarity title pairs
    when year/author evidence is compatible.
    """
    groups: list[dict[str, Any]] = []
    seen: set[frozenset[Any]] = set()

    groups.extend(_group_by_key(
        papers,
        lambda paper: _normalize_doi(paper.get("doi")),
        reason="same DOI",
        seen=seen,
    ))
    groups.extend(_group_by_key(
        papers,
        lambda paper: _normalize_arxiv(paper.get("arxiv_id")),
        reason="same arXiv ID",
        seen=seen,
    ))
    groups.extend(_group_by_key(
        papers,
        lambda paper: _normalize_title(str(paper.get("title") or "")),
        reason="same title",
        seen=seen,
    ))

    for idx, left in enumerate(papers):
        left_id = _paper_id(left)
        left_title = _normalize_title(str(left.get("title") or ""))
        if not left_id or len(left_title) < 12:
            continue
        for right in papers[idx + 1:]:
            right_id = _paper_id(right)
            right_title = _normalize_title(str(right.get("title") or ""))
            if not right_id or len(right_title) < 12:
                continue

            score = SequenceMatcher(None, left_title, right_title).ratio()
            if score < 0.88:
                continue

            left_year = left.get("year")
            right_year = right.get("year")
            if left_year and right_year and abs(int(left_year) - int(right_year)) > 1:
                continue

            left_authors = _author_tokens(left.get("authors"))
            right_authors = _author_tokens(right.get("authors"))
            if left_authors and right_authors and not (left_authors & right_authors):
                continue

            _add_group(
                groups,
                seen,
                [left_id, right_id],
                reason="similar title",
                confidence="medium",
                score=round(score, 3),
            )

    return sorted(groups, key=lambda item: item["score"], reverse=True)
