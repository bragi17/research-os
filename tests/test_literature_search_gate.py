from __future__ import annotations

import pytest

from libs.schemas.literature import (
    LiteratureCandidate,
    LiteratureErrorKind,
    LiteratureGateStatus,
    LiteratureSource,
    LiteratureSourceError,
)
from services.literature_search import LiteratureSearchCoordinator
from services.literature_sources.base import SourceSearchResult


class StubSource:
    def __init__(self, result: SourceSearchResult) -> None:
        self.source = result.source
        self.result = result

    async def search(self, query: str, limit: int = 50) -> SourceSearchResult:
        return self.result

    async def close(self) -> None:
        return None


class RaisingSource:
    source = LiteratureSource.SEMANTIC_SCHOLAR

    async def search(self, query: str, limit: int = 50) -> SourceSearchResult:
        raise RuntimeError("boom with secret-token-that-should-not-leak")


class CloseTrackingSource:
    source = LiteratureSource.LOCAL_LIBRARY

    def __init__(self) -> None:
        self.closed = False

    async def search(self, query: str, limit: int = 50) -> SourceSearchResult:
        return SourceSearchResult(source=self.source)

    async def close(self) -> None:
        self.closed = True


def _candidate(
    candidate_id: str,
    *,
    source: LiteratureSource = LiteratureSource.LOCAL_LIBRARY,
    doi: str | None = None,
    arxiv_id: str | None = None,
) -> LiteratureCandidate:
    return LiteratureCandidate(
        candidate_id=candidate_id,
        title=f"Paper {candidate_id}",
        source=source,
        doi=doi,
        arxiv_id=arxiv_id,
    )


@pytest.mark.asyncio
async def test_gate_blocks_when_enabled_sources_fail_without_candidates() -> None:
    coordinator = LiteratureSearchCoordinator(
        sources=[
            StubSource(
                SourceSearchResult(
                    source=LiteratureSource.SEMANTIC_SCHOLAR,
                    errors=[
                        LiteratureSourceError(
                            source=LiteratureSource.SEMANTIC_SCHOLAR,
                            kind=LiteratureErrorKind.CREDENTIAL_ERROR,
                            message="forbidden",
                        )
                    ],
                )
            )
        ]
    )

    candidates, report = await coordinator.search("topic", [{"query": "topic"}])

    assert candidates == []
    assert report.gate_status == LiteratureGateStatus.BLOCKED
    assert report.contribution_counts == {"semantic_scholar": 0}


@pytest.mark.asyncio
async def test_gate_warns_when_one_source_contributes_and_another_fails() -> None:
    coordinator = LiteratureSearchCoordinator(
        sources=[
            StubSource(
                SourceSearchResult(
                    source=LiteratureSource.LOCAL_LIBRARY,
                    candidates=[
                        LiteratureCandidate(
                            candidate_id="LOCAL:1",
                            title="Local Paper",
                            source=LiteratureSource.LOCAL_LIBRARY,
                        )
                    ],
                )
            ),
            StubSource(
                SourceSearchResult(
                    source=LiteratureSource.OPENALEX,
                    errors=[
                        LiteratureSourceError(
                            source=LiteratureSource.OPENALEX,
                            kind=LiteratureErrorKind.RATE_LIMITED,
                            message="429",
                        )
                    ],
                )
            ),
        ]
    )

    candidates, report = await coordinator.search("topic", [{"query": "topic"}])

    assert [candidate.candidate_id for candidate in candidates] == ["LOCAL:1"]
    assert report.gate_status == LiteratureGateStatus.WARN
    assert report.contributing_sources == [LiteratureSource.LOCAL_LIBRARY]


@pytest.mark.asyncio
async def test_gate_warns_and_keeps_candidates_when_source_raises() -> None:
    coordinator = LiteratureSearchCoordinator(
        sources=[
            RaisingSource(),
            StubSource(
                SourceSearchResult(
                    source=LiteratureSource.LOCAL_LIBRARY,
                    candidates=[_candidate("LOCAL:1")],
                )
            ),
        ]
    )

    candidates, report = await coordinator.search("topic", [{"query": "topic"}])

    assert [candidate.candidate_id for candidate in candidates] == ["LOCAL:1"]
    assert report.gate_status == LiteratureGateStatus.WARN
    assert len(report.source_errors) == 1
    assert report.source_errors[0].source == LiteratureSource.SEMANTIC_SCHOLAR
    assert report.source_errors[0].kind == LiteratureErrorKind.UNAVAILABLE
    assert report.source_errors[0].query == "topic"
    assert "secret-token" not in report.source_errors[0].message


@pytest.mark.asyncio
async def test_gate_warns_when_candidates_exist_with_unavailable_source() -> None:
    coordinator = LiteratureSearchCoordinator(
        sources=[
            StubSource(
                SourceSearchResult(
                    source=LiteratureSource.LOCAL_LIBRARY,
                    candidates=[_candidate("LOCAL:1")],
                )
            ),
            StubSource(
                SourceSearchResult(
                    source=LiteratureSource.ZOTERO,
                    unavailable_reason="Zotero export path is not configured",
                )
            ),
        ]
    )

    candidates, report = await coordinator.search("topic", [{"query": "topic"}])

    assert [candidate.candidate_id for candidate in candidates] == ["LOCAL:1"]
    assert report.gate_status == LiteratureGateStatus.WARN
    assert report.unavailable_sources == {
        "zotero": "Zotero export path is not configured"
    }


@pytest.mark.asyncio
async def test_coordinator_dedupes_doi_variants_across_sources() -> None:
    coordinator = LiteratureSearchCoordinator(
        sources=[
            StubSource(
                SourceSearchResult(
                    source=LiteratureSource.SEMANTIC_SCHOLAR,
                    candidates=[
                        _candidate(
                            "S2:1",
                            source=LiteratureSource.SEMANTIC_SCHOLAR,
                            doi=" https://doi.org/10.1000/ABC. ",
                        )
                    ],
                )
            ),
            StubSource(
                SourceSearchResult(
                    source=LiteratureSource.OPENALEX,
                    candidates=[
                        _candidate(
                            "OPENALEX:1",
                            source=LiteratureSource.OPENALEX,
                            doi="http://dx.doi.org/10.1000/abc",
                        )
                    ],
                )
            ),
            StubSource(
                SourceSearchResult(
                    source=LiteratureSource.ZOTERO,
                    candidates=[
                        _candidate(
                            "ZOTERO:1",
                            source=LiteratureSource.ZOTERO,
                            doi="10.1000/abc;",
                        )
                    ],
                )
            ),
        ]
    )

    candidates, report = await coordinator.search("topic", [{"query": "topic"}])

    assert [candidate.candidate_id for candidate in candidates] == ["S2:1"]
    assert report.contribution_counts == {
        "semantic_scholar": 1,
        "openalex": 0,
        "zotero": 0,
    }


@pytest.mark.asyncio
async def test_coordinator_dedupes_arxiv_version_variants() -> None:
    coordinator = LiteratureSearchCoordinator(
        sources=[
            StubSource(
                SourceSearchResult(
                    source=LiteratureSource.OBSIDIAN,
                    candidates=[
                        _candidate(
                            "OBSIDIAN:1",
                            source=LiteratureSource.OBSIDIAN,
                            arxiv_id="arXiv:2401.12345v2",
                        )
                    ],
                )
            ),
            StubSource(
                SourceSearchResult(
                    source=LiteratureSource.DEEPXIV,
                    candidates=[
                        _candidate(
                            "DEEPXIV:1",
                            source=LiteratureSource.DEEPXIV,
                            arxiv_id="2401.12345",
                        )
                    ],
                )
            ),
        ]
    )

    candidates, report = await coordinator.search("topic", [{"query": "topic"}])

    assert [candidate.candidate_id for candidate in candidates] == ["OBSIDIAN:1"]
    assert report.contribution_counts == {"obsidian": 1, "deepxiv": 0}


@pytest.mark.asyncio
async def test_coordinator_close_closes_sources() -> None:
    source = CloseTrackingSource()
    coordinator = LiteratureSearchCoordinator(sources=[source])

    async with coordinator as active:
        assert active is coordinator

    assert source.closed is True
