from __future__ import annotations

import shlex
from pathlib import Path

import yaml

from scripts.run_production_scheduler import _parse_args


ROOT = Path(__file__).resolve().parents[1]
COMPOSE_PATH = ROOT / "infra/docker/docker-compose.saas.yml"
WORKSPACE_ROOT = "/data/research-os/workspaces"
WORKSPACE_MOUNT = (
    "${RESEARCH_OS_WORKSPACE_ROOT:-/data/research-os/workspaces}:"
    "${RESEARCH_OS_WORKSPACE_ROOT:-/data/research-os/workspaces}"
)


def _compose() -> dict:
    return yaml.safe_load(COMPOSE_PATH.read_text())


def _command_tokens(service: dict) -> list[str]:
    command = service["command"]
    if isinstance(command, list):
        return command
    return shlex.split(command)


def test_saas_compose_defines_required_services_and_gpu_worker() -> None:
    compose = _compose()

    for service in [
        "postgres",
        "redis",
        "minio",
        "minio-init",
        "grobid",
        "api",
        "web",
        "worker",
        "production-scheduler",
        "gpu-worker",
        "job-runtime",
    ]:
        assert service in compose["services"]

    assert compose["services"]["api"]["environment"]["AUTH_REQUIRED"] == "true"
    assert compose["services"]["gpu-worker"]["environment"]["NVIDIA_VISIBLE_DEVICES"] == "all"
    assert "/var/run/docker.sock:/var/run/docker.sock" in compose["services"]["gpu-worker"]["volumes"]
    assert (
        compose["services"]["gpu-worker"]["environment"]["RESEARCH_OS_WORKSPACE_ROOT"]
        == "${RESEARCH_OS_WORKSPACE_ROOT:-/data/research-os/workspaces}"
    )


def test_saas_compose_uses_host_workspace_bind_for_docker_executor() -> None:
    compose = _compose()

    assert "workspace_data" not in compose.get("volumes", {})
    for service_name in ["api", "worker", "production-scheduler", "gpu-worker"]:
        service = compose["services"][service_name]
        assert WORKSPACE_MOUNT in service["volumes"]
        assert "workspace_data:/data/research-os/workspaces" not in service["volumes"]


def test_saas_compose_scheduler_roles_are_valid_and_separated() -> None:
    compose = _compose()

    scheduler_tokens = _command_tokens(compose["services"]["production-scheduler"])
    assert "--disable-experiment-jobs" in scheduler_tokens
    assert "--max-concurrent-tasks" in scheduler_tokens
    assert scheduler_tokens[scheduler_tokens.index("--max-concurrent-tasks") + 1] == "1"
    assert "--max-concurrent-jobs" in scheduler_tokens
    assert scheduler_tokens[scheduler_tokens.index("--max-concurrent-jobs") + 1] == "1"

    gpu_tokens = _command_tokens(compose["services"]["gpu-worker"])
    assert "--disable-coding-tasks" in gpu_tokens
    assert "--max-concurrent-tasks" in gpu_tokens
    assert gpu_tokens[gpu_tokens.index("--max-concurrent-tasks") + 1] == "1"
    assert "--max-concurrent-jobs" in gpu_tokens
    assert gpu_tokens[gpu_tokens.index("--max-concurrent-jobs") + 1] == "1"
    assert "0" not in gpu_tokens


def test_saas_compose_builds_tagged_job_runtime_image() -> None:
    compose = _compose()
    service = compose["services"]["job-runtime"]

    assert service["image"] == "research-os-job-runtime:latest"
    assert service["build"] == {
        "context": "../..",
        "dockerfile": "infra/docker/Dockerfile.job-runtime",
    }
    assert service["profiles"] == ["build"]
    assert service["command"] == ["true"]


def test_saas_compose_uses_saas_env_and_database_substitutions() -> None:
    compose = _compose()

    expected_env_files = [
        "../../.env.saas.example",
        {"path": "../../.env.saas", "required": False},
    ]
    for service_name in ["api", "worker", "production-scheduler", "gpu-worker"]:
        assert compose["services"][service_name]["env_file"] == expected_env_files

    postgres_env = compose["services"]["postgres"]["environment"]
    assert postgres_env["POSTGRES_DB"] == "${POSTGRES_DB:-research_os}"
    assert postgres_env["POSTGRES_USER"] == "${POSTGRES_USER:-ros_user}"
    assert postgres_env["POSTGRES_PASSWORD"] == "${POSTGRES_PASSWORD:-change-me-postgres-password}"
    assert compose["services"]["postgres"]["healthcheck"]["test"] == [
        "CMD-SHELL",
        "pg_isready -U \"$${POSTGRES_USER}\" -d \"$${POSTGRES_DB}\"",
    ]

    for service_name in ["api", "worker", "production-scheduler", "gpu-worker"]:
        assert (
            compose["services"][service_name]["environment"]["DATABASE_URL"]
            == "${DATABASE_URL:-postgresql://ros_user:change-me-postgres-password@postgres:5432/research_os}"
        )

    compose_text = COMPOSE_PATH.read_text()
    assert ":?" not in compose_text
    assert "ros_pass" not in compose_text


def test_saas_compose_initializes_private_minio_bucket() -> None:
    compose = _compose()
    minio = compose["services"]["minio"]
    init = compose["services"]["minio-init"]

    assert minio["healthcheck"]["test"] == [
        "CMD",
        "curl",
        "-f",
        "http://localhost:9000/minio/health/ready",
    ]
    assert init["image"] == "minio/mc:latest"
    assert init["depends_on"]["minio"]["condition"] == "service_healthy"
    assert "mc alias set local http://minio:9000" in init["entrypoint"]
    assert "mc mb --ignore-existing local/$${MINIO_BUCKET}" in init["entrypoint"]

    for service_name in ["api", "worker"]:
        assert compose["services"][service_name]["depends_on"]["minio-init"]["condition"] == (
            "service_completed_successfully"
        )


def test_saas_compose_web_routes_api_to_internal_service() -> None:
    compose = _compose()
    web = compose["services"]["web"]

    assert web["build"]["args"]["NEXT_PUBLIC_API_URL"] == ""
    assert web["build"]["args"]["INTERNAL_API_URL"] == "http://api:8000"
    assert web["environment"]["NEXT_PUBLIC_API_URL"] == ""
    assert web["environment"]["INTERNAL_API_URL"] == "http://api:8000"

    next_config = (ROOT / "apps/web/next.config.ts").read_text()
    assert "process.env.INTERNAL_API_URL" in next_config
    assert "http://localhost:8000/api/:path*" not in next_config


def test_python_app_image_installs_docker_cli_for_gpu_worker() -> None:
    dockerfile = (ROOT / "infra/docker/Dockerfile").read_text()
    pyproject = (ROOT / "pyproject.toml").read_text()

    assert "docker.io" in dockerfile
    assert "README.md" in dockerfile
    for package_path in [
        "apps/api",
        "apps/worker",
        "libs/adapters",
        "libs/prompts",
        "libs/schemas",
    ]:
        assert f"COPY {package_path} ./{package_path}" in dockerfile
        assert dockerfile.index(f"COPY {package_path} ./{package_path}") < dockerfile.index(
            "pip install --no-cache-dir ."
        )
    assert dockerfile.index("README.md") < dockerfile.index("pip install --no-cache-dir .")
    assert "[tool.hatch.build.targets.wheel]" in pyproject
    assert (
        'packages = ["apps/api", "apps/worker", "libs/adapters", "libs/prompts", "libs/schemas"]'
        in pyproject
    )
    assert 'packages = ["apps", "libs"]' not in pyproject


def test_fresh_saas_migration_accepts_docker_gpu_jobs() -> None:
    migration = (ROOT / "scripts/migration/008_research_production.sql").read_text()

    assert "CHECK (executor_type IN ('local', 'ssh', 'docker_gpu'))" in migration


def test_docker_build_context_excludes_local_artifacts() -> None:
    dockerignore = (ROOT / ".dockerignore").read_text()

    for ignored in [
        ".git",
        ".pytest_cache",
        "__pycache__",
        "apps/web/node_modules",
        "apps/web/.next",
        ".worktrees",
    ]:
        assert ignored in dockerignore


def test_web_protected_api_calls_use_token_aware_client() -> None:
    src_root = ROOT / "apps/web/src"
    offenders: list[str] = []
    for path in src_root.rglob("*.tsx"):
        rel = path.relative_to(ROOT).as_posix()
        text = path.read_text()
        if 'fetch("/api/v1' in text or "fetch('/api/v1" in text or "fetch(`/api/v1" in text:
            offenders.append(rel)

    assert offenders == []


def test_saas_env_example_requires_secrets() -> None:
    env = (ROOT / ".env.saas.example").read_text()

    assert "JWT_SECRET=change-me-generate-a-long-random-secret" in env
    assert "CREDENTIAL_ENCRYPTION_KEY=change-me-generate-a-long-random-secret" in env
    assert "AUTH_REQUIRED=true" in env
    assert "S2_API_KEY=" in env
    assert "CROSSREF_EMAIL=" in env
    assert "POSTGRES_DB=research_os" in env
    assert "POSTGRES_USER=ros_user" in env
    assert "POSTGRES_PASSWORD=change-me-postgres-password" in env
    assert "ros_pass" not in env
    assert f"RESEARCH_OS_WORKSPACE_ROOT={WORKSPACE_ROOT}" in env


def test_scheduler_cli_supports_disabling_work_classes() -> None:
    args = _parse_args(["--disable-coding-tasks", "--disable-experiment-jobs"])

    assert args.enable_coding_tasks is False
    assert args.enable_experiment_jobs is False
