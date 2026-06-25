from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import apps.api.routes_settings as routes_settings
from libs.schemas.literature import (
    LiteratureCredentialPreview,
    LiteratureSource,
    LiteratureSourceSettings,
)


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(routes_settings.router)
    return TestClient(app)


def _source(source: LiteratureSource, **overrides: Any) -> LiteratureSourceSettings:
    data = {
        "source": source,
        "label": source.value.replace("_", " ").title(),
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


class FakeLLMRepository:
    def __init__(self) -> None:
        self.get_active_profile = AsyncMock(
            side_effect=RuntimeError("missing llm settings")
        )


class FakeLiteratureRepository:
    def __init__(self) -> None:
        self.semantic_scholar = _source(
            LiteratureSource.SEMANTIC_SCHOLAR,
            credentials=[
                LiteratureCredentialPreview(
                    id=uuid4(),
                    label="primary",
                    preview="sema****7890",
                )
            ],
        )
        self.unconfigured = _source(
            LiteratureSource.WEB_SEARCH,
            enabled=True,
            configured=False,
            credentials=[],
        )
        self.sources = [
            _source(LiteratureSource.LOCAL_LIBRARY),
            self.semantic_scholar,
        ]
        self.list_sources = AsyncMock(return_value=self.sources)
        self.get_source = AsyncMock(return_value=self.semantic_scholar)
        self.update_source = AsyncMock(return_value=self.semantic_scholar)
        self.record_source_test = AsyncMock(return_value=self.semantic_scholar)


def test_get_models_includes_literature_sources_from_repository_without_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = FakeLiteratureRepository()
    monkeypatch.setattr(
        routes_settings,
        "LiteratureSettingsRepository",
        lambda: repo,
        raising=False,
    )
    monkeypatch.setattr(
        routes_settings,
        "LLMSettingsRepository",
        lambda: FakeLLMRepository(),
    )

    response = _client().get("/api/v1/settings/models")

    assert response.status_code == 200
    body = response.json()
    category_ids = [category["id"] for category in body["categories"]]
    literature_index = category_ids.index("literature_sources")
    assert category_ids[literature_index - 1] == "academic"
    assert category_ids[literature_index + 1] == "storage"
    category = body["categories"][literature_index]
    assert category["label"] == "Literature Sources"
    assert category["items"] == []
    assert category["sources"] == [
        source.model_dump(mode="json") for source in repo.sources
    ]
    repo.list_sources.assert_awaited_once_with(include_secrets=False)
    assert "plain-secret-value" not in response.text
    assert "semantic-secret-key-1234567890" not in response.text


def test_put_literature_source_updates_repository_and_redacts_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = FakeLiteratureRepository()
    credential_id = uuid4()
    monkeypatch.setattr(
        routes_settings,
        "LiteratureSettingsRepository",
        lambda: repo,
        raising=False,
    )

    response = _client().put(
        "/api/v1/settings/literature/semantic_scholar",
        json={
            "enabled": False,
            "options": {"timeout_seconds": 15},
            "new_credentials": ["semantic-secret-key-1234567890"],
            "clear_credential_ids": [str(credential_id)],
        },
    )

    assert response.status_code == 200
    repo.update_source.assert_awaited_once_with(
        LiteratureSource.SEMANTIC_SCHOLAR,
        enabled=False,
        options={"timeout_seconds": 15},
        new_credentials=["semantic-secret-key-1234567890"],
        clear_credential_ids=[str(credential_id)],
    )
    assert response.json() == repo.semantic_scholar.model_dump(mode="json")
    assert "semantic-secret-key-1234567890" not in response.text


def test_put_literature_source_redacts_secret_from_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = FakeLiteratureRepository()
    repo.update_source.side_effect = RuntimeError(
        "failed to store semantic-secret-key-1234567890"
    )
    monkeypatch.setattr(
        routes_settings,
        "LiteratureSettingsRepository",
        lambda: repo,
        raising=False,
    )

    response = _client().put(
        "/api/v1/settings/literature/semantic_scholar",
        json={"new_credentials": ["semantic-secret-key-1234567890"]},
    )

    assert response.status_code == 500
    assert "[redacted]" in response.json()["detail"]
    assert "semantic-secret-key-1234567890" not in response.text


def test_post_literature_source_test_records_ok_for_configured_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = FakeLiteratureRepository()
    monkeypatch.setattr(
        routes_settings,
        "LiteratureSettingsRepository",
        lambda: repo,
        raising=False,
    )

    response = _client().post("/api/v1/settings/literature/semantic_scholar/test")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "error": None}
    repo.get_source.assert_awaited_once_with(LiteratureSource.SEMANTIC_SCHOLAR)
    repo.record_source_test.assert_awaited_once_with(
        LiteratureSource.SEMANTIC_SCHOLAR,
        "ok",
        None,
    )


def test_post_literature_source_test_records_error_for_unconfigured_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = FakeLiteratureRepository()
    repo.get_source.return_value = repo.unconfigured
    repo.record_source_test.return_value = repo.unconfigured
    monkeypatch.setattr(
        routes_settings,
        "LiteratureSettingsRepository",
        lambda: repo,
        raising=False,
    )

    response = _client().post("/api/v1/settings/literature/web_search/test")

    assert response.status_code == 200
    assert response.json() == {
        "status": "error",
        "error": "web_search is not configured",
    }
    repo.get_source.assert_awaited_once_with(LiteratureSource.WEB_SEARCH)
    repo.record_source_test.assert_awaited_once_with(
        LiteratureSource.WEB_SEARCH,
        "error",
        "web_search is not configured",
    )
