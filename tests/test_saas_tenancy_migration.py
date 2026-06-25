from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_saas_tenancy_migration_defines_tenant_workspace_membership_and_backfills() -> None:
    sql = (ROOT / "scripts/migration/013_saas_tenancy.sql").read_text()

    assert "CREATE TABLE IF NOT EXISTS tenant" in sql
    assert "CREATE TABLE IF NOT EXISTS workspace_member" in sql
    assert "ALTER TABLE workspace ADD COLUMN IF NOT EXISTS tenant_id" in sql
    assert "ALTER TABLE research_project ADD COLUMN IF NOT EXISTS workspace_id" in sql
    assert "ALTER TABLE remote_host ADD COLUMN IF NOT EXISTS workspace_id" in sql
    assert "ALTER TABLE terminal_session ADD COLUMN IF NOT EXISTS workspace_id" in sql
    assert "INSERT INTO workspace_member" in sql
    assert "idx_workspace_member_user" in sql


def test_development_compose_mounts_all_migrations_directory() -> None:
    compose = (ROOT / "infra/docker/docker-compose.yml").read_text()

    assert "../../scripts/migration:/docker-entrypoint-initdb.d:ro" in compose
    assert "001_init_schema.sql:/docker-entrypoint-initdb.d" not in compose
