from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, Mock
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
from services.literature_settings import LiteratureCredentialSecret


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
        self.get_active_credentials = AsyncMock(return_value=[])


def _credential_secret(
    source: LiteratureSource = LiteratureSource.SEMANTIC_SCHOLAR,
) -> LiteratureCredentialSecret:
    return LiteratureCredentialSecret(
        id=uuid4(),
        source=source,
        label="primary",
        secret="semantic-secret-key-1234567890",
    )


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


def test_get_models_redacts_literature_source_fallback_error_with_active_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = FakeLiteratureRepository()
    repo.list_sources.side_effect = RuntimeError(
        "settings failed for semantic-secret-key-1234567890"
    )
    repo.get_active_credentials = AsyncMock(
        side_effect=lambda source: [_credential_secret(source)]
        if source == LiteratureSource.SEMANTIC_SCHOLAR
        else []
    )
    logger = Mock()
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
    monkeypatch.setattr(routes_settings, "logger", logger)

    response = _client().get("/api/v1/settings/models")

    assert response.status_code == 200
    category = next(
        item for item in response.json()["categories"]
        if item["id"] == "literature_sources"
    )
    assert category["sources"] == []
    logger.warning.assert_any_call(
        "settings.literature_sources_fallback_failed",
        error="settings failed for [redacted]",
    )
    assert "semantic-secret-key-1234567890" not in response.text
    assert "semantic-secret-key-1234567890" not in repr(logger.method_calls)


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


def test_put_literature_source_value_error_returns_400_and_redacts_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = FakeLiteratureRepository()
    repo.update_source.side_effect = ValueError(
        "local_library does not support stored credentials "
        "semantic-secret-key-1234567890"
    )
    logger = Mock()
    monkeypatch.setattr(
        routes_settings,
        "LiteratureSettingsRepository",
        lambda: repo,
        raising=False,
    )
    monkeypatch.setattr(routes_settings, "logger", logger)

    response = _client().put(
        "/api/v1/settings/literature/local_library",
        json={"new_credentials": ["semantic-secret-key-1234567890"]},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "local_library does not support stored credentials [redacted]"
    )
    assert "semantic-secret-key-1234567890" not in response.text
    assert "semantic-secret-key-1234567890" not in repr(logger.method_calls)


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


def test_post_literature_source_test_redacts_exception_with_active_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = FakeLiteratureRepository()
    repo.get_source.side_effect = RuntimeError(
        "probe failed for semantic-secret-key-1234567890"
    )
    repo.get_active_credentials.return_value = [
        _credential_secret(LiteratureSource.SEMANTIC_SCHOLAR)
    ]
    repo.record_source_test.side_effect = RuntimeError(
        "record failed for semantic-secret-key-1234567890"
    )
    logger = Mock()
    monkeypatch.setattr(
        routes_settings,
        "LiteratureSettingsRepository",
        lambda: repo,
        raising=False,
    )
    monkeypatch.setattr(routes_settings, "logger", logger)

    response = _client().post("/api/v1/settings/literature/semantic_scholar/test")

    assert response.status_code == 200
    assert response.json() == {
        "status": "error",
        "error": "probe failed for [redacted]",
    }
    repo.record_source_test.assert_awaited_once_with(
        LiteratureSource.SEMANTIC_SCHOLAR,
        "error",
        "probe failed for [redacted]",
    )
    logger.warning.assert_called_once_with(
        "settings.literature_test_record_failed",
        source="semantic_scholar",
        error="record failed for [redacted]",
    )
    assert "semantic-secret-key-1234567890" not in response.text
    assert "semantic-secret-key-1234567890" not in repr(logger.method_calls)
