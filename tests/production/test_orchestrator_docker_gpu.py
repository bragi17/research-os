from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest


def test_experiment_resources_accept_docker_gpu_executor() -> None:
    from libs.schemas.production import ExperimentResources

    resources = ExperimentResources(
        executor_type="docker_gpu",
        gpu_required=True,
        gpu_count=1,
        job_image="research-os-job-runtime:latest",
    )

    assert resources.executor_type == "docker_gpu"
    assert resources.gpu_required is True
    assert resources.gpu_count == 1
    assert resources.job_image == "research-os-job-runtime:latest"


@pytest.mark.asyncio
async def test_run_job_builds_docker_spec_for_docker_gpu(monkeypatch, tmp_path: Path) -> None:
    import apps.worker.production.orchestrator as orchestrator

    project_id = uuid4()
    workspace_id = uuid4()
    job_id = uuid4()
    base = tmp_path / "trusted-workspaces"
    monkeypatch.setenv("RESEARCH_OS_WORKSPACE_ROOT", str(base))
    workspace = base / "workspaces" / str(workspace_id) / "projects" / str(project_id)
    (workspace / "experiments" / "smoke").mkdir(parents=True)

    fake_job = {
        "id": job_id,
        "project_id": project_id,
        "executor_type": "docker_gpu",
        "cmd": "python train.py",
        "cwd": "experiments/smoke",
        "expected_outputs_json": ["metrics.json"],
        "metrics_json": {
            "timeout_sec": 90,
            "gpu_count": 1,
            "job_image": "research-os-job-runtime:latest",
            "memory": "12g",
            "cpus": "3",
            "network": "none",
        },
    }

    class FakeDb:
        async def get_experiment_job(self, _job_id):
            return fake_job

        async def get_project(self, _project_id):
            return {
                "id": project_id,
                "workspace_id": workspace_id,
                "default_workspace_path": str(workspace),
            }

        async def update_experiment_job(self, _job_id, updates):
            return {**fake_job, **updates}

    class FakeExecutor:
        def __init__(self):
            self.spec = None

        async def run(self, spec):
            self.spec = spec
            from apps.worker.production.experiments.local_executor import LocalJobResult

            return LocalJobResult(
                job_id=str(job_id),
                status="completed",
                returncode=0,
                stdout_log=spec.log_dir / "stdout.log",
                stderr_log=spec.log_dir / "stderr.log",
                expected_outputs_found=[],
                missing_expected_outputs=[],
                failure_reason=None,
                duration_ms=1,
            )

    executor = FakeExecutor()
    monkeypatch.setattr(orchestrator, "db", FakeDb())

    await orchestrator.run_job(job_id, executor=executor)

    assert executor.spec.image == "research-os-job-runtime:latest"
    assert executor.spec.gpu_count == 1
    assert executor.spec.memory == "12g"
    assert executor.spec.cpus == "3"
