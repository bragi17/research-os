"""Run result and multimode database operations."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import orjson

from apps.api.db import pool as db_pool


async def list_hypotheses(run_id: UUID) -> list[dict[str, Any]]:
    """SELECT all hypotheses for a given run."""
    pool = await db_pool.get_pool()
    rows = await pool.fetch(
        """
        SELECT * FROM hypothesis
        WHERE run_id = $1
        ORDER BY created_at ASC
        """,
        run_id,
    )
    return [db_pool.record_to_dict(row) for row in rows]


async def upsert_paper_verification(data: dict[str, Any]) -> dict[str, Any]:
    """Insert or update one paper verification record."""
    pool = await db_pool.get_pool()
    raw_json = orjson.loads(orjson.dumps(data.get("raw_json", {})))
    row = await pool.fetchrow(
        """
        INSERT INTO paper_verification (
            source_run_id, candidate_key, candidate_id, source, input_title,
            canonical_title, canonical_doi, canonical_arxiv_id,
            canonical_s2_id, canonical_openalex_id, verification_status,
            verification_method, verification_reason, raw_json, verified_at
        ) VALUES (
            $1, $2, $3, $4, $5,
            $6, $7, $8,
            $9, $10, $11,
            $12, $13, $14, $15
        )
        ON CONFLICT (
            (COALESCE(source_run_id, '00000000-0000-0000-0000-000000000000'::uuid)),
            candidate_key
        )
        DO UPDATE SET
            candidate_id = EXCLUDED.candidate_id,
            source = EXCLUDED.source,
            input_title = EXCLUDED.input_title,
            canonical_title = EXCLUDED.canonical_title,
            canonical_doi = EXCLUDED.canonical_doi,
            canonical_arxiv_id = EXCLUDED.canonical_arxiv_id,
            canonical_s2_id = EXCLUDED.canonical_s2_id,
            canonical_openalex_id = EXCLUDED.canonical_openalex_id,
            verification_status = EXCLUDED.verification_status,
            verification_method = EXCLUDED.verification_method,
            verification_reason = EXCLUDED.verification_reason,
            raw_json = EXCLUDED.raw_json,
            verified_at = EXCLUDED.verified_at,
            updated_at = NOW()
        RETURNING *
        """,
        data.get("source_run_id"),
        data["candidate_key"],
        data.get("candidate_id"),
        data.get("source"),
        data.get("input_title"),
        data.get("canonical_title"),
        data.get("canonical_doi"),
        data.get("canonical_arxiv_id"),
        data.get("canonical_s2_id"),
        data.get("canonical_openalex_id"),
        data.get("verification_status", "verify_pending"),
        data.get("verification_method", "none"),
        data.get("verification_reason"),
        raw_json,
        data.get("verified_at"),
    )
    return db_pool.record_to_dict(row)


async def list_paper_verifications(run_id: UUID) -> list[dict[str, Any]]:
    """Return paper verification records for one run."""
    pool = await db_pool.get_pool()
    rows = await pool.fetch(
        """
        SELECT * FROM paper_verification
        WHERE source_run_id = $1
        ORDER BY created_at ASC
        """,
        run_id,
    )
    return [db_pool.record_to_dict(row) for row in rows]


async def list_papers_by_run(
    run_id: UUID,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """SELECT papers associated with a run."""
    pool = await db_pool.get_pool()
    rows = await pool.fetch(
        """
        SELECT * FROM paper
        WHERE metadata_json->>'source_run_id' = $1
        ORDER BY publication_year DESC NULLS LAST
        LIMIT $2 OFFSET $3
        """,
        str(run_id),
        limit,
        offset,
    )
    if rows:
        return [db_pool.record_to_dict(row) for row in rows]

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
    return [db_pool.record_to_dict(row) for row in rows]


async def count_papers_by_run(run_id: UUID) -> int:
    """Return the count of papers associated with a run."""
    pool = await db_pool.get_pool()
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


async def create_pain_point(
    run_id: UUID,
    data: dict[str, Any],
) -> dict[str, Any]:
    """INSERT a new pain_point and return the created row."""
    pool = await db_pool.get_pool()
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
    return db_pool.record_to_dict(row)


async def list_pain_points(
    run_id: UUID,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """SELECT pain_points for a given run, newest first."""
    pool = await db_pool.get_pool()
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
    return [db_pool.record_to_dict(row) for row in rows]


async def count_pain_points(run_id: UUID) -> int:
    """Return the total number of pain_points for a given run."""
    pool = await db_pool.get_pool()
    row = await pool.fetchrow(
        "SELECT COUNT(*) AS cnt FROM pain_point WHERE run_id = $1",
        run_id,
    )
    return row["cnt"]


async def create_idea_card(
    run_id: UUID,
    data: dict[str, Any],
) -> dict[str, Any]:
    """INSERT a new idea_card and return the created row."""
    pool = await db_pool.get_pool()
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
    return db_pool.record_to_dict(row)


async def list_idea_cards(
    run_id: UUID,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """SELECT idea_cards for a given run, newest first."""
    pool = await db_pool.get_pool()
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
    return [db_pool.record_to_dict(row) for row in rows]


async def count_idea_cards(run_id: UUID) -> int:
    """Return the total number of idea_cards for a given run."""
    pool = await db_pool.get_pool()
    row = await pool.fetchrow(
        "SELECT COUNT(*) AS cnt FROM idea_card WHERE run_id = $1",
        run_id,
    )
    return row["cnt"]


async def update_idea_card(
    idea_id: UUID,
    updates: dict[str, Any],
) -> dict[str, Any] | None:
    """UPDATE specific columns on an idea_card and return the updated row."""
    if not updates:
        pool = await db_pool.get_pool()
        row = await pool.fetchrow(
            "SELECT * FROM idea_card WHERE id = $1",
            idea_id,
        )
        return db_pool.record_to_dict(row) if row else None

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
    pool = await db_pool.get_pool()
    row = await pool.fetchrow(query, *values)
    if row is None:
        return None
    return db_pool.record_to_dict(row)


async def create_context_bundle(
    data: dict[str, Any],
) -> dict[str, Any]:
    """INSERT a new context_bundle and return the created row."""
    pool = await db_pool.get_pool()
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
    return db_pool.record_to_dict(row)


async def get_context_bundle(
    bundle_id: UUID,
) -> dict[str, Any] | None:
    """SELECT a single context_bundle by ID."""
    pool = await db_pool.get_pool()
    row = await pool.fetchrow(
        "SELECT * FROM context_bundle WHERE id = $1",
        bundle_id,
    )
    if row is None:
        return None
    return db_pool.record_to_dict(row)


async def create_figure_asset(
    paper_id: UUID,
    data: dict[str, Any],
) -> dict[str, Any]:
    """INSERT a new figure_asset and return the created row."""
    pool = await db_pool.get_pool()
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
    return db_pool.record_to_dict(row)


async def list_figures_by_paper(
    paper_id: UUID,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """SELECT figure_assets for a given paper."""
    pool = await db_pool.get_pool()
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
    return [db_pool.record_to_dict(row) for row in rows]


async def list_figures_by_run(
    run_id: UUID,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """SELECT figure_assets associated with a run via paper -> cluster -> run."""
    pool = await db_pool.get_pool()
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
    return [db_pool.record_to_dict(row) for row in rows]


async def create_domain(
    data: dict[str, Any],
) -> dict[str, Any]:
    """INSERT a new research_domain and return the created row."""
    pool = await db_pool.get_pool()
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
    return db_pool.record_to_dict(row)


async def get_domain(
    domain_id: UUID,
) -> dict[str, Any] | None:
    """SELECT a single research_domain by ID."""
    pool = await db_pool.get_pool()
    row = await pool.fetchrow(
        "SELECT * FROM research_domain WHERE id = $1",
        domain_id,
    )
    if row is None:
        return None
    return db_pool.record_to_dict(row)


async def list_domains(
    parent_id: UUID | None = None,
) -> list[dict[str, Any]]:
    """SELECT research_domains, optionally filtered by parent_domain_id."""
    pool = await db_pool.get_pool()
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
    return [db_pool.record_to_dict(row) for row in rows]


async def create_reading_path(
    run_id: UUID,
    data: dict[str, Any],
) -> dict[str, Any]:
    """INSERT a new reading_path and return the created row."""
    pool = await db_pool.get_pool()

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
    return db_pool.record_to_dict(row)


async def get_reading_path(
    run_id: UUID,
) -> dict[str, Any] | None:
    """SELECT the reading_path for a given run."""
    pool = await db_pool.get_pool()
    row = await pool.fetchrow(
        "SELECT * FROM reading_path WHERE run_id = $1",
        run_id,
    )
    if row is None:
        return None
    return db_pool.record_to_dict(row)
