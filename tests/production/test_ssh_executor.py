import asyncio
import signal
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from apps.worker.production.experiments.local_executor import LocalJobResult
from apps.worker.production.experiments.ssh_executor import (
    SSHExperimentExecutor,
    SSHJobSpec,
    SSHRemoteHost,
)


@dataclass
class FakeSSHProcess:
    returncode: int | None

    async def wait(self) -> int:
        return self.returncode if self.returncode is not None else 0


class HangingSSHProcess:
    pid = 4242
    returncode: int | None = None

    async def wait(self) -> int:
        await asyncio.sleep(60)
        return 0


def _remote_host(**overrides: Any) -> SSHRemoteHost:
    return SSHRemoteHost(
        host=overrides.pop("host", "gpu.example.test"),
        port=overrides.pop("port", 2222),
        username=overrides.pop("username", "research"),
        auth_type=overrides.pop("auth_type", "key"),
        key_ref=overrides.pop("key_ref", "/home/research/.ssh/gpu_key"),
        default_workdir=overrides.pop("default_workdir", "/srv/research/project"),
        default_env_json=overrides.pop("default_env_json", {"CUDA_VISIBLE_DEVICES": "0"}),
        **overrides,
    )


def _job_spec(tmp_path: Path, **overrides: Any) -> SSHJobSpec:
    return SSHJobSpec(
        job_id=overrides.pop("job_id", "ssh-job"),
        remote_host=overrides.pop("remote_host", _remote_host()),
        remote_cwd=overrides.pop("remote_cwd", "/srv/research/project/experiments/smoke"),
        command=overrides.pop("command", "python train.py --epochs 1"),
        log_dir=overrides.pop("log_dir", tmp_path / "logs" / "ssh-job"),
        local_artifact_dir=overrides.pop("local_artifact_dir", tmp_path / "artifacts" / "ssh-job"),
        expected_outputs=overrides.pop(
            "expected_outputs",
            [Path("metrics.json"), Path("plots/curve.png")],
        ),
        timeout_sec=overrides.pop("timeout_sec", 5),
        env=overrides.pop("env", {"WANDB_MODE": "offline"}),
        **overrides,
    )


@pytest.mark.asyncio
async def test_ssh_executor_runs_remote_command_with_safe_argv_and_local_logs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, ...]] = []

    async def fake_create_subprocess_exec(*argv: str, **kwargs: Any) -> FakeSSHProcess:
        calls.append(tuple(argv))
        if argv[0] == "scp":
            destination = Path(argv[-1])
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text("copied metrics\n", encoding="utf-8")
            return FakeSSHProcess(0)
        stdout = kwargs.get("stdout")
        stderr = kwargs.get("stderr")
        remote_command = argv[-1]
        if "python train.py" in remote_command:
            stdout.write(b"remote stdout\n")
            stderr.write(b"remote stderr\n")
            return FakeSSHProcess(0)
        if "metrics.json" in remote_command:
            return FakeSSHProcess(0)
        return FakeSSHProcess(1)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    spec = _job_spec(tmp_path)
    result = await SSHExperimentExecutor().run(spec)

    assert result.status == "failed"
    assert result.returncode == 0
    assert result.failure_reason == "missing_expected_outputs"
    assert result.stdout_log.read_text() == "remote stdout\n"
    assert result.stderr_log.read_text() == "remote stderr\n"
    assert result.expected_outputs_found == [tmp_path / "artifacts" / "ssh-job" / "metrics.json"]
    assert result.missing_expected_outputs == [
        Path("/srv/research/project/experiments/smoke/plots/curve.png")
    ]
    assert result.expected_outputs_found[0].read_text(encoding="utf-8") == "copied metrics\n"

    command_argv = calls[0]
    assert command_argv[:7] == (
        "ssh",
        "-o",
        "BatchMode=yes",
        "-p",
        "2222",
        "-i",
        "/home/research/.ssh/gpu_key",
    )
    assert command_argv[-2] == "research@gpu.example.test"
    assert command_argv[-1].startswith("cd /srv/research/project/experiments/smoke && ")
    assert "CUDA_VISIBLE_DEVICES=0" in command_argv[-1]
    assert "WANDB_MODE=offline" in command_argv[-1]
    assert "sh -lc 'python train.py --epochs 1'" in command_argv[-1]

    output_check_argv = calls[1]
    assert output_check_argv[:-1] == command_argv[:-1]
    assert output_check_argv[-1] == "test -f /srv/research/project/experiments/smoke/metrics.json"

    copy_argv = calls[3]
    assert copy_argv[:7] == (
        "scp",
        "-P",
        "2222",
        "-i",
        "/home/research/.ssh/gpu_key",
        "research@gpu.example.test:/srv/research/project/experiments/smoke/metrics.json",
        str(tmp_path / "artifacts" / "ssh-job" / "metrics.json"),
    )


@pytest.mark.asyncio
async def test_ssh_executor_rejects_host_that_could_be_parsed_as_local_ssh_option(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, ...]] = []

    async def fake_create_subprocess_exec(*argv: str, **kwargs: Any) -> FakeSSHProcess:
        calls.append(tuple(argv))
        if argv[0] == "scp":
            destination = Path(argv[-1])
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text("copied metrics\n", encoding="utf-8")
            return FakeSSHProcess(0)
        return FakeSSHProcess(0)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    spec = _job_spec(
        tmp_path,
        remote_host=_remote_host(host="-oProxyCommand=touch /tmp/pwned"),
    )

    result = await SSHExperimentExecutor().run(spec)

    assert result.status == "failed"
    assert result.failure_reason == "invalid_remote_host"
    assert calls == []


@pytest.mark.asyncio
async def test_ssh_executor_records_unsafe_expected_outputs_as_missing_without_shelling_them(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, ...]] = []

    async def fake_create_subprocess_exec(*argv: str, **kwargs: Any) -> FakeSSHProcess:
        calls.append(tuple(argv))
        if argv[0] == "scp":
            destination = Path(argv[-1])
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text("copied metrics\n", encoding="utf-8")
        return FakeSSHProcess(0)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    spec = _job_spec(
        tmp_path,
        expected_outputs=[Path("metrics.json"), Path("../secret.txt")],
    )

    result = await SSHExperimentExecutor().run(spec)

    assert result.status == "failed"
    assert result.failure_reason == "missing_expected_outputs"
    assert result.expected_outputs_found == [tmp_path / "artifacts" / "ssh-job" / "metrics.json"]
    assert result.missing_expected_outputs == [Path("../secret.txt")]
    assert all("../secret.txt" not in argv[-1] for argv in calls)


@pytest.mark.asyncio
async def test_ssh_executor_classifies_remote_oom_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_create_subprocess_exec(*argv: str, **kwargs: Any) -> FakeSSHProcess:
        stderr = kwargs.get("stderr")
        if stderr is not None:
            stderr.write(b"CUDA out of memory on device 0\n")
        return FakeSSHProcess(137)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    spec = _job_spec(tmp_path, expected_outputs=[])
    result = await SSHExperimentExecutor().run(spec)

    assert result.status == "failed_oom"
    assert result.returncode == 137
    assert result.failure_reason == "oom"
    assert "out of memory" in result.stderr_log.read_text().lower()


@pytest.mark.asyncio
async def test_ssh_executor_times_out_and_terminates_process_group(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kill_calls: list[tuple[int, signal.Signals]] = []

    async def fake_create_subprocess_exec(*argv: str, **kwargs: Any) -> HangingSSHProcess:
        return HangingSSHProcess()

    async def fake_wait_for(awaitable: Any, timeout: float) -> Any:
        awaitable.close()
        if timeout == 2:
            return 143
        raise asyncio.TimeoutError

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr(asyncio, "wait_for", fake_wait_for)
    monkeypatch.setattr("os.killpg", lambda pid, sig: kill_calls.append((pid, sig)))

    spec = _job_spec(tmp_path, timeout_sec=0.1)
    result = await SSHExperimentExecutor().run(spec)

    assert result.status == "timeout"
    assert result.failure_reason == "timeout"
    assert kill_calls == [(4242, signal.SIGTERM)]


@dataclass
class FakeProductionDb:
    projects: dict[UUID, dict[str, Any]]
    remote_hosts: dict[UUID, dict[str, Any]]
    experiment_jobs: dict[UUID, dict[str, Any]]
    experiment_job_updates: list[tuple[UUID, dict[str, Any]]]

    async def get_project(self, project_id: UUID) -> dict[str, Any] | None:
        return self.projects.get(project_id)

    async def get_remote_host(self, remote_host_id: UUID) -> dict[str, Any] | None:
        return self.remote_hosts.get(remote_host_id)

    async def get_experiment_job(self, job_id: UUID) -> dict[str, Any] | None:
        return self.experiment_jobs.get(job_id)

    async def update_experiment_job(
        self,
        job_id: UUID,
        updates: dict[str, Any],
    ) -> dict[str, Any] | None:
        row = self.experiment_jobs.get(job_id)
        if row is None:
            return None
        row = {**row, **updates, "updated_at": datetime.now(timezone.utc)}
        self.experiment_jobs[job_id] = row
        self.experiment_job_updates.append((job_id, updates))
        return row


class FakeSSHExecutor:
    def __init__(self) -> None:
        self.specs: list[SSHJobSpec] = []

    async def run(self, spec: SSHJobSpec) -> LocalJobResult:
        self.specs.append(spec)
        return LocalJobResult(
            job_id=spec.job_id,
            status="completed",
            returncode=0,
            stdout_log=spec.log_dir / "stdout.log",
            stderr_log=spec.log_dir / "stderr.log",
            expected_outputs_found=[spec.local_artifact_dir / "metrics.json"],
            missing_expected_outputs=[],
            failure_reason=None,
            duration_ms=25,
        )


def _now_row() -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    return {"created_at": now, "updated_at": now}


@pytest.mark.asyncio
async def test_orchestrator_dispatches_ssh_job_to_ssh_executor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.worker.production import orchestrator

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("RESEARCH_OS_WORKSPACE_ROOT", str(tmp_path))
    project_id = uuid4()
    remote_host_id = uuid4()
    job_id = uuid4()
    owner_user_id = uuid4()
    fake_db = FakeProductionDb(
        projects={
            project_id: {
                "id": project_id,
                "owner_user_id": owner_user_id,
                "default_workspace_path": str(workspace),
                **_now_row(),
            }
        },
        remote_hosts={
            remote_host_id: {
                "id": remote_host_id,
                "owner_user_id": owner_user_id,
                "host": "gpu.example.test",
                "port": 2222,
                "username": "research",
                "auth_type": "key",
                "key_ref": "/home/research/.ssh/gpu_key",
                "default_workdir": "/srv/research/project",
                "default_env_json": {"CUDA_VISIBLE_DEVICES": "0"},
                **_now_row(),
            }
        },
        experiment_jobs={
            job_id: {
                "id": job_id,
                "project_id": project_id,
                "remote_host_id": remote_host_id,
                "executor_type": "ssh",
                "cmd": "python train.py",
                "cwd": "experiments/smoke",
                "expected_outputs_json": ["metrics.json"],
                "metrics_json": {"timeout_sec": 44, "env_json": {"WANDB_MODE": "offline"}},
                "status": "pending",
                **_now_row(),
            }
        },
        experiment_job_updates=[],
    )
    monkeypatch.setattr(orchestrator, "db", fake_db)
    executor = FakeSSHExecutor()

    run = await orchestrator.run_local_job(job_id, executor=executor)

    spec = executor.specs[0]
    assert spec.job_id == str(job_id)
    assert spec.remote_host.host == "gpu.example.test"
    assert spec.remote_cwd == "/srv/research/project/experiments/smoke"
    assert spec.command == "python train.py"
    assert spec.expected_outputs == [Path("metrics.json")]
    assert spec.env == {"WANDB_MODE": "offline"}
    assert spec.timeout_sec == 44
    assert spec.log_dir == (workspace / ".research-os" / "jobs" / str(job_id) / "logs").resolve()
    assert spec.local_artifact_dir == (workspace / ".research-os" / "jobs" / str(job_id) / "artifacts").resolve()
    assert fake_db.experiment_job_updates[0][1]["status"] == "running"
    final_update = fake_db.experiment_job_updates[-1][1]
    assert final_update["status"] == "completed"
    assert final_update["artifact_dir"] == str((workspace / ".research-os" / "jobs" / str(job_id) / "artifacts").resolve())
    assert final_update["metrics_json"]["expected_outputs_found"] == [
        str((workspace / ".research-os" / "jobs" / str(job_id) / "artifacts" / "metrics.json").resolve())
    ]
    assert run.row["status"] == "completed"


@pytest.mark.asyncio
async def test_orchestrator_rejects_ssh_job_when_remote_host_owner_differs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.worker.production import orchestrator

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("RESEARCH_OS_WORKSPACE_ROOT", str(tmp_path))
    project_id = uuid4()
    remote_host_id = uuid4()
    job_id = uuid4()
    fake_db = FakeProductionDb(
        projects={
            project_id: {
                "id": project_id,
                "owner_user_id": uuid4(),
                "default_workspace_path": str(workspace),
                **_now_row(),
            }
        },
        remote_hosts={
            remote_host_id: {
                "id": remote_host_id,
                "owner_user_id": uuid4(),
                "host": "gpu.example.test",
                "port": 2222,
                "username": "research",
                "auth_type": "agent",
                **_now_row(),
            }
        },
        experiment_jobs={
            job_id: {
                "id": job_id,
                "project_id": project_id,
                "remote_host_id": remote_host_id,
                "executor_type": "ssh",
                "cmd": "python train.py",
                "cwd": ".",
                "expected_outputs_json": [],
                "metrics_json": {},
                "status": "pending",
                **_now_row(),
            }
        },
        experiment_job_updates=[],
    )
    monkeypatch.setattr(orchestrator, "db", fake_db)

    with pytest.raises(ValueError, match="Remote host access denied"):
        await orchestrator.run_local_job(job_id, executor=FakeSSHExecutor())

    assert fake_db.experiment_job_updates == []
