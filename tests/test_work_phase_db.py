from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError


MIGRATION = Path("scripts/migration/015_topic_work_phase_artifacts.sql")


def _make_work_pool(
    fetchrow_return: Any = None,
    fetch_return: list[dict[str, Any]] | None = None,
) -> AsyncMock:
    pool = AsyncMock()
    pool.fetchrow = AsyncMock(return_value=fetchrow_return)
    pool.fetch = AsyncMock(return_value=fetch_return or [])
    pool.execute = AsyncMock()

    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=fetchrow_return)
    conn.fetch = AsyncMock(return_value=fetch_return or [])
    conn.execute = AsyncMock()

    tx = AsyncMock()
    tx.__aenter__ = AsyncMock(return_value=None)
    tx.__aexit__ = AsyncMock(return_value=False)
    conn.transaction = MagicMock(return_value=tx)

    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool.acquire = MagicMock(return_value=ctx)
    return pool


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


@pytest.mark.parametrize("field", ["title", "payload", "status", "selection_state"])
def test_work_schemas_reject_explicit_null_for_non_nullable_patch_fields(
    field: str,
) -> None:
    from libs.schemas.work import ArtifactCardPatch

    assert ArtifactCardPatch().model_dump(exclude_unset=True) == {}

    with pytest.raises(ValidationError):
        ArtifactCardPatch(**{field: None})

    assert ArtifactCardPatch(body=None).model_dump(exclude_unset=True) == {"body": None}


def test_work_db_module_exposes_core_operations() -> None:
    from apps.api.db import works

    assert callable(works.create_work)
    assert callable(works.list_works)
    assert callable(works.create_phase_execution)
    assert callable(works.create_artifact_card)
    assert callable(works.update_artifact_card)


@pytest.mark.asyncio
async def test_create_artifact_card_inserts_card_and_initial_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.api.db import works

    card_id = uuid4()
    work_id = uuid4()
    user_id = uuid4()
    pool = _make_work_pool()
    conn = pool.acquire.return_value.__aenter__.return_value
    conn.fetchrow.return_value = {
        "id": card_id,
        "work_id": work_id,
        "phase": "frontier",
        "artifact_type": "gap",
        "title": "Sparse labels",
        "body": "Few labels exist.",
        "payload": {"severity": "high"},
        "status": "active",
        "selection_state": "unselected",
        "source_execution_id": None,
        "source_card_ids": [],
        "created_by": user_id,
        "updated_by": user_id,
    }

    async def fake_get_pool() -> AsyncMock:
        return pool

    monkeypatch.setattr(works.db_pool, "get_pool", fake_get_pool)

    result = await works.create_artifact_card({
        "work_id": work_id,
        "phase": "frontier",
        "artifact_type": "gap",
        "title": "Sparse labels",
        "body": "Few labels exist.",
        "payload": {"severity": "high"},
        "created_by": user_id,
        "edit_source": "user",
    })

    assert result["id"] == card_id
    pool.acquire.assert_called_once()
    conn.transaction.assert_called_once()
    insert_card_sql = conn.fetchrow.call_args.args[0]
    assert "INSERT INTO artifact_card" in insert_card_sql
    assert conn.fetchrow.call_args.args[2] == work_id
    assert conn.fetchrow.call_args.args[4] == "gap"
    assert conn.fetchrow.call_args.args[7] == {"severity": "high"}

    insert_revision_sql = conn.execute.call_args.args[0]
    assert "INSERT INTO artifact_revision" in insert_revision_sql
    assert "VALUES ($1, 1, $2, $3, $4, $5, $6)" in insert_revision_sql
    assert conn.execute.call_args.args[1] == card_id
    assert conn.execute.call_args.args[2] == "Sparse labels"
    assert conn.execute.call_args.args[4] == {"severity": "high"}
    assert conn.execute.call_args.args[5] == "user"


@pytest.mark.asyncio
async def test_update_artifact_card_rejects_unknown_fields_before_db(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.api.db import works

    get_pool_called = False

    async def fake_get_pool() -> AsyncMock:
        nonlocal get_pool_called
        get_pool_called = True
        return _make_work_pool()

    monkeypatch.setattr(works.db_pool, "get_pool", fake_get_pool)

    with pytest.raises(ValueError, match="Invalid artifact_card update fields"):
        await works.update_artifact_card(uuid4(), {"workspace_id": uuid4()})

    assert get_pool_called is False


@pytest.mark.asyncio
async def test_update_artifact_card_revision_fields_insert_next_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.api.db import works

    card_id = uuid4()
    user_id = uuid4()
    updated_card = {
        "id": card_id,
        "work_id": uuid4(),
        "phase": "frontier",
        "artifact_type": "gap",
        "title": "Edited gap",
        "body": "Updated body",
        "payload": {"tags": ["novel", "risky"]},
        "status": "active",
        "selection_state": "selected",
    }
    pool = _make_work_pool()
    conn = pool.acquire.return_value.__aenter__.return_value
    conn.fetchrow.side_effect = [updated_card, {"revision_no": 4}]

    async def fake_get_pool() -> AsyncMock:
        return pool

    monkeypatch.setattr(works.db_pool, "get_pool", fake_get_pool)

    result = await works.update_artifact_card(
        card_id,
        {
            "title": "Edited gap",
            "body": "Updated body",
            "payload": {"tags": ("novel", "risky")},
            "updated_by": user_id,
        },
    )

    assert result == updated_card
    update_sql = conn.fetchrow.call_args_list[0].args[0]
    assert "UPDATE artifact_card SET title = $1, body = $2, payload = $3" in update_sql
    assert conn.fetchrow.call_args_list[0].args[3] == {"tags": ["novel", "risky"]}
    assert conn.fetchrow.call_args_list[0].args[5] == card_id

    next_revision_sql = conn.fetchrow.call_args_list[1].args[0]
    assert "COALESCE(MAX(revision_no), 0) + 1" in next_revision_sql
    insert_revision_sql = conn.execute.call_args.args[0]
    assert "INSERT INTO artifact_revision" in insert_revision_sql
    assert conn.execute.call_args.args[2] == 4
    assert conn.execute.call_args.args[3] == "Edited gap"
    assert conn.execute.call_args.args[4] == "Updated body"
    assert conn.execute.call_args.args[5] == {"tags": ["novel", "risky"]}
    assert conn.execute.call_args.args[6] == user_id


@pytest.mark.asyncio
async def test_list_artifact_cards_with_phase_filters_sql_and_args(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.api.db import works

    work_id = uuid4()
    row = {"id": uuid4(), "work_id": work_id, "phase": "frontier"}
    pool = _make_work_pool(fetch_return=[row])

    async def fake_get_pool() -> AsyncMock:
        return pool

    monkeypatch.setattr(works.db_pool, "get_pool", fake_get_pool)

    result = await works.list_artifact_cards(work_id, phase="frontier")

    assert result == [row]
    sql = pool.fetch.call_args.args[0]
    assert "WHERE work_id = $1 AND phase = $2 AND status != 'deleted'" in sql
    assert pool.fetch.call_args.args[1:] == (work_id, "frontier")


@pytest.mark.asyncio
async def test_upsert_phase_input_selection_conflicts_and_normalizes_manual_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.api.db import works

    work_id = uuid4()
    user_id = uuid4()
    source_card_ids = [uuid4()]
    returned = {
        "id": uuid4(),
        "work_id": work_id,
        "target_phase": "frontier",
        "source_card_ids": source_card_ids,
        "manual_input_json": {"criteria": ["novel", "feasible"]},
        "created_by": user_id,
    }
    pool = _make_work_pool(fetchrow_return=returned)

    async def fake_get_pool() -> AsyncMock:
        return pool

    monkeypatch.setattr(works.db_pool, "get_pool", fake_get_pool)

    result = await works.upsert_phase_input_selection(
        work_id=work_id,
        target_phase="frontier",
        source_card_ids=source_card_ids,
        manual_input_json={"criteria": ("novel", "feasible")},
        created_by=user_id,
    )

    assert result == returned
    sql = pool.fetchrow.call_args.args[0]
    assert "ON CONFLICT (work_id, target_phase) DO UPDATE SET" in sql
    assert pool.fetchrow.call_args.args[1:] == (
        work_id,
        "frontier",
        source_card_ids,
        {"criteria": ["novel", "feasible"]},
        user_id,
    )
