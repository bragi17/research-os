from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import apps.api.routes_settings as routes_settings
from services.llm_settings import (
    DEFAULT_DEEPSEEK_BASE_URL,
    DEFAULT_DEEPSEEK_MODEL,
    DEFAULT_WORKSPACE_ID,
    LLMProfile,
)
from services.workspace_context import current_workspace_id


WORKSPACE_A = UUID("11111111-1111-1111-1111-111111111111")
USER_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


def _user(workspace_id: UUID = WORKSPACE_A) -> dict[str, Any]:
    return {
        "id": USER_A,
        "email": "user-a@example.test",
        "username": "user-a",
        "role": "research_user",
        "workspace_id": workspace_id,
    }


def _client(user: dict[str, Any] | None = None) -> TestClient:
    app = FastAPI()
    app.include_router(routes_settings.router)
    dependency = getattr(routes_settings, "get_current_user", None)
    if user is not None and dependency is not None:
        async def fake_get_current_user() -> dict[str, Any]:
            return user

        app.dependency_overrides[dependency] = fake_get_current_user
    return TestClient(app)


def _profile(**overrides: Any) -> LLMProfile:
    data = {
        "id": "profile-1",
        "workspace_id": DEFAULT_WORKSPACE_ID,
        "provider": "deepseek",
        "label": "DeepSeek",
        "base_url": DEFAULT_DEEPSEEK_BASE_URL,
        "model": DEFAULT_DEEPSEEK_MODEL,
        "api_key": None,
        "api_key_preview": "test****-key",
        "is_key_set": True,
        "last_test_status": None,
        "last_test_error": None,
        "last_test_at": None,
    }
    data.update(overrides)
    return LLMProfile(**data)


class FakeRepository:
    def __init__(self, profile: LLMProfile | None) -> None:
        self.profile = profile
        self.get_active_profile = AsyncMock(return_value=profile)
        self.peek_active_profile = AsyncMock(return_value=profile)
        self.upsert_active_profile = AsyncMock(return_value=profile)
        self.clear_api_key = AsyncMock(return_value=profile)
        self.record_test_result = AsyncMock(return_value=profile)


def test_get_models_exposes_deepseek_llm_settings_without_openai_or_secret(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "LEGACY_LLM_API_KEY=test-secret-key",
                "LEGACY_LLM_MODEL=legacy-model",
                "DASHSCOPE_API_KEY=dashscope-secret",
                "DASHSCOPE_EMBEDDING_MODEL=text-embedding-v4",
            ]
        )
        + "\n"
    )
    repo = FakeRepository(
        _profile(
            api_key="plain-secret-value",
            last_test_status="error",
            last_test_error="connection failed",
            last_test_at="2026-06-24T10:00:00Z",
        )
    )
    monkeypatch.setattr(routes_settings, "ENV_PATH", env_path)
    monkeypatch.setattr(
        routes_settings,
        "LLMSettingsRepository",
        lambda *args, **kwargs: repo,
        raising=False,
    )

    response = _client().get("/api/v1/settings/models")

    assert response.status_code == 200
    body = response.json()
    response_text = response.text
    assert "test-secret-key" not in response_text

    llm_category = next(
        category for category in body["categories"] if category["id"] == "llm"
    )
    llm_items = {item["key"]: item for item in llm_category["items"]}
    assert set(llm_items) == {
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_BASE_URL",
        "DEEPSEEK_MODEL",
    }
    assert llm_items["DEEPSEEK_API_KEY"]["value"] == ""
    assert llm_items["DEEPSEEK_API_KEY"]["display_value"] == "test****-key"
    assert llm_items["DEEPSEEK_API_KEY"]["is_sensitive"] is True
    assert llm_items["DEEPSEEK_API_KEY"]["is_set"] is True
    assert llm_items["DEEPSEEK_BASE_URL"]["value"] == DEFAULT_DEEPSEEK_BASE_URL
    assert llm_items["DEEPSEEK_MODEL"]["value"] == DEFAULT_DEEPSEEK_MODEL
    assert llm_category["profile"] == {
        "provider": "deepseek",
        "label": "DeepSeek",
        "base_url": DEFAULT_DEEPSEEK_BASE_URL,
        "model": DEFAULT_DEEPSEEK_MODEL,
        "api_key_preview": "test****-key",
        "is_key_set": True,
        "last_test_status": "error",
        "last_test_error": "connection failed",
        "last_test_at": "2026-06-24T10:00:00Z",
    }
    assert "api_key" not in llm_category["profile"]
    assert "plain-secret-value" not in response_text
    assert "LEGACY_LLM_API_KEY" not in response_text
    assert "LEGACY_LLM_MODEL" not in response_text


def test_get_models_constructs_repository_for_authenticated_workspace(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("")
    workspace_ids: list[UUID | str | None] = []

    class CapturingRepository:
        def __init__(self, workspace_id: UUID | str | None = None) -> None:
            workspace_ids.append(workspace_id)
            self.get_active_profile = AsyncMock(
                return_value=_profile(workspace_id=str(workspace_id))
            )

    monkeypatch.setattr(routes_settings, "ENV_PATH", env_path)
    monkeypatch.setattr(
        routes_settings,
        "LLMSettingsRepository",
        CapturingRepository,
        raising=False,
    )

    response = _client(user=_user()).get("/api/v1/settings/models")

    assert response.status_code == 200
    assert workspace_ids == [WORKSPACE_A]


def test_get_models_falls_back_when_llm_settings_store_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("DASHSCOPE_EMBEDDING_MODEL=text-embedding-v4\n")
    repo = FakeRepository(None)
    repo.get_active_profile.side_effect = RuntimeError("settings table missing")
    monkeypatch.setattr(routes_settings, "ENV_PATH", env_path)
    monkeypatch.setattr(
        routes_settings,
        "LLMSettingsRepository",
        lambda *args, **kwargs: repo,
        raising=False,
    )

    response = _client().get("/api/v1/settings/models")

    assert response.status_code == 200
    body = response.json()
    llm_category = next(
        category for category in body["categories"] if category["id"] == "llm"
    )
    assert llm_category["profile"]["base_url"] == DEFAULT_DEEPSEEK_BASE_URL
    assert llm_category["profile"]["model"] == DEFAULT_DEEPSEEK_MODEL
    assert llm_category["profile"]["is_key_set"] is False
    assert llm_category["profile"]["last_test_status"] == "error"
    assert "settings table missing" in llm_category["profile"]["last_test_error"]

    storage = next(
        category for category in body["categories"] if category["id"] == "storage"
    )
    storage_items = {item["key"]: item for item in storage["items"]}
    assert storage_items["RESEARCH_OS_WORKSPACE_ROOT"]["value"] == (
        "/data/research-os/experiments"
    )
    assert storage_items["RESEARCH_OS_WORKSPACE_ROOT"]["is_set"] is True


def test_get_models_fallback_does_not_expose_env_key_for_authenticated_workspace(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("DEEPSEEK_API_KEY=operator-global-secret\n")
    repo = FakeRepository(None)
    repo.get_active_profile.side_effect = RuntimeError("settings table missing")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "operator-global-secret")
    monkeypatch.setattr(routes_settings, "ENV_PATH", env_path)
    monkeypatch.setattr(
        routes_settings,
        "LLMSettingsRepository",
        lambda *args, **kwargs: repo,
        raising=False,
    )

    response = _client(user=_user()).get("/api/v1/settings/models")

    assert response.status_code == 200
    llm_category = next(
        category for category in response.json()["categories"] if category["id"] == "llm"
    )
    llm_items = {item["key"]: item for item in llm_category["items"]}
    assert llm_category["profile"]["api_key_preview"] == ""
    assert llm_category["profile"]["is_key_set"] is False
    assert llm_items["DEEPSEEK_API_KEY"]["display_value"] == ""
    assert llm_items["DEEPSEEK_API_KEY"]["is_set"] is False
    assert "operator-global-secret" not in response.text


def test_put_llm_updates_repository_resets_runtime_and_masks_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = FakeRepository(_profile(label="Primary DeepSeek"))
    invalidate = Mock()
    reset_gateway = AsyncMock()
    monkeypatch.setattr(
        routes_settings,
        "LLMSettingsRepository",
        lambda *args, **kwargs: repo,
        raising=False,
    )
    monkeypatch.setattr(
        routes_settings,
        "invalidate_llm_config",
        invalidate,
        raising=False,
    )
    monkeypatch.setattr("apps.worker.llm_gateway.reset_gateway_async", reset_gateway)

    response = _client().put(
        "/api/v1/settings/llm",
        json={
            "label": "Primary DeepSeek",
            "base_url": DEFAULT_DEEPSEEK_BASE_URL,
            "model": DEFAULT_DEEPSEEK_MODEL,
            "api_key": "test-secret-key",
        },
    )

    assert response.status_code == 200
    repo.upsert_active_profile.assert_awaited_once_with(
        label="Primary DeepSeek",
        base_url=DEFAULT_DEEPSEEK_BASE_URL,
        model=DEFAULT_DEEPSEEK_MODEL,
        api_key="test-secret-key",
        clear_api_key=False,
    )
    invalidate.assert_called_once_with()
    reset_gateway.assert_awaited_once_with()
    body = response.json()
    assert body["label"] == "Primary DeepSeek"
    assert body["api_key_preview"] == "test****-key"
    assert body["is_key_set"] is True
    assert "api_key" not in body
    assert "test-secret-key" not in response.text


def test_put_llm_awaits_async_gateway_reset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = FakeRepository(_profile(label="Primary DeepSeek"))
    reset_gateway_async = AsyncMock()
    monkeypatch.setattr(
        routes_settings,
        "LLMSettingsRepository",
        lambda *args, **kwargs: repo,
        raising=False,
    )
    monkeypatch.setattr(
        "apps.worker.llm_gateway.reset_gateway_async",
        reset_gateway_async,
    )

    response = _client().put(
        "/api/v1/settings/llm",
        json={
            "label": "Primary DeepSeek",
            "base_url": DEFAULT_DEEPSEEK_BASE_URL,
            "model": DEFAULT_DEEPSEEK_MODEL,
            "api_key": "test-secret-key",
        },
    )

    assert response.status_code == 200
    reset_gateway_async.assert_awaited_once_with()


def test_put_llm_logs_async_gateway_reset_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = FakeRepository(_profile(label="Primary DeepSeek"))
    reset_gateway_async = AsyncMock(
        side_effect=RuntimeError("reset failed with api_key=test-secret-key")
    )
    log_warning = Mock()
    monkeypatch.setattr(
        routes_settings,
        "LLMSettingsRepository",
        lambda *args, **kwargs: repo,
        raising=False,
    )
    monkeypatch.setattr(
        "apps.worker.llm_gateway.reset_gateway_async",
        reset_gateway_async,
    )
    monkeypatch.setattr(routes_settings.logger, "warning", log_warning)

    response = _client().put(
        "/api/v1/settings/llm",
        json={
            "label": "Primary DeepSeek",
            "base_url": DEFAULT_DEEPSEEK_BASE_URL,
            "model": DEFAULT_DEEPSEEK_MODEL,
            "api_key": "test-secret-key",
        },
    )

    assert response.status_code == 200
    reset_gateway_async.assert_awaited_once_with()
    log_warning.assert_called_once()
    assert log_warning.call_args.args[0] == "settings.llm_runtime_reset_failed"
    assert "test-secret-key" not in log_warning.call_args.kwargs["error"]
    assert "[redacted]" in log_warning.call_args.kwargs["error"]


def test_put_llm_missing_credential_encryption_key_returns_configuration_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = FakeRepository(_profile())
    repo.upsert_active_profile.side_effect = RuntimeError(
        "CREDENTIAL_ENCRYPTION_KEY is required to store DeepSeek API keys"
    )
    monkeypatch.setattr(
        routes_settings,
        "LLMSettingsRepository",
        lambda *args, **kwargs: repo,
        raising=False,
    )

    response = _client().put(
        "/api/v1/settings/llm",
        json={
            "label": "OpenAI-compatible",
            "base_url": "https://example.test/v1",
            "model": "cpu-research-model",
            "api_key": "test-secret-key",
        },
    )

    assert response.status_code == 400
    assert "CREDENTIAL_ENCRYPTION_KEY" in response.json()["detail"]
    assert "test-secret-key" not in response.text


def test_delete_llm_api_key_clears_repository_key_and_resets_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = FakeRepository(_profile(api_key_preview="", is_key_set=False))
    invalidate = Mock()
    reset_gateway = AsyncMock()
    monkeypatch.setattr(
        routes_settings,
        "LLMSettingsRepository",
        lambda *args, **kwargs: repo,
        raising=False,
    )
    monkeypatch.setattr(
        routes_settings,
        "invalidate_llm_config",
        invalidate,
        raising=False,
    )
    monkeypatch.setattr("apps.worker.llm_gateway.reset_gateway_async", reset_gateway)

    response = _client().delete("/api/v1/settings/llm/api-key")

    assert response.status_code == 200
    repo.clear_api_key.assert_awaited_once_with()
    invalidate.assert_called_once_with()
    reset_gateway.assert_awaited_once_with()
    body = response.json()
    assert body["api_key_preview"] == ""
    assert body["is_key_set"] is False
    assert "api_key" not in body


def test_legacy_test_llm_delegates_to_gateway_and_records_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = Mock()
    gateway.chat = AsyncMock(
        return_value={"model": DEFAULT_DEEPSEEK_MODEL, "content": "OK"}
    )
    repo = FakeRepository(
        _profile(last_test_status="ok", last_test_error=None, last_test_at="now")
    )
    monkeypatch.setattr(
        routes_settings,
        "LLMSettingsRepository",
        lambda *args, **kwargs: repo,
        raising=False,
    )
    monkeypatch.setattr("apps.worker.llm_gateway.get_gateway", lambda: gateway)

    response = _client().post("/api/v1/settings/models/test-llm")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["model"] == DEFAULT_DEEPSEEK_MODEL
    assert body["response"] == "OK"
    gateway.chat.assert_awaited_once_with(
        messages=[{"role": "user", "content": "Reply with just: OK"}],
        max_tokens=5,
        temperature=0,
    )
    repo.record_test_result.assert_awaited_once_with("ok", None)


def test_llm_test_runs_gateway_call_inside_authenticated_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen_workspace_ids: list[UUID] = []

    async def fake_chat(*args: Any, **kwargs: Any) -> dict[str, str]:
        seen_workspace_ids.append(current_workspace_id())
        return {"model": DEFAULT_DEEPSEEK_MODEL, "content": "OK"}

    gateway = Mock()
    gateway.chat = AsyncMock(side_effect=fake_chat)
    repo = FakeRepository(
        _profile(
            workspace_id=str(WORKSPACE_A),
            api_key="test-secret-key",
        )
    )
    monkeypatch.setattr(
        routes_settings,
        "LLMSettingsRepository",
        lambda *args, **kwargs: repo,
        raising=False,
    )
    monkeypatch.setattr("apps.worker.llm_gateway.get_gateway", lambda: gateway)

    response = _client(user=_user()).post("/api/v1/settings/llm/test")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert seen_workspace_ids == [WORKSPACE_A]
    repo.record_test_result.assert_awaited_once_with("ok", None)


def test_llm_test_redacts_provider_error_before_response_and_persist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api_key = "test-secret-key-1234567890"
    provider_key = "sk-" + ("x" * 24)
    gateway = Mock()
    gateway.chat = AsyncMock(
        side_effect=RuntimeError(
            f"provider failed Authorization: Bearer {api_key}; token {provider_key}"
        )
    )
    repo = FakeRepository(_profile())
    monkeypatch.setattr(
        routes_settings,
        "LLMSettingsRepository",
        lambda *args, **kwargs: repo,
        raising=False,
    )
    monkeypatch.setattr("apps.worker.llm_gateway.get_gateway", lambda: gateway)

    response = _client().post("/api/v1/settings/llm/test")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "error"
    assert "[redacted]" in body["error"]
    assert api_key not in response.text
    assert provider_key not in response.text
    repo.record_test_result.assert_awaited_once()
    status, error = repo.record_test_result.await_args.args
    assert status == "error"
    assert api_key not in error
    assert provider_key not in error
    assert "[redacted]" in error


def test_llm_test_redacts_unstructured_saved_api_key_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api_key = "custom-deepseek-secret-value"
    gateway = Mock()
    gateway.chat = AsyncMock(
        side_effect=RuntimeError(
            f"provider rejected credential {api_key} for account"
        )
    )
    repo = FakeRepository(_profile(api_key=api_key))
    monkeypatch.setattr(
        routes_settings,
        "LLMSettingsRepository",
        lambda *args, **kwargs: repo,
        raising=False,
    )
    monkeypatch.setattr("apps.worker.llm_gateway.get_gateway", lambda: gateway)

    response = _client().post("/api/v1/settings/llm/test")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "error"
    assert api_key not in response.text
    assert "[redacted]" in body["error"]
    repo.record_test_result.assert_awaited_once()
    _, error = repo.record_test_result.await_args.args
    assert api_key not in error
    assert "[redacted]" in error


@pytest.mark.parametrize(
    "profile",
    [
        None,
        _profile(api_key_preview="", is_key_set=False),
    ],
)
def test_llm_test_requires_saved_active_profile_with_key_without_persisting(
    monkeypatch: pytest.MonkeyPatch,
    profile: LLMProfile | None,
) -> None:
    gateway = Mock()
    gateway.chat = AsyncMock(
        return_value={"model": DEFAULT_DEEPSEEK_MODEL, "content": "OK"}
    )
    repo = FakeRepository(profile)
    monkeypatch.setattr(
        routes_settings,
        "LLMSettingsRepository",
        lambda *args, **kwargs: repo,
        raising=False,
    )
    monkeypatch.setattr("apps.worker.llm_gateway.get_gateway", lambda: gateway)

    response = _client().post("/api/v1/settings/llm/test")

    assert response.status_code == 200
    assert response.json() == {
        "status": "error",
        "error": "DeepSeek API key is not configured",
    }
    gateway.chat.assert_not_called()
    repo.peek_active_profile.assert_awaited_once_with(include_secret=True)
    repo.get_active_profile.assert_not_called()
    repo.upsert_active_profile.assert_not_called()
    repo.record_test_result.assert_not_called()
