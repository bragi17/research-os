"""Encrypted DeepSeek LLM settings storage."""

from __future__ import annotations

import base64
import hashlib
import hmac
import inspect
import os
import subprocess
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable


DEFAULT_WORKSPACE_ID = "00000000-0000-0000-0000-000000000000"
DEEPSEEK_PROVIDER = "deepseek"
DEFAULT_DEEPSEEK_LABEL = "DeepSeek"
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-pro"
LLM_CONFIG_CACHE_TTL_SECONDS = 5

_DEV_ENCRYPTION_SECRET = "research-os-dev-credential-encryption-key"
_FALLBACK_TOKEN_PREFIX = "ros-fernet-v1:"

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
    if fernet is not None:
        return fernet.encrypt(api_key.encode("utf-8")).decode("utf-8")
    return _encrypt_fernet_token(api_key)


def decrypt_api_key(encrypted_api_key: str | None) -> str | None:
    if not encrypted_api_key:
        return None
    fernet = _get_fernet()
    if fernet is not None and not encrypted_api_key.startswith(_FALLBACK_TOKEN_PREFIX):
        return fernet.decrypt(encrypted_api_key.encode("utf-8")).decode("utf-8")
    if not encrypted_api_key.startswith(_FALLBACK_TOKEN_PREFIX):
        return _decrypt_fernet_token(encrypted_api_key)
    return _decrypt_fallback(encrypted_api_key)


def _settings_secret() -> str:
    return (
        os.getenv("CREDENTIAL_ENCRYPTION_KEY")
        or os.getenv("JWT_SECRET")
        or _DEV_ENCRYPTION_SECRET
    )


def _raw_encryption_key() -> bytes:
    return hashlib.sha256(_settings_secret().encode("utf-8")).digest()


def _get_fernet() -> Any | None:
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        return None
    key = base64.urlsafe_b64encode(_raw_encryption_key())
    return Fernet(key)


def _encrypt_fallback(api_key: str) -> str:
    raw_key = _raw_encryption_key()
    nonce = os.urandom(16)
    plaintext = api_key.encode("utf-8")
    ciphertext = _xor_stream(raw_key[:16], nonce, plaintext)
    payload = b"\x80" + int(time.time()).to_bytes(8, "big") + nonce + ciphertext
    mac = hmac.new(raw_key[16:], payload, hashlib.sha256).digest()
    token = base64.urlsafe_b64encode(payload + mac).decode("ascii")
    return f"{_FALLBACK_TOKEN_PREFIX}{token}"


def _encrypt_fernet_token(api_key: str) -> str:
    signing_key, encryption_key = _fernet_keys()
    iv = os.urandom(16)
    padded = _pkcs7_pad(api_key.encode("utf-8"))
    ciphertext = _openssl_aes_cbc(padded, encryption_key, iv, decrypt=False)
    payload = b"\x80" + int(time.time()).to_bytes(8, "big") + iv + ciphertext
    mac = hmac.new(signing_key, payload, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(payload + mac).decode("ascii")


def _decrypt_fernet_token(encrypted_api_key: str) -> str:
    data = base64.urlsafe_b64decode(encrypted_api_key.encode("ascii"))
    if len(data) < 73 or data[0] != 0x80:
        raise ValueError("Invalid encrypted API key")
    payload, actual_mac = data[:-32], data[-32:]
    signing_key, encryption_key = _fernet_keys()
    expected_mac = hmac.new(signing_key, payload, hashlib.sha256).digest()
    if not hmac.compare_digest(actual_mac, expected_mac):
        raise ValueError("Encrypted API key authentication failed")
    iv = payload[9:25]
    plaintext = _openssl_aes_cbc(payload[25:], encryption_key, iv, decrypt=True)
    return _pkcs7_unpad(plaintext).decode("utf-8")


def _fernet_keys() -> tuple[bytes, bytes]:
    key = _raw_encryption_key()
    return key[:16], key[16:]


def _pkcs7_pad(data: bytes) -> bytes:
    padding_size = 16 - (len(data) % 16)
    return data + bytes([padding_size]) * padding_size


def _pkcs7_unpad(data: bytes) -> bytes:
    if not data:
        raise ValueError("Invalid encrypted API key padding")
    padding_size = data[-1]
    if padding_size < 1 or padding_size > 16:
        raise ValueError("Invalid encrypted API key padding")
    if data[-padding_size:] != bytes([padding_size]) * padding_size:
        raise ValueError("Invalid encrypted API key padding")
    return data[:-padding_size]


def _openssl_aes_cbc(
    data: bytes,
    key: bytes,
    iv: bytes,
    *,
    decrypt: bool,
) -> bytes:
    mode = "-d" if decrypt else "-e"
    result = subprocess.run(
        [
            "openssl",
            "enc",
            "-aes-128-cbc",
            mode,
            "-K",
            key.hex(),
            "-iv",
            iv.hex(),
            "-nopad",
        ],
        input=data,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise ValueError("OpenSSL failed to process encrypted API key")
    return result.stdout


def _decrypt_fallback(encrypted_api_key: str) -> str:
    if not encrypted_api_key.startswith(_FALLBACK_TOKEN_PREFIX):
        raise ValueError("Unsupported encrypted API key format")
    token = encrypted_api_key.removeprefix(_FALLBACK_TOKEN_PREFIX)
    data = base64.urlsafe_b64decode(token.encode("ascii"))
    if len(data) < 58 or data[0] != 0x80:
        raise ValueError("Invalid encrypted API key")
    payload, actual_mac = data[:-32], data[-32:]
    raw_key = _raw_encryption_key()
    expected_mac = hmac.new(raw_key[16:], payload, hashlib.sha256).digest()
    if not hmac.compare_digest(actual_mac, expected_mac):
        raise ValueError("Encrypted API key authentication failed")
    nonce = payload[9:25]
    ciphertext = payload[25:]
    return _xor_stream(raw_key[:16], nonce, ciphertext).decode("utf-8")


def _xor_stream(key: bytes, nonce: bytes, data: bytes) -> bytes:
    output = bytearray()
    counter = 0
    while len(output) < len(data):
        block = hmac.new(
            key,
            nonce + counter.to_bytes(8, "big"),
            hashlib.sha256,
        ).digest()
        output.extend(block)
        counter += 1
    return bytes(byte ^ stream for byte, stream in zip(data, output))


class LLMSettingsRepository:
    def __init__(self, pool_getter: PoolGetter | None = None) -> None:
        self._pool_getter = pool_getter

    async def get_active_profile(self, include_secret: bool = False) -> LLMProfile:
        row = await self._fetch_active_row()
        if row is None:
            return await self.bootstrap_from_env(include_secret=include_secret)
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


async def get_active_llm_profile(include_secret: bool = True) -> LLMProfile:
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
