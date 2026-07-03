"""Topic work and phase artifact database operations."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import orjson

from apps.api.db import pool as db_pool


PHASE_EXECUTION_UPDATE_FIELDS = {
    "status",
    "backing_run_id",
    "output_bundle_id",
    "error_message",
    "started_at",
    "completed_at",
    "updated_at",
}

ARTIFACT_CARD_UPDATE_FIELDS = {
    "title",
    "body",
    "payload",
    "status",
    "selection_state",
    "source_execution_id",
    "source_card_ids",
    "updated_by",
    "updated_at",
}

ARTIFACT_REVISION_FIELDS = {"title", "body", "payload"}


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


async def list_works(
    workspace_id: UUID,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
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
        """
        SELECT * FROM research_work
        WHERE id = $1 AND workspace_id = $2 AND status != 'deleted'
        """,
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


async def update_phase_execution(
    execution_id: UUID,
    updates: dict[str, Any],
) -> dict[str, Any] | None:
    invalid = set(updates) - PHASE_EXECUTION_UPDATE_FIELDS
    if invalid:
        raise ValueError(f"Invalid phase_execution update fields: {sorted(invalid)}")
    if not updates:
        return None

    values = list(updates.values())
    set_parts = [f"{key} = ${idx}" for idx, key in enumerate(updates, start=1)]
    values.append(execution_id)

    pool = await db_pool.get_pool()
    row = await pool.fetchrow(
        f"UPDATE phase_execution SET {', '.join(set_parts)} "  # nosec B608
        f"WHERE id = ${len(values)} RETURNING *",
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
                ) VALUES (
                    $1, $2, $3, $4, $5, $6, $7,
                    'active', 'unselected', $8, $9, $10, $10
                )
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
                    artifact_card_id, revision_no, title, body, payload,
                    edit_source, edited_by
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


async def list_artifact_cards(
    work_id: UUID,
    phase: str | None = None,
) -> list[dict[str, Any]]:
    pool = await db_pool.get_pool()
    if phase is not None:
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


async def _get_artifact_card(card_id: UUID) -> dict[str, Any] | None:
    pool = await db_pool.get_pool()
    row = await pool.fetchrow(
        "SELECT * FROM artifact_card WHERE id = $1",
        card_id,
    )
    return db_pool.record_to_dict(row) if row else None


def _prepare_artifact_card_value(field: str, value: Any) -> Any:
    if field == "payload":
        return _json(value)
    return value


async def update_artifact_card(
    card_id: UUID,
    updates: dict[str, Any],
) -> dict[str, Any] | None:
    if not updates:
        return await _get_artifact_card(card_id)

    invalid = set(updates) - ARTIFACT_CARD_UPDATE_FIELDS
    if invalid:
        raise ValueError(f"Invalid artifact_card update fields: {sorted(invalid)}")

    set_parts: list[str] = []
    values: list[Any] = []
    for idx, (col, val) in enumerate(updates.items(), start=1):
        set_parts.append(f"{col} = ${idx}")
        values.append(_prepare_artifact_card_value(col, val))

    values.append(card_id)
    query = (
        f"UPDATE artifact_card SET {', '.join(set_parts)} "  # nosec B608
        f"WHERE id = ${len(values)} RETURNING *"
    )
    revision_needed = bool(set(updates) & ARTIFACT_REVISION_FIELDS)

    pool = await db_pool.get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(query, *values)
            if row is None:
                return None

            card = db_pool.record_to_dict(row)
            if revision_needed:
                revision_row = await conn.fetchrow(
                    """
                    SELECT COALESCE(MAX(revision_no), 0) + 1 AS revision_no
                    FROM artifact_revision
                    WHERE artifact_card_id = $1
                    """,
                    card_id,
                )
                await conn.execute(
                    """
                    INSERT INTO artifact_revision (
                        artifact_card_id, revision_no, title, body, payload,
                        edit_source, edited_by
                    ) VALUES ($1, $2, $3, $4, $5, 'user', $6)
                    """,
                    card["id"],
                    revision_row["revision_no"],
                    card["title"],
                    card.get("body"),
                    _json(card.get("payload", {})),
                    updates.get("updated_by"),
                )
            return card


async def upsert_phase_input_selection(
    work_id: UUID,
    target_phase: str,
    source_card_ids: list[UUID],
    manual_input_json: dict[str, Any],
    created_by: UUID | None = None,
) -> dict[str, Any]:
    pool = await db_pool.get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO phase_input_selection (
            work_id, target_phase, source_card_ids, manual_input_json, created_by
        ) VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (work_id, target_phase) DO UPDATE SET
            source_card_ids = EXCLUDED.source_card_ids,
            manual_input_json = EXCLUDED.manual_input_json,
            updated_at = NOW()
        RETURNING *
        """,
        work_id,
        target_phase,
        source_card_ids,
        _json(manual_input_json),
        created_by,
    )
    return db_pool.record_to_dict(row)
