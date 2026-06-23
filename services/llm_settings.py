"""Encrypted DeepSeek LLM settings storage."""

from __future__ import annotations

import base64
import hashlib
import inspect
import os
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable


DEFAULT_WORKSPACE_ID = "00000000-0000-0000-0000-000000000000"
DEEPSEEK_PROVIDER = "deepseek"
DEFAULT_DEEPSEEK_LABEL = "DeepSeek"
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-pro"
LLM_CONFIG_CACHE_TTL_SECONDS = 5

PoolGetter = Callable[[], Any | Awaitable[Any]]


@dataclass(frozen=True)
class LLMProfile:
    id: str | None
    workspace_id: str
    provider: str
    label: str
    base_url: str
    model: str
    api_key: str | None
    api_key_preview: str
    is_key_set: bool
    last_test_status: str | None
    last_test_error: str | None
    last_test_at: Any | None


def mask_api_key(api_key: str) -> str:
    if not api_key:
        return ""
    if len(api_key) <= 8:
        return "****"
    return f"{api_key[:4]}****{api_key[-4:]}"


def encrypt_api_key(api_key: str) -> str:
    if not api_key:
        return ""
    fernet = _get_fernet()
    return fernet.encrypt(api_key.encode("utf-8")).decode("utf-8")


def decrypt_api_key(encrypted_api_key: str | None) -> str | None:
    if not encrypted_api_key:
        return None
    fernet = _get_fernet()
    return fernet.decrypt(encrypted_api_key.encode("utf-8")).decode("utf-8")


def _settings_secret() -> str:
    secret = os.getenv("CREDENTIAL_ENCRYPTION_KEY")
    if not secret:
        raise RuntimeError(
            "CREDENTIAL_ENCRYPTION_KEY is required to store DeepSeek API keys"
        )
    return secret


def _raw_encryption_key() -> bytes:
    return hashlib.sha256(_settings_secret().encode("utf-8")).digest()


def _get_fernet() -> Any:
    try:
        from cryptography.fernet import Fernet
    except ImportError as exc:
        raise RuntimeError(
            "cryptography is required to store DeepSeek API keys"
        ) from exc
    key = base64.urlsafe_b64encode(_raw_encryption_key())
    return Fernet(key)


class LLMSettingsRepository:
    def __init__(self, pool_getter: PoolGetter | None = None) -> None:
        self._pool_getter = pool_getter

    async def get_active_profile(self, include_secret: bool = False) -> LLMProfile:
        row = await self._fetch_active_row()
        if row is None:
            return await self.bootstrap_from_env(include_secret=include_secret)
        return _profile_from_row(row, include_secret=include_secret)

    async def peek_active_profile(
        self,
        include_secret: bool = False,
    ) -> LLMProfile | None:
        row = await self._fetch_active_row()
        if row is None:
            return None
        return _profile_from_row(row, include_secret=include_secret)

    async def bootstrap_from_env(self, include_secret: bool = False) -> LLMProfile:
        existing = await self._fetch_active_row()
        if existing is not None:
            return _profile_from_row(existing, include_secret=include_secret)

        api_key = os.getenv("DEEPSEEK_API_KEY", "")
        encrypted = encrypt_api_key(api_key) if api_key else None
        preview = mask_api_key(api_key)
        row = await self._upsert_row(
            label=DEFAULT_DEEPSEEK_LABEL,
            base_url=os.getenv("DEEPSEEK_BASE_URL", DEFAULT_DEEPSEEK_BASE_URL),
            model=os.getenv("DEEPSEEK_MODEL", DEFAULT_DEEPSEEK_MODEL),
            api_key_encrypted=encrypted,
            api_key_preview=preview,
        )
        invalidate_llm_config()
        return _profile_from_row(row, include_secret=include_secret)

    async def upsert_active_profile(
        self,
        *,
        label: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        clear_api_key: bool = False,
        include_secret: bool = False,
    ) -> LLMProfile:
        existing = await self._fetch_active_row()
        existing_data = dict(existing) if existing is not None else {}
        encrypted, preview = _next_key_values(existing_data, api_key, clear_api_key)
        row = await self._upsert_row(
            label=_clean(label) or existing_data.get("label") or DEFAULT_DEEPSEEK_LABEL,
            base_url=_clean(base_url)
            or existing_data.get("base_url")
            or DEFAULT_DEEPSEEK_BASE_URL,
            model=_clean(model) or existing_data.get("model") or DEFAULT_DEEPSEEK_MODEL,
            api_key_encrypted=encrypted,
            api_key_preview=preview,
        )
        invalidate_llm_config()
        return _profile_from_row(row, include_secret=include_secret)

    async def clear_api_key(self) -> LLMProfile:
        return await self.upsert_active_profile(clear_api_key=True)

    async def record_test_result(
        self,
        status: str,
        error: str | None = None,
    ) -> LLMProfile:
        pool = await self._get_pool()
        row = await pool.fetchrow(
            """
            UPDATE llm_provider_credentials
            SET last_test_status = $3,
                last_test_error = $4,
                last_test_at = NOW(),
                updated_at = NOW()
            WHERE workspace_id = $1
              AND provider = $2
              AND is_active
            RETURNING *
            """,
            DEFAULT_WORKSPACE_ID,
            DEEPSEEK_PROVIDER,
            status,
            error,
        )
        if row is None:
            await self.bootstrap_from_env(include_secret=False)
            return await self.record_test_result(status, error)
        invalidate_llm_config()
        return _profile_from_row(row, include_secret=False)

    async def _fetch_active_row(self) -> Any | None:
        pool = await self._get_pool()
        return await pool.fetchrow(
            """
            SELECT *
            FROM llm_provider_credentials
            WHERE workspace_id = $1
              AND provider = $2
              AND is_active
            LIMIT 1
            """,
            DEFAULT_WORKSPACE_ID,
            DEEPSEEK_PROVIDER,
        )

    async def _upsert_row(
        self,
        *,
        label: str,
        base_url: str,
        model: str,
        api_key_encrypted: str | None,
        api_key_preview: str,
    ) -> Any:
        pool = await self._get_pool()
        return await pool.fetchrow(
            """
            INSERT INTO llm_provider_credentials (
                workspace_id,
                provider,
                label,
                base_url,
                model,
                api_key_encrypted,
                api_key_preview,
                is_active
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, TRUE)
            ON CONFLICT (workspace_id, provider) WHERE is_active
            DO UPDATE SET
                label = EXCLUDED.label,
                base_url = EXCLUDED.base_url,
                model = EXCLUDED.model,
                api_key_encrypted = EXCLUDED.api_key_encrypted,
                api_key_preview = EXCLUDED.api_key_preview,
                updated_at = NOW()
            RETURNING *
            """,
            DEFAULT_WORKSPACE_ID,
            DEEPSEEK_PROVIDER,
            label,
            base_url,
            model,
            api_key_encrypted,
            api_key_preview,
        )

    async def _get_pool(self) -> Any:
        getter = self._pool_getter or _default_pool_getter
        pool = getter()
        if inspect.isawaitable(pool):
            return await pool
        return pool


def _next_key_values(
    existing_data: dict[str, Any],
    api_key: str | None,
    clear_api_key: bool,
) -> tuple[str | None, str]:
    if clear_api_key:
        return None, ""
    cleaned_key = _clean(api_key)
    if cleaned_key:
        return encrypt_api_key(cleaned_key), mask_api_key(cleaned_key)
    return (
        existing_data.get("api_key_encrypted"),
        existing_data.get("api_key_preview") or "",
    )


def _profile_from_row(row: Any, include_secret: bool) -> LLMProfile:
    data = dict(row)
    encrypted = data.get("api_key_encrypted")
    api_key = decrypt_api_key(encrypted) if include_secret and encrypted else None
    preview = data.get("api_key_preview") or (mask_api_key(api_key or "") if api_key else "")
    return LLMProfile(
        id=str(data["id"]) if data.get("id") is not None else None,
        workspace_id=str(data.get("workspace_id") or DEFAULT_WORKSPACE_ID),
        provider=data.get("provider") or DEEPSEEK_PROVIDER,
        label=data.get("label") or DEFAULT_DEEPSEEK_LABEL,
        base_url=data.get("base_url") or DEFAULT_DEEPSEEK_BASE_URL,
        model=data.get("model") or DEFAULT_DEEPSEEK_MODEL,
        api_key=api_key,
        api_key_preview=preview,
        is_key_set=bool(encrypted),
        last_test_status=data.get("last_test_status"),
        last_test_error=data.get("last_test_error"),
        last_test_at=data.get("last_test_at"),
    )


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


async def _default_pool_getter() -> Any:
    from apps.api.database import get_pool

    return await get_pool()


_llm_config_cache: dict[bool, tuple[float, LLMProfile]] = {}


async def get_active_llm_profile(include_secret: bool = False) -> LLMProfile:
    now = time.monotonic()
    cached = _llm_config_cache.get(include_secret)
    if cached is not None:
        expires_at, profile = cached
        if now < expires_at:
            return profile
    profile = await LLMSettingsRepository().get_active_profile(
        include_secret=include_secret,
    )
    _llm_config_cache[include_secret] = (
        now + LLM_CONFIG_CACHE_TTL_SECONDS,
        profile,
    )
    return profile


def invalidate_llm_config() -> None:
    _llm_config_cache.clear()
