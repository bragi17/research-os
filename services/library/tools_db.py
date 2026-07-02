"""
Paper Library — Deterministic DB tool functions.

All functions follow the same pattern as apps/api/database.py:
  - acquire pool via get_pool()
  - parameterized queries only
  - return plain dicts via _record_to_dict()
"""

from __future__ import annotations

import re
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
# LOOKUP / INSERT
# ---------------------------------------------------------------------------


def _normalize_library_arxiv_id(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    if not text:
        return None
    if text.startswith("arxiv:"):
        text = text.removeprefix("arxiv:").strip()
    text = re.sub(r"^https?://arxiv\.org/(?:abs|pdf)/", "", text)
    text = text.removesuffix(".pdf")
    text = re.sub(r"v\d+\Z", "", text)
    return text or None


def _normalize_library_doi(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    if not text:
        return None
    text = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", text)
    text = text.removeprefix("doi:").strip()
    return text or None


def _normalize_library_title(value: Any) -> str | None:
    text = re.sub(r"\s+", " ", str(value or "").strip().lower())
    return text or None


async def find_existing_library_paper(data: dict[str, Any]) -> dict[str, Any] | None:
    """Find a likely existing library paper by arXiv ID, DOI, or exact title."""
    arxiv_id = _normalize_library_arxiv_id(data.get("arxiv_id"))
    doi = _normalize_library_doi(data.get("doi"))
    title = _normalize_library_title(data.get("title"))
    if not arxiv_id and not doi and not title:
        return None

    pool = await get_pool()
    row = await pool.fetchrow(
        """
        SELECT *
        FROM library_paper
        WHERE
            (
                $1::text IS NOT NULL
                AND arxiv_id IS NOT NULL
                AND regexp_replace(
                    regexp_replace(lower(arxiv_id), '^arxiv:', ''),
                    'v[0-9]+$',
                    ''
                ) = $1
            )
            OR (
                $2::text IS NOT NULL
                AND doi IS NOT NULL
                AND regexp_replace(
                    regexp_replace(lower(doi), '^https?://(dx\\.)?doi\\.org/', ''),
                    '^doi:',
                    ''
                ) = $2
            )
            OR (
                $3::text IS NOT NULL
                AND regexp_replace(lower(title), '\\s+', ' ', 'g') = $3
            )
        ORDER BY
            CASE
                WHEN $1::text IS NOT NULL AND arxiv_id IS NOT NULL THEN 0
                WHEN $2::text IS NOT NULL AND doi IS NOT NULL THEN 1
                ELSE 2
            END,
            created_at ASC,
            id ASC
        LIMIT 1
        """,
        arxiv_id,
        doi,
        title,
    )
    return _record_to_dict(row) if row is not None else None


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
    pool_ids: list[UUID] | list[str] | None = None,
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

    if pool_ids:
        conditions.append(
            f"""
            EXISTS (
                SELECT 1
                FROM library_pool_paper lpp
                WHERE lpp.library_paper_id = library_paper.id
                  AND lpp.pool_id = ANY(${idx}::uuid[])
            )
            """  # nosec B608
        )
        values.append([UUID(str(pool_id)) for pool_id in pool_ids])
        idx += 1

    where = f" WHERE {' AND '.join(conditions)}" if conditions else ""

    values.append(limit)
    limit_idx = idx
    idx += 1

    values.append(offset)
    offset_idx = idx

    query = (
        f"SELECT * FROM library_paper{where} "  # nosec B608
        f"ORDER BY created_at DESC "
        f"LIMIT ${limit_idx} OFFSET ${offset_idx}"
    )

    rows = await pool.fetch(query, *values)
    return [_record_to_dict(r) for r in rows]


async def count_library_papers(
    field: str | None = None,
    project_tag: str | None = None,
    pool_ids: list[UUID] | list[str] | None = None,
) -> int:
    """Return total number of library_paper rows with optional filters."""
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

    if pool_ids:
        conditions.append(
            f"""
            EXISTS (
                SELECT 1
                FROM library_pool_paper lpp
                WHERE lpp.library_paper_id = library_paper.id
                  AND lpp.pool_id = ANY(${idx}::uuid[])
            )
            """  # nosec B608
        )
        values.append([UUID(str(pool_id)) for pool_id in pool_ids])

    where = f" WHERE {' AND '.join(conditions)}" if conditions else ""  # nosec B608
    row = await pool.fetchrow(f"SELECT COUNT(*) AS cnt FROM library_paper{where}", *values)  # nosec B608
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
        f"UPDATE library_paper SET {', '.join(set_parts)} "  # nosec B608
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
                str(chunk["embedding"]) if chunk.get("embedding") else None,
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
    pool_ids: list[UUID] | list[str] | None = None,
) -> list[dict[str, Any]]:
    """Cosine similarity search over library_chunk embeddings.

    Joins library_chunk -> library_paper to include paper metadata.
    Optionally filters by library_paper.field.
    """
    pool = await get_pool()

    embedding_literal = "[" + ",".join(str(v) for v in query_embedding) + "]"

    conditions: list[str] = []
    values: list[Any] = [embedding_literal]
    idx = 2

    if field is not None:
        conditions.append(f"lp.field = ${idx}")
        values.append(field)
        idx += 1

    if pool_ids:
        conditions.append(
            f"""
            EXISTS (
                SELECT 1
                FROM library_pool_paper lpp
                WHERE lpp.library_paper_id = lp.id
                  AND lpp.pool_id = ANY(${idx}::uuid[])
            )
            """  # nosec B608
        )
        values.append([UUID(str(pool_id)) for pool_id in pool_ids])
        idx += 1

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    values.append(limit)

    rows = await pool.fetch(
        f"""
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
        {where}
        ORDER BY lc.embedding <=> $1::vector
        LIMIT ${idx}
        """,  # nosec B608
        *values,
    )

    return [_record_to_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# TEXT SEARCH
# ---------------------------------------------------------------------------


async def search_library_text(
    query: str,
    limit: int = 20,
    pool_ids: list[UUID] | list[str] | None = None,
) -> list[dict[str, Any]]:
    """ILIKE title search on library_paper."""
    pool = await get_pool()
    pattern = f"%{query}%"
    values: list[Any] = [pattern]
    conditions = ["title ILIKE $1"]
    idx = 2
    if pool_ids:
        conditions.append(
            f"""
            EXISTS (
                SELECT 1
                FROM library_pool_paper lpp
                WHERE lpp.library_paper_id = library_paper.id
                  AND lpp.pool_id = ANY(${idx}::uuid[])
            )
            """  # nosec B608
        )
        values.append([UUID(str(pool_id)) for pool_id in pool_ids])
        idx += 1
    values.append(limit)
    rows = await pool.fetch(
        f"""
        SELECT * FROM library_paper
        WHERE {' AND '.join(conditions)}
        ORDER BY created_at DESC
        LIMIT ${idx}
        """,  # nosec B608
        *values,
    )
    return [_record_to_dict(r) for r in rows]
