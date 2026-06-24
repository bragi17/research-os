# Research Memory Ledger Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist project-level research memory so papers, ideas, rejected ideas, claims, gaps, and experiments can influence later runs instead of being trapped inside one run result.

**Architecture:** Add a small ledger with typed memory items and explicit edges. Persist ledger items as a side effect of worker result persistence, then read failed idea memory during Divergent idea composition so future runs can avoid already-rejected directions.

**Tech Stack:** Python 3.10, asyncpg facade, PostgreSQL JSONB, pytest, existing mode `ModeGraphState` data structures.

---

## File Structure

- Create `scripts/migration/011_research_memory.sql` for memory item and edge tables.
- Create `apps/api/db/research_memory.py` for ledger DB helpers.
- Modify `apps/api/database.py` to export ledger helpers.
- Create `services/research_memory.py` for converting mode state into ledger records.
- Modify `apps/worker/runner.py` to persist ledger items after run outputs are saved.
- Modify `apps/worker/modes/divergent.py` to load failed idea memory into `idea_composition()`.
- Add `tests/test_research_memory.py` for DB and service behavior.
- Add `tests/test_runner_research_memory.py` for worker integration.
- Extend `tests/test_divergent_jury.py` for failed idea memory prompts.

## Task 1: Create Isolated Worktree

- [ ] **Step 1: Start after idea jury is merged**

Run from `/root/research-os`:

```bash
git checkout main
git pull --ff-only
git worktree add .worktrees/research-memory-ledger -b feat/research-memory-ledger main
cd .worktrees/research-memory-ledger
```

Expected: worktree is created on `feat/research-memory-ledger` and contains paper verification plus idea jury changes.

- [ ] **Step 2: Run baseline tests**

Run:

```bash
PYTHONPATH=. pytest tests/test_database_v2.py tests/test_divergent_jury.py -q
```

Expected: tests pass or any pre-existing failure is recorded before implementation starts.

## Task 2: Add Research Memory Tables

**Files:**
- Create: `scripts/migration/011_research_memory.sql`
- Create: `apps/api/db/research_memory.py`
- Modify: `apps/api/database.py`
- Test: `tests/test_research_memory.py`

- [ ] **Step 1: Add migration**

Create `scripts/migration/011_research_memory.sql`:

```sql
-- Project-level memory ledger for research artifacts and decisions.
CREATE TABLE IF NOT EXISTS research_memory_item (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id UUID NOT NULL REFERENCES research_project(id) ON DELETE CASCADE,
    source_run_id UUID REFERENCES research_run(id) ON DELETE SET NULL,
    item_type TEXT NOT NULL,
    stable_key TEXT NOT NULL,
    title TEXT,
    status TEXT,
    summary_text TEXT,
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT research_memory_item_type_check
        CHECK (item_type IN ('paper', 'idea', 'failed_idea', 'claim', 'gap', 'experiment')),
    CONSTRAINT research_memory_item_payload_object_check
        CHECK (jsonb_typeof(payload_json) = 'object')
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_research_memory_item_project_type_key
    ON research_memory_item(project_id, item_type, stable_key);
CREATE INDEX IF NOT EXISTS idx_research_memory_item_project_type
    ON research_memory_item(project_id, item_type);
CREATE INDEX IF NOT EXISTS idx_research_memory_item_source_run
    ON research_memory_item(source_run_id);

CREATE TABLE IF NOT EXISTS research_memory_edge (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id UUID NOT NULL REFERENCES research_project(id) ON DELETE CASCADE,
    source_item_id UUID NOT NULL REFERENCES research_memory_item(id) ON DELETE CASCADE,
    target_item_id UUID NOT NULL REFERENCES research_memory_item(id) ON DELETE CASCADE,
    edge_type TEXT NOT NULL,
    evidence TEXT,
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT research_memory_edge_type_check
        CHECK (edge_type IN ('supports', 'contradicts', 'derived_from', 'tests', 'duplicates')),
    CONSTRAINT research_memory_edge_payload_object_check
        CHECK (jsonb_typeof(payload_json) = 'object')
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_research_memory_edge_unique
    ON research_memory_edge(source_item_id, target_item_id, edge_type);
CREATE INDEX IF NOT EXISTS idx_research_memory_edge_project
    ON research_memory_edge(project_id);
```

- [ ] **Step 2: Write failing DB tests**

Create `tests/test_research_memory.py`:

```python
from uuid import uuid4

import pytest

PROJECT_ID = uuid4()
RUN_ID = uuid4()
ITEM_ID = uuid4()
TARGET_ID = uuid4()


def _record(data):
    class FakeRecord(dict):
        def __iter__(self):
            return iter(self.items())

    return FakeRecord(data)


@pytest.mark.asyncio
async def test_upsert_memory_item(mock_pool):
    mock_pool.fetchrow.return_value = _record({
        "id": ITEM_ID,
        "project_id": PROJECT_ID,
        "source_run_id": RUN_ID,
        "item_type": "failed_idea",
        "stable_key": "weak-retrieval-idea",
        "title": "Weak Retrieval Idea",
        "status": "reject",
        "payload_json": {"quality_verdict": "reject"},
    })

    from apps.api.database import upsert_research_memory_item

    result = await upsert_research_memory_item({
        "project_id": PROJECT_ID,
        "source_run_id": RUN_ID,
        "item_type": "failed_idea",
        "stable_key": "weak-retrieval-idea",
        "title": "Weak Retrieval Idea",
        "status": "reject",
        "payload_json": {"quality_verdict": "reject"},
    })

    sql = mock_pool.fetchrow.call_args.args[0]
    assert "INSERT INTO research_memory_item" in sql
    assert "ON CONFLICT (project_id, item_type, stable_key)" in sql
    assert result["item_type"] == "failed_idea"


@pytest.mark.asyncio
async def test_list_memory_items_filters_by_type(mock_pool):
    mock_pool.fetch.return_value = [
        _record({"stable_key": "weak-retrieval-idea", "item_type": "failed_idea"}),
    ]

    from apps.api.database import list_research_memory_items

    result = await list_research_memory_items(PROJECT_ID, item_type="failed_idea", limit=10)

    sql = mock_pool.fetch.call_args.args[0]
    assert "FROM research_memory_item" in sql
    assert "item_type = $2" in sql
    assert result[0]["stable_key"] == "weak-retrieval-idea"


@pytest.mark.asyncio
async def test_create_memory_edge(mock_pool):
    mock_pool.fetchrow.return_value = _record({
        "id": uuid4(),
        "project_id": PROJECT_ID,
        "source_item_id": ITEM_ID,
        "target_item_id": TARGET_ID,
        "edge_type": "derived_from",
    })

    from apps.api.database import create_research_memory_edge

    result = await create_research_memory_edge({
        "project_id": PROJECT_ID,
        "source_item_id": ITEM_ID,
        "target_item_id": TARGET_ID,
        "edge_type": "derived_from",
        "evidence": "Generated from the recorded pain point.",
    })

    sql = mock_pool.fetchrow.call_args.args[0]
    assert "INSERT INTO research_memory_edge" in sql
    assert "ON CONFLICT (source_item_id, target_item_id, edge_type)" in sql
    assert result["edge_type"] == "derived_from"
```

Run:

```bash
PYTHONPATH=. pytest tests/test_research_memory.py -q
```

Expected: fails because DB helpers do not exist.

- [ ] **Step 3: Add DB helper module**

Create `apps/api/db/research_memory.py`:

```python
"""Database helpers for project-level research memory."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from apps.api.db import db


def _json_value(value: Any) -> str:
    return json.dumps(value or {})


async def upsert_research_memory_item(data: dict[str, Any]) -> dict[str, Any]:
    fields = [
        "project_id",
        "source_run_id",
        "item_type",
        "stable_key",
        "title",
        "status",
        "summary_text",
        "payload_json",
    ]
    columns = [field for field in fields if field in data]
    values = [
        _json_value(data[field]) if field == "payload_json" else data[field]
        for field in columns
    ]
    param_sql = [f"${index}" for index in range(1, len(values) + 1)]
    updates = [
        f"{field} = EXCLUDED.{field}"
        for field in columns
        if field not in {"project_id", "item_type", "stable_key"}
    ]
    updates.append("updated_at = NOW()")
    query = f"""
        INSERT INTO research_memory_item ({", ".join(columns)})
        VALUES ({", ".join(param_sql)})
        ON CONFLICT (project_id, item_type, stable_key)
        DO UPDATE SET {", ".join(updates)}
        RETURNING *
    """
    record = await db.fetchrow(query, *values)
    return dict(record)


async def list_research_memory_items(
    project_id: UUID,
    *,
    item_type: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    values: list[Any] = [project_id]
    filters = ["project_id = $1"]
    if item_type:
        values.append(item_type)
        filters.append(f"item_type = ${len(values)}")
    values.append(limit)
    query = f"""
        SELECT *
        FROM research_memory_item
        WHERE {" AND ".join(filters)}
        ORDER BY updated_at DESC
        LIMIT ${len(values)}
    """
    rows = await db.fetch(query, *values)
    return [dict(row) for row in rows]


async def create_research_memory_edge(data: dict[str, Any]) -> dict[str, Any]:
    fields = [
        "project_id",
        "source_item_id",
        "target_item_id",
        "edge_type",
        "evidence",
        "payload_json",
    ]
    columns = [field for field in fields if field in data]
    values = [
        _json_value(data[field]) if field == "payload_json" else data[field]
        for field in columns
    ]
    param_sql = [f"${index}" for index in range(1, len(values) + 1)]
    query = f"""
        INSERT INTO research_memory_edge ({", ".join(columns)})
        VALUES ({", ".join(param_sql)})
        ON CONFLICT (source_item_id, target_item_id, edge_type)
        DO UPDATE SET
            evidence = EXCLUDED.evidence,
            payload_json = EXCLUDED.payload_json
        RETURNING *
    """
    record = await db.fetchrow(query, *values)
    return dict(record)
```

- [ ] **Step 4: Export helpers**

In `apps/api/database.py`, add:

```python
from apps.api.db.research_memory import (
    create_research_memory_edge,
    list_research_memory_items,
    upsert_research_memory_item,
)
```

- [ ] **Step 5: Run DB tests and commit**

Run:

```bash
PYTHONPATH=. pytest tests/test_research_memory.py -q
```

Expected: the three DB tests pass.

Commit:

```bash
git add scripts/migration/011_research_memory.sql apps/api/db/research_memory.py apps/api/database.py tests/test_research_memory.py
git commit -m "feat: add research memory ledger tables"
```

## Task 3: Convert Mode State Into Memory Items

**Files:**
- Create: `services/research_memory.py`
- Test: `tests/test_research_memory.py`

- [ ] **Step 1: Write failing service tests**

Append to `tests/test_research_memory.py`:

```python
def test_memory_items_from_state_emits_paper_and_failed_idea():
    from apps.worker.modes.base import ModeGraphState
    from services.research_memory import memory_items_from_state

    state = ModeGraphState(
        project_id=str(PROJECT_ID),
        run_id=str(RUN_ID),
        topic="research agents",
        mode="divergent",
    )
    state.paper_summaries = [
        {
            "paper_id": "s2:123",
            "title": "Agentic Retrieval",
            "summary": "Retrieval systems for agents.",
        }
    ]
    state.idea_cards = [
        {
            "title": "Reviewer-Guided Retrieval",
            "problem_statement": "Agents cite plausible papers.",
            "dedup_key": "reviewer-guided-retrieval-agents-cite-plausible-papers",
            "quality_verdict": "reject",
            "strongest_objection": "Covered by verified prior art.",
        }
    ]

    items = memory_items_from_state(state)

    item_types = {item["item_type"] for item in items}
    assert "paper" in item_types
    assert "failed_idea" in item_types
    failed = next(item for item in items if item["item_type"] == "failed_idea")
    assert failed["stable_key"] == "reviewer-guided-retrieval-agents-cite-plausible-papers"
    assert failed["payload_json"]["strongest_objection"] == "Covered by verified prior art."
```

Run:

```bash
PYTHONPATH=. pytest tests/test_research_memory.py::test_memory_items_from_state_emits_paper_and_failed_idea -q
```

Expected: fails because `services.research_memory` does not exist.

- [ ] **Step 2: Add service module**

Create `services/research_memory.py`:

```python
"""Project-level research memory extraction and persistence."""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from apps.api.database import list_research_memory_items, upsert_research_memory_item
from apps.worker.modes.base import ModeGraphState


def _stable_key(*parts: object) -> str:
    raw = " ".join(str(part or "") for part in parts).lower()
    key = re.sub(r"[^a-z0-9:./-]+", "-", raw).strip("-")
    return key[:180] or "memory-item"


def _uuid(value: object) -> UUID:
    return UUID(str(value))


def memory_items_from_state(state: ModeGraphState) -> list[dict[str, Any]]:
    project_id = _uuid(state.project_id)
    run_id = _uuid(state.run_id)
    items: list[dict[str, Any]] = []

    for paper in getattr(state, "paper_summaries", []) or []:
        paper_id = paper.get("paper_id") or paper.get("id") or paper.get("title")
        title = paper.get("title") or str(paper_id)
        items.append({
            "project_id": project_id,
            "source_run_id": run_id,
            "item_type": "paper",
            "stable_key": _stable_key("paper", paper_id),
            "title": title,
            "status": "seen",
            "summary_text": paper.get("summary") or paper.get("tl_dr"),
            "payload_json": paper,
        })

    for gap in getattr(state, "pain_points", []) or []:
        title = gap.get("title") or gap.get("pain_point") or gap.get("description")
        items.append({
            "project_id": project_id,
            "source_run_id": run_id,
            "item_type": "gap",
            "stable_key": _stable_key("gap", title),
            "title": title,
            "status": gap.get("severity") or "observed",
            "summary_text": gap.get("description") or gap.get("pain_point"),
            "payload_json": gap,
        })

    for idea in getattr(state, "idea_cards", []) or []:
        quality = idea.get("quality_verdict") or idea.get("status") or "hold"
        item_type = "failed_idea" if quality == "reject" else "idea"
        title = idea.get("title") or "Untitled idea"
        items.append({
            "project_id": project_id,
            "source_run_id": run_id,
            "item_type": item_type,
            "stable_key": idea.get("dedup_key") or _stable_key("idea", title, idea.get("problem_statement")),
            "title": title,
            "status": quality,
            "summary_text": idea.get("problem_statement") or idea.get("strongest_objection"),
            "payload_json": idea,
        })

    for claim in getattr(state, "claims", []) or []:
        text = claim.get("claim") or claim.get("text")
        items.append({
            "project_id": project_id,
            "source_run_id": run_id,
            "item_type": "claim",
            "stable_key": _stable_key("claim", text),
            "title": text,
            "status": claim.get("status") or "draft",
            "summary_text": text,
            "payload_json": claim,
        })

    return items


async def persist_run_memory(state: ModeGraphState) -> list[dict[str, Any]]:
    saved: list[dict[str, Any]] = []
    for item in memory_items_from_state(state):
        saved.append(await upsert_research_memory_item(item))
    return saved


async def load_failed_idea_memory(project_id: object, *, limit: int = 20) -> list[dict[str, Any]]:
    return await list_research_memory_items(
        _uuid(project_id),
        item_type="failed_idea",
        limit=limit,
    )
```

- [ ] **Step 3: Run service test and commit**

Run:

```bash
PYTHONPATH=. pytest tests/test_research_memory.py::test_memory_items_from_state_emits_paper_and_failed_idea -q
```

Expected: test passes.

Commit:

```bash
git add services/research_memory.py tests/test_research_memory.py
git commit -m "feat: extract research memory from mode state"
```

## Task 4: Persist Memory From Worker Runs

**Files:**
- Modify: `apps/worker/runner.py`
- Test: `tests/test_runner_research_memory.py`

- [ ] **Step 1: Write failing worker integration tests**

Create `tests/test_runner_research_memory.py`:

```python
import logging

import pytest

from apps.worker.modes.base import ModeGraphState
from apps.worker.runner import Worker


@pytest.mark.asyncio
async def test_worker_persists_research_memory_after_outputs(monkeypatch):
    persisted = []

    async def fake_persist_run_memory(state):
        persisted.append(state.run_id)
        return []

    monkeypatch.setattr("apps.worker.runner.persist_run_memory", fake_persist_run_memory)

    worker = Worker()
    state = ModeGraphState(
        project_id="00000000-0000-0000-0000-000000000001",
        run_id="00000000-0000-0000-0000-000000000002",
        topic="research agents",
        mode="divergent",
    )

    await worker._persist_results(state)

    assert persisted == [state.run_id]


@pytest.mark.asyncio
async def test_worker_logs_memory_error_without_failing_run(monkeypatch, caplog):
    async def fake_persist_run_memory(state):
        raise RuntimeError("ledger unavailable")

    monkeypatch.setattr("apps.worker.runner.persist_run_memory", fake_persist_run_memory)

    worker = Worker()
    state = ModeGraphState(
        project_id="00000000-0000-0000-0000-000000000001",
        run_id="00000000-0000-0000-0000-000000000002",
        topic="research agents",
        mode="divergent",
    )

    with caplog.at_level(logging.WARNING):
        await worker._persist_results(state)

    assert "Failed to persist research memory" in caplog.text
```

Run:

```bash
PYTHONPATH=. pytest tests/test_runner_research_memory.py -q
```

Expected: fails because `runner.py` does not import or call `persist_run_memory()`.

- [ ] **Step 2: Import service**

In `apps/worker/runner.py`, add:

```python
from services.research_memory import persist_run_memory
```

- [ ] **Step 3: Persist ledger with isolated failure handling**

At the end of `Worker._persist_results()`, after existing output persistence, add:

```python
        try:
            await persist_run_memory(state)
        except Exception as exc:
            logger.warning("Failed to persist research memory for run %s: %s", state.run_id, exc)
```

- [ ] **Step 4: Run worker tests and commit**

Run:

```bash
PYTHONPATH=. pytest tests/test_runner_research_memory.py -q
```

Expected: tests pass.

Commit:

```bash
git add apps/worker/runner.py tests/test_runner_research_memory.py
git commit -m "feat: persist research memory after runs"
```

## Task 5: Feed Failed Idea Memory Into Divergent Composition

**Files:**
- Modify: `apps/worker/modes/divergent.py`
- Test: `tests/test_divergent_jury.py`

- [ ] **Step 1: Write failing prompt test**

Append to `tests/test_divergent_jury.py`:

```python
@pytest.mark.asyncio
async def test_idea_composition_includes_failed_idea_memory(monkeypatch):
    from apps.worker.modes.base import ModeGraphState
    from apps.worker.modes.divergent import idea_composition

    captured = {}

    async def fake_load_failed_idea_memory(project_id, limit=20):
        return [
            {
                "title": "Reviewer-Guided Retrieval",
                "summary_text": "Covered by verified prior art.",
                "payload_json": {
                    "strongest_objection": "Closest prior work already implements the mechanism."
                },
            }
        ]

    async def fake_generate_llm_json(**kwargs):
        captured["user_prompt"] = kwargs["user_prompt"]
        return {
            "ideas": [
                {
                    "title": "Audit-Gated Citation Planning",
                    "problem_statement": "Citations are not audited before manuscript submission.",
                }
            ]
        }

    monkeypatch.setattr(
        "apps.worker.modes.divergent.load_failed_idea_memory",
        fake_load_failed_idea_memory,
    )
    monkeypatch.setattr("apps.worker.modes.divergent.generate_llm_json", fake_generate_llm_json)

    state = ModeGraphState(
        project_id="00000000-0000-0000-0000-000000000001",
        run_id="00000000-0000-0000-0000-000000000002",
        topic="research agents",
        mode="divergent",
    )
    state.pain_points = [{"title": "Citation audit gap", "description": "Weak citation checks."}]
    state.context_bundle = {}

    await idea_composition(state)

    assert "Reviewer-Guided Retrieval" in captured["user_prompt"]
    assert "Closest prior work already implements the mechanism." in captured["user_prompt"]
```

Run:

```bash
PYTHONPATH=. pytest tests/test_divergent_jury.py::test_idea_composition_includes_failed_idea_memory -q
```

Expected: fails because `idea_composition()` does not load failed idea memory.

- [ ] **Step 2: Import memory loader**

In `apps/worker/modes/divergent.py`, add:

```python
from services.research_memory import load_failed_idea_memory
```

- [ ] **Step 3: Add failed memory to composition payload**

In `idea_composition()`, before building the LLM payload, add:

```python
failed_idea_memory = await load_failed_idea_memory(state.project_id, limit=20)
state.context_bundle["failed_idea_memory"] = failed_idea_memory
```

Include this field in the JSON payload passed to `generate_llm_json()`:

```python
"failed_idea_memory": [
    {
        "title": item.get("title"),
        "summary_text": item.get("summary_text"),
        "strongest_objection": (item.get("payload_json") or {}).get("strongest_objection"),
        "closest_prior_work": (item.get("payload_json") or {}).get("closest_prior_work", []),
    }
    for item in failed_idea_memory
],
```

Add this sentence to the existing idea-composition system prompt:

```python
"Do not recreate failed_idea_memory entries unless the new mechanism directly resolves the recorded strongest_objection."
```

- [ ] **Step 4: Run prompt test and commit**

Run:

```bash
PYTHONPATH=. pytest tests/test_divergent_jury.py::test_idea_composition_includes_failed_idea_memory -q
```

Expected: test passes.

Commit:

```bash
git add apps/worker/modes/divergent.py tests/test_divergent_jury.py
git commit -m "feat: use failed idea memory in divergent composition"
```

## Task 6: Final Verification And Branch Handoff

- [ ] **Step 1: Run focused suite**

Run:

```bash
PYTHONPATH=. pytest tests/test_research_memory.py tests/test_runner_research_memory.py tests/test_divergent_jury.py -q
```

Expected: all selected tests pass.

- [ ] **Step 2: Run diff check**

Run:

```bash
git diff --check
```

Expected: no whitespace errors.

- [ ] **Step 3: Show branch state**

Run:

```bash
git status --short
git log --oneline main..HEAD
```

Expected: working tree is clean and the branch contains four commits from this plan.
