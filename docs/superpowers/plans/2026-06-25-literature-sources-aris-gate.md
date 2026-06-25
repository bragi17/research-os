# Literature Sources and ARIS Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add configurable literature retrieval sources, multi-key rate-limited search, and an ARIS-style retrieval gate so failed search is never treated as novelty evidence.

**Architecture:** Add database-backed literature source settings, a per-provider key pool, normalized source adapters, and a coordinator that returns candidates plus a source contribution report. Keep the existing worker API shape compatible by making `search_academic_sources()` delegate to the coordinator while optionally returning the new report to callers that need gate decisions.

**Tech Stack:** Python 3.10, FastAPI, asyncpg, Pydantic v2, httpx, pytest, Next.js 15, React 19, TypeScript, Tailwind, lucide-react.

---

## File Structure

- Create `scripts/migration/013_literature_source_settings.sql` for source settings and encrypted credentials.
- Modify `infra/docker/docker-compose.yml` so fresh Docker databases include migration 013.
- Modify `tests/production/test_docker_compose.py` to assert migration 013 is mounted after migration 012.
- Create `libs/schemas/literature.py` for source settings, candidates, errors, and reports.
- Create `services/literature_settings.py` for database-backed source configuration and env fallback.
- Create `services/source_key_pool.py` for multi-key rotation, per-key rate limiting, cooldown, and failure classification.
- Create `services/literature_errors.py` for normalized source errors used by adapters and the gate.
- Modify `libs/adapters/semantic_scholar.py` to default to `burst_capacity=1`, raise classified errors, and respect `Retry-After`.
- Modify `libs/adapters/openalex.py` to lower default rate, retry 429/5xx, include polite-pool mailto, and raise classified errors.
- Create `services/literature_sources/base.py` for the source adapter protocol and normalizers.
- Create `services/literature_sources/local_library.py` for Research OS library table search.
- Create `services/literature_sources/zotero.py` for local Zotero JSON and BibTeX export parsing.
- Create `services/literature_sources/obsidian.py` for Markdown vault scanning.
- Create `services/literature_sources/web_search.py` for provider-backed web search.
- Create `services/literature_sources/semantic_scholar.py` for multi-key S2 search.
- Create `services/literature_sources/openalex.py` for OpenAlex work search.
- Create `services/literature_sources/deepxiv.py` for optional configured DeepXiv command search.
- Create `services/literature_search.py` for source orchestration, dedupe, and ARIS gate decisions.
- Modify `apps/api/routes_settings.py` to expose literature source settings and source test endpoints.
- Modify `apps/web/src/features/settings/types.ts` for literature source types.
- Modify `apps/web/src/features/settings/metadata.ts` to describe the new category.
- Create `apps/web/src/features/settings/LiteratureSourcesPanel.tsx` for the source settings UI.
- Modify `apps/web/src/features/settings/SettingsCategoryCard.tsx` to route the new category to `LiteratureSourcesPanel`.
- Modify `apps/web/src/app/settings/page.tsx` to load, edit, save, test, and clear literature source settings.
- Modify `apps/worker/modes/base.py` to delegate academic search to the coordinator and use configured S2 keys in verification fallback.
- Modify `apps/worker/modes/divergent.py` to honor `pass`, `warn`, `pending`, and `blocked` gate reports in prior-art checking.
- Add `tests/test_literature_settings.py`.
- Add `tests/test_source_key_pool.py`.
- Add `tests/test_academic_adapter_errors.py`.
- Add `tests/test_literature_sources.py`.
- Add `tests/test_literature_search_gate.py`.
- Add `tests/test_routes_settings_literature.py`.
- Extend `tests/test_divergent_prior_art_verification.py`.

## Task 1: Create Worktree And Baseline

**Files:**
- No source files changed in this task.

- [ ] **Step 1: Create the feature worktree**

Run from `/root/research-os`:

```bash
git worktree add .worktrees/literature-sources-aris-gate -b feat/literature-sources-aris-gate main
cd .worktrees/literature-sources-aris-gate
```

Expected: the worktree exists at `.worktrees/literature-sources-aris-gate` and `git branch --show-current` prints `feat/literature-sources-aris-gate`.

- [ ] **Step 2: Run focused backend baseline tests**

Run:

```bash
PYTHONPATH=. pytest \
  tests/test_routes_settings_llm.py \
  tests/test_llm_settings.py \
  tests/test_paper_verification.py \
  tests/test_divergent_prior_art_verification.py \
  tests/production/test_docker_compose.py \
  -q
```

Expected: tests pass. If a test fails before changes, capture the failure text in the task notes before editing.

- [ ] **Step 3: Run focused frontend baseline build**

Run:

```bash
cd apps/web
npm run build
cd ../..
```

Expected: `next build` completes. If it fails before changes, capture the exact error before editing.

## Task 2: Add Literature Settings Migration And Schemas

**Files:**
- Create: `scripts/migration/013_literature_source_settings.sql`
- Modify: `infra/docker/docker-compose.yml`
- Modify: `tests/production/test_docker_compose.py`
- Create: `libs/schemas/literature.py`

- [ ] **Step 1: Write the failing Docker migration test**

Modify `tests/production/test_docker_compose.py` so `expected_migrations` includes this entry after migration 012:

```python
"../../scripts/migration/013_literature_source_settings.sql:/docker-entrypoint-initdb.d/013_literature_source_settings.sql",
```

Run:

```bash
PYTHONPATH=. pytest tests/production/test_docker_compose.py -q
```

Expected: FAIL because `infra/docker/docker-compose.yml` does not mount migration 013.

- [ ] **Step 2: Add migration 013**

Create `scripts/migration/013_literature_source_settings.sql`:

```sql
-- Literature source settings and multi-key credential storage.

CREATE TABLE IF NOT EXISTS literature_source_settings (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    workspace_id UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000000',
    source TEXT NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    options_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_test_status TEXT,
    last_test_error TEXT,
    last_test_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT literature_source_settings_source_check CHECK (
        source IN (
            'local_library',
            'zotero',
            'obsidian',
            'web_search',
            'semantic_scholar',
            'openalex',
            'deepxiv'
        )
    ),
    CONSTRAINT literature_source_settings_options_object_check
        CHECK (jsonb_typeof(options_json) = 'object'),
    CONSTRAINT literature_source_settings_test_status_check CHECK (
        last_test_status IS NULL OR last_test_status IN ('ok', 'error')
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_literature_source_settings_workspace_source
    ON literature_source_settings (workspace_id, source);

CREATE TABLE IF NOT EXISTS literature_source_credentials (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    workspace_id UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000000',
    source TEXT NOT NULL,
    label TEXT NOT NULL DEFAULT 'primary',
    secret_encrypted TEXT NOT NULL,
    secret_preview TEXT NOT NULL DEFAULT '',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    last_status TEXT,
    last_error TEXT,
    last_used_at TIMESTAMPTZ,
    cooldown_until TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT literature_source_credentials_source_check CHECK (
        source IN ('web_search', 'semantic_scholar', 'openalex')
    ),
    CONSTRAINT literature_source_credentials_status_check CHECK (
        last_status IS NULL OR last_status IN ('ok', 'rate_limited', 'credential_error', 'error')
    )
);

CREATE INDEX IF NOT EXISTS idx_literature_source_credentials_workspace_source
    ON literature_source_credentials (workspace_id, source)
    WHERE is_active;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgname = 'update_literature_source_settings_updated'
    ) THEN
        CREATE TRIGGER update_literature_source_settings_updated
            BEFORE UPDATE ON literature_source_settings
            FOR EACH ROW EXECUTE FUNCTION update_updated_at();
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgname = 'update_literature_source_credentials_updated'
    ) THEN
        CREATE TRIGGER update_literature_source_credentials_updated
            BEFORE UPDATE ON literature_source_credentials
            FOR EACH ROW EXECUTE FUNCTION update_updated_at();
    END IF;
END;
$$;
```

- [ ] **Step 3: Mount migration 013 in Docker Compose**

Modify the `postgres.volumes` list in `infra/docker/docker-compose.yml` and add this line after migration 012:

```yaml
      - ../../scripts/migration/013_literature_source_settings.sql:/docker-entrypoint-initdb.d/013_literature_source_settings.sql
```

Run:

```bash
PYTHONPATH=. pytest tests/production/test_docker_compose.py -q
```

Expected: PASS.

- [ ] **Step 4: Add literature schemas**

Create `libs/schemas/literature.py`:

```python
"""Literature source settings and search schemas."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, SecretStr


class LiteratureSource(str, Enum):
    LOCAL_LIBRARY = "local_library"
    ZOTERO = "zotero"
    OBSIDIAN = "obsidian"
    WEB_SEARCH = "web_search"
    SEMANTIC_SCHOLAR = "semantic_scholar"
    OPENALEX = "openalex"
    DEEPXIV = "deepxiv"


class LiteratureErrorKind(str, Enum):
    CREDENTIAL_ERROR = "credential_error"
    RATE_LIMITED = "rate_limited"
    TRANSIENT_ERROR = "transient_error"
    CONFIGURATION_ERROR = "configuration_error"
    UNAVAILABLE = "unavailable"


class LiteratureGateStatus(str, Enum):
    PASS = "pass"
    WARN = "warn"
    PENDING = "pending"
    BLOCKED = "blocked"


class LiteratureCredentialPreview(BaseModel):
    id: UUID | None = None
    label: str = "primary"
    preview: str = ""
    is_active: bool = True
    last_status: Literal["ok", "rate_limited", "credential_error", "error"] | None = None
    last_error: str | None = None
    last_used_at: datetime | None = None
    cooldown_until: datetime | None = None


class LiteratureSourceSettings(BaseModel):
    source: LiteratureSource
    label: str
    enabled: bool = False
    configured: bool = False
    options: dict[str, Any] = Field(default_factory=dict)
    credentials: list[LiteratureCredentialPreview] = Field(default_factory=list)
    last_test_status: Literal["ok", "error"] | None = None
    last_test_error: str | None = None
    last_test_at: datetime | None = None


class LiteratureSourceUpdate(BaseModel):
    enabled: bool | None = None
    options: dict[str, Any] | None = None
    new_credentials: list[SecretStr] = Field(default_factory=list)
    clear_credential_ids: list[UUID] = Field(default_factory=list)


class LiteratureCandidate(BaseModel):
    candidate_id: str
    title: str
    source: LiteratureSource
    doi: str | None = None
    arxiv_id: str | None = None
    s2_id: str | None = None
    openalex_id: str | None = None
    url: str | None = None
    abstract: str | None = None
    year: int | None = None
    venue: str | None = None
    authors: list[str] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)


class LiteratureSourceError(BaseModel):
    source: LiteratureSource
    kind: LiteratureErrorKind
    message: str
    query: str | None = None
    status_code: int | None = None
    retry_after_seconds: float | None = None


class LiteratureSearchReport(BaseModel):
    requested_sources: list[LiteratureSource] = Field(default_factory=list)
    enabled_sources: list[LiteratureSource] = Field(default_factory=list)
    contributing_sources: list[LiteratureSource] = Field(default_factory=list)
    contribution_counts: dict[str, int] = Field(default_factory=dict)
    source_errors: list[LiteratureSourceError] = Field(default_factory=list)
    unavailable_sources: dict[str, str] = Field(default_factory=dict)
    candidate_count: int = 0
    gate_status: LiteratureGateStatus
```

- [ ] **Step 5: Commit migration and schema**

Run:

```bash
git add scripts/migration/013_literature_source_settings.sql infra/docker/docker-compose.yml tests/production/test_docker_compose.py libs/schemas/literature.py
git commit -m "feat: add literature source settings schema"
```

Expected: commit succeeds.

## Task 3: Add Literature Settings Repository

**Files:**
- Create: `services/literature_settings.py`
- Add: `tests/test_literature_settings.py`

- [ ] **Step 1: Write failing repository tests**

Create `tests/test_literature_settings.py` with these tests:

```python
from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import uuid4

import pytest

from libs.schemas.literature import LiteratureSource
from services.literature_settings import LiteratureSettingsRepository
from services.llm_settings import encrypt_api_key


class FakePool:
    def __init__(self, handler: Callable[[str, tuple[Any, ...]], Any]):
        self.handler = handler
        self.fetch_calls: list[tuple[str, tuple[Any, ...]]] = []
        self.fetchrow_calls: list[tuple[str, tuple[Any, ...]]] = []
        self.execute_calls: list[tuple[str, tuple[Any, ...]]] = []

    async def fetch(self, sql: str, *args: Any) -> list[dict[str, Any]]:
        self.fetch_calls.append((sql, args))
        return self.handler(sql, args) or []

    async def fetchrow(self, sql: str, *args: Any) -> dict[str, Any] | None:
        self.fetchrow_calls.append((sql, args))
        return self.handler(sql, args)

    async def execute(self, sql: str, *args: Any) -> str:
        self.execute_calls.append((sql, args))
        self.handler(sql, args)
        return "UPDATE 1"


def _settings_row(source: str, enabled: bool = True, options: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "source": source,
        "enabled": enabled,
        "options_json": options or {},
        "last_test_status": None,
        "last_test_error": None,
        "last_test_at": None,
    }


def _credential_row(secret: str = "secret-key") -> dict[str, Any]:
    return {
        "id": uuid4(),
        "source": "semantic_scholar",
        "label": "primary",
        "secret_encrypted": encrypt_api_key(secret),
        "secret_preview": "secr****-key",
        "is_active": True,
        "last_status": None,
        "last_error": None,
        "last_used_at": None,
        "cooldown_until": None,
    }


@pytest.mark.asyncio
async def test_list_sources_bootstraps_env_without_plaintext(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", "unit-test-encryption-secret")
    monkeypatch.setenv("S2_API_KEY", "semantic-secret-key")
    monkeypatch.setenv("OPENALEX_EMAIL", "user@example.com")

    def handler(sql: str, args: tuple[Any, ...]) -> Any:
        if "FROM literature_source_settings" in sql:
            return []
        if "FROM literature_source_credentials" in sql:
            return []
        return None

    repo = LiteratureSettingsRepository(pool_getter=lambda: FakePool(handler))

    sources = await repo.list_sources(include_secrets=False)
    serialized = [source.model_dump(mode="json") for source in sources]
    s2 = next(source for source in sources if source.source == LiteratureSource.SEMANTIC_SCHOLAR)
    openalex = next(source for source in sources if source.source == LiteratureSource.OPENALEX)

    assert s2.enabled is True
    assert s2.configured is True
    assert s2.credentials[0].preview == "sema****-key"
    assert openalex.enabled is True
    assert openalex.options["email"] == "user@example.com"
    assert "semantic-secret-key" not in str(serialized)


@pytest.mark.asyncio
async def test_get_active_credentials_decrypts_only_when_requested(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", "unit-test-encryption-secret")
    rows = [_credential_row("semantic-secret-key")]

    def handler(sql: str, args: tuple[Any, ...]) -> Any:
        if "FROM literature_source_credentials" in sql:
            return rows
        return []

    repo = LiteratureSettingsRepository(pool_getter=lambda: FakePool(handler))

    credentials = await repo.get_active_credentials(LiteratureSource.SEMANTIC_SCHOLAR)

    assert credentials[0].secret == "semantic-secret-key"
    assert credentials[0].preview == "secr****-key"


@pytest.mark.asyncio
async def test_update_source_replaces_requested_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", "unit-test-encryption-secret")
    calls: list[tuple[str, tuple[Any, ...]]] = []

    def handler(sql: str, args: tuple[Any, ...]) -> Any:
        calls.append((sql, args))
        if "RETURNING *" in sql and "literature_source_settings" in sql:
            return _settings_row("semantic_scholar", enabled=True)
        if "FROM literature_source_settings" in sql:
            return [_settings_row("semantic_scholar", enabled=True)]
        if "FROM literature_source_credentials" in sql:
            return []
        return None

    repo = LiteratureSettingsRepository(pool_getter=lambda: FakePool(handler))

    updated = await repo.update_source(
        LiteratureSource.SEMANTIC_SCHOLAR,
        enabled=True,
        options={},
        new_credentials=["new-semantic-key"],
        clear_credential_ids=[],
    )

    assert updated.enabled is True
    assert any("INSERT INTO literature_source_credentials" in sql for sql, _ in calls)
    assert "new-semantic-key" not in str(calls)
```

Run:

```bash
PYTHONPATH=. pytest tests/test_literature_settings.py -q
```

Expected: FAIL because `services.literature_settings` does not exist.

- [ ] **Step 2: Implement repository types and env fallback**

Create `services/literature_settings.py` with:

```python
"""Database-backed literature source settings."""

from __future__ import annotations

import inspect
import os
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import orjson

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

SOURCE_LABELS = {
    LiteratureSource.LOCAL_LIBRARY: "Local Library",
    LiteratureSource.ZOTERO: "Zotero",
    LiteratureSource.OBSIDIAN: "Obsidian",
    LiteratureSource.WEB_SEARCH: "WebSearch",
    LiteratureSource.SEMANTIC_SCHOLAR: "Semantic Scholar",
    LiteratureSource.OPENALEX: "OpenAlex",
    LiteratureSource.DEEPXIV: "DeepXiv",
}

DEFAULT_ENABLED = {
    LiteratureSource.LOCAL_LIBRARY: True,
    LiteratureSource.ZOTERO: False,
    LiteratureSource.OBSIDIAN: False,
    LiteratureSource.WEB_SEARCH: False,
    LiteratureSource.SEMANTIC_SCHOLAR: False,
    LiteratureSource.OPENALEX: False,
    LiteratureSource.DEEPXIV: False,
}


@dataclass(frozen=True)
class LiteratureCredentialSecret:
    id: str | None
    source: LiteratureSource
    label: str
    secret: str
    preview: str
    cooldown_until: Any | None = None


class LiteratureSettingsRepository:
    def __init__(self, pool_getter: Any | None = None) -> None:
        self._pool_getter = pool_getter

    async def list_sources(self, include_secrets: bool = False) -> list[LiteratureSourceSettings]:
        settings_rows = await self._fetch_settings_rows()
        credential_rows = await self._fetch_credential_rows()
        settings_by_source = {LiteratureSource(row["source"]): row for row in settings_rows}
        credentials_by_source: dict[LiteratureSource, list[dict[str, Any]]] = {}
        for row in credential_rows:
            credentials_by_source.setdefault(LiteratureSource(row["source"]), []).append(row)

        result: list[LiteratureSourceSettings] = []
        for source in LiteratureSource:
            row = settings_by_source.get(source)
            options = dict(row.get("options_json") or {}) if row else self._env_options(source)
            credentials = [
                self._credential_preview(credential)
                for credential in credentials_by_source.get(source, [])
            ]
            credentials.extend(self._env_credential_previews(source, bool(credentials)))
            enabled = bool(row["enabled"]) if row else self._default_enabled(source, options, credentials)
            configured = self._configured(source, options, credentials)
            result.append(
                LiteratureSourceSettings(
                    source=source,
                    label=SOURCE_LABELS[source],
                    enabled=enabled,
                    configured=configured,
                    options=options,
                    credentials=credentials,
                    last_test_status=row.get("last_test_status") if row else None,
                    last_test_error=redact_secret_text(row.get("last_test_error")) if row else None,
                    last_test_at=row.get("last_test_at") if row else None,
                )
            )
        return result

    async def get_active_credentials(self, source: LiteratureSource) -> list[LiteratureCredentialSecret]:
        rows = await self._fetch_credential_rows(source)
        secrets = [
            LiteratureCredentialSecret(
                id=str(row["id"]),
                source=source,
                label=row.get("label") or "primary",
                secret=decrypt_api_key(row["secret_encrypted"]) or "",
                preview=row.get("secret_preview") or "",
                cooldown_until=row.get("cooldown_until"),
            )
            for row in rows
            if row.get("secret_encrypted")
        ]
        if not secrets:
            env_secret = self._env_secret(source)
            if env_secret:
                secrets.append(
                    LiteratureCredentialSecret(
                        id=None,
                        source=source,
                        label="env",
                        secret=env_secret,
                        preview=mask_api_key(env_secret),
                    )
                )
        return secrets

    async def update_source(
        self,
        source: LiteratureSource,
        *,
        enabled: bool | None,
        options: dict[str, Any] | None,
        new_credentials: list[str],
        clear_credential_ids: list[str],
    ) -> LiteratureSourceSettings:
        pool = await self._get_pool()
        current = await self.get_source(source)
        next_options = dict(current.options)
        if options is not None:
            next_options.update(options)
        row = await pool.fetchrow(
            """
            INSERT INTO literature_source_settings (
                workspace_id, source, enabled, options_json
            ) VALUES ($1, $2, $3, $4)
            ON CONFLICT (workspace_id, source)
            DO UPDATE SET
                enabled = EXCLUDED.enabled,
                options_json = EXCLUDED.options_json,
                updated_at = NOW()
            RETURNING *
            """,
            DEFAULT_WORKSPACE_ID,
            source.value,
            current.enabled if enabled is None else enabled,
            orjson.loads(orjson.dumps(next_options)),
        )
        for credential_id in clear_credential_ids:
            await pool.execute(
                """
                UPDATE literature_source_credentials
                SET is_active = FALSE, updated_at = NOW()
                WHERE workspace_id = $1 AND id = $2
                """,
                DEFAULT_WORKSPACE_ID,
                UUID(str(credential_id)),
            )
        for index, secret in enumerate([item.strip() for item in new_credentials if item.strip()]):
            encrypted = encrypt_api_key(secret)
            await pool.execute(
                """
                INSERT INTO literature_source_credentials (
                    workspace_id, source, label, secret_encrypted, secret_preview, is_active
                ) VALUES ($1, $2, $3, $4, $5, TRUE)
                """,
                DEFAULT_WORKSPACE_ID,
                source.value,
                f"key-{index + 1}",
                encrypted,
                mask_api_key(secret),
            )
        return await self.get_source(source, row=dict(row) if row else None)

    async def get_source(
        self,
        source: LiteratureSource,
        row: dict[str, Any] | None = None,
    ) -> LiteratureSourceSettings:
        sources = await self.list_sources(include_secrets=False)
        for item in sources:
            if item.source == source:
                if row is None:
                    return item
                return item.model_copy(
                    update={
                        "enabled": bool(row.get("enabled")),
                        "options": dict(row.get("options_json") or {}),
                    }
                )
        raise ValueError(f"Unknown literature source: {source}")

    async def record_source_test(
        self,
        source: LiteratureSource,
        status: str,
        error: str | None,
    ) -> None:
        pool = await self._get_pool()
        await pool.execute(
            """
            INSERT INTO literature_source_settings (
                workspace_id, source, enabled, options_json, last_test_status,
                last_test_error, last_test_at
            ) VALUES ($1, $2, FALSE, '{}'::jsonb, $3, $4, NOW())
            ON CONFLICT (workspace_id, source)
            DO UPDATE SET
                last_test_status = EXCLUDED.last_test_status,
                last_test_error = EXCLUDED.last_test_error,
                last_test_at = NOW(),
                updated_at = NOW()
            """,
            DEFAULT_WORKSPACE_ID,
            source.value,
            status,
            redact_secret_text(error) if error else None,
        )

    async def _fetch_settings_rows(self) -> list[dict[str, Any]]:
        pool = await self._get_pool()
        rows = await pool.fetch(
            """
            SELECT * FROM literature_source_settings
            WHERE workspace_id = $1
            ORDER BY source
            """,
            DEFAULT_WORKSPACE_ID,
        )
        return [record_to_dict(row) for row in rows]

    async def _fetch_credential_rows(
        self,
        source: LiteratureSource | None = None,
    ) -> list[dict[str, Any]]:
        pool = await self._get_pool()
        if source is None:
            rows = await pool.fetch(
                """
                SELECT * FROM literature_source_credentials
                WHERE workspace_id = $1 AND is_active
                ORDER BY source, created_at ASC
                """,
                DEFAULT_WORKSPACE_ID,
            )
        else:
            rows = await pool.fetch(
                """
                SELECT * FROM literature_source_credentials
                WHERE workspace_id = $1 AND source = $2 AND is_active
                ORDER BY created_at ASC
                """,
                DEFAULT_WORKSPACE_ID,
                source.value,
            )
        return [record_to_dict(row) for row in rows]

    async def _get_pool(self) -> Any:
        if self._pool_getter is not None:
            pool = self._pool_getter()
            if inspect.isawaitable(pool):
                return await pool
            return pool
        from apps.api.database import get_pool

        return await get_pool()

    def _default_enabled(
        self,
        source: LiteratureSource,
        options: dict[str, Any],
        credentials: list[LiteratureCredentialPreview],
    ) -> bool:
        if source in (LiteratureSource.SEMANTIC_SCHOLAR, LiteratureSource.WEB_SEARCH):
            return bool(credentials)
        if source == LiteratureSource.OPENALEX:
            return bool(options.get("email") or credentials)
        return DEFAULT_ENABLED[source]

    def _configured(
        self,
        source: LiteratureSource,
        options: dict[str, Any],
        credentials: list[LiteratureCredentialPreview],
    ) -> bool:
        if source == LiteratureSource.LOCAL_LIBRARY:
            return True
        if source in (LiteratureSource.SEMANTIC_SCHOLAR, LiteratureSource.WEB_SEARCH):
            return bool(credentials)
        if source == LiteratureSource.OPENALEX:
            return bool(options.get("email") or credentials)
        if source in (LiteratureSource.ZOTERO, LiteratureSource.OBSIDIAN):
            return bool(options.get("path"))
        if source == LiteratureSource.DEEPXIV:
            return bool(options.get("command"))
        return False

    def _credential_preview(self, row: dict[str, Any]) -> LiteratureCredentialPreview:
        return LiteratureCredentialPreview(
            id=row.get("id"),
            label=row.get("label") or "primary",
            preview=row.get("secret_preview") or "",
            is_active=bool(row.get("is_active", True)),
            last_status=row.get("last_status"),
            last_error=redact_secret_text(row.get("last_error")),
            last_used_at=row.get("last_used_at"),
            cooldown_until=row.get("cooldown_until"),
        )

    def _env_options(self, source: LiteratureSource) -> dict[str, Any]:
        if source == LiteratureSource.OPENALEX:
            return {"email": os.getenv("OPENALEX_EMAIL", "")}
        if source == LiteratureSource.ZOTERO:
            return {"path": os.getenv("ZOTERO_LIBRARY_PATH", "")}
        if source == LiteratureSource.OBSIDIAN:
            return {"path": os.getenv("OBSIDIAN_VAULT_PATH", "")}
        if source == LiteratureSource.WEB_SEARCH:
            return {"provider": os.getenv("WEB_SEARCH_PROVIDER", "")}
        if source == LiteratureSource.DEEPXIV:
            return {"command": os.getenv("DEEPXIV_COMMAND", "")}
        return {}

    def _env_secret(self, source: LiteratureSource) -> str:
        if source == LiteratureSource.SEMANTIC_SCHOLAR:
            return os.getenv("SEMANTIC_SCHOLAR_API_KEY") or os.getenv("S2_API_KEY", "")
        if source == LiteratureSource.OPENALEX:
            return os.getenv("OPENALEX_API_KEY", "")
        if source == LiteratureSource.WEB_SEARCH:
            return os.getenv("WEB_SEARCH_API_KEY", "")
        return ""

    def _env_credential_previews(
        self,
        source: LiteratureSource,
        has_db_credentials: bool,
    ) -> list[LiteratureCredentialPreview]:
        if has_db_credentials:
            return []
        secret = self._env_secret(source)
        if not secret:
            return []
        return [
            LiteratureCredentialPreview(
                id=None,
                label="env",
                preview=mask_api_key(secret),
                is_active=True,
            )
        ]
```

- [ ] **Step 3: Run repository tests**

Run:

```bash
PYTHONPATH=. pytest tests/test_literature_settings.py -q
```

Expected: PASS.

- [ ] **Step 4: Commit repository**

Run:

```bash
git add services/literature_settings.py tests/test_literature_settings.py
git commit -m "feat: add literature source settings repository"
```

Expected: commit succeeds.

## Task 4: Add Multi-Key Pool And Classified Adapter Errors

**Files:**
- Create: `services/source_key_pool.py`
- Create: `services/literature_errors.py`
- Modify: `libs/adapters/semantic_scholar.py`
- Modify: `libs/adapters/openalex.py`
- Add: `tests/test_source_key_pool.py`
- Add: `tests/test_academic_adapter_errors.py`

- [ ] **Step 1: Write failing key pool tests**

Create `tests/test_source_key_pool.py`:

```python
from __future__ import annotations

import pytest

from services.source_key_pool import KeyMaterial, SourceKeyPool


@pytest.mark.asyncio
async def test_key_pool_rotates_available_keys_without_reusing_first_key() -> None:
    pool = SourceKeyPool(
        [
            KeyMaterial(id="a", secret="key-a", preview="key****y-a"),
            KeyMaterial(id="b", secret="key-b", preview="key****y-b"),
            KeyMaterial(id="c", secret="key-c", preview="key****y-c"),
        ],
        requests_per_second=1000.0,
        burst_capacity=1,
    )

    first = await pool.acquire()
    second = await pool.acquire()
    third = await pool.acquire()

    assert [first.secret, second.secret, third.secret] == ["key-a", "key-b", "key-c"]


@pytest.mark.asyncio
async def test_key_pool_cools_down_only_rate_limited_key() -> None:
    now = 100.0

    async def fake_sleep(seconds: float) -> None:
        nonlocal now
        now += seconds

    pool = SourceKeyPool(
        [
            KeyMaterial(id="a", secret="key-a", preview="key****y-a"),
            KeyMaterial(id="b", secret="key-b", preview="key****y-b"),
        ],
        requests_per_second=1000.0,
        burst_capacity=1,
        now=lambda: now,
        sleep=fake_sleep,
    )

    first = await pool.acquire()
    pool.record_rate_limit(first, retry_after_seconds=30.0)
    second = await pool.acquire()

    assert second.secret == "key-b"
```

Run:

```bash
PYTHONPATH=. pytest tests/test_source_key_pool.py -q
```

Expected: FAIL because `services.source_key_pool` does not exist.

- [ ] **Step 2: Add normalized error classes**

Create `services/literature_errors.py`:

```python
"""Normalized literature retrieval errors."""

from __future__ import annotations

from dataclasses import dataclass

from libs.schemas.literature import LiteratureErrorKind, LiteratureSource, LiteratureSourceError


@dataclass
class SourceRequestError(Exception):
    source: LiteratureSource
    kind: LiteratureErrorKind
    message: str
    status_code: int | None = None
    retry_after_seconds: float | None = None

    def __str__(self) -> str:
        return self.message

    def to_report_error(self, query: str | None = None) -> LiteratureSourceError:
        return LiteratureSourceError(
            source=self.source,
            kind=self.kind,
            message=self.message,
            query=query,
            status_code=self.status_code,
            retry_after_seconds=self.retry_after_seconds,
        )


def retry_after_seconds(value: str | None) -> float | None:
    if not value:
        return None
    try:
        parsed = float(value)
    except ValueError:
        return None
    return parsed if parsed >= 0 else None
```

- [ ] **Step 3: Implement key pool**

Create `services/source_key_pool.py`:

```python
"""Multi-key rotation and per-key rate limiting."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class KeyMaterial:
    id: str | None
    secret: str
    preview: str


@dataclass(frozen=True)
class KeyLease:
    id: str | None
    secret: str
    preview: str


class NoAvailableSourceKey(RuntimeError):
    pass


class _KeyState:
    def __init__(self, material: KeyMaterial, burst_capacity: int, now: Callable[[], float]) -> None:
        self.material = material
        self.tokens = float(burst_capacity)
        self.last_refill = now()
        self.cooldown_until = 0.0


class SourceKeyPool:
    def __init__(
        self,
        keys: list[KeyMaterial],
        *,
        requests_per_second: float,
        burst_capacity: int,
        now: Callable[[], float] | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        if requests_per_second <= 0:
            raise ValueError("requests_per_second must be positive")
        if burst_capacity < 1:
            raise ValueError("burst_capacity must be at least 1")
        self._now = now or time.monotonic
        self._sleep = sleep or asyncio.sleep
        self._rps = requests_per_second
        self._burst = burst_capacity
        self._states = [_KeyState(key, burst_capacity, self._now) for key in keys if key.secret]
        self._cursor = 0

    def __len__(self) -> int:
        return len(self._states)

    async def acquire(self) -> KeyLease:
        if not self._states:
            raise NoAvailableSourceKey("No active source keys are configured")

        while True:
            state = self._next_state()
            wait_seconds = self._seconds_until_available(state)
            if wait_seconds <= 0:
                self._consume(state)
                material = state.material
                return KeyLease(id=material.id, secret=material.secret, preview=material.preview)
            await self._sleep(wait_seconds)

    def record_rate_limit(self, lease: KeyLease, retry_after_seconds: float | None = None) -> None:
        state = self._find_state(lease)
        if state is None:
            return
        cooldown = retry_after_seconds if retry_after_seconds is not None else 5.0
        state.cooldown_until = max(state.cooldown_until, self._now() + cooldown)

    def record_credential_error(self, lease: KeyLease) -> None:
        state = self._find_state(lease)
        if state is None:
            return
        state.cooldown_until = float("inf")

    def _next_state(self) -> _KeyState:
        state = self._states[self._cursor % len(self._states)]
        self._cursor = (self._cursor + 1) % len(self._states)
        return state

    def _seconds_until_available(self, state: _KeyState) -> float:
        now = self._now()
        if state.cooldown_until > now:
            return state.cooldown_until - now
        elapsed = now - state.last_refill
        state.tokens = min(float(self._burst), state.tokens + elapsed * self._rps)
        state.last_refill = now
        if state.tokens >= 1:
            return 0.0
        return (1 - state.tokens) / self._rps

    def _consume(self, state: _KeyState) -> None:
        state.tokens = max(0.0, state.tokens - 1.0)

    def _find_state(self, lease: KeyLease) -> _KeyState | None:
        for state in self._states:
            if state.material.id == lease.id and state.material.secret == lease.secret:
                return state
        return None
```

- [ ] **Step 4: Write failing adapter error tests**

Create `tests/test_academic_adapter_errors.py`:

```python
from __future__ import annotations

import httpx
import pytest

from libs.adapters.openalex import OpenAlexAdapter, OpenAlexConfig
from libs.adapters.semantic_scholar import RateLimitConfig, SemanticScholarAdapter
from libs.schemas.literature import LiteratureErrorKind
from services.literature_errors import SourceRequestError


@pytest.mark.asyncio
async def test_semantic_scholar_defaults_to_one_request_burst() -> None:
    adapter = SemanticScholarAdapter(api_key="key")

    assert adapter.rate_limit.requests_per_second == 1.0
    assert adapter.rate_limit.burst_capacity == 1


@pytest.mark.asyncio
async def test_semantic_scholar_429_raises_rate_limited_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "2"}, json={"error": "slow down"})

    adapter = SemanticScholarAdapter(
        api_key="key",
        rate_limit=RateLimitConfig(retry_attempts=1, burst_capacity=1),
    )
    adapter._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://api.semanticscholar.org/graph/v1",
    )

    with pytest.raises(SourceRequestError) as excinfo:
        await adapter.search_papers("graph matching", limit=1)

    assert excinfo.value.kind == LiteratureErrorKind.RATE_LIMITED
    assert excinfo.value.status_code == 429
    assert excinfo.value.retry_after_seconds == 2.0
    await adapter.close()


@pytest.mark.asyncio
async def test_semantic_scholar_403_raises_credential_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": "forbidden"})

    adapter = SemanticScholarAdapter(
        api_key="key",
        rate_limit=RateLimitConfig(retry_attempts=1, burst_capacity=1),
    )
    adapter._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://api.semanticscholar.org/graph/v1",
    )

    with pytest.raises(SourceRequestError) as excinfo:
        await adapter.search_papers("graph matching", limit=1)

    assert excinfo.value.kind == LiteratureErrorKind.CREDENTIAL_ERROR
    assert excinfo.value.status_code == 403
    await adapter.close()


@pytest.mark.asyncio
async def test_openalex_429_raises_rate_limited_error_after_retry() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "1"}, json={"error": "slow down"})

    adapter = OpenAlexAdapter(
        email="user@example.com",
        config=OpenAlexConfig(email="user@example.com", requests_per_second=1000.0, retry_attempts=1),
    )
    adapter._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://api.openalex.org",
    )

    with pytest.raises(SourceRequestError) as excinfo:
        await adapter.search_works("graph matching", per_page=1)

    assert excinfo.value.kind == LiteratureErrorKind.RATE_LIMITED
    assert excinfo.value.status_code == 429
    await adapter.close()
```

Run:

```bash
PYTHONPATH=. pytest tests/test_source_key_pool.py tests/test_academic_adapter_errors.py -q
```

Expected: key pool tests pass and adapter tests fail until adapter changes are made.

- [ ] **Step 5: Modify Semantic Scholar adapter**

Modify `libs/adapters/semantic_scholar.py`:

- Change `RateLimitConfig.burst_capacity` from `5` to `1`.
- Import `LiteratureErrorKind`, `LiteratureSource`, `SourceRequestError`, and `retry_after_seconds`.
- In `_request_with_retry`, set `last_error` to a `SourceRequestError` for 429, 403, timeout, request error, and 5xx.
- On final failure, raise `last_error` when it is a `SourceRequestError`.

The 429 branch must become:

```python
                elif response.status_code == 429:
                    retry_after = retry_after_seconds(response.headers.get("Retry-After"))
                    delay = retry_after if retry_after is not None else min(
                        self.rate_limit.retry_base_delay * (2**attempt),
                        self.rate_limit.retry_max_delay,
                    )
                    last_error = SourceRequestError(
                        source=LiteratureSource.SEMANTIC_SCHOLAR,
                        kind=LiteratureErrorKind.RATE_LIMITED,
                        message=f"Semantic Scholar rate limited request to {url}",
                        status_code=429,
                        retry_after_seconds=retry_after,
                    )
                    logger.warning("rate_limited", attempt=attempt, delay=delay)
                    await asyncio.sleep(delay)
                    continue
```

The 403 branch must be inserted before the 404 branch:

```python
                elif response.status_code == 403:
                    raise SourceRequestError(
                        source=LiteratureSource.SEMANTIC_SCHOLAR,
                        kind=LiteratureErrorKind.CREDENTIAL_ERROR,
                        message=f"Semantic Scholar credential rejected for {url}",
                        status_code=403,
                    )
```

- [ ] **Step 6: Modify OpenAlex adapter**

Modify `libs/adapters/openalex.py`:

- Add fields to `OpenAlexConfig`:

```python
    api_key: str | None = None
    requests_per_second: float = 2.0
    retry_attempts: int = 3
    retry_base_delay: float = 1.0
    retry_max_delay: float = 30.0
```

- Include `api_key` in `OpenAlexAdapter.__init__` and headers:

```python
        api_key: str | None = None,
```

```python
        self.config = config or OpenAlexConfig(email=email, api_key=api_key)
```

```python
            if self.config.api_key:
                headers["api-key"] = self.config.api_key
```

- Rewrite `_request` to loop for `retry_attempts`, retry 429 and 5xx, and raise `SourceRequestError` for final errors.

- [ ] **Step 7: Run adapter and key pool tests**

Run:

```bash
PYTHONPATH=. pytest tests/test_source_key_pool.py tests/test_academic_adapter_errors.py -q
```

Expected: PASS.

- [ ] **Step 8: Run existing verification tests**

Run:

```bash
PYTHONPATH=. pytest tests/test_paper_verification.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit key pool and adapter errors**

Run:

```bash
git add services/source_key_pool.py services/literature_errors.py libs/adapters/semantic_scholar.py libs/adapters/openalex.py tests/test_source_key_pool.py tests/test_academic_adapter_errors.py
git commit -m "feat: add classified literature rate limiting"
```

Expected: commit succeeds.

## Task 5: Add Source Adapters And Coordinator Gate

**Files:**
- Create: `services/literature_sources/base.py`
- Create: `services/literature_sources/local_library.py`
- Create: `services/literature_sources/zotero.py`
- Create: `services/literature_sources/obsidian.py`
- Create: `services/literature_sources/web_search.py`
- Create: `services/literature_sources/semantic_scholar.py`
- Create: `services/literature_sources/openalex.py`
- Create: `services/literature_sources/deepxiv.py`
- Create: `services/literature_search.py`
- Add: `tests/test_literature_sources.py`
- Add: `tests/test_literature_search_gate.py`

- [ ] **Step 1: Write failing source normalizer tests**

Create `tests/test_literature_sources.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from libs.schemas.literature import LiteratureSource
from services.literature_sources.base import normalize_title_key
from services.literature_sources.obsidian import ObsidianSource
from services.literature_sources.zotero import ZoteroSource


def test_normalize_title_key_collapses_case_and_spacing() -> None:
    assert normalize_title_key("  A  New   Method ") == "a new method"


@pytest.mark.asyncio
async def test_zotero_source_reads_json_export(tmp_path: Path) -> None:
    export = tmp_path / "zotero.json"
    export.write_text(
        '[{"title":"Graph Matching Paper","DOI":"10.1000/graph","date":"2024","creators":[{"lastName":"Ada"}]}]',
        encoding="utf-8",
    )
    source = ZoteroSource({"path": str(export)})

    result = await source.search("graph matching")

    assert result.candidates[0].title == "Graph Matching Paper"
    assert result.candidates[0].doi == "10.1000/graph"
    assert result.candidates[0].source == LiteratureSource.ZOTERO


@pytest.mark.asyncio
async def test_obsidian_source_extracts_doi_from_markdown(tmp_path: Path) -> None:
    note = tmp_path / "paper.md"
    note.write_text(
        "---\ntitle: Obsidian Graph Paper\nyear: 2025\n---\nDOI: 10.1000/obsidian\n",
        encoding="utf-8",
    )
    source = ObsidianSource({"path": str(tmp_path)})

    result = await source.search("obsidian graph")

    assert result.candidates[0].title == "Obsidian Graph Paper"
    assert result.candidates[0].doi == "10.1000/obsidian"
    assert result.candidates[0].source == LiteratureSource.OBSIDIAN
```

Run:

```bash
PYTHONPATH=. pytest tests/test_literature_sources.py -q
```

Expected: FAIL because source modules do not exist.

- [ ] **Step 2: Add source base module**

Create `services/literature_sources/base.py`:

```python
"""Shared interfaces for literature sources."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Protocol

from libs.schemas.literature import LiteratureCandidate, LiteratureSource, LiteratureSourceError


def normalize_title_key(title: str | None) -> str:
    return " ".join((title or "").casefold().split())


def candidate_key(candidate: LiteratureCandidate) -> str:
    if candidate.doi:
        return f"doi:{candidate.doi.casefold()}"
    if candidate.arxiv_id:
        return f"arxiv:{candidate.arxiv_id.casefold()}"
    if candidate.s2_id:
        return f"s2:{candidate.s2_id}"
    if candidate.openalex_id:
        return f"openalex:{candidate.openalex_id}"
    return f"title:{normalize_title_key(candidate.title)}"


def parse_year(value: object) -> int | None:
    if value is None:
        return None
    match = re.search(r"(19|20)\\d{2}", str(value))
    return int(match.group(0)) if match else None


@dataclass
class SourceSearchResult:
    source: LiteratureSource
    candidates: list[LiteratureCandidate] = field(default_factory=list)
    errors: list[LiteratureSourceError] = field(default_factory=list)
    unavailable_reason: str | None = None


class LiteratureSourceAdapter(Protocol):
    source: LiteratureSource

    async def search(self, query: str, limit: int = 50) -> SourceSearchResult:
        ...

    async def close(self) -> None:
        ...
```

- [ ] **Step 3: Implement local file-backed sources**

Implement `ZoteroSource` and `ObsidianSource`:

- `ZoteroSource({"path": "/path/to/export.json"})` reads JSON arrays and objects with an `items` array.
- `ZoteroSource` also accepts `.bib` files and extracts `title`, `doi`, `year`, and `url` with regular expressions.
- `ObsidianSource({"path": "/path/to/vault"})` scans `*.md`, extracts YAML frontmatter `title` and `year`, DOI patterns, arXiv ids, and first heading fallback.
- Both sources filter by token overlap between query terms and title/body text.

- [ ] **Step 4: Implement local library source**

Create `services/literature_sources/local_library.py` with a `LocalLibrarySource` that uses `services.library.tools_db.list_library_papers(limit=200)` and filters in Python by query token overlap across `title`, `keywords`, `methods`, `innovation_points`, and `summary_json`.

The candidate id format must be:

```python
candidate_id=f"LOCAL:{paper['id']}"
```

- [ ] **Step 5: Implement external source wrappers**

Create these wrappers:

- `SemanticScholarSource` accepts a `SourceKeyPool`; it acquires a key for each API call and creates `SemanticScholarAdapter(api_key=lease.secret, rate_limit=RateLimitConfig(burst_capacity=1))`.
- `OpenAlexSource` accepts `email` and optional `api_key`; it uses `OpenAlexAdapter(email=email, api_key=api_key)`.
- `WebSearchSource` supports providers `tavily`, `exa`, and `serpapi` using `httpx.AsyncClient`.
- `DeepXivSource` returns unavailable unless `options["command"]` is configured; when configured, it runs the command with `--query`, `--limit`, and `--json`.

Each wrapper catches `SourceRequestError` and returns `SourceSearchResult(errors=[exc.to_report_error(query)])`.

Every wrapper must expose this constructor and method shape:

```python
class ConcreteSource:
    source: LiteratureSource

    def __init__(self, options: dict[str, object] | None = None, **dependencies: object) -> None:
        self.options = dict(options or {})

    async def search(self, query: str, limit: int = 50) -> SourceSearchResult:
        ...

    async def close(self) -> None:
        return None
```

- [ ] **Step 6: Write failing gate tests**

Create `tests/test_literature_search_gate.py`:

```python
from __future__ import annotations

import pytest

from libs.schemas.literature import (
    LiteratureCandidate,
    LiteratureErrorKind,
    LiteratureGateStatus,
    LiteratureSource,
    LiteratureSourceError,
)
from services.literature_search import LiteratureSearchCoordinator
from services.literature_sources.base import SourceSearchResult


class StubSource:
    def __init__(self, result: SourceSearchResult) -> None:
        self.source = result.source
        self.result = result

    async def search(self, query: str, limit: int = 50) -> SourceSearchResult:
        return self.result

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_gate_blocks_when_enabled_sources_fail_without_candidates() -> None:
    coordinator = LiteratureSearchCoordinator(
        sources=[
            StubSource(
                SourceSearchResult(
                    source=LiteratureSource.SEMANTIC_SCHOLAR,
                    errors=[
                        LiteratureSourceError(
                            source=LiteratureSource.SEMANTIC_SCHOLAR,
                            kind=LiteratureErrorKind.CREDENTIAL_ERROR,
                            message="forbidden",
                        )
                    ],
                )
            )
        ]
    )

    candidates, report = await coordinator.search("topic", [{"query": "topic"}])

    assert candidates == []
    assert report.gate_status == LiteratureGateStatus.BLOCKED
    assert report.contribution_counts == {"semantic_scholar": 0}


@pytest.mark.asyncio
async def test_gate_warns_when_one_source_contributes_and_another_fails() -> None:
    coordinator = LiteratureSearchCoordinator(
        sources=[
            StubSource(
                SourceSearchResult(
                    source=LiteratureSource.LOCAL_LIBRARY,
                    candidates=[
                        LiteratureCandidate(
                            candidate_id="LOCAL:1",
                            title="Local Paper",
                            source=LiteratureSource.LOCAL_LIBRARY,
                        )
                    ],
                )
            ),
            StubSource(
                SourceSearchResult(
                    source=LiteratureSource.OPENALEX,
                    errors=[
                        LiteratureSourceError(
                            source=LiteratureSource.OPENALEX,
                            kind=LiteratureErrorKind.RATE_LIMITED,
                            message="429",
                        )
                    ],
                )
            ),
        ]
    )

    candidates, report = await coordinator.search("topic", [{"query": "topic"}])

    assert [candidate.candidate_id for candidate in candidates] == ["LOCAL:1"]
    assert report.gate_status == LiteratureGateStatus.WARN
    assert report.contributing_sources == [LiteratureSource.LOCAL_LIBRARY]
```

Run:

```bash
PYTHONPATH=. pytest tests/test_literature_sources.py tests/test_literature_search_gate.py -q
```

Expected: source tests pass after local source implementations; gate tests fail until coordinator is implemented.

- [ ] **Step 7: Implement coordinator**

Create `services/literature_search.py` with:

```python
"""Coordinator for multi-source literature retrieval and ARIS gate reports."""

from __future__ import annotations

from collections.abc import Iterable

from libs.schemas.literature import (
    LiteratureCandidate,
    LiteratureErrorKind,
    LiteratureGateStatus,
    LiteratureSearchReport,
    LiteratureSource,
)
from services.literature_sources.base import LiteratureSourceAdapter, candidate_key


class LiteratureSearchCoordinator:
    def __init__(self, sources: Iterable[LiteratureSourceAdapter]) -> None:
        self.sources = list(sources)

    async def search(
        self,
        topic: str,
        queries: list[dict[str, object]],
        limit_per_query: int = 50,
    ) -> tuple[list[LiteratureCandidate], LiteratureSearchReport]:
        requested = [source.source for source in self.sources]
        candidates: list[LiteratureCandidate] = []
        seen: set[str] = set()
        errors = []
        unavailable: dict[str, str] = {}
        counts = {source.value: 0 for source in requested}

        for query_spec in queries:
            query_text = str(query_spec.get("query") or topic).strip()
            if not query_text:
                continue
            for source in self.sources:
                result = await source.search(query_text, limit=limit_per_query)
                if result.unavailable_reason:
                    unavailable[source.source.value] = result.unavailable_reason
                errors.extend(result.errors)
                for candidate in result.candidates:
                    key = candidate_key(candidate)
                    if key in seen:
                        continue
                    seen.add(key)
                    candidates.append(candidate)
                    counts[source.source.value] = counts.get(source.source.value, 0) + 1

        contributing = [
            LiteratureSource(source)
            for source, count in counts.items()
            if count > 0
        ]
        gate_status = self._gate_status(candidates, errors, unavailable)
        return candidates, LiteratureSearchReport(
            requested_sources=requested,
            enabled_sources=requested,
            contributing_sources=contributing,
            contribution_counts=counts,
            source_errors=errors,
            unavailable_sources=unavailable,
            candidate_count=len(candidates),
            gate_status=gate_status,
        )

    def _gate_status(self, candidates, errors, unavailable) -> LiteratureGateStatus:
        if candidates and errors:
            return LiteratureGateStatus.WARN
        if candidates:
            return LiteratureGateStatus.PASS
        if not errors:
            return LiteratureGateStatus.BLOCKED
        transient_kinds = {
            LiteratureErrorKind.RATE_LIMITED,
            LiteratureErrorKind.TRANSIENT_ERROR,
        }
        if all(error.kind in transient_kinds for error in errors):
            return LiteratureGateStatus.PENDING
        return LiteratureGateStatus.BLOCKED
```

- [ ] **Step 8: Run source and gate tests**

Run:

```bash
PYTHONPATH=. pytest tests/test_literature_sources.py tests/test_literature_search_gate.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit source adapters and gate**

Run:

```bash
git add services/literature_sources services/literature_search.py tests/test_literature_sources.py tests/test_literature_search_gate.py
git commit -m "feat: add literature source coordinator gate"
```

Expected: commit succeeds.

## Task 6: Add Literature Settings API

**Files:**
- Modify: `apps/api/routes_settings.py`
- Add: `tests/test_routes_settings_literature.py`

- [ ] **Step 1: Write failing API tests**

Create `tests/test_routes_settings_literature.py`:

```python
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import apps.api.routes_settings as routes_settings
from libs.schemas.literature import LiteratureSource, LiteratureSourceSettings


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


class FakeLiteratureRepository:
    def __init__(self) -> None:
        self.sources = [
            _source(LiteratureSource.LOCAL_LIBRARY),
            _source(LiteratureSource.SEMANTIC_SCHOLAR),
        ]
        self.list_sources = AsyncMock(return_value=self.sources)
        self.update_source = AsyncMock(return_value=self.sources[1])
        self.record_source_test = AsyncMock(return_value=None)


def test_get_models_includes_literature_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = FakeLiteratureRepository()
    monkeypatch.setattr(routes_settings, "LiteratureSettingsRepository", lambda: repo)
    monkeypatch.setattr(
        routes_settings,
        "LLMSettingsRepository",
        lambda: type("Repo", (), {"get_active_profile": AsyncMock(side_effect=RuntimeError("missing"))})(),
    )

    response = _client().get("/api/v1/settings/models")

    assert response.status_code == 200
    category = next(item for item in response.json()["categories"] if item["id"] == "literature_sources")
    assert category["label"] == "Literature Sources"
    assert category["sources"][0]["source"] == "local_library"
    assert "secret" not in response.text


def test_put_literature_source_updates_repository_and_redacts_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = FakeLiteratureRepository()
    monkeypatch.setattr(routes_settings, "LiteratureSettingsRepository", lambda: repo)

    response = _client().put(
        "/api/v1/settings/literature/semantic_scholar",
        json={"enabled": True, "options": {}, "new_credentials": ["secret-key"], "clear_credential_ids": []},
    )

    assert response.status_code == 200
    repo.update_source.assert_awaited_once()
    assert repo.update_source.await_args.kwargs["new_credentials"] == ["secret-key"]
    assert "secret-key" not in response.text
```

Run:

```bash
PYTHONPATH=. pytest tests/test_routes_settings_literature.py -q
```

Expected: FAIL because routes are not implemented.

- [ ] **Step 2: Extend settings routes**

Modify `apps/api/routes_settings.py`:

- Import `LiteratureSource`, `LiteratureSourceUpdate`, and `LiteratureSettingsRepository`.
- Add category id `literature_sources` after `academic`.
- Add helper:

```python
async def _literature_sources_category() -> dict[str, Any]:
    try:
        sources = await LiteratureSettingsRepository().list_sources(include_secrets=False)
    except Exception as exc:
        logger.warning("settings.literature_sources_fallback_failed", error=str(exc)[:200])
        sources = []
    return {
        "id": "literature_sources",
        "label": "Literature Sources",
        "items": [],
        "sources": [source.model_dump(mode="json") for source in sources],
    }
```

- In `get_model_settings`, append `await _literature_sources_category()` before `storage`.
- Add:

```python
@router.put("/literature/{source}")
async def update_literature_source(
    source: LiteratureSource,
    body: LiteratureSourceUpdate,
) -> dict[str, Any]:
    new_credentials = [secret.get_secret_value() for secret in body.new_credentials]
    try:
        updated = await LiteratureSettingsRepository().update_source(
            source,
            enabled=body.enabled,
            options=body.options,
            new_credentials=new_credentials,
            clear_credential_ids=[str(credential_id) for credential_id in body.clear_credential_ids],
        )
        return updated.model_dump(mode="json")
    except Exception as exc:
        error = redact_secret_text(str(exc), secrets=new_credentials)[:200]
        logger.error("settings.literature_update_failed", source=source.value, error=error)
        raise HTTPException(status_code=500, detail=error)
```

- Add a test route:

```python
@router.post("/literature/{source}/test")
async def test_literature_source(source: LiteratureSource) -> dict[str, Any]:
    try:
        settings = await LiteratureSettingsRepository().get_source(source)
        status = "ok" if settings.configured else "error"
        error = None if settings.configured else f"{source.value} is not configured"
        await LiteratureSettingsRepository().record_source_test(source, status, error)
        return {"status": status, "error": error}
    except Exception as exc:
        error = redact_secret_text(str(exc))[:200]
        await LiteratureSettingsRepository().record_source_test(source, "error", error)
        return {"status": "error", "error": error}
```

- [ ] **Step 3: Run API tests**

Run:

```bash
PYTHONPATH=. pytest tests/test_routes_settings_literature.py tests/test_routes_settings_llm.py -q
```

Expected: PASS.

- [ ] **Step 4: Commit settings API**

Run:

```bash
git add apps/api/routes_settings.py tests/test_routes_settings_literature.py
git commit -m "feat: expose literature source settings api"
```

Expected: commit succeeds.

## Task 7: Add Settings UI For Literature Sources

**Files:**
- Modify: `apps/web/src/features/settings/types.ts`
- Modify: `apps/web/src/features/settings/metadata.ts`
- Create: `apps/web/src/features/settings/LiteratureSourcesPanel.tsx`
- Modify: `apps/web/src/features/settings/SettingsCategoryCard.tsx`
- Modify: `apps/web/src/app/settings/page.tsx`

- [ ] **Step 1: Add frontend types**

Modify `apps/web/src/features/settings/types.ts`:

```typescript
export interface LiteratureCredentialPreview {
  id: string | null;
  label: string;
  preview: string;
  is_active: boolean;
  last_status: string | null;
  last_error: string | null;
  last_used_at: string | null;
  cooldown_until: string | null;
}

export interface LiteratureSourceProfile {
  source: string;
  label: string;
  enabled: boolean;
  configured: boolean;
  options: Record<string, unknown>;
  credentials: LiteratureCredentialPreview[];
  last_test_status: string | null;
  last_test_error: string | null;
  last_test_at: string | null;
}
```

Add to `Category`:

```typescript
  sources?: LiteratureSourceProfile[];
```

- [ ] **Step 2: Add category metadata and icon**

Modify `apps/web/src/features/settings/metadata.ts`:

```typescript
  literature_sources: "Configure local and external sources for prior-art retrieval.",
```

Modify `SettingsCategoryCard.tsx` imports to add `Search` from `lucide-react`, then add:

```typescript
  literature_sources: Search,
```

- [ ] **Step 3: Create literature panel**

Create `apps/web/src/features/settings/LiteratureSourcesPanel.tsx` with a compact table-like card body:

```tsx
import { Trash2 } from "lucide-react";
import type { LiteratureSourceProfile } from "./types";

interface LiteratureSourcesPanelProps {
  sources: LiteratureSourceProfile[];
  edits: Record<string, LiteratureSourceProfile>;
  saving: boolean;
  testing: string | null;
  onEdit: (source: string, value: LiteratureSourceProfile) => void;
  onSave: (source: string) => void;
  onTest: (source: string) => void;
}

function currentSource(
  source: LiteratureSourceProfile,
  edits: Record<string, LiteratureSourceProfile>,
): LiteratureSourceProfile {
  return edits[source.source] || source;
}

export function LiteratureSourcesPanel({
  sources,
  edits,
  saving,
  testing,
  onEdit,
  onSave,
  onTest,
}: LiteratureSourcesPanelProps) {
  return (
    <div className="divide-y divide-[var(--border-subtle)]">
      {sources.map((source) => {
        const draft = currentSource(source, edits);
        const nextKeys = String(draft.options.new_credentials || "");
        return (
          <div key={source.source} className="px-5 py-4 space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <div className="flex items-center gap-2">
                  <span className="text-[13px] font-semibold text-[var(--text-primary)]">
                    {source.label}
                  </span>
                  <span className={draft.configured ? "text-[11px] text-[var(--accent-green)]" : "text-[11px] text-[var(--accent-amber)]"}>
                    {draft.configured ? "configured" : "not configured"}
                  </span>
                </div>
                {source.last_test_status && (
                  <p className="mt-0.5 text-[11px] text-[var(--text-muted)]">
                    Last test: {source.last_test_status}
                    {source.last_test_error ? ` (${source.last_test_error})` : ""}
                  </p>
                )}
              </div>
              <label className="flex items-center gap-2 text-[12px] text-[var(--text-secondary)]">
                <input
                  type="checkbox"
                  checked={draft.enabled}
                  onChange={(event) => onEdit(source.source, { ...draft, enabled: event.target.checked })}
                />
                Enabled
              </label>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-[140px_1fr] gap-2 items-center">
              <span className="text-[12px] text-[var(--text-secondary)]">Options</span>
              <input
                className="input-field text-[12px] py-1.5"
                value={JSON.stringify(draft.options || {})}
                onChange={(event) => {
                  try {
                    onEdit(source.source, { ...draft, options: JSON.parse(event.target.value) });
                  } catch {
                    onEdit(source.source, { ...draft, options: { raw: event.target.value } });
                  }
                }}
              />

              <span className="text-[12px] text-[var(--text-secondary)]">API keys</span>
              <div className="space-y-2">
                <div className="flex flex-wrap gap-2">
                  {source.credentials.map((credential) => (
                    <span key={credential.id || credential.label} className="inline-flex items-center gap-1 rounded-md border border-[var(--border-subtle)] px-2 py-1 text-[11px] text-[var(--text-muted)]">
                      {credential.preview || credential.label}
                      {credential.id && (
                        <button
                          type="button"
                          onClick={() => onEdit(source.source, {
                            ...draft,
                            options: {
                              ...draft.options,
                              clear_credential_ids: [
                                ...((draft.options.clear_credential_ids as string[] | undefined) || []),
                                credential.id,
                              ],
                            },
                          })}
                          className="text-[var(--accent-red)]"
                          aria-label={`Remove ${credential.label}`}
                        >
                          <Trash2 size={12} />
                        </button>
                      )}
                    </span>
                  ))}
                </div>
                <div>
                  <textarea
                    className="input-field min-h-[64px] text-[12px] py-1.5"
                    value={nextKeys}
                    placeholder="Paste one or more keys, separated by new lines"
                    onChange={(event) => onEdit(source.source, {
                      ...draft,
                      options: { ...draft.options, new_credentials: event.target.value },
                    })}
                  />
                </div>
              </div>
            </div>

            <div className="flex flex-wrap gap-2">
              <button className="btn-primary text-[11px] px-3 py-1" disabled={saving} onClick={() => onSave(source.source)}>
                {saving ? "Saving..." : "Save"}
              </button>
              <button className="btn-secondary text-[11px] px-3 py-1" disabled={testing === source.source} onClick={() => onTest(source.source)}>
                {testing === source.source ? "Testing..." : "Test"}
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 4: Wire panel into settings card**

Modify `SettingsCategoryCard.tsx`:

- Import `LiteratureSourcesPanel` and `LiteratureSourceProfile`.
- Add props:

```typescript
  literatureEdits: Record<string, LiteratureSourceProfile>;
  onLiteratureEdit: (source: string, value: LiteratureSourceProfile) => void;
  onSaveLiterature: (source: string) => void;
  onTestLiterature: (source: string) => void;
```

- Before the LLM branch, add:

```tsx
      {category.id === "literature_sources" ? (
        <LiteratureSourcesPanel
          sources={category.sources || []}
          edits={literatureEdits}
          saving={saving}
          testing={testing}
          onEdit={onLiteratureEdit}
          onSave={onSaveLiterature}
          onTest={onTestLiterature}
        />
      ) : category.id === "llm" ? (
```

- [ ] **Step 5: Wire page state and API calls**

Modify `apps/web/src/app/settings/page.tsx`:

- Add state:

```typescript
  const [literatureEdits, setLiteratureEdits] = useState<Record<string, LiteratureSourceProfile>>({});
```

- Add handlers:

```typescript
  const handleLiteratureEdit = (source: string, value: LiteratureSourceProfile) => {
    setLiteratureEdits((prev) => ({ ...prev, [source]: value }));
    setSaveResult(null);
  };

  const handleSaveLiterature = async (source: string) => {
    const draft = literatureEdits[source];
    if (!draft) return;
    setSaving(true);
    setSaveResult(null);
    try {
      const newCredentials = String(draft.options.new_credentials || "")
        .split(/\s+/)
        .map((item) => item.trim())
        .filter(Boolean);
      const clearCredentialIds = (draft.options.clear_credential_ids as string[] | undefined) || [];
      const cleanOptions = { ...draft.options };
      delete cleanOptions.new_credentials;
      delete cleanOptions.clear_credential_ids;
      const res = await fetch(`/api/v1/settings/literature/${source}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          enabled: draft.enabled,
          options: cleanOptions,
          new_credentials: newCredentials,
          clear_credential_ids: clearCredentialIds,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        setSaveResult(`Error: ${err.detail || res.statusText}`);
        return;
      }
      setLiteratureEdits((prev) => {
        const next = { ...prev };
        delete next[source];
        return next;
      });
      setSaveResult("Literature source settings saved.");
      fetchSettings();
    } catch (error) {
      setSaveResult(`Error: ${String(error)}`);
    } finally {
      setSaving(false);
    }
  };

  const handleTestLiterature = async (source: string) => {
    setTesting(source);
    try {
      const res = await fetch(`/api/v1/settings/literature/${source}/test`, { method: "POST" });
      const data = await res.json();
      setTestResults((prev) => ({
        ...prev,
        [source]: { status: data.status, detail: data.error || data.status },
      }));
    } catch (error) {
      setTestResults((prev) => ({
        ...prev,
        [source]: { status: "error", detail: String(error) },
      }));
    } finally {
      setTesting(null);
    }
  };
```

- Pass the new props into `SettingsCategoryCard`.

- [ ] **Step 6: Run frontend build**

Run:

```bash
cd apps/web
npm run build
cd ../..
```

Expected: PASS.

- [ ] **Step 7: Commit settings UI**

Run:

```bash
git add apps/web/src/features/settings/types.ts apps/web/src/features/settings/metadata.ts apps/web/src/features/settings/LiteratureSourcesPanel.tsx apps/web/src/features/settings/SettingsCategoryCard.tsx apps/web/src/app/settings/page.tsx
git commit -m "feat: add literature source settings ui"
```

Expected: commit succeeds.

## Task 8: Integrate Coordinator With Worker Prior-Art Search

**Files:**
- Modify: `apps/worker/modes/base.py`
- Modify: `apps/worker/modes/divergent.py`
- Extend: `tests/test_divergent_prior_art_verification.py`

- [ ] **Step 1: Write failing blocked-gate test**

Append to `tests/test_divergent_prior_art_verification.py`:

```python
@pytest.mark.asyncio
async def test_prior_art_check_marks_retrieval_failed_without_llm_verifier(monkeypatch):
    run_id = uuid4()
    llm_called = False

    async def fake_emit_progress(*args, **kwargs):
        return None

    async def fake_search_academic_sources(**kwargs):
        assert kwargs.get("return_report") is True
        return (
            [],
            ["transfer title borrowed method"],
            ["semantic_scholar credential_error: forbidden"],
            {},
            {
                "gate_status": "blocked",
                "candidate_count": 0,
                "contribution_counts": {"semantic_scholar": 0},
                "source_errors": [
                    {
                        "source": "semantic_scholar",
                        "kind": "credential_error",
                        "message": "forbidden",
                    }
                ],
            },
        )

    async def fake_generate_llm_json(*args, **kwargs):
        nonlocal llm_called
        llm_called = True
        return [], 0.0, []

    monkeypatch.setattr(divergent, "emit_progress", fake_emit_progress)
    monkeypatch.setattr(divergent, "get_gateway", lambda: object())
    monkeypatch.setattr(divergent, "search_academic_sources", fake_search_academic_sources)
    monkeypatch.setattr(divergent, "generate_llm_json", fake_generate_llm_json)

    state = ModeGraphState(
        run_id=run_id,
        topic="target task",
        idea_cards=[
            {
                "id": "idea-0",
                "title": "Transfer Title",
                "borrowed_method": "borrowed method",
                "prior_art_check_status": "pending",
                "novelty_score": 0.8,
            }
        ],
        context_bundle={},
    )

    updates = await divergent.prior_art_check(state)

    assert llm_called is False
    assert updates["idea_cards"][0]["prior_art_check_status"] == "retrieval_failed"
    assert updates["idea_cards"][0]["prior_art_found"] is None
    assert updates["context_bundle"]["literature_search_reports"]["transfer-title"][
        "gate_status"
    ] == "blocked"
```

Run:

```bash
PYTHONPATH=. pytest tests/test_divergent_prior_art_verification.py -q
```

Expected: FAIL because `prior_art_check` does not request or honor the report.

- [ ] **Step 2: Delegate `search_academic_sources` to coordinator**

Modify `apps/worker/modes/base.py`:

- Add parameter:

```python
    return_report: bool = False,
```

- Build a coordinator from settings with a helper named `_build_literature_search_coordinator()`.
- Convert `LiteratureCandidate` values into the existing return shape:

```python
    candidate_ids = [candidate.candidate_id for candidate in candidates]
    id_to_title = {candidate.candidate_id: candidate.title for candidate in candidates}
```

- Keep compatibility:

```python
    if return_report:
        return candidate_ids, executed, errors, id_to_title, report.model_dump(mode="json")
    return candidate_ids, executed, errors, id_to_title
```

- Use the old S2/OpenAlex direct code only as fallback when the coordinator cannot be built because the new tables do not exist.

- [ ] **Step 3: Honor gate reports in divergent prior-art**

Modify `apps/worker/modes/divergent.py::prior_art_check`:

- Call:

```python
        found, _executed, search_errors, title_map, search_report = await search_academic_sources(
            topic=state.topic,
            queries=[job["query"]],
            existing_titles=existing_titles,
            return_report=True,
        )
```

- Store reports:

```python
        literature_reports_by_key[job["dedup_key"]] = search_report
```

- If `gate_status` is `blocked` or `pending`, do not call verification for that job.
- If every job is blocked or pending and no prior-art records exist, return early with card statuses:

```python
status = "retrieval_pending" if any(
    report.get("gate_status") == "pending"
    for report in literature_reports_by_key.values()
) else "retrieval_failed"
```

- Set `prior_art_found` to `None` for these cards.
- Persist `literature_search_reports` in `context_bundle`.

- [ ] **Step 4: Preserve existing verified prior-art behavior**

Run:

```bash
PYTHONPATH=. pytest tests/test_divergent_prior_art_verification.py -q
```

Expected: PASS for both the existing verification test and the new blocked-gate test.

- [ ] **Step 5: Run worker-adjacent tests**

Run:

```bash
PYTHONPATH=. pytest tests/test_divergent_jury.py tests/test_frontier_paper_verification.py tests/test_paper_verification.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit worker integration**

Run:

```bash
git add apps/worker/modes/base.py apps/worker/modes/divergent.py tests/test_divergent_prior_art_verification.py
git commit -m "feat: gate divergent prior art retrieval"
```

Expected: commit succeeds.

## Task 9: Full Verification And Manual Smoke

**Files:**
- No planned source edits in this task unless verification exposes a defect.

- [ ] **Step 1: Run focused backend tests**

Run:

```bash
PYTHONPATH=. pytest \
  tests/test_literature_settings.py \
  tests/test_source_key_pool.py \
  tests/test_academic_adapter_errors.py \
  tests/test_literature_sources.py \
  tests/test_literature_search_gate.py \
  tests/test_routes_settings_literature.py \
  tests/test_routes_settings_llm.py \
  tests/test_divergent_prior_art_verification.py \
  tests/test_paper_verification.py \
  tests/production/test_docker_compose.py \
  -q
```

Expected: PASS.

- [ ] **Step 2: Run broader backend tests touched by these changes**

Run:

```bash
PYTHONPATH=. pytest tests/test_database_v2.py tests/test_frontier_paper_verification.py tests/test_divergent_jury.py -q
```

Expected: PASS.

- [ ] **Step 3: Run frontend build**

Run:

```bash
cd apps/web
npm run build
cd ../..
```

Expected: PASS.

- [ ] **Step 4: Apply migration to local database**

Run:

```bash
psql "$DATABASE_URL" -f scripts/migration/013_literature_source_settings.sql
```

Expected: `CREATE TABLE`, `CREATE INDEX`, or equivalent `already exists` notices with exit code 0.

- [ ] **Step 5: Configure the user-provided Semantic Scholar key locally**

Use the Settings page or a local API request. Do not commit the key. When using the API, replace `REDACTED_USER_S2_KEY` with the key supplied by the user in the private conversation:

```bash
curl -sS -X PUT http://localhost:8000/api/v1/settings/literature/semantic_scholar \
  -H 'Content-Type: application/json' \
  -d '{"enabled":true,"options":{},"new_credentials":["REDACTED_USER_S2_KEY"],"clear_credential_ids":[]}'
```

Expected: response contains a masked credential preview and does not contain the plaintext key.

- [ ] **Step 6: Start local services and smoke test Settings**

Run the API and web app using the repository's normal commands. Then open the Settings page and verify:

- `Literature Sources` is visible.
- Semantic Scholar can be enabled.
- Multiple key input accepts newline-separated keys.
- No emoji appear in the Settings category UI.
- Saved keys reload as masked previews.

- [ ] **Step 7: Run one prior-art smoke query through the worker helper**

Run:

```bash
PYTHONPATH=. python - <<'PY'
import asyncio
from apps.worker.modes.base import search_academic_sources

async def main():
    result = await search_academic_sources(
        topic="integer divisor summatory function elementary bounds",
        queries=[{"query": "integer divisor summatory function elementary bounds", "source": "both"}],
        return_report=True,
    )
    print(result[-1])

asyncio.run(main())
PY
```

Expected: printed report has `gate_status` equal to `pass` or `warn` when at least one configured source contributes. If all external APIs are unavailable, the report must say `pending` or `blocked` with classified source errors.

- [ ] **Step 8: Final git status and branch push**

Run:

```bash
git status --short
git log --oneline --max-count=8
git push -u origin feat/literature-sources-aris-gate
```

Expected: worktree is clean before push and the remote branch is created or updated.

## Spec Coverage Checklist

- Configurable sources are covered by Tasks 2, 3, 6, and 7.
- Multiple keys are covered by Tasks 3, 4, 6, and 7.
- Semantic Scholar `1 rps` and `burst=1` are covered by Task 4.
- OpenAlex 429 handling is covered by Task 4.
- Local library, Zotero, Obsidian, WebSearch, S2, OpenAlex, and DeepXiv are covered by Task 5.
- ARIS source contribution gate is covered by Tasks 5 and 8.
- Existing verification table reuse is covered by Task 8, which keeps `verify_paper_candidates_for_run`.
- Settings visual consistency and no emoji are covered by Task 7.
- Docker fresh database migration is covered by Task 2.
- End-to-end smoke verification and remote branch push are covered by Task 9.
