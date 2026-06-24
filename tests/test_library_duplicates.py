"""Tests for deterministic Paper Library duplicate detection."""

from __future__ import annotations

from uuid import uuid4


def _paper(
    title: str,
    *,
    doi: str | None = None,
    arxiv_id: str | None = None,
    authors: list[str] | None = None,
    year: int | None = None,
) -> dict:
    return {
        "id": uuid4(),
        "title": title,
        "doi": doi,
        "arxiv_id": arxiv_id,
        "authors": authors or [],
        "year": year,
    }


def test_duplicate_detection_groups_exact_doi_matches():
    from services.library.duplicates import find_duplicate_candidates

    first = _paper("Paper A", doi="10.1145/123")
    second = _paper("Paper A Extended", doi="https://doi.org/10.1145/123")

    groups = find_duplicate_candidates([first, second])

    assert len(groups) == 1
    assert set(groups[0]["paper_ids"]) == {first["id"], second["id"]}
    assert groups[0]["reason"] == "same DOI"
    assert groups[0]["confidence"] == "high"


def test_duplicate_detection_groups_arxiv_versions():
    from services.library.duplicates import find_duplicate_candidates

    first = _paper("Paper A", arxiv_id="arXiv:2505.24431v1")
    second = _paper("Paper A", arxiv_id="2505.24431v2")

    groups = find_duplicate_candidates([first, second])

    assert len(groups) == 1
    assert groups[0]["reason"] == "same arXiv ID"


def test_duplicate_detection_flags_similar_titles_with_author_overlap():
    from services.library.duplicates import find_duplicate_candidates

    first = _paper(
        "Bridging 3D Anomaly Localization and Repair",
        authors=["Ada Lovelace", "Grace Hopper"],
        year=2025,
    )
    second = _paper(
        "Bridging 3D Anomaly Localisation & Repair",
        authors=["Ada Lovelace"],
        year=2025,
    )

    groups = find_duplicate_candidates([first, second])

    assert len(groups) == 1
    assert groups[0]["reason"] == "similar title"
    assert groups[0]["confidence"] == "medium"


def test_duplicate_detection_ignores_different_titles():
    from services.library.duplicates import find_duplicate_candidates

    groups = find_duplicate_candidates([
        _paper("Attention Is All You Need", year=2017),
        _paper("Deep Residual Learning for Image Recognition", year=2016),
    ])

    assert groups == []
