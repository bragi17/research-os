"""Asyncpg pool management and record conversion helpers."""

from __future__ import annotations

import os
from typing import Any
from uuid import UUID

import asyncpg
import orjson

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    """Return the global connection pool, creating it on first call."""
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


def record_to_dict(record: asyncpg.Record) -> dict[str, Any]:
    """Convert an asyncpg Record to a plain dict."""
    row: dict[str, Any] = dict(record)
    for key, value in row.items():
        if isinstance(value, UUID):
            row[key] = value
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
