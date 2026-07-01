"""Tests for encrypted DeepSeek LLM settings."""

from __future__ import annotations

import builtins
from collections.abc import Callable
from typing import Any
from uuid import UUID

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
    redact_secret_text,
)
from services.workspace_context import workspace_context


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


def _is_select_active(sql: str) -> bool:
    normalized = " ".join(sql.upper().split())
    return normalized.startswith("SELECT") and "FROM LLM_PROVIDER_CREDENTIALS" in normalized


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
        match="CREDENTIAL_ENCRYPTION_KEY is required to store LLM API keys",
    ):
        encrypt_api_key("test-secret-key")


def test_encrypt_api_key_requires_cryptography(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", "unit-test-encryption-secret")
    original_import = builtins.__import__

    def fake_import(
        name: str,
        globals: dict[str, Any] | None = None,
        locals: dict[str, Any] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> Any:
        if name == "cryptography.fernet":
            raise ImportError("simulated missing cryptography")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(
        RuntimeError,
        match="cryptography is required to store LLM API keys",
    ):
        encrypt_api_key("test-secret-key")


def test_redact_secret_text_removes_keys_from_provider_errors() -> None:
    api_key = "test-secret-key-1234567890"
    provider_key = "sk-" + ("x" * 24)
    message = (
        f"request failed Authorization: Bearer {api_key}; "
        f"api_key={api_key}; provider token {provider_key}"
    )

    redacted = redact_secret_text(message, secrets=[api_key])

    assert api_key not in redacted
    assert provider_key not in redacted
    assert "[redacted]" in redacted


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
async def test_upsert_saves_provider_and_deactivates_other_active_profiles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", "unit-test-encryption-secret")
    updates: list[tuple[Any, ...]] = []

    def handler(sql: str, args: tuple[Any, ...]) -> dict[str, Any] | None:
        if _is_select_active(sql):
            return None
        if sql.lstrip().upper().startswith("UPDATE"):
            updates.append(("deactivate", *args))
            return None
        updates.append(args)
        return _row(
            provider=args[1],
            label=args[2],
            base_url=args[3],
            model=args[4],
            api_key_encrypted=args[5],
            api_key_preview=args[6],
        )

    pool = FakePool(handler)
    repo = LLMSettingsRepository(pool_getter=lambda: pool)

    profile = await repo.upsert_active_profile(
        provider="openai-compatible",
        label="OpenAI-compatible",
        base_url="https://example.test/v1",
        model="research-pro",
    )

    assert profile.provider == "openai-compatible"
    assert profile.label == "OpenAI-compatible"
    assert pool.execute_calls
    assert pool.execute_calls[0][1] == (
        UUID(DEFAULT_WORKSPACE_ID),
        "openai-compatible",
    )
    assert updates[-1][1] == "openai-compatible"


@pytest.mark.asyncio
async def test_get_active_profile_resets_legacy_qwen_deepseek_profile_to_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", "unit-test-encryption-secret")
    existing_encrypted = encrypt_api_key("test-secret-key")
    stored_row = _row(
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model="qwen-max",
        api_key_encrypted=existing_encrypted,
        api_key_preview="test****-key",
    )
    updates: list[tuple[Any, ...]] = []

    def handler(sql: str, args: tuple[Any, ...]) -> dict[str, Any] | None:
        nonlocal stored_row
        if _is_select_active(sql):
            return stored_row
        if sql.lstrip().upper().startswith("UPDATE"):
            updates.append(("deactivate", *args))
            return None
        updates.append(args)
        stored_row = _row(
            provider=args[1],
            label=args[2],
            base_url=args[3],
            model=args[4],
            api_key_encrypted=args[5],
            api_key_preview=args[6],
        )
        return stored_row

    pool = FakePool(handler)
    repo = LLMSettingsRepository(pool_getter=lambda: pool)

    profile = await repo.get_active_profile()

    assert profile.provider == "deepseek"
    assert profile.base_url == DEFAULT_DEEPSEEK_BASE_URL
    assert profile.model == DEFAULT_DEEPSEEK_MODEL
    assert profile.api_key_preview == "test****-key"
    assert updates[-1][3] == DEFAULT_DEEPSEEK_BASE_URL
    assert updates[-1][4] == DEFAULT_DEEPSEEK_MODEL


@pytest.mark.asyncio
async def test_get_active_profile_deactivates_legacy_non_deepseek_qwen_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", "unit-test-encryption-secret")
    stored_row = _row(
        provider="openai",
        label="Qwen",
        base_url="https://yunwu.ai/v1",
        model="qwen-max",
        api_key_encrypted=encrypt_api_key("old-qwen-key"),
        api_key_preview="old****-key",
    )

    class MutatingFakePool(FakePool):
        async def execute(self, sql: str, *args: Any) -> str:
            nonlocal stored_row
            stored_row = None
            return await super().execute(sql, *args)

    def handler(sql: str, args: tuple[Any, ...]) -> dict[str, Any] | None:
        nonlocal stored_row
        if _is_select_active(sql):
            return stored_row
        stored_row = _row(
            provider=args[1],
            label=args[2],
            base_url=args[3],
            model=args[4],
            api_key_encrypted=args[5],
            api_key_preview=args[6],
        )
        return stored_row

    pool = MutatingFakePool(handler)
    repo = LLMSettingsRepository(pool_getter=lambda: pool)

    profile = await repo.get_active_profile()

    assert profile.provider == "deepseek"
    assert profile.base_url == DEFAULT_DEEPSEEK_BASE_URL
    assert profile.model == DEFAULT_DEEPSEEK_MODEL
    assert profile.is_key_set is False
    assert pool.execute_calls


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
async def test_repository_uses_explicit_workspace_id_in_queries() -> None:
    workspace_id = UUID("11111111-1111-1111-1111-111111111111")

    def handler(sql: str, args: tuple[Any, ...]) -> dict[str, Any] | None:
        return _row(workspace_id=args[0])

    pool = FakePool(handler)
    repo = LLMSettingsRepository(pool_getter=lambda: pool, workspace_id=workspace_id)

    profile = await repo.peek_active_profile()

    assert profile is not None
    assert profile.workspace_id == str(workspace_id)
    assert pool.fetchrow_calls[0][1][0] == workspace_id


@pytest.mark.asyncio
async def test_non_default_workspace_without_row_does_not_bootstrap_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id = UUID("33333333-3333-3333-3333-333333333333")
    inserts: list[tuple[Any, ...]] = []
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", "unit-test-encryption-secret")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "operator-global-secret")

    def handler(sql: str, args: tuple[Any, ...]) -> dict[str, Any] | None:
        if sql.lstrip().upper().startswith("SELECT"):
            return None
        inserts.append(args)
        return _row(
            workspace_id=args[0],
            api_key_encrypted=args[5],
            api_key_preview=args[6],
        )

    pool = FakePool(handler)
    repo = LLMSettingsRepository(pool_getter=lambda: pool, workspace_id=workspace_id)

    profile = await repo.get_active_profile(include_secret=True)

    assert profile.workspace_id == str(workspace_id)
    assert profile.api_key is None
    assert profile.api_key_preview == ""
    assert profile.is_key_set is False
    assert inserts == []


@pytest.mark.asyncio
async def test_get_active_llm_profile_hides_secret_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[bool] = []

    class FakeRepository:
        def __init__(self, workspace_id: UUID | str | None = None) -> None:
            self.workspace_id = workspace_id

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


@pytest.mark.asyncio
async def test_get_active_llm_profile_cache_is_scoped_by_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_workspace_id = UUID("11111111-1111-1111-1111-111111111111")
    second_workspace_id = UUID("22222222-2222-2222-2222-222222222222")
    calls: list[tuple[str, bool]] = []

    class FakeRepository:
        def __init__(self, workspace_id: UUID | str | None = None) -> None:
            self.workspace_id = workspace_id

        async def get_active_profile(
            self,
            include_secret: bool = False,
        ) -> LLMProfile:
            workspace_id = str(self.workspace_id)
            calls.append((workspace_id, include_secret))
            return LLMProfile(
                id="profile-1",
                workspace_id=workspace_id,
                provider="deepseek",
                label="DeepSeek",
                base_url=DEFAULT_DEEPSEEK_BASE_URL,
                model=DEFAULT_DEEPSEEK_MODEL,
                api_key=None,
                api_key_preview="",
                is_key_set=False,
                last_test_status=None,
                last_test_error=None,
                last_test_at=None,
            )

    import services.llm_settings as llm_settings

    invalidate_llm_config()
    monkeypatch.setattr(llm_settings, "LLMSettingsRepository", FakeRepository)

    with workspace_context(first_workspace_id):
        first = await get_active_llm_profile()
    with workspace_context(second_workspace_id):
        second = await get_active_llm_profile()
    with workspace_context(first_workspace_id):
        cached_first = await get_active_llm_profile()

    assert first.workspace_id == str(first_workspace_id)
    assert second.workspace_id == str(second_workspace_id)
    assert cached_first.workspace_id == str(first_workspace_id)
    assert calls == [
        (str(first_workspace_id), False),
        (str(second_workspace_id), False),
    ]
    invalidate_llm_config()
