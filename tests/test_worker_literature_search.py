from __future__ import annotations

from typing import Any

import pytest

from apps.worker.modes import base
from libs.schemas.literature import (
    LiteratureCandidate,
    LiteratureErrorKind,
    LiteratureGateStatus,
    LiteratureSearchReport,
    LiteratureSource,
    LiteratureSourceError,
)


class FakeCoordinator:
    def __init__(self, candidates: list[LiteratureCandidate] | None = None) -> None:
        self.closed = False
        self.search_args: dict[str, Any] | None = None
        self.candidates = candidates or [
            LiteratureCandidate(
                candidate_id="S2:old",
                title="Existing Paper",
                source=LiteratureSource.SEMANTIC_SCHOLAR,
            ),
            LiteratureCandidate(
                candidate_id="S2:new",
                title="New Paper",
                source=LiteratureSource.SEMANTIC_SCHOLAR,
            ),
        ]

    async def search(
        self,
        topic: str,
        queries: list[dict[str, object]],
        limit_per_query: int = 50,
    ) -> tuple[list[LiteratureCandidate], LiteratureSearchReport]:
        self.search_args = {
            "topic": topic,
            "queries": queries,
            "limit_per_query": limit_per_query,
        }
        query_text = str(queries[0]["query"])
        return (
            self.candidates,
            LiteratureSearchReport(
                requested_sources=[
                    LiteratureSource.SEMANTIC_SCHOLAR,
                    LiteratureSource.OPENALEX,
                ],
                enabled_sources=[
                    LiteratureSource.SEMANTIC_SCHOLAR,
                    LiteratureSource.OPENALEX,
                ],
                contributing_sources=[LiteratureSource.SEMANTIC_SCHOLAR],
                contribution_counts={
                    LiteratureSource.SEMANTIC_SCHOLAR.value: 2,
                    LiteratureSource.OPENALEX.value: 0,
                },
                source_errors=[
                    LiteratureSourceError(
                        source=LiteratureSource.OPENALEX,
                        kind=LiteratureErrorKind.RATE_LIMITED,
                        message="slow down",
                        query=query_text,
                    )
                ],
                unavailable_sources={LiteratureSource.ZOTERO.value: "path missing"},
                candidate_count=2,
                gate_status=LiteratureGateStatus.WARN,
            ),
        )

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_search_academic_sources_uses_literature_coordinator(monkeypatch):
    coordinator = FakeCoordinator()

    async def fake_build_literature_search_coordinator():
        return coordinator

    monkeypatch.setattr(
        base,
        "_build_literature_search_coordinator",
        fake_build_literature_search_coordinator,
    )

    result = await base.search_academic_sources(
        topic="topic",
        queries=[{"query": "query text"}],
        existing_titles={base._normalize_title("Existing Paper")},
        return_report=True,
    )

    new_candidates, executed, errors, title_map, report = result

    assert new_candidates == ["S2:new"]
    assert executed == ["query text"]
    assert errors == [
        "openalex rate_limited for 'query text': slow down",
        "zotero unavailable: path missing",
    ]
    assert title_map == {"S2:new": "New Paper"}
    assert report is not None
    assert report["gate_status"] == LiteratureGateStatus.WARN.value
    assert report["source_errors"][0]["kind"] == LiteratureErrorKind.RATE_LIMITED.value
    assert coordinator.search_args == {
        "topic": "topic",
        "queries": [{"query": "query text"}],
        "limit_per_query": 50,
    }
    assert coordinator.closed is True


@pytest.mark.asyncio
async def test_search_academic_sources_default_return_uses_legacy_ids(monkeypatch):
    coordinator = FakeCoordinator(
        candidates=[
            LiteratureCandidate(
                candidate_id="S2:s2-paper-id",
                title="S2 Paper",
                source=LiteratureSource.SEMANTIC_SCHOLAR,
                s2_id="s2-paper-id",
            ),
            LiteratureCandidate(
                candidate_id="OPENALEX:W123",
                title="OpenAlex Paper",
                source=LiteratureSource.OPENALEX,
                openalex_id="W123",
            ),
            LiteratureCandidate(
                candidate_id="ZOTERO:local",
                title="DOI Paper",
                source=LiteratureSource.ZOTERO,
                doi="https://doi.org/10.1234/example",
            ),
            LiteratureCandidate(
                candidate_id="LOCAL:unresolvable",
                title="Local Paper Without External ID",
                source=LiteratureSource.LOCAL_LIBRARY,
            ),
        ]
    )

    async def fake_build_literature_search_coordinator():
        return coordinator

    monkeypatch.setattr(
        base,
        "_build_literature_search_coordinator",
        fake_build_literature_search_coordinator,
    )

    new_candidates, _executed, _errors, title_map = await base.search_academic_sources(
        topic="topic",
        queries=[{"query": "query text"}],
    )

    assert new_candidates == ["s2-paper-id", "OA:W123", "10.1234/example"]
    assert title_map == {
        "s2-paper-id": "S2 Paper",
        "OA:W123": "OpenAlex Paper",
        "10.1234/example": "DOI Paper",
    }
    assert coordinator.closed is True


@pytest.mark.asyncio
async def test_search_academic_sources_report_return_uses_verifiable_ids(monkeypatch):
    coordinator = FakeCoordinator(
        candidates=[
            LiteratureCandidate(
                candidate_id="ZOTERO:local",
                title="DOI Paper",
                source=LiteratureSource.ZOTERO,
                doi="https://doi.org/10.1234/example",
            ),
            LiteratureCandidate(
                candidate_id="OBSIDIAN:note.md",
                title="Arxiv Paper",
                source=LiteratureSource.OBSIDIAN,
                arxiv_id="2401.12345v2",
            ),
            LiteratureCandidate(
                candidate_id="LOCAL:no-external-id",
                title="Local Paper",
                source=LiteratureSource.LOCAL_LIBRARY,
            ),
        ]
    )

    async def fake_build_literature_search_coordinator():
        return coordinator

    monkeypatch.setattr(
        base,
        "_build_literature_search_coordinator",
        fake_build_literature_search_coordinator,
    )

    new_candidates, _executed, _errors, title_map, report = await base.search_academic_sources(
        topic="topic",
        queries=[{"query": "query text"}],
        return_report=True,
    )

    assert new_candidates == [
        "10.1234/example",
        "arxiv:2401.12345v2",
        "LOCAL:no-external-id",
    ]
    assert title_map == {
        "10.1234/example": "DOI Paper",
        "arxiv:2401.12345v2": "Arxiv Paper",
        "LOCAL:no-external-id": "Local Paper",
    }
    assert report is not None
    assert coordinator.closed is True


@pytest.mark.asyncio
async def test_search_academic_sources_falls_back_when_settings_tables_missing(
    monkeypatch,
):
    class UndefinedTableError(Exception):
        sqlstate = "42P01"

    async def fake_build_literature_search_coordinator():
        raise UndefinedTableError("literature_source_settings does not exist")

    async def fake_legacy_search_academic_sources(**kwargs):
        return ["legacy-id"], ["legacy query"], [], {"legacy-id": "Legacy Paper"}

    monkeypatch.setattr(
        base,
        "_build_literature_search_coordinator",
        fake_build_literature_search_coordinator,
    )
    monkeypatch.setattr(
        base,
        "_legacy_search_academic_sources",
        fake_legacy_search_academic_sources,
    )

    result = await base.search_academic_sources(
        topic="topic",
        queries=[{"query": "legacy query"}],
        return_report=True,
    )

    assert result == (
        ["legacy-id"],
        ["legacy query"],
        [],
        {"legacy-id": "Legacy Paper"},
        None,
    )
