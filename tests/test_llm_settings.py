"""Tests for encrypted DeepSeek LLM settings."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from services.llm_settings import (
    DEFAULT_DEEPSEEK_BASE_URL,
    DEFAULT_DEEPSEEK_MODEL,
    DEFAULT_WORKSPACE_ID,
    LLMProfile,
    LLMSettingsRepository,
    decrypt_api_key,
    encrypt_api_key,
    get_active_llm_profile,
    invalidate_llm_config,
    mask_api_key,
)


class FakePool:
    def __init__(self, handler: Callable[[str, tuple[Any, ...]], dict[str, Any] | None]):
        self.handler = handler
        self.fetchrow_calls: list[tuple[str, tuple[Any, ...]]] = []
        self.execute_calls: list[tuple[str, tuple[Any, ...]]] = []

    async def fetchrow(self, sql: str, *args: Any) -> dict[str, Any] | None:
        self.fetchrow_calls.append((sql, args))
        return self.handler(sql, args)

    async def execute(self, sql: str, *args: Any) -> str:
        self.execute_calls.append((sql, args))
        return "UPDATE 1"


def _row(**overrides: Any) -> dict[str, Any]:
    row = {
        "id": "profile-1",
        "workspace_id": DEFAULT_WORKSPACE_ID,
        "provider": "deepseek",
        "label": "DeepSeek",
        "base_url": DEFAULT_DEEPSEEK_BASE_URL,
        "model": DEFAULT_DEEPSEEK_MODEL,
        "api_key_encrypted": None,
        "api_key_preview": "",
        "last_test_status": None,
        "last_test_error": None,
        "last_test_at": None,
    }
    row.update(overrides)
    return row


@pytest.mark.parametrize(
    ("api_key", "expected"),
    [
        ("test-secret-key-123456", "test****3456"),
        ("", ""),
    ],
)
def test_mask_api_key(api_key: str, expected: str) -> None:
    assert mask_api_key(api_key) == expected


def test_encrypt_decrypt_api_key_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", "unit-test-encryption-secret")

    encrypted = encrypt_api_key("test-secret-key")

    assert "test-secret-key" not in encrypted
    assert decrypt_api_key(encrypted) == "test-secret-key"


def test_encrypt_api_key_requires_credential_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CREDENTIAL_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("JWT_SECRET", raising=False)

    with pytest.raises(
        RuntimeError,
        match="CREDENTIAL_ENCRYPTION_KEY is required to store DeepSeek API keys",
    ):
        encrypt_api_key("test-secret-key")


@pytest.mark.asyncio
async def test_bootstrap_creates_deepseek_profile_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", "unit-test-encryption-secret")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-secret-key")
    inserts: list[tuple[Any, ...]] = []
    stored_row: dict[str, Any] | None = None

    def handler(sql: str, args: tuple[Any, ...]) -> dict[str, Any] | None:
        nonlocal stored_row
        if sql.lstrip().upper().startswith("SELECT"):
            return stored_row
        inserts.append(args)
        encrypted = args[5]
        assert encrypted != "test-secret-key"
        assert "test-secret-key" not in encrypted
        stored_row = _row(api_key_encrypted=encrypted, api_key_preview=args[6])
        return stored_row

    pool = FakePool(handler)
    repo = LLMSettingsRepository(pool_getter=lambda: pool)

    hidden = await repo.bootstrap_from_env(include_secret=False)
    secret = await repo.get_active_profile(include_secret=True)

    assert hidden.provider == "deepseek"
    assert hidden.base_url == "https://api.deepseek.com"
    assert hidden.model == "deepseek-v4-pro"
    assert hidden.api_key is None
    assert hidden.api_key_preview == "test****-key"
    assert hidden.is_key_set is True
    assert secret.api_key == "test-secret-key"
    assert len(inserts) == 1


@pytest.mark.asyncio
async def test_upsert_preserves_existing_encrypted_key_when_api_key_omitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", "unit-test-encryption-secret")
    existing_encrypted = encrypt_api_key("test-secret-key")
    updates: list[tuple[Any, ...]] = []

    def handler(sql: str, args: tuple[Any, ...]) -> dict[str, Any] | None:
        if sql.lstrip().upper().startswith("SELECT"):
            return _row(
                api_key_encrypted=existing_encrypted,
                api_key_preview="test****-key",
            )
        updates.append(args)
        assert args[5] == existing_encrypted
        assert args[6] == "test****-key"
        return _row(
            label=args[2],
            base_url=args[3],
            model=args[4],
            api_key_encrypted=args[5],
            api_key_preview=args[6],
        )

    pool = FakePool(handler)
    repo = LLMSettingsRepository(pool_getter=lambda: pool)

    profile = await repo.upsert_active_profile(
        label="Primary DeepSeek",
        base_url="https://api.deepseek.com",
        model="deepseek-v4-pro",
    )

    assert profile.label == "Primary DeepSeek"
    assert profile.is_key_set is True
    assert profile.api_key is None
    assert updates


@pytest.mark.asyncio
async def test_clear_api_key_removes_secret_and_preview(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", "unit-test-encryption-secret")

    def handler(sql: str, args: tuple[Any, ...]) -> dict[str, Any] | None:
        if sql.lstrip().upper().startswith("SELECT"):
            return _row(api_key_encrypted=encrypt_api_key("test-secret-key"))
        assert args[5] is None
        assert args[6] == ""
        return _row(api_key_encrypted=None, api_key_preview="")

    pool = FakePool(handler)
    repo = LLMSettingsRepository(pool_getter=lambda: pool)

    profile = await repo.clear_api_key()

    assert profile.api_key is None
    assert profile.api_key_preview == ""
    assert profile.is_key_set is False


@pytest.mark.asyncio
async def test_get_active_llm_profile_hides_secret_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[bool] = []

    class FakeRepository:
        async def get_active_profile(
            self,
            include_secret: bool = False,
        ) -> LLMProfile:
            calls.append(include_secret)
            return LLMProfile(
                id="profile-1",
                workspace_id=DEFAULT_WORKSPACE_ID,
                provider="deepseek",
                label="DeepSeek",
                base_url=DEFAULT_DEEPSEEK_BASE_URL,
                model=DEFAULT_DEEPSEEK_MODEL,
                api_key="test-secret-key" if include_secret else None,
                api_key_preview="test****-key",
                is_key_set=True,
                last_test_status=None,
                last_test_error=None,
                last_test_at=None,
            )

    import services.llm_settings as llm_settings

    invalidate_llm_config()
    monkeypatch.setattr(llm_settings, "LLMSettingsRepository", FakeRepository)

    hidden = await get_active_llm_profile()
    secret = await get_active_llm_profile(include_secret=True)

    assert hidden.api_key is None
    assert secret.api_key == "test-secret-key"
    assert calls == [False, True]
    invalidate_llm_config()
