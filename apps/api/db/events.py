"""Run event database operations."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from apps.api.db import pool as db_pool


async def create_event(
    run_id: UUID,
    event_type: str,
    severity: str = "info",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """INSERT a new run_event and return the created row."""
    pool = await db_pool.get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO run_event (run_id, event_type, severity, payload)
        VALUES ($1, $2, $3, $4)
        RETURNING *
        """,
        run_id,
        event_type,
        severity,
        payload or {},
    )
    return db_pool.record_to_dict(row)


async def list_events(
    run_id: UUID,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """SELECT run_events for a given run, newest first."""
    pool = await db_pool.get_pool()
    rows = await pool.fetch(
        """
        SELECT * FROM run_event
        WHERE run_id = $1
        ORDER BY created_at DESC
        LIMIT $2 OFFSET $3
        """,
        run_id,
        limit,
        offset,
    )
    return [db_pool.record_to_dict(row) for row in rows]


async def count_events(run_id: UUID) -> int:
    """Return the total number of events for a given run."""
    pool = await db_pool.get_pool()
    row = await pool.fetchrow(
        "SELECT COUNT(*) AS cnt FROM run_event WHERE run_id = $1",
        run_id,
    )
    return row["cnt"]
