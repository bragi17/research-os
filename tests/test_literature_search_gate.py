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
