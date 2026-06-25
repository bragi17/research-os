from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_saas_compose_defines_required_services_and_gpu_worker() -> None:
    compose = (ROOT / "infra/docker/docker-compose.saas.yml").read_text()

    for service in [
        "postgres:",
        "redis:",
        "minio:",
        "grobid:",
        "api:",
        "web:",
        "worker:",
        "production-scheduler:",
        "gpu-worker:",
    ]:
        assert service in compose

    assert "AUTH_REQUIRED: \"true\"" in compose
    assert "NVIDIA_VISIBLE_DEVICES" in compose
    assert "/var/run/docker.sock:/var/run/docker.sock" in compose
    assert "RESEARCH_OS_WORKSPACE_ROOT: /data/research-os/workspaces" in compose


def test_saas_env_example_requires_secrets() -> None:
    env = (ROOT / ".env.saas.example").read_text()

    assert "JWT_SECRET=change-me-generate-a-long-random-secret" in env
    assert "CREDENTIAL_ENCRYPTION_KEY=change-me-generate-a-long-random-secret" in env
    assert "AUTH_REQUIRED=true" in env
