"""Research run database operations."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from apps.api.db import pool as db_pool


async def create_run(run_data: dict[str, Any]) -> dict[str, Any]:
    """INSERT a new research_run and return the created row."""
    pool = await db_pool.get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO research_run (
            id, workspace_id, created_by, title, topic, status,
            goal_type, autonomy_mode, budget_json, policy_json,
            current_step, progress_pct, started_at, completed_at,
            created_at, updated_at,
            mode, parent_run_id, context_bundle_id, current_stage,
            project_id
        ) VALUES (
            $1, $2, $3, $4, $5, $6,
            $7, $8, $9, $10,
            $11, $12, $13, $14,
            $15, $16,
            $17, $18, $19, $20,
            $21
        )
        RETURNING *
        """,
        run_data["id"],
        run_data.get("workspace_id", UUID("00000000-0000-0000-0000-000000000000")),
        run_data.get("created_by", UUID("00000000-0000-0000-0000-000000000000")),
        run_data["title"],
        run_data["topic"],
        run_data["status"],
        run_data["goal_type"],
        run_data.get("autonomy_mode", "default_autonomous"),
        run_data.get("budget_json", {}),
        run_data.get("policy_json", {}),
        run_data.get("current_step"),
        run_data.get("progress_pct", 0),
        run_data.get("started_at"),
        run_data.get("completed_at"),
        run_data["created_at"],
        run_data["updated_at"],
        run_data.get("mode", "atlas"),
        run_data.get("parent_run_id"),
        run_data.get("context_bundle_id"),
        run_data.get("current_stage"),
        run_data.get("project_id"),
    )
    return db_pool.record_to_dict(row)


async def get_run(
    run_id: UUID,
    workspace_id: UUID | None = None,
) -> dict[str, Any] | None:
    """SELECT a single research_run by ID."""
    pool = await db_pool.get_pool()
    if workspace_id is not None:
        row = await pool.fetchrow(
            "SELECT * FROM research_run WHERE id = $1 AND workspace_id = $2",
            run_id,
            workspace_id,
        )
    else:
        row = await pool.fetchrow(
            "SELECT * FROM research_run WHERE id = $1",
            run_id,
        )
    if row is None:
        return None
    return db_pool.record_to_dict(row)


async def list_runs(
    status: str | None = None,
    limit: int = 20,
    offset: int = 0,
    workspace_id: UUID | None = None,
) -> list[dict[str, Any]]:
    """SELECT research_runs with optional status filter."""
    pool = await db_pool.get_pool()
    if status is not None and workspace_id is not None:
        rows = await pool.fetch(
            """
            SELECT * FROM research_run
            WHERE status = $1 AND workspace_id = $2
            ORDER BY created_at DESC
            LIMIT $3 OFFSET $4
            """,
            status,
            workspace_id,
            limit,
            offset,
        )
    elif status is not None:
        rows = await pool.fetch(
            """
            SELECT * FROM research_run
            WHERE status = $1
            ORDER BY created_at DESC
            LIMIT $2 OFFSET $3
            """,
            status,
            limit,
            offset,
        )
    elif workspace_id is not None:
        rows = await pool.fetch(
            """
            SELECT * FROM research_run
            WHERE workspace_id = $1
            ORDER BY created_at DESC
            LIMIT $2 OFFSET $3
            """,
            workspace_id,
            limit,
            offset,
        )
    else:
        rows = await pool.fetch(
            """
            SELECT * FROM research_run
            ORDER BY created_at DESC
            LIMIT $1 OFFSET $2
            """,
            limit,
            offset,
        )
    return [db_pool.record_to_dict(row) for row in rows]


_RUN_UPDATABLE_COLUMNS = frozenset({
    "title",
    "status",
    "current_step",
    "progress_pct",
    "started_at",
    "completed_at",
    "updated_at",
    "pause_reason",
    "mode",
    "current_stage",
    "budget_json",
    "policy_json",
    "context_bundle_id",
    "output_bundle_id",
})


async def update_run(
    run_id: UUID,
    updates: dict[str, Any],
) -> dict[str, Any] | None:
    """UPDATE specific columns on a research_run and return the updated row."""
    if not updates:
        return await get_run(run_id)

    invalid = set(updates.keys()) - _RUN_UPDATABLE_COLUMNS
    if invalid:
        raise ValueError(f"Invalid column names: {invalid}")

    set_parts: list[str] = []
    values: list[Any] = []
    idx = 1
    for col, val in updates.items():
        set_parts.append(f"{col} = ${idx}")
        values.append(val)
        idx += 1

    values.append(run_id)
    query = (
        f"UPDATE research_run SET {', '.join(set_parts)} "  # nosec B608
        f"WHERE id = ${idx} RETURNING *"
    )
    pool = await db_pool.get_pool()
    row = await pool.fetchrow(query, *values)
    if row is None:
        return None
    return db_pool.record_to_dict(row)


async def delete_run(run_id: UUID) -> bool:
    """DELETE a research_run by ID."""
    pool = await db_pool.get_pool()
    result = await pool.execute(
        "DELETE FROM research_run WHERE id = $1",
        run_id,
    )
    return result.endswith("1")


async def count_runs(
    status: str | None = None,
    workspace_id: UUID | None = None,
) -> int:
    """Return the total number of runs, optionally filtered by status."""
    pool = await db_pool.get_pool()
    if status is not None and workspace_id is not None:
        row = await pool.fetchrow(
            """
            SELECT COUNT(*) AS cnt
            FROM research_run
            WHERE status = $1 AND workspace_id = $2
            """,
            status,
            workspace_id,
        )
    elif status is not None:
        row = await pool.fetchrow(
            "SELECT COUNT(*) AS cnt FROM research_run WHERE status = $1",
            status,
        )
    elif workspace_id is not None:
        row = await pool.fetchrow(
            "SELECT COUNT(*) AS cnt FROM research_run WHERE workspace_id = $1",
            workspace_id,
        )
    else:
        row = await pool.fetchrow("SELECT COUNT(*) AS cnt FROM research_run")
    return row["cnt"]


async def count_runs_by_status(
    workspace_id: UUID | None = None,
) -> dict[str, int]:
    """Return a mapping of status to count for all runs."""
    pool = await db_pool.get_pool()
    if workspace_id is not None:
        rows = await pool.fetch(
            """
            SELECT status, COUNT(*) AS cnt
            FROM research_run
            WHERE workspace_id = $1
            GROUP BY status
            """,
            workspace_id,
        )
    else:
        rows = await pool.fetch(
            "SELECT status, COUNT(*) AS cnt FROM research_run GROUP BY status"
        )
    return {row["status"]: row["cnt"] for row in rows}
