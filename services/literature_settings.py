"""Encrypted literature source settings storage."""

from __future__ import annotations

import inspect
import os
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Awaitable, Callable
from uuid import UUID

from apps.api.db.pool import record_to_dict
from libs.schemas.literature import (
    LiteratureCredentialPreview,
    LiteratureSource,
    LiteratureSourceSettings,
)
from services.llm_settings import (
    DEFAULT_WORKSPACE_ID,
    decrypt_api_key,
    encrypt_api_key,
    mask_api_key,
    redact_secret_text,
)

PoolGetter = Callable[[], Any | Awaitable[Any]]

SOURCE_LABELS: dict[LiteratureSource, str] = {
    LiteratureSource.LOCAL_LIBRARY: "Local library",
    LiteratureSource.ZOTERO: "Zotero",
    LiteratureSource.OBSIDIAN: "Obsidian",
    LiteratureSource.WEB_SEARCH: "Web search",
    LiteratureSource.SEMANTIC_SCHOLAR: "Semantic Scholar",
    LiteratureSource.OPENALEX: "OpenAlex",
    LiteratureSource.DEEPXIV: "DeepXiv",
}

DEFAULT_ENABLED: dict[LiteratureSource, bool] = {
    LiteratureSource.LOCAL_LIBRARY: True,
    LiteratureSource.ZOTERO: False,
    LiteratureSource.OBSIDIAN: False,
    LiteratureSource.WEB_SEARCH: False,
    LiteratureSource.SEMANTIC_SCHOLAR: True,
    LiteratureSource.OPENALEX: True,
    LiteratureSource.DEEPXIV: False,
}


@dataclass(frozen=True)
class LiteratureCredentialSecret:
    id: UUID | None
    source: LiteratureSource
    label: str
    secret: str


class LiteratureSettingsRepository:
    def __init__(self, pool_getter: PoolGetter | None = None) -> None:
        self._pool_getter = pool_getter

    async def list_sources(
        self,
        include_secrets: bool = False,
    ) -> list[LiteratureSourceSettings]:
        del include_secrets
        settings_rows = await self._fetch_all_source_settings()
        credential_rows = await self._fetch_all_active_credential_rows()
        settings_by_source = {
            str(row["source"]): row for row in settings_rows if row.get("source")
        }
        credentials_by_source: dict[str, list[dict[str, Any]]] = {}
        for row in credential_rows:
            credentials_by_source.setdefault(str(row["source"]), []).append(row)

        return [
            _source_settings_from_data(
                source,
                settings_by_source.get(source.value),
                credentials_by_source.get(source.value, []),
            )
            for source in LiteratureSource
        ]

    async def get_source(self, source: LiteratureSource | str) -> LiteratureSourceSettings:
        parsed_source = _coerce_source(source)
        settings_row = await self._fetch_source_settings(parsed_source)
        credential_rows = await self._fetch_active_credential_rows(parsed_source)
        return _source_settings_from_data(parsed_source, settings_row, credential_rows)

    async def get_active_credentials(
        self,
        source: LiteratureSource | str,
    ) -> list[LiteratureCredentialSecret]:
        parsed_source = _coerce_source(source)
        credential_rows = await self._fetch_active_credential_rows(parsed_source)
        if credential_rows:
            return [
                _credential_secret_from_row(parsed_source, row)
                for row in credential_rows
            ]
        return _env_credential_secrets(parsed_source)

    async def update_source(
        self,
        source: LiteratureSource | str,
        enabled: bool | None = None,
        options: dict[str, Any] | None = None,
        new_credentials: list[str] | None = None,
        clear_credential_ids: Iterable[str | UUID] | None = None,
    ) -> LiteratureSourceSettings:
        parsed_source = _coerce_source(source)
        existing = await self._fetch_source_settings(parsed_source)
        existing_options = _options_from_row(existing)
        if existing is None:
            existing_options = _env_options(parsed_source)
        next_options = existing_options if options is None else dict(options)
        next_enabled = (
            bool(existing["enabled"])
            if enabled is None and existing is not None
            else DEFAULT_ENABLED[parsed_source]
            if enabled is None
            else enabled
        )

        await self._upsert_source_settings(
            parsed_source,
            enabled=next_enabled,
            options=next_options,
        )

        clear_ids = [
            UUID(str(credential_id))
            for credential_id in clear_credential_ids or []
        ]
        if clear_ids:
            await self._clear_credentials(parsed_source, clear_ids)

        for credential in new_credentials or []:
            cleaned = _clean(credential)
            if cleaned:
                await self._insert_credential(parsed_source, cleaned)

        return await self.get_source(parsed_source)

    async def record_source_test(
        self,
        source: LiteratureSource | str,
        status: str,
        error: str | None = None,
    ) -> LiteratureSourceSettings:
        parsed_source = _coerce_source(source)
        safe_error = redact_secret_text(error) if error else None
        pool = await self._get_pool()
        row = await pool.fetchrow(
            """
            UPDATE literature_source_settings
            SET last_test_status = $3,
                last_test_error = $4,
                last_test_at = NOW(),
                updated_at = NOW()
            WHERE workspace_id = $1
              AND source = $2
            RETURNING *
            """,
            DEFAULT_WORKSPACE_ID,
            parsed_source.value,
            status,
            safe_error,
        )
        if row is None:
            await self._upsert_source_settings(
                parsed_source,
                enabled=DEFAULT_ENABLED[parsed_source],
                options=_env_options(parsed_source),
            )
            return await self.record_source_test(parsed_source, status, safe_error)

        credential_rows = await self._fetch_active_credential_rows(parsed_source)
        return _source_settings_from_data(
            parsed_source,
            _record_to_dict(row),
            credential_rows,
        )

    async def _fetch_all_source_settings(self) -> list[dict[str, Any]]:
        pool = await self._get_pool()
        rows = await pool.fetch(
            """
            SELECT *
            FROM literature_source_settings
            WHERE workspace_id = $1
            """,
            DEFAULT_WORKSPACE_ID,
        )
        return [_record_to_dict(row) for row in rows]

    async def _fetch_source_settings(
        self,
        source: LiteratureSource,
    ) -> dict[str, Any] | None:
        pool = await self._get_pool()
        row = await pool.fetchrow(
            """
            SELECT *
            FROM literature_source_settings
            WHERE workspace_id = $1
              AND source = $2
            LIMIT 1
            """,
            DEFAULT_WORKSPACE_ID,
            source.value,
        )
        return _record_to_dict(row) if row is not None else None

    async def _fetch_all_active_credential_rows(self) -> list[dict[str, Any]]:
        pool = await self._get_pool()
        rows = await pool.fetch(
            """
            SELECT *
            FROM literature_source_credentials
            WHERE workspace_id = $1
              AND is_active
            ORDER BY source, created_at ASC
            """,
            DEFAULT_WORKSPACE_ID,
        )
        return [_record_to_dict(row) for row in rows]

    async def _fetch_active_credential_rows(
        self,
        source: LiteratureSource,
    ) -> list[dict[str, Any]]:
        pool = await self._get_pool()
        rows = await pool.fetch(
            """
            SELECT *
            FROM literature_source_credentials
            WHERE workspace_id = $1
              AND source = $2
              AND is_active
            ORDER BY created_at ASC
            """,
            DEFAULT_WORKSPACE_ID,
            source.value,
        )
        return [_record_to_dict(row) for row in rows]

    async def _upsert_source_settings(
        self,
        source: LiteratureSource,
        *,
        enabled: bool,
        options: dict[str, Any],
    ) -> dict[str, Any]:
        pool = await self._get_pool()
        row = await pool.fetchrow(
            """
            INSERT INTO literature_source_settings (
                workspace_id,
                source,
                enabled,
                options_json
            )
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (workspace_id, source)
            DO UPDATE SET
                enabled = EXCLUDED.enabled,
                options_json = EXCLUDED.options_json,
                updated_at = NOW()
            RETURNING *
            """,
            DEFAULT_WORKSPACE_ID,
            source.value,
            enabled,
            options,
        )
        return _record_to_dict(row)

    async def _clear_credentials(
        self,
        source: LiteratureSource,
        credential_ids: list[UUID],
    ) -> None:
        pool = await self._get_pool()
        await pool.execute(
            """
            UPDATE literature_source_credentials
            SET is_active = FALSE,
                updated_at = NOW()
            WHERE workspace_id = $1
              AND source = $2
              AND id = ANY($3::uuid[])
            """,
            DEFAULT_WORKSPACE_ID,
            source.value,
            credential_ids,
        )

    async def _insert_credential(
        self,
        source: LiteratureSource,
        secret: str,
    ) -> dict[str, Any]:
        pool = await self._get_pool()
        row = await pool.fetchrow(
            """
            INSERT INTO literature_source_credentials (
                workspace_id,
                source,
                label,
                secret_encrypted,
                secret_preview,
                is_active
            )
            VALUES ($1, $2, $3, $4, $5, TRUE)
            RETURNING *
            """,
            DEFAULT_WORKSPACE_ID,
            source.value,
            "primary",
            encrypt_api_key(secret),
            mask_api_key(secret),
        )
        return _record_to_dict(row)

    async def _get_pool(self) -> Any:
        getter = self._pool_getter or _default_pool_getter
        pool = getter()
        if inspect.isawaitable(pool):
            return await pool
        return pool


def _source_settings_from_data(
    source: LiteratureSource,
    settings_row: dict[str, Any] | None,
    credential_rows: list[dict[str, Any]],
) -> LiteratureSourceSettings:
    db_credentials = [
        _credential_preview_from_row(row)
        for row in credential_rows
        if row.get("is_active", True)
    ]
    credentials = db_credentials or _env_credential_previews(source)
    options = _options_from_row(settings_row)
    if settings_row is None:
        options = _env_options(source)

    configured = (
        settings_row is not None
        or bool(options)
        or bool(credentials)
        or source is LiteratureSource.LOCAL_LIBRARY
    )

    return LiteratureSourceSettings(
        source=source,
        label=SOURCE_LABELS[source],
        enabled=(
            bool(settings_row["enabled"])
            if settings_row is not None
            else DEFAULT_ENABLED[source]
        ),
        configured=configured,
        options=options,
        credentials=credentials,
        last_test_status=settings_row.get("last_test_status")
        if settings_row is not None
        else None,
        last_test_error=redact_secret_text(settings_row.get("last_test_error"))
        if settings_row is not None and settings_row.get("last_test_error")
        else None,
        last_test_at=settings_row.get("last_test_at")
        if settings_row is not None
        else None,
    )


def _credential_preview_from_row(row: dict[str, Any]) -> LiteratureCredentialPreview:
    return LiteratureCredentialPreview(
        id=row.get("id"),
        label=row.get("label") or "primary",
        preview=row.get("secret_preview") or "",
        is_active=bool(row.get("is_active", True)),
        last_status=row.get("last_status"),
        last_error=redact_secret_text(row.get("last_error"))
        if row.get("last_error")
        else None,
        last_used_at=row.get("last_used_at"),
        cooldown_until=row.get("cooldown_until"),
    )


def _credential_secret_from_row(
    source: LiteratureSource,
    row: dict[str, Any],
) -> LiteratureCredentialSecret:
    secret = decrypt_api_key(row.get("secret_encrypted")) or ""
    return LiteratureCredentialSecret(
        id=row.get("id"),
        source=source,
        label=row.get("label") or "primary",
        secret=secret,
    )


def _env_options(source: LiteratureSource) -> dict[str, Any]:
    if source is LiteratureSource.ZOTERO:
        path = _clean(os.getenv("ZOTERO_LIBRARY_PATH"))
        return {"library_path": path} if path else {}
    if source is LiteratureSource.OBSIDIAN:
        path = _clean(os.getenv("OBSIDIAN_VAULT_PATH"))
        return {"vault_path": path} if path else {}
    if source is LiteratureSource.WEB_SEARCH:
        provider = _clean(os.getenv("WEB_SEARCH_PROVIDER"))
        return {"provider": provider} if provider else {}
    if source is LiteratureSource.OPENALEX:
        email = _clean(os.getenv("OPENALEX_EMAIL"))
        return {"email": email} if email else {}
    if source is LiteratureSource.DEEPXIV:
        command = _clean(os.getenv("DEEPXIV_COMMAND"))
        return {"command": command} if command else {}
    return {}


def _env_credential_previews(
    source: LiteratureSource,
) -> list[LiteratureCredentialPreview]:
    return [
        LiteratureCredentialPreview(
            id=None,
            label=secret.label,
            preview=mask_api_key(secret.secret),
            is_active=True,
        )
        for secret in _env_credential_secrets(source)
    ]


def _env_credential_secrets(
    source: LiteratureSource,
) -> list[LiteratureCredentialSecret]:
    secret = _env_secret_for_source(source)
    if not secret:
        return []
    return [
        LiteratureCredentialSecret(
            id=None,
            source=source,
            label="primary",
            secret=secret,
        )
    ]


def _env_secret_for_source(source: LiteratureSource) -> str | None:
    if source is LiteratureSource.SEMANTIC_SCHOLAR:
        return _first_env("S2_API_KEY", "SEMANTIC_SCHOLAR_API_KEY")
    if source is LiteratureSource.OPENALEX:
        return _clean(os.getenv("OPENALEX_API_KEY"))
    if source is LiteratureSource.WEB_SEARCH:
        return _clean(os.getenv("WEB_SEARCH_API_KEY"))
    return None


def _first_env(*keys: str) -> str | None:
    for key in keys:
        value = _clean(os.getenv(key))
        if value:
            return value
    return None


def _options_from_row(row: dict[str, Any] | None) -> dict[str, Any]:
    if row is None:
        return {}
    options = row.get("options_json") or {}
    return dict(options)


def _record_to_dict(row: Any) -> dict[str, Any]:
    return record_to_dict(row)


def _coerce_source(source: LiteratureSource | str) -> LiteratureSource:
    if isinstance(source, LiteratureSource):
        return source
    return LiteratureSource(str(source))


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


async def _default_pool_getter() -> Any:
    from apps.api.database import get_pool

    return await get_pool()
