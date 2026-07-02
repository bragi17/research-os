from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from libs.schemas.literature import (
    LiteratureCandidate,
    LiteratureErrorKind,
    LiteratureSource,
    LiteratureSourceError,
    LiteratureSourceSettings,
)
from services.literature_sources.base import SourceSearchResult


def _source(source: LiteratureSource, **overrides: Any) -> LiteratureSourceSettings:
    data = {
        "source": source,
        "label": source.value,
        "enabled": True,
        "configured": True,
        "options": {},
        "credentials": [],
        "last_test_status": None,
        "last_test_error": None,
        "last_test_at": None,
    }
    data.update(overrides)
    return LiteratureSourceSettings(**data)


class FakeLiteratureRepository:
    def __init__(self, settings: LiteratureSourceSettings) -> None:
        self.settings = settings

    async def get_source(self, source: LiteratureSource) -> LiteratureSourceSettings:
        assert source == self.settings.source
        return self.settings

    async def get_active_credentials(self, source: LiteratureSource) -> list[Any]:
        assert source == self.settings.source
        return []


class CredentialRepository(FakeLiteratureRepository):
    def __init__(
        self,
        settings: LiteratureSourceSettings,
        credentials: list[Any],
    ) -> None:
        super().__init__(settings)
        self.credentials = credentials

    async def get_active_credentials(self, source: LiteratureSource) -> list[Any]:
        assert source == self.settings.source
        return self.credentials


class StubAdapter:
    def __init__(self, result: SourceSearchResult) -> None:
        self.result = result
        self.queries: list[tuple[str, int]] = []
        self.closed = False

    async def search(self, query: str, limit: int = 50) -> SourceSearchResult:
        self.queries.append((query, limit))
        return self.result

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_probe_literature_source_returns_ok_when_adapter_yields_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from services import literature_source_probe

    adapter = StubAdapter(
        SourceSearchResult(
            source=LiteratureSource.LOCAL_LIBRARY,
            candidates=[
                LiteratureCandidate(
                    candidate_id="LOCAL:1",
                    title="Prime gap residual envelopes",
                    source=LiteratureSource.LOCAL_LIBRARY,
                )
            ],
        )
    )
    monkeypatch.setattr(
        literature_source_probe,
        "_adapter_for_source",
        lambda *args, **kwargs: adapter,
    )

    result = await literature_source_probe.probe_literature_source(
        LiteratureSource.LOCAL_LIBRARY,
        repo=FakeLiteratureRepository(_source(LiteratureSource.LOCAL_LIBRARY)),
        query="prime gaps",
    )

    assert result == {"status": "ok", "error": None, "candidate_count": 1}
    assert adapter.queries == [("prime gaps", 3)]
    assert adapter.closed is True


@pytest.mark.asyncio
async def test_probe_literature_source_reports_classified_adapter_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from services import literature_source_probe

    adapter = StubAdapter(
        SourceSearchResult(
            source=LiteratureSource.SEMANTIC_SCHOLAR,
            errors=[
                LiteratureSourceError(
                    source=LiteratureSource.SEMANTIC_SCHOLAR,
                    kind=LiteratureErrorKind.CREDENTIAL_ERROR,
                    message="Semantic Scholar credentials were rejected",
                    status_code=403,
                )
            ],
        )
    )
    monkeypatch.setattr(
        literature_source_probe,
        "_adapter_for_source",
        lambda *args, **kwargs: adapter,
    )

    result = await literature_source_probe.probe_literature_source(
        LiteratureSource.SEMANTIC_SCHOLAR,
        repo=FakeLiteratureRepository(_source(LiteratureSource.SEMANTIC_SCHOLAR)),
        query="prime gaps",
    )

    assert result == {
        "status": "error",
        "error": "credential_error: Semantic Scholar credentials were rejected",
        "candidate_count": 0,
    }
    assert adapter.closed is True


@pytest.mark.asyncio
async def test_openalex_probe_adapter_receives_all_credentials() -> None:
    from services.literature_source_probe import _adapter_for_source
    from services.literature_sources.openalex import OpenAlexSource

    adapter = _adapter_for_source(
        _source(LiteratureSource.OPENALEX, options={"email": "owner@example.com"}),
        [
            SimpleNamespace(id="one", secret="openalex-one"),
            SimpleNamespace(id="two", secret="openalex-two"),
        ],
    )

    assert isinstance(adapter, OpenAlexSource)
    assert adapter.source_key_pool is not None
