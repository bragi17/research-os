"""
Paper Library — Deterministic DB tool functions.

All functions follow the same pattern as apps/api/database.py:
  - acquire pool via get_pool()
  - parameterized queries only
  - return plain dicts via _record_to_dict()
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from structlog import get_logger

from apps.api.database import get_pool, _record_to_dict

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Column whitelist for UPDATE
# ---------------------------------------------------------------------------

_PAPER_UPDATABLE_COLUMNS = frozenset({
    "status", "field", "sub_field", "keywords", "datasets",
    "benchmarks", "methods", "innovation_points", "summary_json",
    "deep_analysis_json", "architecture_figure_path", "arxiv_id",
    "doi", "title", "authors", "year", "venue", "citation_count",
    "latex_source_path", "compiled_pdf_path", "project_tags",
    "is_manually_uploaded", "updated_at",
})


# ---------------------------------------------------------------------------
# INSERT
# ---------------------------------------------------------------------------


async def insert_library_paper(data: dict[str, Any]) -> dict[str, Any]:
    """INSERT INTO library_paper with all columns, RETURNING *."""
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO library_paper (
            paper_id, source_run_id, status, field, sub_field,
            keywords, datasets, benchmarks, methods, innovation_points,
            summary_json, deep_analysis_json, architecture_figure_path,
            arxiv_id, doi, title, authors, year, venue,
            citation_count, latex_source_path, compiled_pdf_path,
            project_tags
        ) VALUES (
            $1,  $2,  $3,  $4,  $5,
            $6,  $7,  $8,  $9,  $10,
            $11, $12, $13,
            $14, $15, $16, $17, $18, $19,
            $20, $21, $22,
            $23
        )
        RETURNING *
        """,
        data.get("paper_id"),
        data.get("source_run_id"),
        data.get("status", "pending"),
        data.get("field"),
        data.get("sub_field"),
        data.get("keywords", []),
        data.get("datasets", []),
        data.get("benchmarks", []),
        data.get("methods", []),
        data.get("innovation_points", []),
        data.get("summary_json", {}),
        data.get("deep_analysis_json"),
        data.get("architecture_figure_path"),
        data.get("arxiv_id"),
        data.get("doi"),
        data["title"],
        data.get("authors", []),
        data.get("year"),
        data.get("venue"),
        data.get("citation_count", 0),
        data.get("latex_source_path"),
        data.get("compiled_pdf_path"),
        data.get("project_tags", []),
    )
    return _record_to_dict(row)


# ---------------------------------------------------------------------------
# GET / LIST / COUNT
# ---------------------------------------------------------------------------


async def get_library_paper(paper_id: UUID) -> dict[str, Any] | None:
    """SELECT * FROM library_paper WHERE id = $1."""
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT * FROM library_paper WHERE id = $1",
        paper_id,
    )
    if row is None:
        return None
    return _record_to_dict(row)


async def list_library_papers(
    field: str | None = None,
    project_tag: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """SELECT library_papers with optional field/project_tag filters.

    ORDER BY created_at DESC.
    """
    pool = await get_pool()

    conditions: list[str] = []
    values: list[Any] = []
    idx = 1

    if field is not None:
        conditions.append(f"field = ${idx}")
        values.append(field)
        idx += 1

    if project_tag is not None:
        conditions.append(f"${idx} = ANY(project_tags)")
        values.append(project_tag)
        idx += 1

    where = f" WHERE {' AND '.join(conditions)}" if conditions else ""

    values.append(limit)
    limit_idx = idx
    idx += 1

    values.append(offset)
    offset_idx = idx

    query = (
        f"SELECT * FROM library_paper{where} "
        f"ORDER BY created_at DESC "
        f"LIMIT ${limit_idx} OFFSET ${offset_idx}"
    )

    rows = await pool.fetch(query, *values)
    return [_record_to_dict(r) for r in rows]


async def count_library_papers() -> int:
    """Return total number of library_paper rows."""
    pool = await get_pool()
    row = await pool.fetchrow("SELECT COUNT(*) AS cnt FROM library_paper")
    return row["cnt"]


async def count_library_chunks() -> int:
    """Return total number of library_chunk rows."""
    pool = await get_pool()
    row = await pool.fetchrow("SELECT COUNT(*) AS cnt FROM library_chunk")
    return row["cnt"]


# ---------------------------------------------------------------------------
# UPDATE
# ---------------------------------------------------------------------------


async def update_library_paper(
    paper_id: UUID,
    updates: dict[str, Any],
) -> dict[str, Any] | None:
    """UPDATE specific columns on a library_paper and return the updated row.

    Only the keys present in *updates* are written. Column names are validated
    against a whitelist.
    """
    if not updates:
        return await get_library_paper(paper_id)

    invalid = set(updates.keys()) - _PAPER_UPDATABLE_COLUMNS
    if invalid:
        raise ValueError(f"Invalid column names: {invalid}")

    set_parts: list[str] = []
    values: list[Any] = []
    idx = 1
    for col, val in updates.items():
        set_parts.append(f"{col} = ${idx}")
        values.append(val)
        idx += 1

    values.append(paper_id)
    query = (
        f"UPDATE library_paper SET {', '.join(set_parts)} "
        f"WHERE id = ${idx} RETURNING *"
    )

    pool = await get_pool()
    row = await pool.fetchrow(query, *values)
    if row is None:
        return None
    return _record_to_dict(row)


# ---------------------------------------------------------------------------
# DELETE
# ---------------------------------------------------------------------------


async def delete_library_paper(paper_id: UUID) -> bool:
    """DELETE a library_paper by ID. Returns True if a row was deleted."""
    pool = await get_pool()
    result = await pool.execute(
        "DELETE FROM library_paper WHERE id = $1",
        paper_id,
    )
    # asyncpg returns e.g. "DELETE 1" or "DELETE 0"
    return result.endswith("1")


# ---------------------------------------------------------------------------
# CHUNKS — batch insert
# ---------------------------------------------------------------------------


async def insert_library_chunks(
    library_paper_id: UUID,
    chunks: list[dict[str, Any]],
) -> int:
    """Batch INSERT chunks for a library_paper. Returns the number of rows inserted."""
    if not chunks:
        return 0

    pool = await get_pool()
    inserted = 0

    async with pool.acquire() as conn:
        for chunk in chunks:
            await conn.execute(
                """
                INSERT INTO library_chunk (
                    library_paper_id, section_type, paragraph_index,
                    text, token_count, tags, claim_type, embedding
                ) VALUES (
                    $1, $2, $3,
                    $4, $5, $6, $7, $8
                )
                """,
                library_paper_id,
                chunk.get("section_type", "body"),
                chunk.get("paragraph_index", 0),
                chunk["text"],
                chunk.get("token_count", 0),
                chunk.get("tags", []),
                chunk.get("claim_type"),
                chunk.get("embedding"),
            )
            inserted += 1

    return inserted


# ---------------------------------------------------------------------------
# VECTOR SEARCH
# ---------------------------------------------------------------------------


async def search_library_vectors(
    query_embedding: list[float],
    limit: int = 30,
    field: str | None = None,
) -> list[dict[str, Any]]:
    """Cosine similarity search over library_chunk embeddings.

    Joins library_chunk -> library_paper to include paper metadata.
    Optionally filters by library_paper.field.
    """
    pool = await get_pool()

    embedding_literal = "[" + ",".join(str(v) for v in query_embedding) + "]"

    if field is not None:
        rows = await pool.fetch(
            """
            SELECT
                lc.id AS chunk_id,
                lc.library_paper_id,
                lc.section_type,
                lc.paragraph_index,
                lc.text,
                lc.tags,
                lc.claim_type,
                lp.title,
                lp.field,
                lp.arxiv_id,
                lp.year,
                (lc.embedding <=> $1::vector) AS distance
            FROM library_chunk lc
            JOIN library_paper lp ON lp.id = lc.library_paper_id
            WHERE lp.field = $2
            ORDER BY lc.embedding <=> $1::vector
            LIMIT $3
            """,
            embedding_literal,
            field,
            limit,
        )
    else:
        rows = await pool.fetch(
            """
            SELECT
                lc.id AS chunk_id,
                lc.library_paper_id,
                lc.section_type,
                lc.paragraph_index,
                lc.text,
                lc.tags,
                lc.claim_type,
                lp.title,
                lp.field,
                lp.arxiv_id,
                lp.year,
                (lc.embedding <=> $1::vector) AS distance
            FROM library_chunk lc
            JOIN library_paper lp ON lp.id = lc.library_paper_id
            ORDER BY lc.embedding <=> $1::vector
            LIMIT $2
            """,
            embedding_literal,
            limit,
        )

    return [_record_to_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# TEXT SEARCH
# ---------------------------------------------------------------------------


async def search_library_text(
    query: str,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """ILIKE title search on library_paper."""
    pool = await get_pool()
    pattern = f"%{query}%"
    rows = await pool.fetch(
        """
        SELECT * FROM library_paper
        WHERE title ILIKE $1
        ORDER BY created_at DESC
        LIMIT $2
        """,
        pattern,
        limit,
    )
    return [_record_to_dict(r) for r in rows]
