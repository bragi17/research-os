from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_docker_compose_runs_production_scheduler_service() -> None:
    compose = (ROOT / "infra/docker/docker-compose.yml").read_text(encoding="utf-8")
    expected_migration_filenames = [
        "001_init_schema.sql",
        "002_add_users.sql",
        "003_v2_multimode.sql",
        "004_add_trace_id.sql",
        "005_library_tables.sql",
        "006_llm_provider_credentials.sql",
        "007_library_pools.sql",
        "008_research_production.sql",
        "009_paper_verification.sql",
        "010_idea_jury_fields.sql",
        "011_research_memory.sql",
        "012_submission_audit_gates.sql",
        "013_literature_source_settings.sql",
        "013_saas_tenancy.sql",
        "014_generalize_llm_provider_credentials.sql",
        "015_topic_work_phase_artifacts.sql",
    ]
    migration_filenames = sorted(
        path.name for path in (ROOT / "scripts/migration").glob("*.sql")
    )

    assert "production-scheduler:" in compose
    assert "python scripts/run_production_scheduler.py" in compose
    assert "DATABASE_URL: postgresql://ros_user:ros_pass@postgres:5432/research_os" in compose
    assert "../../scripts/migration:/docker-entrypoint-initdb.d:ro" in compose
    assert "001_init_schema.sql:/docker-entrypoint-initdb.d" not in compose
    assert migration_filenames == expected_migration_filenames
