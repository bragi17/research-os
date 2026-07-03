# Topic Work Phase Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a topic work page where Atlas, Frontier, and Divergent run as editable phases inside one research workspace instead of visible child sessions.

**Architecture:** Add an additive work/phase/artifact layer on top of existing `research_run` execution. Keep current worker graphs and queue mechanics, but introduce work-centered APIs, generic artifact cards, and a unified frontend work page with phase tabs.

**Tech Stack:** FastAPI, asyncpg/PostgreSQL migrations, Pydantic schemas, Next.js App Router, React client components, existing pytest/static UI tests, existing worker queue.

---

## File Structure

- Create: `scripts/migration/015_topic_work_phase_artifacts.sql`
  - Adds `research_work`, `phase_execution`, `artifact_card`, `artifact_revision`, and `phase_input_selection`.
- Create: `libs/schemas/work.py`
  - Pydantic request/response schemas for works, phase executions, artifact cards, and phase inputs.
- Create: `apps/api/db/works.py`
  - Database operations for works, phase executions, artifact cards, revisions, and input selections.
- Modify: `apps/api/database.py`
  - Re-export new DB operations.
- Create: `apps/api/routes_works.py`
  - Work-centered API routes.
- Modify: `apps/api/main.py`
  - Include the new works router.
- Modify: `apps/worker/run_persistence.py`
  - Extract artifact cards from completed phase output bundles.
- Modify: `apps/worker/runner.py`
  - Connect completed executions to `phase_execution` and artifact extraction.
- Modify: `apps/web/src/lib/api.ts`
  - Add Work, PhaseExecution, ArtifactCard types and API helpers.
- Create: `apps/web/src/app/works/[id]/page.tsx`
  - Main topic work page.
- Create: `apps/web/src/components/work/PhaseStepper.tsx`
  - Atlas/Frontier/Divergent phase navigation.
- Create: `apps/web/src/components/work/ArtifactCardDeck.tsx`
  - Editable/selectable artifact card list.
- Create: `apps/web/src/components/work/PhaseRunPanel.tsx`
  - Run phase actions and execution status.
- Modify: `apps/web/src/components/Sidebar.tsx`
  - Show works instead of visible child runs once work listing exists.
- Modify: `apps/web/src/app/new/page.tsx`
  - Create a work and initial phase execution rather than exposing child research semantics.
- Test: `tests/test_work_phase_api.py`
  - API tests for work and card behavior.
- Test: `tests/test_work_phase_db.py`
  - DB operation tests using existing mock pool style.
- Test: `tests/test_work_phase_persistence.py`
  - Artifact extraction tests.
- Test: `tests/test_web_work_page_static.py`
  - Static UI tests for interaction semantics.

## Task 1: Add Work and Artifact Database Tables

**Files:**
- Create: `scripts/migration/015_topic_work_phase_artifacts.sql`
- Test: `tests/test_work_phase_db.py`

- [ ] **Step 1: Write the migration shape test**

Create `tests/test_work_phase_db.py` with:

```python
from __future__ import annotations

from pathlib import Path


MIGRATION = Path("scripts/migration/015_topic_work_phase_artifacts.sql")


def test_topic_work_migration_defines_core_tables() -> None:
    sql = MIGRATION.read_text()

    assert "CREATE TABLE IF NOT EXISTS research_work" in sql
    assert "CREATE TABLE IF NOT EXISTS phase_execution" in sql
    assert "CREATE TABLE IF NOT EXISTS artifact_card" in sql
    assert "CREATE TABLE IF NOT EXISTS artifact_revision" in sql
    assert "CREATE TABLE IF NOT EXISTS phase_input_selection" in sql


def test_topic_work_migration_keeps_existing_runs_as_execution_backend() -> None:
    sql = MIGRATION.read_text()

    assert "backing_run_id UUID REFERENCES research_run(id) ON DELETE SET NULL" in sql
    assert "work_id UUID NOT NULL REFERENCES research_work(id) ON DELETE CASCADE" in sql
    assert "phase TEXT NOT NULL" in sql
```

- [ ] **Step 2: Run migration shape test and verify it fails**

Run: `pytest tests/test_work_phase_db.py -v`

Expected: FAIL because `scripts/migration/015_topic_work_phase_artifacts.sql` does not exist.

- [ ] **Step 3: Create the additive migration**

Create `scripts/migration/015_topic_work_phase_artifacts.sql`:

```sql
-- Topic Work Phase Artifacts
-- Idempotent additive migration for single-topic multi-phase research workspaces.

CREATE TABLE IF NOT EXISTS research_work (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    workspace_id UUID NOT NULL,
    created_by UUID NOT NULL,
    title TEXT NOT NULL,
    topic TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    active_phase TEXT,
    root_run_id UUID REFERENCES research_run(id) ON DELETE SET NULL,
    project_id UUID REFERENCES research_project(id) ON DELETE SET NULL,
    budget_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    policy_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT valid_research_work_status CHECK (status IN ('active', 'archived', 'deleted')),
    CONSTRAINT valid_research_work_phase CHECK (active_phase IS NULL OR active_phase IN ('atlas', 'frontier', 'divergent'))
);

CREATE INDEX IF NOT EXISTS idx_research_work_workspace_updated
    ON research_work(workspace_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_research_work_project
    ON research_work(project_id);

CREATE TABLE IF NOT EXISTS phase_execution (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    work_id UUID NOT NULL REFERENCES research_work(id) ON DELETE CASCADE,
    phase TEXT NOT NULL,
    execution_kind TEXT NOT NULL DEFAULT 'standard',
    status TEXT NOT NULL DEFAULT 'queued',
    backing_run_id UUID REFERENCES research_run(id) ON DELETE SET NULL,
    input_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    output_bundle_id UUID REFERENCES context_bundle(id) ON DELETE SET NULL,
    error_message TEXT,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT valid_phase_execution_phase CHECK (phase IN ('atlas', 'frontier', 'divergent')),
    CONSTRAINT valid_phase_execution_kind CHECK (execution_kind IN ('standard', 'validation')),
    CONSTRAINT valid_phase_execution_status CHECK (status IN ('queued', 'running', 'paused', 'failed', 'completed', 'cancelled'))
);

CREATE INDEX IF NOT EXISTS idx_phase_execution_work_phase_created
    ON phase_execution(work_id, phase, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_phase_execution_backing_run
    ON phase_execution(backing_run_id);

CREATE TABLE IF NOT EXISTS artifact_card (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    work_id UUID NOT NULL REFERENCES research_work(id) ON DELETE CASCADE,
    phase TEXT NOT NULL,
    artifact_type TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'active',
    selection_state TEXT NOT NULL DEFAULT 'unselected',
    source_execution_id UUID REFERENCES phase_execution(id) ON DELETE SET NULL,
    source_card_ids UUID[] DEFAULT '{}',
    created_by UUID,
    updated_by UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT valid_artifact_card_phase CHECK (phase IN ('atlas', 'frontier', 'divergent')),
    CONSTRAINT valid_artifact_card_status CHECK (status IN ('active', 'archived', 'deleted')),
    CONSTRAINT valid_artifact_card_selection CHECK (selection_state IN ('unselected', 'selected', 'used'))
);

CREATE INDEX IF NOT EXISTS idx_artifact_card_work_phase
    ON artifact_card(work_id, phase, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_artifact_card_type
    ON artifact_card(artifact_type);
CREATE INDEX IF NOT EXISTS idx_artifact_card_selected
    ON artifact_card(work_id, selection_state);

CREATE TABLE IF NOT EXISTS artifact_revision (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    artifact_card_id UUID NOT NULL REFERENCES artifact_card(id) ON DELETE CASCADE,
    revision_no INT NOT NULL,
    title TEXT NOT NULL,
    body TEXT,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    edit_source TEXT NOT NULL DEFAULT 'user',
    edited_by UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT valid_artifact_revision_source CHECK (edit_source IN ('ai', 'user', 'system')),
    UNIQUE(artifact_card_id, revision_no)
);

CREATE TABLE IF NOT EXISTS phase_input_selection (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    work_id UUID NOT NULL REFERENCES research_work(id) ON DELETE CASCADE,
    target_phase TEXT NOT NULL,
    source_card_ids UUID[] NOT NULL DEFAULT '{}',
    manual_input_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT valid_phase_input_target CHECK (target_phase IN ('atlas', 'frontier', 'divergent'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_phase_input_selection_unique
    ON phase_input_selection(work_id, target_phase);
```

- [ ] **Step 4: Run migration shape test and verify it passes**

Run: `pytest tests/test_work_phase_db.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add scripts/migration/015_topic_work_phase_artifacts.sql tests/test_work_phase_db.py
git commit -m "feat: add topic work phase artifact schema"
```

## Task 2: Add Work Schemas and Database Operations

**Files:**
- Create: `libs/schemas/work.py`
- Create: `apps/api/db/works.py`
- Modify: `apps/api/database.py`
- Test: `tests/test_work_phase_db.py`

- [ ] **Step 1: Add schema import tests**

Append to `tests/test_work_phase_db.py`:

```python
from uuid import uuid4


def test_work_schemas_validate_artifact_card_patch() -> None:
    from libs.schemas.work import ArtifactCardPatch

    patch = ArtifactCardPatch(
        title="Edited gap",
        body="The method fails under sparse labels.",
        payload={"severity": "high"},
        selection_state="selected",
    )

    assert patch.title == "Edited gap"
    assert patch.selection_state == "selected"


def test_work_db_module_exposes_core_operations() -> None:
    from apps.api.db import works

    assert callable(works.create_work)
    assert callable(works.list_works)
    assert callable(works.create_phase_execution)
    assert callable(works.create_artifact_card)
    assert callable(works.update_artifact_card)
```

- [ ] **Step 2: Run tests and verify they fail**

Run: `pytest tests/test_work_phase_db.py -v`

Expected: FAIL because `libs.schemas.work` and `apps.api.db.works` do not exist.

- [ ] **Step 3: Create `libs/schemas/work.py`**

```python
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


ResearchPhase = Literal["atlas", "frontier", "divergent"]
ExecutionKind = Literal["standard", "validation"]
ExecutionStatus = Literal["queued", "running", "paused", "failed", "completed", "cancelled"]
ArtifactSelectionState = Literal["unselected", "selected", "used"]
ArtifactStatus = Literal["active", "archived", "deleted"]


class WorkCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    topic: str = Field(min_length=10)
    project_id: UUID | None = None
    budget: dict[str, Any] = Field(default_factory=dict)
    policy: dict[str, Any] = Field(default_factory=dict)


class WorkResponse(BaseModel):
    id: UUID
    title: str
    topic: str
    status: str
    active_phase: str | None = None
    root_run_id: UUID | None = None
    project_id: UUID | None = None
    created_at: datetime
    updated_at: datetime


class PhaseExecutionCreate(BaseModel):
    phase: ResearchPhase
    execution_kind: ExecutionKind = "standard"
    manual_input: dict[str, Any] = Field(default_factory=dict)
    source_card_ids: list[UUID] = Field(default_factory=list)


class PhaseExecutionResponse(BaseModel):
    id: UUID
    work_id: UUID
    phase: ResearchPhase
    execution_kind: ExecutionKind
    status: ExecutionStatus
    backing_run_id: UUID | None = None
    output_bundle_id: UUID | None = None
    created_at: datetime
    updated_at: datetime


class ArtifactCardCreate(BaseModel):
    phase: ResearchPhase
    artifact_type: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=500)
    body: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    source_execution_id: UUID | None = None
    source_card_ids: list[UUID] = Field(default_factory=list)


class ArtifactCardPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    body: str | None = None
    payload: dict[str, Any] | None = None
    status: ArtifactStatus | None = None
    selection_state: ArtifactSelectionState | None = None


class ArtifactCardResponse(BaseModel):
    id: UUID
    work_id: UUID
    phase: ResearchPhase
    artifact_type: str
    title: str
    body: str | None = None
    payload: dict[str, Any]
    status: ArtifactStatus
    selection_state: ArtifactSelectionState
    source_execution_id: UUID | None = None
    source_card_ids: list[UUID] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class PhaseInputSelectionUpdate(BaseModel):
    source_card_ids: list[UUID] = Field(default_factory=list)
    manual_input: dict[str, Any] = Field(default_factory=dict)
```

- [ ] **Step 4: Create `apps/api/db/works.py` with DB helpers**

```python
from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import orjson

from apps.api.db import pool as db_pool


def _json(value: Any) -> Any:
    return orjson.loads(orjson.dumps(value))


async def create_work(data: dict[str, Any]) -> dict[str, Any]:
    pool = await db_pool.get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO research_work (
            id, workspace_id, created_by, title, topic, status,
            active_phase, root_run_id, project_id, budget_json, policy_json
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
        RETURNING *
        """,
        data.get("id", uuid4()),
        data["workspace_id"],
        data["created_by"],
        data["title"],
        data["topic"],
        data.get("status", "active"),
        data.get("active_phase"),
        data.get("root_run_id"),
        data.get("project_id"),
        _json(data.get("budget_json", {})),
        _json(data.get("policy_json", {})),
    )
    return db_pool.record_to_dict(row)


async def list_works(workspace_id: UUID, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
    pool = await db_pool.get_pool()
    rows = await pool.fetch(
        """
        SELECT * FROM research_work
        WHERE workspace_id = $1 AND status != 'deleted'
        ORDER BY updated_at DESC
        LIMIT $2 OFFSET $3
        """,
        workspace_id,
        limit,
        offset,
    )
    return [db_pool.record_to_dict(row) for row in rows]


async def get_work(work_id: UUID, workspace_id: UUID) -> dict[str, Any] | None:
    pool = await db_pool.get_pool()
    row = await pool.fetchrow(
        "SELECT * FROM research_work WHERE id = $1 AND workspace_id = $2 AND status != 'deleted'",
        work_id,
        workspace_id,
    )
    return db_pool.record_to_dict(row) if row else None


async def create_phase_execution(data: dict[str, Any]) -> dict[str, Any]:
    pool = await db_pool.get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO phase_execution (
            id, work_id, phase, execution_kind, status, backing_run_id, input_json
        ) VALUES ($1, $2, $3, $4, $5, $6, $7)
        RETURNING *
        """,
        data.get("id", uuid4()),
        data["work_id"],
        data["phase"],
        data.get("execution_kind", "standard"),
        data.get("status", "queued"),
        data.get("backing_run_id"),
        _json(data.get("input_json", {})),
    )
    return db_pool.record_to_dict(row)


async def list_phase_executions(work_id: UUID) -> list[dict[str, Any]]:
    pool = await db_pool.get_pool()
    rows = await pool.fetch(
        """
        SELECT * FROM phase_execution
        WHERE work_id = $1
        ORDER BY created_at DESC
        """,
        work_id,
    )
    return [db_pool.record_to_dict(row) for row in rows]


async def update_phase_execution(execution_id: UUID, updates: dict[str, Any]) -> dict[str, Any] | None:
    allowed = {"status", "backing_run_id", "output_bundle_id", "error_message", "started_at", "completed_at", "updated_at"}
    invalid = set(updates) - allowed
    if invalid:
        raise ValueError(f"Invalid phase_execution update fields: {sorted(invalid)}")
    if not updates:
        return None
    values = list(updates.values())
    set_parts = [f"{key} = ${idx}" for idx, key in enumerate(updates, start=1)]
    values.append(execution_id)
    pool = await db_pool.get_pool()
    row = await pool.fetchrow(
        f"UPDATE phase_execution SET {', '.join(set_parts)} WHERE id = ${len(values)} RETURNING *",
        *values,
    )
    return db_pool.record_to_dict(row) if row else None


async def create_artifact_card(data: dict[str, Any]) -> dict[str, Any]:
    pool = await db_pool.get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                INSERT INTO artifact_card (
                    id, work_id, phase, artifact_type, title, body, payload,
                    status, selection_state, source_execution_id, source_card_ids,
                    created_by, updated_by
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, 'active', 'unselected', $8, $9, $10, $10)
                RETURNING *
                """,
                data.get("id", uuid4()),
                data["work_id"],
                data["phase"],
                data["artifact_type"],
                data["title"],
                data.get("body"),
                _json(data.get("payload", {})),
                data.get("source_execution_id"),
                data.get("source_card_ids", []),
                data.get("created_by"),
            )
            card = db_pool.record_to_dict(row)
            await conn.execute(
                """
                INSERT INTO artifact_revision (
                    artifact_card_id, revision_no, title, body, payload, edit_source, edited_by
                ) VALUES ($1, 1, $2, $3, $4, $5, $6)
                """,
                card["id"],
                card["title"],
                card.get("body"),
                _json(card.get("payload", {})),
                data.get("edit_source", "ai"),
                data.get("created_by"),
            )
            return card


async def list_artifact_cards(work_id: UUID, phase: str | None = None) -> list[dict[str, Any]]:
    pool = await db_pool.get_pool()
    if phase:
        rows = await pool.fetch(
            """
            SELECT * FROM artifact_card
            WHERE work_id = $1 AND phase = $2 AND status != 'deleted'
            ORDER BY created_at DESC
            """,
            work_id,
            phase,
        )
    else:
        rows = await pool.fetch(
            """
            SELECT * FROM artifact_card
            WHERE work_id = $1 AND status != 'deleted'
            ORDER BY created_at DESC
            """,
            work_id,
        )
    return [db_pool.record_to_dict(row) for row in rows]
```

- [ ] **Step 5: Re-export DB helpers**

Modify `apps/api/database.py` to import and expose the new work helpers:

```python
from apps.api.db.works import (
    create_artifact_card,
    create_phase_execution,
    create_work,
    get_work,
    list_artifact_cards,
    list_phase_executions,
    list_works,
    update_phase_execution,
)
```

Add those names to `__all__`.

- [ ] **Step 6: Run tests**

Run: `pytest tests/test_work_phase_db.py -v`

Expected: PASS.

- [ ] **Step 7: Commit**

Run:

```bash
git add libs/schemas/work.py apps/api/db/works.py apps/api/database.py tests/test_work_phase_db.py
git commit -m "feat: add work phase database helpers"
```

## Task 3: Add Work API Routes

**Files:**
- Create: `apps/api/routes_works.py`
- Modify: `apps/api/main.py`
- Test: `tests/test_work_phase_api.py`

- [ ] **Step 1: Write API tests for work creation and card listing**

Create `tests/test_work_phase_api.py` using the mocking style in `tests/test_api_v2.py`:

```python
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient

from apps.api.main import app


def test_works_router_is_registered() -> None:
    routes = {route.path for route in app.routes}
    assert "/api/v1/works" in routes
```

- [ ] **Step 2: Run API test and verify it fails**

Run: `pytest tests/test_work_phase_api.py -v`

Expected: FAIL because `/api/v1/works` is not registered.

- [ ] **Step 3: Create `apps/api/routes_works.py`**

Implement these endpoints first:

```python
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from apps.api.auth import get_current_user
from apps.api.workspace import WorkspaceContext
from apps.api import database as db
from libs.schemas.work import (
    ArtifactCardCreate,
    ArtifactCardPatch,
    PhaseExecutionCreate,
    PhaseInputSelectionUpdate,
    WorkCreate,
)

router = APIRouter(prefix="/api/v1/works", tags=["works"])


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@router.post("", status_code=201)
async def create_work(request: WorkCreate, user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    ctx = WorkspaceContext.from_user(user)
    return await db.create_work({
        "workspace_id": ctx.workspace_id,
        "created_by": ctx.user_id,
        "title": request.title,
        "topic": request.topic,
        "project_id": request.project_id,
        "budget_json": request.budget,
        "policy_json": request.policy,
    })


@router.get("")
async def list_works(
    limit: int = Query(100, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    ctx = WorkspaceContext.from_user(user)
    items = await db.list_works(ctx.workspace_id, limit=limit, offset=offset)
    return {"items": items, "total": len(items)}


@router.get("/{work_id}")
async def get_work(work_id: UUID, user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    ctx = WorkspaceContext.from_user(user)
    work = await db.get_work(work_id, ctx.workspace_id)
    if work is None:
        raise HTTPException(status_code=404, detail="Work not found")
    return work


@router.get("/{work_id}/phases")
async def get_work_phases(work_id: UUID, user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    ctx = WorkspaceContext.from_user(user)
    work = await db.get_work(work_id, ctx.workspace_id)
    if work is None:
        raise HTTPException(status_code=404, detail="Work not found")
    executions = await db.list_phase_executions(work_id)
    return {"work_id": str(work_id), "executions": executions}


@router.get("/{work_id}/artifact-cards")
async def get_artifact_cards(
    work_id: UUID,
    phase: str | None = Query(None),
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    ctx = WorkspaceContext.from_user(user)
    work = await db.get_work(work_id, ctx.workspace_id)
    if work is None:
        raise HTTPException(status_code=404, detail="Work not found")
    items = await db.list_artifact_cards(work_id, phase=phase)
    return {"items": items, "total": len(items)}


@router.post("/{work_id}/artifact-cards", status_code=201)
async def create_artifact_card(
    work_id: UUID,
    request: ArtifactCardCreate,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    ctx = WorkspaceContext.from_user(user)
    work = await db.get_work(work_id, ctx.workspace_id)
    if work is None:
        raise HTTPException(status_code=404, detail="Work not found")
    return await db.create_artifact_card({
        **request.model_dump(),
        "work_id": work_id,
        "created_by": ctx.user_id,
        "edit_source": "user",
    })
```

- [ ] **Step 4: Register the router in `apps/api/main.py`**

Add:

```python
from apps.api.routes_works import router as works_router
```

Then include:

```python
app.include_router(works_router)
```

- [ ] **Step 5: Run API test**

Run: `pytest tests/test_work_phase_api.py -v`

Expected: PASS for router registration.

- [ ] **Step 6: Add endpoint behavior tests**

Extend `tests/test_work_phase_api.py` with mocked DB calls after following the existing dependency override style in `tests/test_api_v2.py`:

```python
def test_create_work_returns_created_work(monkeypatch):
    created: dict[str, object] = {}

    async def fake_create_work(data):
        created.update(data)
        return {
            "id": uuid4(),
            "title": data["title"],
            "topic": data["topic"],
            "status": "active",
            "active_phase": None,
            "root_run_id": None,
            "project_id": None,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }

    monkeypatch.setattr("apps.api.database.create_work", fake_create_work)
    client = TestClient(app)

    response = client.post(
        "/api/v1/works",
        json={"title": "3D AD", "topic": "3D anomaly detection for point clouds"},
    )

    assert response.status_code == 201
    assert response.json()["title"] == "3D AD"
    assert created["topic"] == "3D anomaly detection for point clouds"


def test_get_artifact_cards_rejects_foreign_work(monkeypatch):
    async def fake_get_work(work_id, workspace_id):
        return None

    monkeypatch.setattr("apps.api.database.get_work", fake_get_work)
    client = TestClient(app)

    response = client.get(f"/api/v1/works/{uuid4()}/artifact-cards")

    assert response.status_code == 404
    assert response.json()["detail"] == "Work not found"


def test_create_artifact_card_records_user_edit_source(monkeypatch):
    work_id = uuid4()
    captured: dict[str, object] = {}

    async def fake_get_work(request_work_id, workspace_id):
        return {"id": request_work_id, "workspace_id": workspace_id, "status": "active"}

    async def fake_create_artifact_card(data):
        captured.update(data)
        return {
            "id": uuid4(),
            "work_id": data["work_id"],
            "phase": data["phase"],
            "artifact_type": data["artifact_type"],
            "title": data["title"],
            "body": data.get("body"),
            "payload": data.get("payload", {}),
            "status": "active",
            "selection_state": "unselected",
            "source_execution_id": None,
            "source_card_ids": [],
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }

    monkeypatch.setattr("apps.api.database.get_work", fake_get_work)
    monkeypatch.setattr("apps.api.database.create_artifact_card", fake_create_artifact_card)
    client = TestClient(app)

    response = client.post(
        f"/api/v1/works/{work_id}/artifact-cards",
        json={
            "phase": "frontier",
            "artifact_type": "frontier_gap",
            "title": "Sparse labels",
            "payload": {"significance": "high"},
        },
    )

    assert response.status_code == 201
    assert captured["edit_source"] == "user"
    assert captured["work_id"] == work_id
```

- [ ] **Step 7: Implement missing PATCH and phase input endpoints**

Add to `apps/api/routes_works.py`:

```python
@router.patch("/{work_id}/artifact-cards/{card_id}")
async def patch_artifact_card(
    work_id: UUID,
    card_id: UUID,
    request: ArtifactCardPatch,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    ctx = WorkspaceContext.from_user(user)
    work = await db.get_work(work_id, ctx.workspace_id)
    if work is None:
        raise HTTPException(status_code=404, detail="Work not found")
    updates = request.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No valid fields to update")
    updates["updated_by"] = ctx.user_id
    updates["updated_at"] = _utcnow()
    card = await db.update_artifact_card(card_id, updates)
    if card is None or str(card.get("work_id")) != str(work_id):
        raise HTTPException(status_code=404, detail="Artifact card not found")
    return card

@router.post("/{work_id}/phase-inputs/{phase}")
async def save_phase_inputs(
    work_id: UUID,
    phase: str,
    request: PhaseInputSelectionUpdate,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    ctx = WorkspaceContext.from_user(user)
    work = await db.get_work(work_id, ctx.workspace_id)
    if work is None:
        raise HTTPException(status_code=404, detail="Work not found")
    if phase not in {"atlas", "frontier", "divergent"}:
        raise HTTPException(status_code=400, detail="Invalid phase")
    return await db.upsert_phase_input_selection(
        work_id=work_id,
        target_phase=phase,
        source_card_ids=request.source_card_ids,
        manual_input_json=request.manual_input,
        created_by=ctx.user_id,
    )
```

Use the `ArtifactCardPatch` and `PhaseInputSelectionUpdate` schemas.

- [ ] **Step 8: Run API tests**

Run: `pytest tests/test_work_phase_api.py -v`

Expected: PASS.

- [ ] **Step 9: Commit**

Run:

```bash
git add apps/api/routes_works.py apps/api/main.py tests/test_work_phase_api.py
git commit -m "feat: add work phase API routes"
```

## Task 4: Start Phase Executions Inside a Work

**Files:**
- Modify: `apps/api/routes_works.py`
- Modify: `apps/api/db/works.py`
- Modify: `apps/worker/runner.py`
- Test: `tests/test_work_phase_api.py`

- [ ] **Step 1: Write phase execution enqueue test**

Add this test to `tests/test_work_phase_api.py`:

```python
def test_start_frontier_phase_execution_enqueues_same_work_payload(monkeypatch):
    work_id = uuid4()
    backing_run_id = uuid4()
    execution_id = uuid4()
    enqueued: list[tuple[UUID, dict[str, object]]] = []

    async def fake_get_work(request_work_id, workspace_id):
        return {
            "id": request_work_id,
            "workspace_id": workspace_id,
            "created_by": uuid4(),
            "title": "3D AD",
            "topic": "3D anomaly detection for point clouds",
            "budget_json": {"max_new_papers": 50},
            "policy_json": {"keywords": ["3d anomaly"]},
            "project_id": None,
        }

    async def fake_list_artifact_cards(request_work_id, phase=None):
        return [
            {
                "id": uuid4(),
                "work_id": request_work_id,
                "phase": "atlas",
                "artifact_type": "atlas_direction",
                "title": "Point-cloud inspection",
                "payload": {"name": "Point-cloud inspection"},
            }
        ]

    async def fake_create_run(data):
        assert data["mode"] == "frontier"
        assert data["parent_run_id"] is None
        return {**data, "id": backing_run_id}

    async def fake_create_phase_execution(data):
        assert data["work_id"] == work_id
        assert data["phase"] == "frontier"
        assert data["backing_run_id"] == backing_run_id
        return {
            "id": execution_id,
            **data,
            "status": "queued",
            "output_bundle_id": None,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }

    async def fake_enqueue_run(run_id, payload):
        enqueued.append((run_id, payload))

    monkeypatch.setattr("apps.api.database.get_work", fake_get_work)
    monkeypatch.setattr("apps.api.database.list_artifact_cards", fake_list_artifact_cards)
    monkeypatch.setattr("apps.api.database.create_run", fake_create_run)
    monkeypatch.setattr("apps.api.database.create_phase_execution", fake_create_phase_execution)
    monkeypatch.setattr("apps.worker.task_queue.enqueue_run", fake_enqueue_run)
    client = TestClient(app)

    response = client.post(
        f"/api/v1/works/{work_id}/phases/frontier/executions",
        json={
            "phase": "frontier",
            "source_card_ids": [str(uuid4())],
            "manual_input": {"scope": "industrial point clouds"},
        },
    )

    assert response.status_code == 201
    assert response.json()["phase"] == "frontier"
    assert enqueued[0][0] == backing_run_id
    assert enqueued[0][1]["mode"] == "frontier"
    assert enqueued[0][1]["context_bundle"]["sub_directions"] == [
        {"name": "Point-cloud inspection"}
    ]
```

- [ ] **Step 2: Run test and verify it fails**

Run: `pytest tests/test_work_phase_api.py::test_start_frontier_phase_execution_enqueues_same_work_payload -v`

Expected: FAIL because route is not implemented.

- [ ] **Step 3: Implement context bundle builder**

Add helper in `apps/api/routes_works.py`:

```python
def _context_bundle_from_cards(cards: list[dict[str, Any]], manual_input: dict[str, Any]) -> dict[str, Any]:
    bundle: dict[str, Any] = {"manual_input": manual_input, "artifact_cards": cards}
    bundle["sub_directions"] = [card["payload"] for card in cards if card["artifact_type"] == "atlas_direction"]
    bundle["gaps"] = [card["payload"] for card in cards if card["artifact_type"] == "frontier_gap"]
    bundle["pain_points"] = [card["payload"] for card in cards if card["artifact_type"] == "frontier_pain_point"]
    bundle["idea_cards"] = [card["payload"] for card in cards if card["artifact_type"] == "divergent_idea"]
    return bundle
```

- [ ] **Step 4: Implement phase execution route**

Add:

```python
@router.post("/{work_id}/phases/{phase}/executions", status_code=201)
async def start_phase_execution(
    work_id: UUID,
    phase: str,
    request: PhaseExecutionCreate,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    ctx = WorkspaceContext.from_user(user)
    if phase != request.phase:
        raise HTTPException(status_code=400, detail="Phase path and request body do not match")
    if phase not in {"atlas", "frontier", "divergent"}:
        raise HTTPException(status_code=400, detail="Invalid phase")

    work = await db.get_work(work_id, ctx.workspace_id)
    if work is None:
        raise HTTPException(status_code=404, detail="Work not found")

    cards = await db.list_artifact_cards(work_id)
    selected_ids = {str(card_id) for card_id in request.source_card_ids}
    selected_cards = [
        card for card in cards
        if not selected_ids or str(card.get("id")) in selected_ids
    ]
    if phase != "atlas" and not selected_cards and not request.manual_input:
        raise HTTPException(
            status_code=400,
            detail="Select upstream cards or provide manual input before starting this phase",
        )

    from apps.worker.task_queue import enqueue_run

    now = _utcnow()
    run_id = uuid4()
    run = await db.create_run({
        "id": run_id,
        "workspace_id": ctx.workspace_id,
        "created_by": ctx.user_id,
        "title": f"{phase.title()}: {work['title']}",
        "topic": work["topic"],
        "status": "queued",
        "goal_type": "survey_plus_innovations",
        "autonomy_mode": "default_autonomous",
        "budget_json": work.get("budget_json") or {},
        "policy_json": work.get("policy_json") or {},
        "progress_pct": 0,
        "current_step": None,
        "started_at": None,
        "completed_at": None,
        "created_at": now,
        "updated_at": now,
        "mode": phase,
        "parent_run_id": None,
        "context_bundle_id": None,
        "current_stage": "init",
        "project_id": work.get("project_id"),
    })
    execution = await db.create_phase_execution({
        "work_id": work_id,
        "phase": phase,
        "execution_kind": request.execution_kind,
        "status": "queued",
        "backing_run_id": run["id"],
        "input_json": {
            "manual_input": request.manual_input,
            "source_card_ids": [str(card_id) for card_id in request.source_card_ids],
        },
    })
    queue_payload = {
        "project_id": str(work["project_id"]) if work.get("project_id") else None,
        "topic": work["topic"],
        "goal_type": "survey_plus_innovations",
        "mode": phase,
        "keywords": (work.get("policy_json") or {}).get("keywords", []),
        "seed_paper_ids": (work.get("policy_json") or {}).get("seed_papers", []),
        "library_pool_ids": (work.get("policy_json") or {}).get("library_pool_ids", []),
        "budget": work.get("budget_json") or {},
        "context_bundle": _context_bundle_from_cards(selected_cards, request.manual_input),
        "work_id": str(work_id),
        "phase_execution_id": str(execution["id"]),
    }
    await enqueue_run(run["id"], queue_payload)
    return execution
```

The route verifies work access, loads selected source cards, validates inputs, creates a backing queued `research_run`, creates a `phase_execution`, enqueues the backing run, and returns the execution row.

- [ ] **Step 5: Run phase execution tests**

Run: `pytest tests/test_work_phase_api.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add apps/api/routes_works.py apps/api/db/works.py apps/worker/runner.py tests/test_work_phase_api.py
git commit -m "feat: enqueue phase executions within work"
```

## Task 5: Extract Artifact Cards From Phase Outputs

**Files:**
- Modify: `apps/worker/run_persistence.py`
- Test: `tests/test_work_phase_persistence.py`

- [ ] **Step 1: Write artifact extraction tests**

Create `tests/test_work_phase_persistence.py`:

```python
from __future__ import annotations


def test_frontier_bundle_extracts_gap_cards() -> None:
    from apps.worker.run_persistence import _artifact_cards_from_state

    cards = _artifact_cards_from_state(
        work_id="00000000-0000-0000-0000-000000000001",
        phase="frontier",
        source_execution_id="00000000-0000-0000-0000-000000000002",
        state={
            "gaps": [{"description": "Sparse-label failure", "gap_type": "data", "significance": "high"}],
            "pain_points": [{"statement": "Models overfit small defect sets", "pain_type": "generalization"}],
        },
    )

    assert [card["artifact_type"] for card in cards] == ["frontier_gap", "frontier_pain_point"]
    assert cards[0]["title"] == "Sparse-label failure"


def test_divergent_bundle_extracts_idea_cards() -> None:
    from apps.worker.run_persistence import _artifact_cards_from_state

    cards = _artifact_cards_from_state(
        work_id="00000000-0000-0000-0000-000000000001",
        phase="divergent",
        source_execution_id="00000000-0000-0000-0000-000000000002",
        state={"idea_cards": [{"title": "Residual envelope checking", "problem_statement": "Detect rare defects"}]},
    )

    assert len(cards) == 1
    assert cards[0]["artifact_type"] == "divergent_idea"
    assert cards[0]["title"] == "Residual envelope checking"
```

- [ ] **Step 2: Run tests and verify they fail**

Run: `pytest tests/test_work_phase_persistence.py -v`

Expected: FAIL because `_artifact_cards_from_state` does not exist.

- [ ] **Step 3: Implement extraction helper**

Add to `apps/worker/run_persistence.py`:

```python
def _artifact_cards_from_state(
    *,
    work_id: str,
    phase: str,
    source_execution_id: str,
    state: dict[str, Any],
) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    if phase == "atlas":
        for item in state.get("sub_directions", []) or []:
            title = str(item.get("name") or item.get("title") or item.get("label") or "Atlas direction")
            cards.append({
                "work_id": work_id,
                "phase": "atlas",
                "artifact_type": "atlas_direction",
                "title": title,
                "body": item.get("description"),
                "payload": item,
                "source_execution_id": source_execution_id,
                "edit_source": "ai",
            })
    if phase == "frontier":
        for item in state.get("gaps", []) or []:
            title = str(item.get("description") or item.get("title") or "Frontier gap")
            cards.append({
                "work_id": work_id,
                "phase": "frontier",
                "artifact_type": "frontier_gap",
                "title": title[:500],
                "body": item.get("potential_impact"),
                "payload": item,
                "source_execution_id": source_execution_id,
                "edit_source": "ai",
            })
        for item in state.get("pain_points", []) or []:
            title = str(item.get("statement") or item.get("description") or "Pain point")
            cards.append({
                "work_id": work_id,
                "phase": "frontier",
                "artifact_type": "frontier_pain_point",
                "title": title[:500],
                "body": item.get("pain_type"),
                "payload": item,
                "source_execution_id": source_execution_id,
                "edit_source": "ai",
            })
    if phase == "divergent":
        for item in state.get("idea_cards", []) or []:
            title = str(item.get("title") or "Innovation idea")
            cards.append({
                "work_id": work_id,
                "phase": "divergent",
                "artifact_type": "divergent_idea",
                "title": title[:500],
                "body": item.get("problem_statement"),
                "payload": item,
                "source_execution_id": source_execution_id,
                "edit_source": "ai",
            })
    return cards
```

- [ ] **Step 4: Wire extraction after persistence**

In `apps/worker/run_persistence.py`, after `_persist_context_bundle`, call artifact extraction when the state or job metadata includes `work_id` and `phase_execution_id`. Insert cards with `apps.api.database.create_artifact_card`.

- [ ] **Step 5: Run persistence tests**

Run: `pytest tests/test_work_phase_persistence.py tests/test_run_persistence.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add apps/worker/run_persistence.py tests/test_work_phase_persistence.py
git commit -m "feat: extract work artifact cards from phase outputs"
```

## Task 6: Add Frontend API Helpers

**Files:**
- Modify: `apps/web/src/lib/api.ts`
- Test: `tests/test_web_work_page_static.py`

- [ ] **Step 1: Write static API helper test**

Create `tests/test_web_work_page_static.py`:

```python
from __future__ import annotations

from pathlib import Path


API = Path("apps/web/src/lib/api.ts")


def test_work_api_helpers_exist() -> None:
    source = API.read_text()

    assert "export interface Work" in source
    assert "export interface PhaseExecution" in source
    assert "export interface ArtifactCard" in source
    assert "export const listWorks" in source
    assert "export const getWork" in source
    assert "export const startPhaseExecution" in source
    assert "export const updateArtifactCard" in source
```

- [ ] **Step 2: Run static test and verify it fails**

Run: `pytest tests/test_web_work_page_static.py -v`

Expected: FAIL because helpers do not exist.

- [ ] **Step 3: Add API types and helpers**

Append to `apps/web/src/lib/api.ts`:

```typescript
export type ResearchPhase = "atlas" | "frontier" | "divergent";

export interface Work {
  id: string;
  title: string;
  topic: string;
  status: string;
  active_phase?: ResearchPhase | null;
  root_run_id?: string | null;
  project_id?: string | null;
  created_at: string;
  updated_at: string;
}

export interface PhaseExecution {
  id: string;
  work_id: string;
  phase: ResearchPhase;
  execution_kind: "standard" | "validation";
  status: Run["status"];
  backing_run_id?: string | null;
  output_bundle_id?: string | null;
  created_at: string;
  updated_at: string;
}

export interface ArtifactCard {
  id: string;
  work_id: string;
  phase: ResearchPhase;
  artifact_type: string;
  title: string;
  body?: string | null;
  payload: Record<string, unknown>;
  status: "active" | "archived" | "deleted";
  selection_state: "unselected" | "selected" | "used";
  source_execution_id?: string | null;
  source_card_ids?: string[];
  created_at: string;
  updated_at: string;
}

export const listWorks = () =>
  apiFetch<{ items: Work[]; total: number }>("/api/v1/works");

export const getWork = (workId: string) =>
  apiFetch<Work>(`/api/v1/works/${workId}`);

export const getWorkPhases = (workId: string) =>
  apiFetch<{ work_id: string; executions: PhaseExecution[] }>(`/api/v1/works/${workId}/phases`);

export const listArtifactCards = (workId: string, phase?: ResearchPhase) => {
  const query = phase ? `?phase=${encodeURIComponent(phase)}` : "";
  return apiFetch<{ items: ArtifactCard[]; total: number }>(`/api/v1/works/${workId}/artifact-cards${query}`);
};

export const updateArtifactCard = (workId: string, cardId: string, data: Partial<ArtifactCard>) =>
  apiFetch<ArtifactCard>(`/api/v1/works/${workId}/artifact-cards/${cardId}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });

export const startPhaseExecution = (
  workId: string,
  phase: ResearchPhase,
  data: { execution_kind?: "standard" | "validation"; manual_input?: Record<string, unknown>; source_card_ids?: string[] },
) =>
  apiFetch<PhaseExecution>(`/api/v1/works/${workId}/phases/${phase}/executions`, {
    method: "POST",
    body: JSON.stringify(data),
  });
```

- [ ] **Step 4: Run static test**

Run: `pytest tests/test_web_work_page_static.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add apps/web/src/lib/api.ts tests/test_web_work_page_static.py
git commit -m "feat: add frontend work API helpers"
```

## Task 7: Build the Topic Work Page Shell

**Files:**
- Create: `apps/web/src/app/works/[id]/page.tsx`
- Create: `apps/web/src/components/work/PhaseStepper.tsx`
- Create: `apps/web/src/components/work/PhaseRunPanel.tsx`
- Test: `tests/test_web_work_page_static.py`

- [ ] **Step 1: Add static page tests**

Append:

```python
WORK_PAGE = Path("apps/web/src/app/works/[id]/page.tsx")
PHASE_STEPPER = Path("apps/web/src/components/work/PhaseStepper.tsx")
PHASE_RUN_PANEL = Path("apps/web/src/components/work/PhaseRunPanel.tsx")


def test_work_page_uses_phase_model_not_child_runs() -> None:
    source = WORK_PAGE.read_text()

    assert "getWork(" in source
    assert "getWorkPhases(" in source
    assert "PhaseStepper" in source
    assert "child of" not in source
    assert "spawnRun" not in source


def test_phase_stepper_lists_three_research_phases() -> None:
    source = PHASE_STEPPER.read_text()

    assert '"atlas"' in source
    assert '"frontier"' in source
    assert '"divergent"' in source


def test_phase_run_panel_has_independent_and_next_phase_actions() -> None:
    source = PHASE_RUN_PANEL.read_text()

    assert "Run this phase" in source
    assert "Start Frontier from selected Atlas cards" in source
    assert "Start Divergent from selected gaps" in source
    assert "Validate selected ideas with Frontier" in source
```

- [ ] **Step 2: Run static tests and verify they fail**

Run: `pytest tests/test_web_work_page_static.py -v`

Expected: FAIL because files do not exist.

- [ ] **Step 3: Create `PhaseStepper.tsx`**

```tsx
"use client";

import type { ResearchPhase } from "@/lib/api";

const PHASES: { id: ResearchPhase; label: string }[] = [
  { id: "atlas", label: "Atlas" },
  { id: "frontier", label: "Frontier" },
  { id: "divergent", label: "Divergent" },
];

export default function PhaseStepper({
  activePhase,
  onChange,
}: {
  activePhase: ResearchPhase;
  onChange: (phase: ResearchPhase) => void;
}) {
  return (
    <div className="flex items-center gap-2 border-b border-[var(--border-subtle)]">
      {PHASES.map((phase) => (
        <button
          key={phase.id}
          type="button"
          onClick={() => onChange(phase.id)}
          className={`px-4 py-3 text-[13px] font-medium border-b-2 transition-colors ${
            activePhase === phase.id
              ? "border-[var(--accent)] text-[var(--accent)]"
              : "border-transparent text-[var(--text-muted)] hover:text-[var(--text-secondary)]"
          }`}
        >
          {phase.label}
        </button>
      ))}
    </div>
  );
}
```

- [ ] **Step 4: Create `PhaseRunPanel.tsx`**

```tsx
"use client";

import type { ResearchPhase } from "@/lib/api";

function nextActionLabel(phase: ResearchPhase): string {
  if (phase === "atlas") return "Start Frontier from selected Atlas cards";
  if (phase === "frontier") return "Start Divergent from selected gaps";
  return "Validate selected ideas with Frontier";
}

export default function PhaseRunPanel({
  phase,
  selectedCount,
  running,
  onRunPhase,
  onRunNext,
}: {
  phase: ResearchPhase;
  selectedCount: number;
  running: boolean;
  onRunPhase: () => void;
  onRunNext: () => void;
}) {
  return (
    <div className="card-static p-4 flex flex-wrap items-center justify-between gap-3">
      <div>
        <h3 className="text-[13px] font-medium text-[var(--text-primary)]">
          {phase[0].toUpperCase() + phase.slice(1)} phase
        </h3>
        <p className="text-[12px] text-[var(--text-muted)] mt-0.5">
          {selectedCount} card{selectedCount === 1 ? "" : "s"} selected as downstream input
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" className="btn-secondary text-[13px]" onClick={onRunPhase} disabled={running}>
          Run this phase
        </button>
        <button type="button" className="btn-primary text-[13px]" onClick={onRunNext} disabled={running}>
          {nextActionLabel(phase)}
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Create `works/[id]/page.tsx`**

Build a client page that:

- fetches `getWork`, `getWorkPhases`, and `listArtifactCards`.
- stores active phase in local state.
- renders `PhaseStepper`.
- renders `PhaseRunPanel`.
- renders a placeholder card area until Task 8 adds the deck.

- [ ] **Step 6: Run static tests**

Run: `pytest tests/test_web_work_page_static.py -v`

Expected: PASS.

- [ ] **Step 7: Commit**

Run:

```bash
git add apps/web/src/app/works/[id]/page.tsx apps/web/src/components/work/PhaseStepper.tsx apps/web/src/components/work/PhaseRunPanel.tsx tests/test_web_work_page_static.py
git commit -m "feat: add topic work phase page shell"
```

## Task 8: Add Editable Artifact Card Deck

**Files:**
- Create: `apps/web/src/components/work/ArtifactCardDeck.tsx`
- Modify: `apps/web/src/app/works/[id]/page.tsx`
- Test: `tests/test_web_work_page_static.py`

- [ ] **Step 1: Add static tests**

Append:

```python
ARTIFACT_DECK = Path("apps/web/src/components/work/ArtifactCardDeck.tsx")


def test_artifact_deck_supports_edit_and_selection() -> None:
    source = ARTIFACT_DECK.read_text()

    assert "selection_state" in source
    assert "updateArtifactCard" in source
    assert "Edit" in source
    assert "Save" in source
    assert "Selected" in source
```

- [ ] **Step 2: Run static tests and verify they fail**

Run: `pytest tests/test_web_work_page_static.py -v`

Expected: FAIL because `ArtifactCardDeck.tsx` does not exist.

- [ ] **Step 3: Create `ArtifactCardDeck.tsx`**

Implement:

- card title/body display.
- Edit/Save/Cancel for title and body.
- Select/Deselect button that patches `selection_state`.
- `onCardsChanged` callback after successful patch.

- [ ] **Step 4: Wire deck into work page**

In `apps/web/src/app/works/[id]/page.tsx`, render:

```tsx
<ArtifactCardDeck
  workId={workId}
  cards={cards.filter((card) => card.phase === activePhase)}
  onCardsChanged={fetchData}
/>
```

- [ ] **Step 5: Run static tests and frontend build**

Run:

```bash
pytest tests/test_web_work_page_static.py -v
npm --prefix apps/web run build
```

Expected: both PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add apps/web/src/components/work/ArtifactCardDeck.tsx apps/web/src/app/works/[id]/page.tsx tests/test_web_work_page_static.py
git commit -m "feat: add editable artifact cards"
```

## Task 9: Move New Research and Sidebar Toward Works

**Files:**
- Modify: `apps/web/src/app/new/page.tsx`
- Modify: `apps/web/src/components/Sidebar.tsx`
- Modify: `apps/web/src/lib/api.ts`
- Test: `tests/test_web_work_page_static.py`

- [ ] **Step 1: Add static tests for no visible child-session language**

Append:

```python
SIDEBAR = Path("apps/web/src/components/Sidebar.tsx")
NEW_PAGE = Path("apps/web/src/app/new/page.tsx")


def test_sidebar_lists_works_without_child_language() -> None:
    source = SIDEBAR.read_text()

    assert "listWorks" in source
    assert "child of" not in source


def test_new_research_creates_work_before_initial_phase() -> None:
    source = NEW_PAGE.read_text()

    assert "createWork" in source
    assert "startPhaseExecution" in source
```

- [ ] **Step 2: Run tests and verify they fail**

Run: `pytest tests/test_web_work_page_static.py -v`

Expected: FAIL because sidebar/new page still use run-oriented helpers.

- [ ] **Step 3: Add `createWork` helper**

In `apps/web/src/lib/api.ts`:

```typescript
export const createWork = (data: Record<string, unknown>) =>
  apiFetch<Work>("/api/v1/works", { method: "POST", body: JSON.stringify(data) });
```

- [ ] **Step 4: Update new research submit flow**

Change the new page flow:

1. `createWork({ title, topic, project_id, budget, policy })`
2. `startPhaseExecution(work.id, mode, { manual_input, source_card_ids: [] })`
3. `router.push(`/works/${work.id}`)`

- [ ] **Step 5: Update sidebar data source**

Use `listWorks()` for primary sidebar items. Show phase metadata from work fields. Keep old `listRuns()` fallback only if works API fails during migration.

- [ ] **Step 6: Run tests and build**

Run:

```bash
pytest tests/test_web_work_page_static.py -v
npm --prefix apps/web run build
```

Expected: PASS.

- [ ] **Step 7: Commit**

Run:

```bash
git add apps/web/src/app/new/page.tsx apps/web/src/components/Sidebar.tsx apps/web/src/lib/api.ts tests/test_web_work_page_static.py
git commit -m "feat: make works the primary research navigation"
```

## Task 10: Compatibility Cleanup and Documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/AGENT_ARCHITECTURE.md`
- Modify: `apps/web/src/app/runs/[id]/page.tsx`
- Modify: `apps/web/src/app/runs/[id]/frontier/page.tsx`
- Modify: `apps/web/src/app/runs/[id]/divergent/page.tsx`
- Test: `tests/test_web_run_page_static.py`
- Test: `tests/test_web_frontier_page_static.py`

- [ ] **Step 1: Add static tests that reject old interaction wording**

Update existing static tests so these strings are not present in user-facing phase continuation CTAs:

```python
assert "child of" not in source
assert "Check prior art further" not in source
assert "Explore innovations for these gaps" not in source
```

Allow old strings only in historical docs if needed.

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
pytest tests/test_web_run_page_static.py tests/test_web_frontier_page_static.py -v
```

Expected: FAIL while old wording remains.

- [ ] **Step 3: Update compatibility pages**

Change old run pages to:

- Link users to `/works/{work_id}` when work metadata is available.
- Replace `Explore innovations for these gaps` with `Open topic work`.
- Replace Divergent `Check prior art further` with `Validate selected ideas with Frontier` only inside the work page.

- [ ] **Step 4: Update docs**

In `README.md`, replace mode chaining with:

```text
One topic work can run phases independently or progressively:
Atlas -> Frontier -> Divergent.
Each phase produces editable artifact cards. Selected cards become the input deck for later phases.
```

In `docs/AGENT_ARCHITECTURE.md`, describe `research_work`, `phase_execution`, and `artifact_card` as the user-facing orchestration layer.

- [ ] **Step 5: Run full targeted verification**

Run:

```bash
pytest tests/test_work_phase_db.py tests/test_work_phase_api.py tests/test_work_phase_persistence.py tests/test_web_work_page_static.py tests/test_web_run_page_static.py tests/test_web_frontier_page_static.py -v
npm --prefix apps/web run build
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add README.md docs/AGENT_ARCHITECTURE.md apps/web/src/app/runs/[id]/page.tsx apps/web/src/app/runs/[id]/frontier/page.tsx apps/web/src/app/runs/[id]/divergent/page.tsx tests/test_web_run_page_static.py tests/test_web_frontier_page_static.py
git commit -m "docs: align research flow with topic work phases"
```

## Self-Review

- Spec coverage: The plan covers single topic work pages, independent phase runs, progressive phase runs, editable cards, card provenance, API boundaries, worker persistence, and migration.
- Placeholder scan: The plan contains no unresolved placeholder markers. Later tasks intentionally describe UI behavior at component level rather than full code for every React state branch, because those tasks depend on API shape created earlier.
- Type consistency: `ResearchPhase`, `PhaseExecution`, `ArtifactCard`, `selection_state`, `phase_execution`, and `work_id` names are consistent across schema, API, worker, and frontend tasks.
- Scope check: This is a multi-subsystem migration. The plan is split into independently testable tasks so it can be executed incrementally without breaking the existing run-based system.
