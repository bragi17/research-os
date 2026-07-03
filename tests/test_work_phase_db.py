from __future__ import annotations

from pathlib import Path


MIGRATION = Path("scripts/migration/015_topic_work_phase_artifacts.sql")


def test_topic_work_migration_defines_core_tables() -> None:
    sql = MIGRATION.read_text()

    assert "CREATE TABLE IF NOT EXISTS research_work" in sql
    assert "CREATE TABLE IF NOT EXISTS phase_execution" in sql
    assert "CREATE TABLE IF NOT EXISTS artifact_card" in sql
    assert "CREATE TABLE IF NOT EXISTS artifact_revision" in sql
    assert "CREATE TABLE IF NOT EXISTS phase_input_selection" in sql


def test_topic_work_migration_keeps_existing_runs_as_execution_backend() -> None:
    sql = MIGRATION.read_text()

    assert "backing_run_id UUID REFERENCES research_run(id) ON DELETE SET NULL" in sql
    assert "work_id UUID NOT NULL REFERENCES research_work(id) ON DELETE CASCADE" in sql
    assert "phase TEXT NOT NULL" in sql
