from pathlib import Path


def test_docker_compose_runs_production_scheduler_service() -> None:
    compose = Path("infra/docker/docker-compose.yml").read_text(encoding="utf-8")

    assert "production-scheduler:" in compose
    assert "python scripts/run_production_scheduler.py" in compose
    assert "DATABASE_URL: postgresql://ros_user:ros_pass@postgres:5432/research_os" in compose
    assert "../../scripts/migration/008_research_production.sql:/docker-entrypoint-initdb.d/008_research_production.sql" in compose
