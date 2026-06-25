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


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("network", "host"),
        ("job_image", ""),
        ("job_image", "--privileged"),
        ("job_image", "research os/runtime"),
        ("memory", ""),
        ("memory", "--privileged"),
        ("memory", "16g --privileged"),
        ("memory", "999999999999g"),
        ("cpus", ""),
        ("cpus", "--privileged"),
        ("cpus", "3 --privileged"),
    ],
)
def test_experiment_resources_reject_unsafe_docker_metadata(field: str, value: str) -> None:
    from libs.schemas.production import ExperimentResources

    with pytest.raises(ValueError):
        ExperimentResources(**{field: value})


def _manifest(resources: dict) -> dict:
    return {
        "project": "demo",
        "workspace": ".",
        "resources": resources,
        "phases": [
            {
                "name": "smoke",
                "jobs": [
                    {
                        "name": "train",
                        "cmd": "python train.py",
                        "cwd": "experiments/smoke",
                        "expected_outputs": ["metrics.json"],
                    }
                ],
            }
        ],
    }


@pytest.mark.asyncio
async def test_create_manifest_jobs_preserves_ssh_for_remote_gpu_resources(monkeypatch) -> None:
    import apps.worker.production.orchestrator as orchestrator

    manifest_id = uuid4()
    project_id = uuid4()
    plan_id = uuid4()
    owner_id = uuid4()
    remote_host_id = uuid4()

    class FakeDb:
        def __init__(self):
            self.created = []
            self.remote_host_requests = []

        async def get_experiment_manifest(self, _manifest_id):
            return {
                "id": manifest_id,
                "experiment_plan_id": plan_id,
                "project_id": project_id,
                "status": "accepted",
                "manifest_json": _manifest(
                    {
                        "remote_host_id": str(remote_host_id),
                        "local_first": False,
                        "gpu_required": True,
                    }
                ),
            }

        async def get_project(self, _project_id):
            return {"id": project_id, "owner_user_id": owner_id}

        async def get_remote_host(self, requested_remote_host_id):
            self.remote_host_requests.append(requested_remote_host_id)
            return {
                "id": requested_remote_host_id,
                "owner_user_id": owner_id,
                "host": "gpu.example.test",
            }

        async def create_experiment_job(self, payload):
            self.created.append(payload)
            return {"id": uuid4(), **payload}

    fake_db = FakeDb()
    monkeypatch.setattr(orchestrator, "db", fake_db)

    jobs = await orchestrator.create_manifest_jobs(manifest_id)

    assert len(jobs) == 1
    assert fake_db.remote_host_requests == [remote_host_id]
    assert fake_db.created[0]["executor_type"] == "ssh"
    assert fake_db.created[0]["remote_host_id"] == remote_host_id


@pytest.mark.asyncio
async def test_create_manifest_jobs_uses_normalized_string_booleans(monkeypatch) -> None:
    import apps.worker.production.orchestrator as orchestrator

    manifest_id = uuid4()
    project_id = uuid4()
    plan_id = uuid4()

    class FakeDb:
        def __init__(self):
            self.created = []

        async def get_experiment_manifest(self, _manifest_id):
            return {
                "id": manifest_id,
                "experiment_plan_id": plan_id,
                "project_id": project_id,
                "status": "accepted",
                "manifest_json": _manifest({"gpu_required": "true"}),
            }

        async def create_experiment_job(self, payload):
            self.created.append(payload)
            return {"id": uuid4(), **payload}

    fake_db = FakeDb()
    monkeypatch.setattr(orchestrator, "db", fake_db)

    await orchestrator.create_manifest_jobs(manifest_id)

    assert fake_db.created[0]["executor_type"] == "docker_gpu"


@pytest.mark.asyncio
async def test_create_manifest_jobs_rejects_unsafe_docker_metadata(monkeypatch) -> None:
    import apps.worker.production.orchestrator as orchestrator

    manifest_id = uuid4()
    project_id = uuid4()
    plan_id = uuid4()

    class FakeDb:
        async def get_experiment_manifest(self, _manifest_id):
            return {
                "id": manifest_id,
                "experiment_plan_id": plan_id,
                "project_id": project_id,
                "status": "accepted",
                "manifest_json": _manifest({"gpu_required": True, "network": "host"}),
            }

        async def create_experiment_job(self, payload):
            return {"id": uuid4(), **payload}

    monkeypatch.setattr(orchestrator, "db", FakeDb())

    with pytest.raises(ValueError, match="network"):
        await orchestrator.create_manifest_jobs(manifest_id)


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
        def __init__(self):
            self.updates = []

        async def get_experiment_job(self, _job_id):
            return fake_job

        async def get_project(self, _project_id):
            return {
                "id": project_id,
                "workspace_id": workspace_id,
                "default_workspace_path": str(workspace),
            }

        async def update_experiment_job(self, _job_id, updates):
            self.updates.append(updates)
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
    fake_db = FakeDb()
    monkeypatch.setattr(orchestrator, "db", fake_db)

    await orchestrator.run_job(job_id, executor=executor)

    assert executor.spec.image == "research-os-job-runtime:latest"
    assert executor.spec.gpu_count == 1
    assert executor.spec.memory == "12g"
    assert executor.spec.cpus == "3"
    assert fake_db.updates[-1]["artifact_dir"] == str(workspace / "experiments" / "smoke")
