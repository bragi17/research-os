from __future__ import annotations

import os
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_saas_tenancy_migration_defines_tenant_workspace_membership_and_backfills() -> None:
    sql = (ROOT / "scripts/migration/013_saas_tenancy.sql").read_text()

    assert "CREATE TABLE IF NOT EXISTS tenant" in sql
    assert "CREATE TABLE IF NOT EXISTS workspace_member" in sql
    assert "ALTER TABLE workspace ADD COLUMN IF NOT EXISTS tenant_id" in sql
    assert "ALTER TABLE research_project ADD COLUMN IF NOT EXISTS workspace_id" in sql
    assert "ALTER TABLE remote_host ADD COLUMN IF NOT EXISTS workspace_id" in sql
    assert "ALTER TABLE terminal_session ADD COLUMN IF NOT EXISTS workspace_id" in sql
    assert "ALTER TABLE code_artifact ADD COLUMN IF NOT EXISTS workspace_id" in sql
    assert "INSERT INTO workspace_member" in sql
    assert "idx_workspace_member_user" in sql
    assert "idx_code_artifact_workspace" in sql


def test_development_compose_mounts_all_migrations_directory() -> None:
    compose = (ROOT / "infra/docker/docker-compose.yml").read_text()

    assert "../../scripts/migration:/docker-entrypoint-initdb.d:ro" in compose
    assert "001_init_schema.sql:/docker-entrypoint-initdb.d" not in compose


@pytest.mark.asyncio
async def test_saas_tenancy_migrations_apply_to_postgres_and_are_idempotent() -> None:
    database_url = os.environ.get("RESEARCH_OS_MIGRATION_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip(
            "set RESEARCH_OS_MIGRATION_TEST_DATABASE_URL to run PostgreSQL migration smoke test"
        )

    import asyncpg

    connection = await asyncpg.connect(database_url)
    try:
        migration_paths = sorted((ROOT / "scripts/migration").glob("*.sql"))
        for migration_path in migration_paths:
            await connection.execute(migration_path.read_text())

        await connection.execute(
            (ROOT / "scripts/migration/013_saas_tenancy.sql").read_text()
        )

        tenant_table = await connection.fetchval("SELECT to_regclass('public.tenant')")
        workspace_member_table = await connection.fetchval(
            "SELECT to_regclass('public.workspace_member')"
        )

        assert tenant_table is not None
        assert workspace_member_table is not None
    finally:
        await connection.close()
