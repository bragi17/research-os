from pathlib import Path


def test_docker_compose_runs_production_scheduler_service() -> None:
    compose = Path("infra/docker/docker-compose.yml").read_text(encoding="utf-8")
    expected_migrations = [
        "../../scripts/migration/001_init_schema.sql:/docker-entrypoint-initdb.d/001_init_schema.sql",
        "../../scripts/migration/002_add_users.sql:/docker-entrypoint-initdb.d/002_add_users.sql",
        "../../scripts/migration/003_v2_multimode.sql:/docker-entrypoint-initdb.d/003_v2_multimode.sql",
        "../../scripts/migration/008_research_production.sql:/docker-entrypoint-initdb.d/008_research_production.sql",
        "../../scripts/migration/009_paper_verification.sql:/docker-entrypoint-initdb.d/009_paper_verification.sql",
        "../../scripts/migration/010_idea_jury_fields.sql:/docker-entrypoint-initdb.d/010_idea_jury_fields.sql",
        "../../scripts/migration/011_research_memory.sql:/docker-entrypoint-initdb.d/011_research_memory.sql",
        "../../scripts/migration/012_submission_audit_gates.sql:/docker-entrypoint-initdb.d/012_submission_audit_gates.sql",
    ]

    assert "production-scheduler:" in compose
    assert "python scripts/run_production_scheduler.py" in compose
    assert "DATABASE_URL: postgresql://ros_user:ros_pass@postgres:5432/research_os" in compose
    for migration in expected_migrations:
        assert migration in compose
    positions = [compose.index(migration) for migration in expected_migrations]
    assert positions == sorted(positions)
