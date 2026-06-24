"""Database helpers for Paper Library knowledge-base pools."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from apps.api.database import get_pool, _record_to_dict
from services.library.duplicates import find_duplicate_candidates


SYSTEM_DEFAULT_KIND = "default"
SYSTEM_UNASSIGNED_KIND = "unassigned"


async def _get_system_pool_id(kind: str, conn: Any | None = None) -> UUID:
    db = conn or await get_pool()
    row = await db.fetchrow("SELECT id FROM library_pool WHERE kind = $1", kind)
    if row is None:
        row = await db.fetchrow(
            """
            INSERT INTO library_pool (name, description, kind, is_system)
            VALUES ($1, $2, $3, TRUE)
            RETURNING id
            """,
            "Default Library" if kind == SYSTEM_DEFAULT_KIND else "Unassigned",
            (
                "Default pool for library papers"
                if kind == SYSTEM_DEFAULT_KIND
                else "Papers without another pool membership"
            ),
            kind,
        )
    return row["id"]


async def ensure_system_pools() -> dict[str, UUID]:
    """Create the default and unassigned pools if missing."""
    pool = await get_pool()
    default_id = await _get_system_pool_id(SYSTEM_DEFAULT_KIND, pool)
    unassigned_id = await _get_system_pool_id(SYSTEM_UNASSIGNED_KIND, pool)
    return {"default": default_id, "unassigned": unassigned_id}


async def list_library_pools() -> list[dict[str, Any]]:
    pool = await get_pool()
    await ensure_system_pools()
    rows = await pool.fetch(
        """
        SELECT
            lp.*,
            COUNT(lpp.library_paper_id)::int AS paper_count
        FROM library_pool lp
        LEFT JOIN library_pool_paper lpp ON lpp.pool_id = lp.id
        GROUP BY lp.id
        ORDER BY
            CASE lp.kind
                WHEN 'default' THEN 0
                WHEN 'custom' THEN 1
                WHEN 'unassigned' THEN 2
                ELSE 3
            END,
            LOWER(lp.name)
        """
    )
    return [_record_to_dict(row) for row in rows]


async def create_library_pool(
    name: str,
    description: str | None = None,
    kind: str = "custom",
) -> dict[str, Any]:
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO library_pool (name, description, kind, is_system)
        VALUES ($1, $2, $3, $4)
        RETURNING *, 0::int AS paper_count
        """,
        name.strip(),
        description,
        kind,
        kind != "custom",
    )
    return _record_to_dict(row)


async def update_library_pool(
    pool_id: UUID,
    updates: dict[str, Any],
) -> dict[str, Any] | None:
    allowed = {"name", "description"}
    selected = {key: value for key, value in updates.items() if key in allowed}
    if not selected:
        pool = await get_pool()
        row = await pool.fetchrow(
            """
            SELECT lp.*, COUNT(lpp.library_paper_id)::int AS paper_count
            FROM library_pool lp
            LEFT JOIN library_pool_paper lpp ON lpp.pool_id = lp.id
            WHERE lp.id = $1
            GROUP BY lp.id
            """,
            pool_id,
        )
        return _record_to_dict(row) if row else None

    set_parts: list[str] = []
    values: list[Any] = []
    idx = 1
    for col, val in selected.items():
        set_parts.append(f"{col} = ${idx}")
        values.append(val.strip() if isinstance(val, str) else val)
        idx += 1
    values.append(pool_id)

    pool = await get_pool()
    row = await pool.fetchrow(
        f"""
        UPDATE library_pool
        SET {", ".join(set_parts)}
        WHERE id = ${idx}
        RETURNING *, (
            SELECT COUNT(*)::int
            FROM library_pool_paper
            WHERE pool_id = library_pool.id
        ) AS paper_count
        """,
        *values,
    )
    return _record_to_dict(row) if row else None


async def assign_paper_to_pools(
    paper_id: UUID,
    pool_ids: list[UUID] | list[str] | None,
) -> list[UUID]:
    """Attach a paper to selected pools, defaulting to Default Library."""
    pool = await get_pool()
    selected = [UUID(str(pool_id)) for pool_id in (pool_ids or [])]
    if not selected:
        selected = [await _get_system_pool_id(SYSTEM_DEFAULT_KIND, pool)]

    for pool_id in selected:
        await pool.execute(
            """
            INSERT INTO library_pool_paper (pool_id, library_paper_id)
            VALUES ($1, $2)
            ON CONFLICT DO NOTHING
            """,
            pool_id,
            paper_id,
        )
    return selected


async def copy_library_paper(
    paper_id: UUID,
    target_pool_id: UUID,
) -> dict[str, str]:
    pool = await get_pool()
    await pool.execute(
        """
        INSERT INTO library_pool_paper (pool_id, library_paper_id)
        VALUES ($1, $2)
        ON CONFLICT DO NOTHING
        """,
        target_pool_id,
        paper_id,
    )
    return {"status": "copied", "paper_id": str(paper_id)}


async def move_library_paper(
    paper_id: UUID,
    source_pool_id: UUID,
    target_pool_id: UUID,
) -> dict[str, str]:
    pool = await get_pool()
    await pool.execute(
        """
        INSERT INTO library_pool_paper (pool_id, library_paper_id)
        VALUES ($1, $2)
        ON CONFLICT DO NOTHING
        """,
        target_pool_id,
        paper_id,
    )
    if source_pool_id != target_pool_id:
        await pool.execute(
            """
            DELETE FROM library_pool_paper
            WHERE pool_id = $1 AND library_paper_id = $2
            """,
            source_pool_id,
            paper_id,
        )
    return {"status": "moved", "paper_id": str(paper_id)}


async def remove_paper_from_pool(
    paper_id: UUID,
    pool_id: UUID,
) -> dict[str, str]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                DELETE FROM library_pool_paper
                WHERE pool_id = $1 AND library_paper_id = $2
                """,
                pool_id,
                paper_id,
            )
            remaining = await conn.fetchrow(
                """
                SELECT COUNT(*) AS cnt
                FROM library_pool_paper
                WHERE library_paper_id = $1
                """,
                paper_id,
            )
            if remaining["cnt"] == 0:
                unassigned_id = await _get_system_pool_id(SYSTEM_UNASSIGNED_KIND, conn)
                await conn.execute(
                    """
                    INSERT INTO library_pool_paper (pool_id, library_paper_id)
                    VALUES ($1, $2)
                    ON CONFLICT DO NOTHING
                    """,
                    unassigned_id,
                    paper_id,
                )
    return {"status": "removed", "paper_id": str(paper_id)}


async def delete_library_pool(
    pool_id: UUID,
    delete_papers: bool = False,
) -> dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            pool_row = await conn.fetchrow(
                "SELECT id, kind FROM library_pool WHERE id = $1",
                pool_id,
            )
            if pool_row is None:
                return {"status": "missing", "pool_id": str(pool_id)}
            if pool_row["kind"] in {SYSTEM_DEFAULT_KIND, SYSTEM_UNASSIGNED_KIND}:
                raise ValueError("System pools cannot be deleted")

            if delete_papers:
                rows = await conn.fetch(
                    """
                    SELECT library_paper_id
                    FROM library_pool_paper
                    WHERE pool_id = $1
                    """,
                    pool_id,
                )
                await conn.execute(
                    """
                    DELETE FROM library_paper
                    WHERE id IN (
                        SELECT library_paper_id
                        FROM library_pool_paper
                        WHERE pool_id = $1
                    )
                    """,
                    pool_id,
                )
                deleted_papers = len(rows)
                moved_to_unassigned = 0
            else:
                orphan_rows = await conn.fetch(
                    """
                    SELECT lpp.library_paper_id
                    FROM library_pool_paper lpp
                    WHERE lpp.pool_id = $1
                    AND NOT EXISTS (
                        SELECT 1
                        FROM library_pool_paper other
                        WHERE other.library_paper_id = lpp.library_paper_id
                          AND other.pool_id <> $1
                    )
                    """,
                    pool_id,
                )
                unassigned_id = await _get_system_pool_id(SYSTEM_UNASSIGNED_KIND, conn)
                for row in orphan_rows:
                    await conn.execute(
                        """
                        INSERT INTO library_pool_paper (pool_id, library_paper_id)
                        VALUES ($1, $2)
                        ON CONFLICT DO NOTHING
                        """,
                        unassigned_id,
                        row["library_paper_id"],
                    )
                deleted_papers = 0
                moved_to_unassigned = len(orphan_rows)

            await conn.execute("DELETE FROM library_pool WHERE id = $1", pool_id)

    return {
        "status": "deleted",
        "pool_id": str(pool_id),
        "deleted_papers": deleted_papers,
        "moved_to_unassigned": moved_to_unassigned,
    }


async def get_pool_duplicate_candidates(pool_id: UUID) -> list[dict[str, Any]]:
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT lp.id, lp.title, lp.doi, lp.arxiv_id, lp.authors, lp.year
        FROM library_paper lp
        JOIN library_pool_paper lpp ON lpp.library_paper_id = lp.id
        WHERE lpp.pool_id = $1
        ORDER BY lp.created_at DESC
        """,
        pool_id,
    )
    papers = [_record_to_dict(row) for row in rows]
    return find_duplicate_candidates(papers)
