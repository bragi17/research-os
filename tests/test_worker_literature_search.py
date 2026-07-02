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
                candidate_id="LOCAL:arxiv-paper",
                title="Local arXiv Paper",
                source=LiteratureSource.LOCAL_LIBRARY,
                arxiv_id="2505.24431",
            ),
            LiteratureCandidate(
                candidate_id="",
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

    assert new_candidates == [
        "s2-paper-id",
        "OA:W123",
        "10.1234/example",
        "arxiv:2505.24431",
        "title:local paper without external id",
    ]
    assert title_map == {
        "s2-paper-id": "S2 Paper",
        "OA:W123": "OpenAlex Paper",
        "10.1234/example": "DOI Paper",
        "arxiv:2505.24431": "Local arXiv Paper",
        "title:local paper without external id": "Local Paper Without External ID",
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
async def test_search_academic_sources_report_return_keeps_title_only_candidates(monkeypatch):
    coordinator = FakeCoordinator(
        candidates=[
            LiteratureCandidate(
                candidate_id="",
                title="Title Only Local Paper",
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

    assert new_candidates == ["title:title only local paper"]
    assert title_map == {"title:title only local paper": "Title Only Local Paper"}
    assert report is not None
    assert coordinator.closed is True


@pytest.mark.asyncio
async def test_tool_resolve_metadata_handles_arxiv_and_title_ids(monkeypatch):
    calls: list[dict[str, str]] = []

    class FakeFusion:
        def __init__(self, **_kwargs):
            pass

        async def resolve_paper(self, **kwargs):
            calls.append(kwargs)
            return object()

        async def close(self):
            pass

    monkeypatch.setattr(base, "ScholarFusionService", FakeFusion)

    await base.tool_resolve_metadata("arxiv:2505.24431")
    await base.tool_resolve_metadata("title:structured light paper")

    assert calls == [
        {"s2_id": "ARXIV:2505.24431"},
        {"title": "structured light paper"},
    ]


@pytest.mark.asyncio
async def test_tool_resolve_metadata_falls_back_to_arxiv_parser(monkeypatch):
    class FakeFusion:
        def __init__(self, **_kwargs):
            pass

        async def resolve_paper(self, **_kwargs):
            return None

        async def close(self):
            pass

    class FakeParsedPaper:
        title = "Parsed arXiv Paper"
        abstract = "Parsed abstract"
        parse_quality = "medium"
        sections = []

    async def fake_parse_paper(identifier: str):
        assert identifier == "2505.24431"
        return FakeParsedPaper()

    monkeypatch.setattr(base, "ScholarFusionService", FakeFusion)
    monkeypatch.setattr(base, "parse_paper", fake_parse_paper)

    fused, errors = await base.tool_resolve_metadata("arxiv:2505.24431")

    assert errors == []
    assert fused is not None
    assert fused.canonical_title == "Parsed arXiv Paper"
    assert fused.normalized_title == "parsed arxiv paper"
    assert fused.abstract == "Parsed abstract"
    assert fused.arxiv_id == "2505.24431"
    assert fused.sources == ["arxiv"]


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
