"""Tests for encrypted literature source settings storage."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any
from uuid import UUID, uuid4

import pytest

import services.literature_settings as literature_settings
from libs.schemas.literature import LiteratureSource
from libs.schemas.literature import LiteratureSourceUpdate
from services.literature_settings import (
    DEFAULT_WORKSPACE_ID,
    LiteratureCredentialSecret,
    LiteratureSettingsRepository,
    encrypt_api_key,
    mask_api_key,
)


def _setting_row(source: LiteratureSource | str, **overrides: Any) -> dict[str, Any]:
    row = {
        "id": uuid4(),
        "workspace_id": DEFAULT_WORKSPACE_ID,
        "source": str(source.value if isinstance(source, LiteratureSource) else source),
        "enabled": True,
        "options_json": {},
        "last_test_status": None,
        "last_test_error": None,
        "last_test_at": None,
    }
    row.update(overrides)
    return row


def _credential_row(source: LiteratureSource | str, **overrides: Any) -> dict[str, Any]:
    row = {
        "id": uuid4(),
        "workspace_id": DEFAULT_WORKSPACE_ID,
        "source": str(source.value if isinstance(source, LiteratureSource) else source),
        "label": "primary",
        "secret_encrypted": "encrypted-secret",
        "secret_preview": "secr****cret",
        "is_active": True,
        "last_status": None,
        "last_error": None,
        "last_used_at": None,
        "cooldown_until": None,
    }
    row.update(overrides)
    return row


class FakePool:
    def __init__(
        self,
        *,
        settings: Iterable[dict[str, Any]] | None = None,
        credentials: Iterable[dict[str, Any]] | None = None,
    ) -> None:
        self.settings: dict[str, dict[str, Any]] = {
            str(row["source"]): dict(row) for row in settings or []
        }
        self.credentials: dict[str, list[dict[str, Any]]] = {}
        for row in credentials or []:
            self.credentials.setdefault(str(row["source"]), []).append(dict(row))
        self.fetch_calls: list[tuple[str, tuple[Any, ...]]] = []
        self.fetchrow_calls: list[tuple[str, tuple[Any, ...]]] = []
        self.execute_calls: list[tuple[str, tuple[Any, ...]]] = []

    async def fetch(self, sql: str, *args: Any) -> list[dict[str, Any]]:
        self.fetch_calls.append((sql, args))
        if "FROM literature_source_settings" in sql:
            return list(self.settings.values())
        if "FROM literature_source_credentials" in sql:
            if len(args) >= 2:
                return [
                    row
                    for row in self.credentials.get(str(args[1]), [])
                    if row.get("is_active", True)
                ]
            return [
                row
                for rows in self.credentials.values()
                for row in rows
                if row.get("is_active", True)
            ]
        return []

    async def fetchrow(self, sql: str, *args: Any) -> dict[str, Any] | None:
        self.fetchrow_calls.append((sql, args))
        if "INSERT INTO literature_source_settings" in sql:
            row = _setting_row(args[1], enabled=args[2], options_json=args[3])
            self.settings[str(args[1])] = row
            return row
        if "INSERT INTO literature_source_credentials" in sql:
            row = _credential_row(
                args[1],
                label=args[2],
                secret_encrypted=args[3],
                secret_preview=args[4],
            )
            self.credentials.setdefault(str(args[1]), []).append(row)
            return row
        if "UPDATE literature_source_settings" in sql:
            source = str(args[1])
            existing = self.settings.get(source) or _setting_row(source)
            existing.update(
                last_test_status=args[2],
                last_test_error=args[3],
            )
            self.settings[source] = existing
            return existing
        if "FROM literature_source_settings" in sql and len(args) >= 2:
            return self.settings.get(str(args[1]))
        return None

    async def execute(self, sql: str, *args: Any) -> str:
        self.execute_calls.append((sql, args))
        if "UPDATE literature_source_credentials" in sql and len(args) >= 3:
            source = str(args[1])
            clear_ids = set(args[2])
            for row in self.credentials.get(source, []):
                if row["id"] in clear_ids:
                    row["is_active"] = False
            return f"UPDATE {len(clear_ids)}"
        return "UPDATE 0"

    def captured_arguments(self) -> str:
        return repr(
            [
                args
                for calls in (self.fetch_calls, self.fetchrow_calls, self.execute_calls)
                for _, args in calls
            ]
        )


class FakeTransaction:
    def __init__(self, pool: "DirectTransactionalFakePool") -> None:
        self.pool = pool

    async def __aenter__(self) -> None:
        self.pool.transaction_entries += 1

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: Any,
    ) -> None:
        return None


class DirectTransactionalFakePool(FakePool):
    def __init__(
        self,
        *,
        settings: Iterable[dict[str, Any]] | None = None,
        credentials: Iterable[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(settings=settings, credentials=credentials)
        self.transaction_entries = 0

    def transaction(self) -> FakeTransaction:
        return FakeTransaction(self)


class FakeAcquire:
    def __init__(self, pool: "AcquireTransactionalFakePool") -> None:
        self.pool = pool

    async def __aenter__(self) -> "AcquireTransactionalFakePool":
        self.pool.acquire_entries += 1
        return self.pool

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: Any,
    ) -> None:
        return None


class AcquireTransactionalFakePool(DirectTransactionalFakePool):
    def __init__(
        self,
        *,
        settings: Iterable[dict[str, Any]] | None = None,
        credentials: Iterable[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(settings=settings, credentials=credentials)
        self.acquire_entries = 0

    def acquire(self) -> FakeAcquire:
        return FakeAcquire(self)


@pytest.mark.asyncio
async def test_env_bootstrap_for_s2_and_openalex_hides_plaintext(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("S2_API_KEY", "s2-secret-key-123456")
    monkeypatch.setenv("OPENALEX_EMAIL", "researcher@example.com")
    monkeypatch.setenv("OPENALEX_API_KEY", "openalex-secret-key-abcdef")
    pool = FakePool()
    repo = LiteratureSettingsRepository(pool_getter=lambda: pool)

    sources = await repo.list_sources()

    by_source = {settings.source: settings for settings in sources}
    assert set(by_source) == set(LiteratureSource)
    semantic_scholar = by_source[LiteratureSource.SEMANTIC_SCHOLAR]
    openalex = by_source[LiteratureSource.OPENALEX]
    assert semantic_scholar.configured is True
    assert semantic_scholar.credentials[0].preview == mask_api_key(
        "s2-secret-key-123456"
    )
    assert openalex.configured is True
    assert openalex.options["email"] == "researcher@example.com"
    assert openalex.credentials[0].preview == mask_api_key(
        "openalex-secret-key-abcdef"
    )
    dumped = [settings.model_dump(mode="json") for settings in sources]
    serialized = repr(dumped)
    assert "s2-secret-key-123456" not in serialized
    assert "openalex-secret-key-abcdef" not in serialized


@pytest.mark.asyncio
async def test_env_fallbacks_cover_non_openalex_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("S2_API_KEY", raising=False)
    monkeypatch.setenv("SEMANTIC_SCHOLAR_API_KEY", "semantic-secret-key-123456")
    monkeypatch.setenv("ZOTERO_LIBRARY_PATH", "/data/zotero/library.sqlite")
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", "/notes/research-vault")
    monkeypatch.setenv("WEB_SEARCH_PROVIDER", "tavily")
    monkeypatch.setenv("WEB_SEARCH_API_KEY", "web-secret-key-123456")
    monkeypatch.setenv("DEEPXIV_COMMAND", "deepxiv search --json")
    pool = FakePool()
    repo = LiteratureSettingsRepository(pool_getter=lambda: pool)

    sources = await repo.list_sources()

    by_source = {settings.source: settings for settings in sources}
    assert by_source[LiteratureSource.SEMANTIC_SCHOLAR].credentials[0].preview == (
        mask_api_key("semantic-secret-key-123456")
    )
    assert by_source[LiteratureSource.ZOTERO].options == {
        "library_path": "/data/zotero/library.sqlite"
    }
    assert by_source[LiteratureSource.OBSIDIAN].options == {
        "vault_path": "/notes/research-vault"
    }
    assert by_source[LiteratureSource.WEB_SEARCH].options == {"provider": "tavily"}
    assert by_source[LiteratureSource.WEB_SEARCH].credentials[0].preview == (
        mask_api_key("web-secret-key-123456")
    )
    assert by_source[LiteratureSource.DEEPXIV].options == {
        "command": "deepxiv search --json"
    }


@pytest.mark.asyncio
async def test_db_source_rows_take_precedence_over_env_fallbacks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WEB_SEARCH_PROVIDER", "env-provider")
    monkeypatch.setenv("WEB_SEARCH_API_KEY", "env-secret-key-123456")
    pool = FakePool(
        settings=[
            _setting_row(
                LiteratureSource.WEB_SEARCH,
                enabled=True,
                options_json={"provider": "db-provider"},
            )
        ],
        credentials=[
            _credential_row(
                LiteratureSource.WEB_SEARCH,
                secret_encrypted="encrypted-db-secret",
                secret_preview="db-s****3456",
            )
        ],
    )
    repo = LiteratureSettingsRepository(pool_getter=lambda: pool)

    settings = await repo.get_source(LiteratureSource.WEB_SEARCH)

    assert settings.options == {"provider": "db-provider"}
    assert len(settings.credentials) == 1
    assert settings.credentials[0].preview == "db-s****3456"
    assert settings.credentials[0].preview != mask_api_key("env-secret-key-123456")


@pytest.mark.asyncio
async def test_configured_requires_source_specific_required_inputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("S2_API_KEY", raising=False)
    monkeypatch.delenv("SEMANTIC_SCHOLAR_API_KEY", raising=False)
    monkeypatch.delenv("WEB_SEARCH_API_KEY", raising=False)
    monkeypatch.delenv("OPENALEX_API_KEY", raising=False)
    monkeypatch.delenv("OPENALEX_EMAIL", raising=False)
    pool = FakePool(
        settings=[
            _setting_row(LiteratureSource.SEMANTIC_SCHOLAR),
            _setting_row(
                LiteratureSource.WEB_SEARCH,
                options_json={"provider": "tavily"},
            ),
            _setting_row(LiteratureSource.OPENALEX),
            _setting_row(
                LiteratureSource.ZOTERO,
                options_json={"library_path": "/data/zotero.json"},
            ),
            _setting_row(
                LiteratureSource.OBSIDIAN,
                options_json={"vault_path": "/notes/research"},
            ),
            _setting_row(
                LiteratureSource.DEEPXIV,
                options_json={"command": "deepxiv search"},
            ),
        ],
    )
    repo = LiteratureSettingsRepository(pool_getter=lambda: pool)

    sources = {source.source: source for source in await repo.list_sources()}

    assert sources[LiteratureSource.LOCAL_LIBRARY].configured is True
    assert sources[LiteratureSource.SEMANTIC_SCHOLAR].configured is False
    assert sources[LiteratureSource.WEB_SEARCH].configured is False
    assert sources[LiteratureSource.OPENALEX].configured is False
    assert sources[LiteratureSource.ZOTERO].configured is True
    assert sources[LiteratureSource.OBSIDIAN].configured is True
    assert sources[LiteratureSource.DEEPXIV].configured is True


@pytest.mark.asyncio
async def test_configured_uses_db_credentials_for_keyed_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        literature_settings,
        "decrypt_api_key",
        lambda secret: "db-secret-key-123456",
    )
    pool = FakePool(
        settings=[
            _setting_row(LiteratureSource.SEMANTIC_SCHOLAR),
            _setting_row(
                LiteratureSource.WEB_SEARCH,
                options_json={"provider": "tavily"},
            ),
            _setting_row(LiteratureSource.OPENALEX),
        ],
        credentials=[
            _credential_row(LiteratureSource.SEMANTIC_SCHOLAR),
            _credential_row(LiteratureSource.WEB_SEARCH),
            _credential_row(LiteratureSource.OPENALEX),
        ],
    )
    repo = LiteratureSettingsRepository(pool_getter=lambda: pool)

    sources = {source.source: source for source in await repo.list_sources()}

    assert sources[LiteratureSource.SEMANTIC_SCHOLAR].configured is True
    assert sources[LiteratureSource.WEB_SEARCH].configured is True
    assert sources[LiteratureSource.OPENALEX].configured is True


@pytest.mark.asyncio
async def test_async_pool_getter_is_awaited_for_repository_calls() -> None:
    getter_calls = 0
    pool = FakePool()

    async def get_pool() -> FakePool:
        nonlocal getter_calls
        getter_calls += 1
        return pool

    repo = LiteratureSettingsRepository(pool_getter=get_pool)

    settings = await repo.get_source(LiteratureSource.WEB_SEARCH)

    assert settings.source == LiteratureSource.WEB_SEARCH
    assert getter_calls > 0


@pytest.mark.asyncio
async def test_list_sources_rejects_include_secrets() -> None:
    pool = FakePool()
    repo = LiteratureSettingsRepository(pool_getter=lambda: pool)

    with pytest.raises(ValueError, match="include_secrets"):
        await repo.list_sources(include_secrets=True)

    assert pool.fetch_calls == []
    assert pool.fetchrow_calls == []
    assert pool.execute_calls == []


@pytest.mark.asyncio
async def test_db_credentials_decrypt_only_through_get_active_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    decrypt_calls: list[str] = []

    def fake_decrypt(secret: str | None) -> str | None:
        assert secret is not None
        decrypt_calls.append(secret)
        return "db-secret-key-123456"

    monkeypatch.setattr(literature_settings, "decrypt_api_key", fake_decrypt)
    pool = FakePool(
        settings=[
            _setting_row(
                LiteratureSource.SEMANTIC_SCHOLAR,
                options_json={"limit": 10},
            )
        ],
        credentials=[
            _credential_row(
                LiteratureSource.SEMANTIC_SCHOLAR,
                secret_encrypted="encrypted-db-secret",
                secret_preview="db-s****3456",
            )
        ],
    )
    repo = LiteratureSettingsRepository(pool_getter=lambda: pool)

    settings = await repo.get_source(LiteratureSource.SEMANTIC_SCHOLAR)

    assert decrypt_calls == []
    assert "db-secret-key-123456" not in repr(settings.model_dump(mode="json"))

    credentials = await repo.get_active_credentials(LiteratureSource.SEMANTIC_SCHOLAR)

    assert decrypt_calls == ["encrypted-db-secret"]
    assert credentials == [
        LiteratureCredentialSecret(
            id=pool.credentials[LiteratureSource.SEMANTIC_SCHOLAR.value][0]["id"],
            source=LiteratureSource.SEMANTIC_SCHOLAR,
            label="primary",
            secret="db-secret-key-123456",
        )
    ]


@pytest.mark.asyncio
async def test_update_source_rejects_unsupported_credentials_before_settings_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", "unit-test-encryption-secret")
    pool = FakePool(
        settings=[
            _setting_row(
                LiteratureSource.ZOTERO,
                enabled=False,
                options_json={"library_path": "/papers/zotero.sqlite"},
            )
        ]
    )
    repo = LiteratureSettingsRepository(pool_getter=lambda: pool)

    with pytest.raises(ValueError, match="does not support stored credentials"):
        await repo.update_source(
            LiteratureSource.ZOTERO,
            enabled=True,
            options={"library_path": "/papers/other.sqlite"},
            new_credentials=["zotero-secret-key"],
            clear_credential_ids=[],
        )

    assert not [
        args
        for sql, args in pool.fetchrow_calls
        if "INSERT INTO literature_source_settings" in sql
    ]


@pytest.mark.asyncio
async def test_update_source_rejects_invalid_clear_id_before_settings_write() -> None:
    pool = FakePool(
        settings=[
            _setting_row(
                LiteratureSource.WEB_SEARCH,
                enabled=False,
                options_json={"provider": "exa"},
            )
        ]
    )
    repo = LiteratureSettingsRepository(pool_getter=lambda: pool)

    with pytest.raises(ValueError, match="Invalid credential id"):
        await repo.update_source(
            LiteratureSource.WEB_SEARCH,
            enabled=True,
            options={"provider": "tavily"},
            new_credentials=[],
            clear_credential_ids=["not-a-uuid"],
        )

    assert not [
        args
        for sql, args in pool.fetchrow_calls
        if "INSERT INTO literature_source_settings" in sql
    ]


@pytest.mark.asyncio
async def test_update_source_encrypts_new_credentials_before_settings_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CREDENTIAL_ENCRYPTION_KEY", raising=False)
    pool = FakePool(
        settings=[
            _setting_row(
                LiteratureSource.WEB_SEARCH,
                enabled=False,
                options_json={"provider": "exa"},
            )
        ]
    )
    repo = LiteratureSettingsRepository(pool_getter=lambda: pool)

    with pytest.raises(RuntimeError, match="CREDENTIAL_ENCRYPTION_KEY is required"):
        await repo.update_source(
            LiteratureSource.WEB_SEARCH,
            enabled=True,
            options={"provider": "tavily"},
            new_credentials=["web-search-secret-key-123456"],
            clear_credential_ids=[],
        )

    assert not [
        args
        for sql, args in pool.fetchrow_calls
        if "INSERT INTO literature_source_settings" in sql
    ]


@pytest.mark.asyncio
async def test_update_source_encrypts_inserts_clears_and_hides_plaintext(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", "unit-test-encryption-secret")
    plaintext = "web-search-secret-key-123456"
    clear_id = uuid4()
    pool = FakePool(
        settings=[
            _setting_row(
                LiteratureSource.WEB_SEARCH,
                enabled=False,
                options_json={"limit": 5, "provider": "exa"},
            )
        ],
        credentials=[
            _credential_row(
                LiteratureSource.WEB_SEARCH,
                id=clear_id,
                secret_encrypted=encrypt_api_key("old-secret-key"),
                secret_preview="old-****-key",
            )
        ],
    )
    repo = LiteratureSettingsRepository(pool_getter=lambda: pool)

    updated = await repo.update_source(
        LiteratureSource.WEB_SEARCH,
        enabled=True,
        options={"provider": "tavily"},
        new_credentials=[plaintext],
        clear_credential_ids=[str(clear_id)],
    )

    assert updated.enabled is True
    assert updated.options == {"limit": 5, "provider": "tavily"}
    assert len(updated.credentials) == 1
    assert updated.credentials[0].preview == mask_api_key(plaintext)
    settings_write = [
        args
        for sql, args in pool.fetchrow_calls
        if "INSERT INTO literature_source_settings" in sql
    ][0]
    assert settings_write[1] == LiteratureSource.WEB_SEARCH.value
    assert settings_write[2] is True
    assert settings_write[3] == {"limit": 5, "provider": "tavily"}
    clear_write = [
        args
        for sql, args in pool.execute_calls
        if "UPDATE literature_source_credentials" in sql
    ][0]
    assert clear_write[2] == [clear_id]
    inserted_credential = [
        args
        for sql, args in pool.fetchrow_calls
        if "INSERT INTO literature_source_credentials" in sql
    ][0]
    assert inserted_credential[3] != plaintext
    assert plaintext not in inserted_credential[3]
    assert plaintext not in pool.captured_arguments()
    assert plaintext not in repr(updated.model_dump(mode="json"))


@pytest.mark.asyncio
async def test_update_source_accepts_schema_secret_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", "unit-test-encryption-secret")
    plaintext = "schema-secret-key-123456"
    body = LiteratureSourceUpdate(new_credentials=[plaintext])
    pool = FakePool(
        settings=[
            _setting_row(
                LiteratureSource.WEB_SEARCH,
                enabled=False,
                options_json={"provider": "exa"},
            )
        ]
    )
    repo = LiteratureSettingsRepository(pool_getter=lambda: pool)

    updated = await repo.update_source(
        LiteratureSource.WEB_SEARCH,
        enabled=True,
        options={"provider": "tavily"},
        new_credentials=body.new_credentials,
        clear_credential_ids=[],
    )

    assert len(updated.credentials) == 1
    assert updated.credentials[0].preview == mask_api_key(plaintext)
    inserted_credential = [
        args
        for sql, args in pool.fetchrow_calls
        if "INSERT INTO literature_source_credentials" in sql
    ][0]
    assert inserted_credential[3] != plaintext
    assert plaintext not in inserted_credential[3]
    assert plaintext not in pool.captured_arguments()
    assert plaintext not in repr(updated.model_dump(mode="json"))


@pytest.mark.asyncio
async def test_update_source_uses_direct_executor_transaction() -> None:
    pool = DirectTransactionalFakePool(
        settings=[
            _setting_row(
                LiteratureSource.WEB_SEARCH,
                enabled=False,
                options_json={"provider": "exa"},
            )
        ]
    )
    repo = LiteratureSettingsRepository(pool_getter=lambda: pool)

    updated = await repo.update_source(
        LiteratureSource.WEB_SEARCH,
        enabled=True,
        options={"provider": "tavily"},
        new_credentials=[],
        clear_credential_ids=[],
    )

    assert updated.enabled is True
    assert updated.options == {"provider": "tavily"}
    assert pool.transaction_entries == 1


@pytest.mark.asyncio
async def test_update_source_uses_acquired_connection_transaction() -> None:
    pool = AcquireTransactionalFakePool(
        settings=[
            _setting_row(
                LiteratureSource.WEB_SEARCH,
                enabled=False,
                options_json={"provider": "exa"},
            )
        ]
    )
    repo = LiteratureSettingsRepository(pool_getter=lambda: pool)

    updated = await repo.update_source(
        LiteratureSource.WEB_SEARCH,
        enabled=True,
        options={"provider": "tavily"},
        new_credentials=[],
        clear_credential_ids=[],
    )

    assert updated.enabled is True
    assert updated.options == {"provider": "tavily"}
    assert pool.acquire_entries == 1
    assert pool.transaction_entries == 1


@pytest.mark.asyncio
async def test_update_source_options_none_and_empty_dict_preserve_existing() -> None:
    pool = FakePool(
        settings=[
            _setting_row(
                LiteratureSource.WEB_SEARCH,
                enabled=True,
                options_json={"provider": "tavily", "limit": 5},
            )
        ]
    )
    repo = LiteratureSettingsRepository(pool_getter=lambda: pool)

    preserved = await repo.update_source(
        LiteratureSource.WEB_SEARCH,
        enabled=False,
        options=None,
        new_credentials=[],
        clear_credential_ids=[],
    )
    cleared = await repo.update_source(
        LiteratureSource.WEB_SEARCH,
        enabled=False,
        options={},
        new_credentials=[],
        clear_credential_ids=[],
    )

    assert preserved.options == {"provider": "tavily", "limit": 5}
    assert cleared.options == {"provider": "tavily", "limit": 5}
    settings_writes = [
        args
        for sql, args in pool.fetchrow_calls
        if "INSERT INTO literature_source_settings" in sql
    ]
    assert settings_writes[0][3] == {"provider": "tavily", "limit": 5}
    assert settings_writes[1][3] == {"provider": "tavily", "limit": 5}
    assert isinstance(settings_writes[0][2], bool)
    assert isinstance(UUID(str(settings_writes[0][0])), UUID)


@pytest.mark.asyncio
async def test_record_source_test_redacts_exact_env_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("S2_API_KEY", "s2-secret-key-123456")
    pool = FakePool(
        settings=[
            _setting_row(
                LiteratureSource.SEMANTIC_SCHOLAR,
                enabled=True,
            )
        ]
    )
    repo = LiteratureSettingsRepository(pool_getter=lambda: pool)

    settings = await repo.record_source_test(
        LiteratureSource.SEMANTIC_SCHOLAR,
        status="error",
        error="provider echoed s2-secret-key-123456",
    )

    assert settings.last_test_error == "provider echoed [redacted]"
    update_args = [
        args
        for sql, args in pool.fetchrow_calls
        if "UPDATE literature_source_settings" in sql
    ][0]
    assert update_args[3] == "provider echoed [redacted]"
    assert "s2-secret-key-123456" not in repr(pool.fetchrow_calls)


@pytest.mark.asyncio
async def test_record_source_test_redacts_exact_db_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    decrypt_calls: list[str] = []

    def fake_decrypt(secret: str | None) -> str | None:
        assert secret is not None
        decrypt_calls.append(secret)
        return "db-secret-key"

    monkeypatch.setattr(literature_settings, "decrypt_api_key", fake_decrypt)
    pool = FakePool(
        settings=[
            _setting_row(
                LiteratureSource.SEMANTIC_SCHOLAR,
                enabled=True,
            )
        ],
        credentials=[
            _credential_row(
                LiteratureSource.SEMANTIC_SCHOLAR,
                secret_encrypted="encrypted-db-secret",
                secret_preview="db-s****-key",
            )
        ],
    )
    repo = LiteratureSettingsRepository(pool_getter=lambda: pool)

    settings = await repo.record_source_test(
        LiteratureSource.SEMANTIC_SCHOLAR,
        status="error",
        error="provider echoed db-secret-key",
    )

    assert settings.last_test_error == "provider echoed [redacted]"
    update_args = [
        args
        for sql, args in pool.fetchrow_calls
        if "UPDATE literature_source_settings" in sql
    ][0]
    assert update_args[3] == "provider echoed [redacted]"
    assert "db-secret-key" not in update_args[3]
    assert decrypt_calls == ["encrypted-db-secret"]


@pytest.mark.asyncio
async def test_record_source_test_success_does_not_decrypt_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    decrypt_calls: list[str] = []

    def fake_decrypt(secret: str | None) -> str | None:
        assert secret is not None
        decrypt_calls.append(secret)
        return "db-secret-key-123456"

    monkeypatch.setattr(literature_settings, "decrypt_api_key", fake_decrypt)
    pool = FakePool(
        settings=[
            _setting_row(
                LiteratureSource.SEMANTIC_SCHOLAR,
                enabled=True,
            )
        ],
        credentials=[
            _credential_row(
                LiteratureSource.SEMANTIC_SCHOLAR,
                secret_encrypted="encrypted-db-secret",
                secret_preview="db-s****3456",
            )
        ],
    )
    repo = LiteratureSettingsRepository(pool_getter=lambda: pool)

    settings = await repo.record_source_test(
        LiteratureSource.SEMANTIC_SCHOLAR,
        status="ok",
        error=None,
    )

    assert settings.last_test_status == "ok"
    assert settings.last_test_error is None
    assert decrypt_calls == []
