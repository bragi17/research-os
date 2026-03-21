"""
Research OS - Database Access Layer

Provides async CRUD operations for the Research OS API using asyncpg connection pooling.
All queries use parameterized statements to prevent SQL injection.
"""

from __future__ import annotations

import os
from typing import Any
from uuid import UUID

import asyncpg
import orjson
from structlog import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Connection Pool Management
# ---------------------------------------------------------------------------

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    """Return the global connection pool, creating it via init_pool() on first call."""
    global _pool
    if _pool is None:
        return await init_pool()
    return _pool


async def close_pool() -> None:
    """Gracefully close the connection pool."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _uuid(value: Any) -> str:
    """Ensure a UUID value is returned as a string."""
    if isinstance(value, UUID):
        return str(value)
    return str(value)


def _record_to_dict(record: asyncpg.Record) -> dict[str, Any]:
    """Convert an asyncpg Record to a plain dict with str UUIDs."""
    row: dict[str, Any] = dict(record)
    for key, value in row.items():
        if isinstance(value, UUID):
            row[key] = value
        # asyncpg returns JSONB as str when using default codec;
        # with the orjson init_codec below it returns dicts already.
    return row


def _json_serializer(obj: Any) -> str:
    return orjson.dumps(obj).decode("utf-8")


async def _init_codecs(conn: asyncpg.Connection) -> None:
    """Register JSON codecs on a fresh connection."""
    await conn.set_type_codec(
        "jsonb",
        encoder=_json_serializer,
        decoder=orjson.loads,
        schema="pg_catalog",
    )
    await conn.set_type_codec(
        "json",
        encoder=_json_serializer,
        decoder=orjson.loads,
        schema="pg_catalog",
    )


async def init_pool() -> asyncpg.Pool:
    """Create the pool with JSON codecs pre-registered on every connection."""
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            dsn=os.getenv(
                "DATABASE_URL",
                "postgresql://ros_user:ros_pass@localhost:5432/research_os",
            ),
            min_size=2,
            max_size=10,
            init=_init_codecs,
        )
    return _pool


# ---------------------------------------------------------------------------
# Research Run CRUD
# ---------------------------------------------------------------------------


async def create_run(run_data: dict[str, Any]) -> dict[str, Any]:
    """INSERT a new research_run and return the created row."""
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO research_run (
            id, workspace_id, created_by, title, topic, status,
            goal_type, autonomy_mode, budget_json, policy_json,
            current_step, progress_pct, started_at, completed_at,
            created_at, updated_at,
            mode, parent_run_id, context_bundle_id, current_stage
        ) VALUES (
            $1, $2, $3, $4, $5, $6,
            $7, $8, $9, $10,
            $11, $12, $13, $14,
            $15, $16,
            $17, $18, $19, $20
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
    )
    return _record_to_dict(row)


async def get_run(run_id: UUID) -> dict[str, Any] | None:
    """SELECT a single research_run by ID."""
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT * FROM research_run WHERE id = $1",
        run_id,
    )
    if row is None:
        return None
    return _record_to_dict(row)


async def list_runs(
    status: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """SELECT research_runs with optional status filter, ordered by created_at DESC."""
    pool = await get_pool()
    if status is not None:
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
    return [_record_to_dict(r) for r in rows]


_RUN_UPDATABLE_COLUMNS = frozenset({
    "title", "status", "current_step", "progress_pct", "started_at", "completed_at",
    "updated_at", "pause_reason", "mode", "current_stage", "budget_json",
    "policy_json", "context_bundle_id", "output_bundle_id",
})


async def update_run(
    run_id: UUID,
    updates: dict[str, Any],
) -> dict[str, Any] | None:
    """UPDATE specific columns on a research_run and return the updated row.

    Only the keys present in *updates* are written. The ``updated_at`` column
    is handled automatically by the database trigger, but we also set it
    explicitly for consistency.
    """
    if not updates:
        return await get_run(run_id)

    # Validate column names against whitelist
    invalid = set(updates.keys()) - _RUN_UPDATABLE_COLUMNS
    if invalid:
        raise ValueError(f"Invalid column names: {invalid}")

    # Build dynamic SET clause
    set_parts: list[str] = []
    values: list[Any] = []
    idx = 1
    for col, val in updates.items():
        set_parts.append(f"{col} = ${idx}")
        values.append(val)
        idx += 1

    values.append(run_id)
    query = (
        f"UPDATE research_run SET {', '.join(set_parts)} "
        f"WHERE id = ${idx} RETURNING *"
    )
    pool = await get_pool()
    row = await pool.fetchrow(query, *values)
    if row is None:
        return None
    return _record_to_dict(row)


async def delete_run(run_id: UUID) -> bool:
    """DELETE a research_run by ID. Returns True if a row was deleted."""
    pool = await get_pool()
    result = await pool.execute(
        "DELETE FROM research_run WHERE id = $1",
        run_id,
    )
    # asyncpg returns e.g. "DELETE 1" or "DELETE 0"
    return result.endswith("1")


async def count_runs(status: str | None = None) -> int:
    """Return the total number of runs, optionally filtered by status."""
    pool = await get_pool()
    if status is not None:
        row = await pool.fetchrow(
            "SELECT COUNT(*) AS cnt FROM research_run WHERE status = $1",
            status,
        )
    else:
        row = await pool.fetchrow("SELECT COUNT(*) AS cnt FROM research_run")
    return row["cnt"]


async def count_runs_by_status() -> dict[str, int]:
    """Return a mapping of status -> count for all runs."""
    pool = await get_pool()
    rows = await pool.fetch(
        "SELECT status, COUNT(*) AS cnt FROM research_run GROUP BY status"
    )
    return {r["status"]: r["cnt"] for r in rows}


# ---------------------------------------------------------------------------
# Run Event CRUD
# ---------------------------------------------------------------------------


async def create_event(
    run_id: UUID,
    event_type: str,
    severity: str = "info",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """INSERT a new run_event and return the created row."""
    pool = await get_pool()
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
    return _record_to_dict(row)


async def list_events(
    run_id: UUID,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """SELECT run_events for a given run, newest first."""
    pool = await get_pool()
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
    return [_record_to_dict(r) for r in rows]


async def count_events(run_id: UUID) -> int:
    """Return the total number of events for a given run."""
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT COUNT(*) AS cnt FROM run_event WHERE run_id = $1",
        run_id,
    )
    return row["cnt"]


# ---------------------------------------------------------------------------
# Hypothesis CRUD
# ---------------------------------------------------------------------------


async def list_hypotheses(run_id: UUID) -> list[dict[str, Any]]:
    """SELECT all hypotheses for a given run."""
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT * FROM hypothesis
        WHERE run_id = $1
        ORDER BY created_at ASC
        """,
        run_id,
    )
    return [_record_to_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Paper CRUD
# ---------------------------------------------------------------------------


async def list_papers_by_run(
    run_id: UUID,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """SELECT papers associated with a run via topic_cluster membership.

    The path is:  research_run -> topic_cluster -> paper_cluster_membership -> paper.
    """
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT DISTINCT p.*
        FROM paper p
        JOIN paper_cluster_membership pcm ON pcm.paper_id = p.id
        JOIN topic_cluster tc ON tc.id = pcm.cluster_id
        WHERE tc.run_id = $1
        ORDER BY p.publication_year DESC NULLS LAST
        LIMIT $2 OFFSET $3
        """,
        run_id,
        limit,
        offset,
    )
    return [_record_to_dict(r) for r in rows]


async def count_papers_by_run(run_id: UUID) -> int:
    """Return the count of papers associated with a run."""
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        SELECT COUNT(DISTINCT p.id) AS cnt
        FROM paper p
        JOIN paper_cluster_membership pcm ON pcm.paper_id = p.id
        JOIN topic_cluster tc ON tc.id = pcm.cluster_id
        WHERE tc.run_id = $1
        """,
        run_id,
    )
    return row["cnt"]


# ---------------------------------------------------------------------------
# Pain Point CRUD  (merged from database_v2)
# ---------------------------------------------------------------------------


async def create_pain_point(
    run_id: UUID,
    data: dict[str, Any],
) -> dict[str, Any]:
    """INSERT a new pain_point and return the created row."""
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO pain_point (
            run_id, cluster_id, statement, pain_type,
            supporting_paper_ids, counter_evidence_paper_ids,
            severity_score, novelty_potential
        ) VALUES (
            $1, $2, $3, $4,
            $5, $6,
            $7, $8
        )
        RETURNING *
        """,
        run_id,
        data.get("cluster_id"),
        data["statement"],
        data.get("pain_type", "general"),
        data.get("supporting_paper_ids", []),
        data.get("counter_evidence_paper_ids", []),
        data.get("severity_score", 0.0),
        data.get("novelty_potential", 0.0),
    )
    return _record_to_dict(row)


async def list_pain_points(
    run_id: UUID,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """SELECT pain_points for a given run, newest first."""
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT * FROM pain_point
        WHERE run_id = $1
        ORDER BY created_at DESC
        LIMIT $2 OFFSET $3
        """,
        run_id,
        limit,
        offset,
    )
    return [_record_to_dict(r) for r in rows]


async def count_pain_points(run_id: UUID) -> int:
    """Return the total number of pain_points for a given run."""
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT COUNT(*) AS cnt FROM pain_point WHERE run_id = $1",
        run_id,
    )
    return row["cnt"]


# ---------------------------------------------------------------------------
# Idea Card CRUD  (merged from database_v2)
# ---------------------------------------------------------------------------


async def create_idea_card(
    run_id: UUID,
    data: dict[str, Any],
) -> dict[str, Any]:
    """INSERT a new idea_card and return the created row."""
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO idea_card (
            run_id, title, problem_statement,
            source_pain_point_ids, borrowed_methods, source_domains,
            mechanism_of_transfer, expected_benefit,
            risks, required_experiments,
            prior_art_check_status, novelty_score, feasibility_score,
            status
        ) VALUES (
            $1, $2, $3,
            $4, $5, $6,
            $7, $8,
            $9, $10,
            $11, $12, $13,
            $14
        )
        RETURNING *
        """,
        run_id,
        data["title"],
        data.get("problem_statement"),
        data.get("source_pain_point_ids", []),
        data.get("borrowed_methods", []),
        data.get("source_domains", []),
        data.get("mechanism_of_transfer"),
        data.get("expected_benefit"),
        data.get("risks", []),
        data.get("required_experiments", []),
        data.get("prior_art_check_status", "pending"),
        data.get("novelty_score"),
        data.get("feasibility_score"),
        data.get("status", "candidate"),
    )
    return _record_to_dict(row)


async def list_idea_cards(
    run_id: UUID,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """SELECT idea_cards for a given run, newest first."""
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT * FROM idea_card
        WHERE run_id = $1
        ORDER BY created_at DESC
        LIMIT $2 OFFSET $3
        """,
        run_id,
        limit,
        offset,
    )
    return [_record_to_dict(r) for r in rows]


async def count_idea_cards(run_id: UUID) -> int:
    """Return the total number of idea_cards for a given run."""
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT COUNT(*) AS cnt FROM idea_card WHERE run_id = $1",
        run_id,
    )
    return row["cnt"]


async def update_idea_card(
    idea_id: UUID,
    updates: dict[str, Any],
) -> dict[str, Any] | None:
    """UPDATE specific columns on an idea_card and return the updated row.

    Only the keys present in *updates* are written.
    """
    if not updates:
        pool = await get_pool()
        row = await pool.fetchrow(
            "SELECT * FROM idea_card WHERE id = $1",
            idea_id,
        )
        return _record_to_dict(row) if row else None

    set_parts: list[str] = []
    values: list[Any] = []
    idx = 1
    for col, val in updates.items():
        set_parts.append(f"{col} = ${idx}")
        values.append(val)
        idx += 1

    values.append(idea_id)
    query = (
        f"UPDATE idea_card SET {', '.join(set_parts)} "
        f"WHERE id = ${idx} RETURNING *"
    )
    pool = await get_pool()
    row = await pool.fetchrow(query, *values)
    if row is None:
        return None
    return _record_to_dict(row)


# ---------------------------------------------------------------------------
# Context Bundle CRUD  (merged from database_v2)
# ---------------------------------------------------------------------------


async def create_context_bundle(
    data: dict[str, Any],
) -> dict[str, Any]:
    """INSERT a new context_bundle and return the created row."""
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO context_bundle (
            source_run_id, source_mode, summary_text,
            selected_paper_ids, cluster_ids, figure_ids,
            pain_point_ids, idea_card_ids,
            benchmark_data, mindmap_json, user_annotations
        ) VALUES (
            $1, $2, $3,
            $4, $5, $6,
            $7, $8,
            $9, $10, $11
        )
        RETURNING *
        """,
        data.get("source_run_id"),
        data.get("source_mode"),
        data.get("summary_text"),
        data.get("selected_paper_ids", []),
        data.get("cluster_ids", []),
        data.get("figure_ids", []),
        data.get("pain_point_ids", []),
        data.get("idea_card_ids", []),
        data.get("benchmark_data"),
        data.get("mindmap_json"),
        data.get("user_annotations"),
    )
    return _record_to_dict(row)


async def get_context_bundle(
    bundle_id: UUID,
) -> dict[str, Any] | None:
    """SELECT a single context_bundle by ID."""
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT * FROM context_bundle WHERE id = $1",
        bundle_id,
    )
    if row is None:
        return None
    return _record_to_dict(row)


# ---------------------------------------------------------------------------
# Figure Asset CRUD  (merged from database_v2)
# ---------------------------------------------------------------------------


async def create_figure_asset(
    paper_id: UUID,
    data: dict[str, Any],
) -> dict[str, Any]:
    """INSERT a new figure_asset and return the created row."""
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO figure_asset (
            paper_id, source_type, page_no, caption,
            image_path, figure_type, related_section,
            license_note, extraction_confidence
        ) VALUES (
            $1, $2, $3, $4,
            $5, $6, $7,
            $8, $9
        )
        RETURNING *
        """,
        paper_id,
        data.get("source_type"),
        data.get("page_no"),
        data.get("caption"),
        data.get("image_path"),
        data.get("figure_type"),
        data.get("related_section"),
        data.get("license_note"),
        data.get("extraction_confidence"),
    )
    return _record_to_dict(row)


async def list_figures_by_paper(
    paper_id: UUID,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """SELECT figure_assets for a given paper."""
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT * FROM figure_asset
        WHERE paper_id = $1
        ORDER BY page_no ASC NULLS LAST
        LIMIT $2
        """,
        paper_id,
        limit,
    )
    return [_record_to_dict(r) for r in rows]


async def list_figures_by_run(
    run_id: UUID,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """SELECT figure_assets associated with a run via paper -> cluster -> run."""
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT DISTINCT fa.*
        FROM figure_asset fa
        JOIN paper p ON p.id = fa.paper_id
        JOIN paper_cluster_membership pcm ON pcm.paper_id = p.id
        JOIN topic_cluster tc ON tc.id = pcm.cluster_id
        WHERE tc.run_id = $1
        ORDER BY fa.created_at DESC
        LIMIT $2
        """,
        run_id,
        limit,
    )
    return [_record_to_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Research Domain CRUD  (merged from database_v2)
# ---------------------------------------------------------------------------


async def create_domain(
    data: dict[str, Any],
) -> dict[str, Any]:
    """INSERT a new research_domain and return the created row."""
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO research_domain (
            name, aliases, parent_domain_id,
            description_short, description_detailed,
            keywords, representative_venues,
            representative_datasets, representative_methods,
            canonical_paper_ids, recent_frontier_paper_ids,
            prerequisite_domain_ids
        ) VALUES (
            $1, $2, $3,
            $4, $5,
            $6, $7,
            $8, $9,
            $10, $11,
            $12
        )
        RETURNING *
        """,
        data["name"],
        data.get("aliases", []),
        data.get("parent_domain_id"),
        data.get("description_short"),
        data.get("description_detailed"),
        data.get("keywords", []),
        data.get("representative_venues", []),
        data.get("representative_datasets", []),
        data.get("representative_methods", []),
        data.get("canonical_paper_ids", []),
        data.get("recent_frontier_paper_ids", []),
        data.get("prerequisite_domain_ids", []),
    )
    return _record_to_dict(row)


async def get_domain(
    domain_id: UUID,
) -> dict[str, Any] | None:
    """SELECT a single research_domain by ID."""
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT * FROM research_domain WHERE id = $1",
        domain_id,
    )
    if row is None:
        return None
    return _record_to_dict(row)


async def list_domains(
    parent_id: UUID | None = None,
) -> list[dict[str, Any]]:
    """SELECT research_domains, optionally filtered by parent_domain_id."""
    pool = await get_pool()
    if parent_id is not None:
        rows = await pool.fetch(
            """
            SELECT * FROM research_domain
            WHERE parent_domain_id = $1
            ORDER BY name ASC
            """,
            parent_id,
        )
    else:
        rows = await pool.fetch(
            """
            SELECT * FROM research_domain
            ORDER BY name ASC
            """
        )
    return [_record_to_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Reading Path CRUD  (merged from database_v2)
# ---------------------------------------------------------------------------


async def create_reading_path(
    run_id: UUID,
    data: dict[str, Any],
) -> dict[str, Any]:
    """INSERT a new reading_path and return the created row."""
    pool = await get_pool()

    # ordered_units is JSONB, serialise with orjson if not already done
    ordered_units = data.get("ordered_units")
    if ordered_units is not None and not isinstance(ordered_units, str):
        ordered_units = orjson.loads(orjson.dumps(ordered_units))

    row = await pool.fetchrow(
        """
        INSERT INTO reading_path (
            run_id, domain_id, difficulty_level,
            ordered_units, estimated_hours,
            goal, generated_rationale
        ) VALUES (
            $1, $2, $3,
            $4, $5,
            $6, $7
        )
        RETURNING *
        """,
        run_id,
        data.get("domain_id"),
        data.get("difficulty_level"),
        ordered_units,
        data.get("estimated_hours"),
        data.get("goal"),
        data.get("generated_rationale"),
    )
    return _record_to_dict(row)


async def get_reading_path(
    run_id: UUID,
) -> dict[str, Any] | None:
    """SELECT the reading_path for a given run (one path per run expected)."""
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT * FROM reading_path WHERE run_id = $1",
        run_id,
    )
    if row is None:
        return None
    return _record_to_dict(row)
