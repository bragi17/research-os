"""Database helpers for project-level research memory."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import orjson

from apps.api.db import pool as db_pool


def _jsonb_object(value: Any) -> dict[str, Any]:
    normalized = orjson.loads(orjson.dumps(value or {}))
    if not isinstance(normalized, dict):
        raise ValueError("payload_json must be a JSON object")
    return normalized


async def upsert_research_memory_item(data: dict[str, Any]) -> dict[str, Any]:
    """Insert or update one typed memory item."""
    payload_json = _jsonb_object(data.get("payload_json"))
    pool = await db_pool.get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO research_memory_item (
            project_id, source_run_id, item_type, stable_key,
            title, status, summary_text, payload_json
        ) VALUES (
            $1, $2, $3, $4,
            $5, $6, $7, $8
        )
        ON CONFLICT (project_id, item_type, stable_key)
        DO UPDATE SET
            source_run_id = EXCLUDED.source_run_id,
            title = EXCLUDED.title,
            status = EXCLUDED.status,
            summary_text = EXCLUDED.summary_text,
            payload_json = EXCLUDED.payload_json,
            updated_at = NOW()
        RETURNING *
        """,
        data["project_id"],
        data.get("source_run_id"),
        data["item_type"],
        data["stable_key"],
        data.get("title"),
        data.get("status"),
        data.get("summary_text"),
        payload_json,
    )
    return db_pool.record_to_dict(row)


async def list_research_memory_items(
    project_id: UUID,
    *,
    item_type: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """List project memory items, optionally filtered by item type."""
    values: list[Any] = [project_id]
    filters = ["project_id = $1"]
    if item_type:
        values.append(item_type)
        filters.append(f"item_type = ${len(values)}")
    values.append(limit)

    pool = await db_pool.get_pool()
    rows = await pool.fetch(
        f"""
        SELECT *
        FROM research_memory_item
        WHERE {" AND ".join(filters)}
        ORDER BY updated_at DESC
        LIMIT ${len(values)}
        """,
        *values,
    )
    return [db_pool.record_to_dict(row) for row in rows]


async def create_research_memory_edge(data: dict[str, Any]) -> dict[str, Any]:
    """Insert or update a typed edge between two memory items."""
    payload_json = _jsonb_object(data.get("payload_json"))
    pool = await db_pool.get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO research_memory_edge (
            project_id, source_item_id, target_item_id,
            edge_type, evidence, payload_json
        )
        SELECT
            source_item.project_id,
            source_item.id,
            target_item.id,
            $4,
            $5,
            $6
        FROM research_memory_item source_item
        JOIN research_memory_item target_item
            ON target_item.id = $2
            AND target_item.project_id = source_item.project_id
        WHERE source_item.id = $1
            AND source_item.project_id = $3
        ON CONFLICT (source_item_id, target_item_id, edge_type)
        DO UPDATE SET
            evidence = EXCLUDED.evidence,
            payload_json = EXCLUDED.payload_json
        RETURNING *
        """,
        data["source_item_id"],
        data["target_item_id"],
        data["project_id"],
        data["edge_type"],
        data.get("evidence"),
        payload_json,
    )
    if row is None:
        raise ValueError("Memory edge endpoints must belong to the same project")
    return db_pool.record_to_dict(row)
