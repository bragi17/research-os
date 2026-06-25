from __future__ import annotations

import asyncio
import signal
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from apps.worker.production.experiments.docker_executor import (
    DockerExperimentExecutor,
    DockerJobSpec,
    build_docker_run_argv,
)


@dataclass
class FakeDockerProcess:
    returncode: int | None
    pid: int = 4321

    async def wait(self) -> int:
        return self.returncode if self.returncode is not None else 0


class HangingDockerProcess:
    pid = 4321
    returncode: int | None = None

    async def wait(self) -> int:
        await asyncio.sleep(60)
        return 0


def _job_spec(tmp_path: Path, **overrides: Any) -> DockerJobSpec:
    workspace = overrides.pop("workspace_root", tmp_path / "workspace")
    workspace.mkdir(exist_ok=True)
    return DockerJobSpec(
        job_id=overrides.pop("job_id", "job-1"),
        workspace_root=workspace,
        cwd=overrides.pop("cwd", Path("experiments/smoke")),
        command=overrides.pop("command", "python train.py"),
        image=overrides.pop("image", "research-os-job-runtime:latest"),
        log_dir=overrides.pop("log_dir", workspace / ".research-os" / "jobs" / "job-1" / "logs"),
        expected_outputs=overrides.pop("expected_outputs", [Path("metrics.json")]),
        timeout_sec=overrides.pop("timeout_sec", 60),
        gpu_count=overrides.pop("gpu_count", 1),
        memory=overrides.pop("memory", "16g"),
        cpus=overrides.pop("cpus", "4"),
        network=overrides.pop("network", "none"),
        **overrides,
    )


def test_build_docker_run_argv_uses_gpu_workspace_limits_and_network_none(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    log_dir = workspace / ".research-os" / "jobs" / "job-1" / "logs"
    spec = DockerJobSpec(
        job_id="job-1",
        workspace_root=workspace,
        cwd=Path("experiments/smoke"),
        command="python train.py",
        image="research-os-job-runtime:latest",
        log_dir=log_dir,
        expected_outputs=[Path("metrics.json")],
        timeout_sec=60,
        gpu_count=1,
        memory="16g",
        cpus="4",
        network="none",
    )

    argv = build_docker_run_argv(spec)

    assert argv[:3] == ["docker", "run", "--rm"]
    assert "--gpus" in argv
    assert "device=0" in argv
    assert "--network" in argv
    assert "none" in argv
    assert str(workspace) + ":/workspace:rw" in argv
    assert argv[-3:] == ["/bin/bash", "-lc", "python train.py"]


def test_build_docker_run_argv_rejects_cwd_escape(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    spec = DockerJobSpec(
        job_id="job-1",
        workspace_root=workspace,
        cwd=Path("../outside"),
        command="python train.py",
        image="research-os-job-runtime:latest",
        log_dir=workspace / "logs",
        expected_outputs=[],
        timeout_sec=60,
        gpu_count=1,
        memory="16g",
        cpus="4",
        network="none",
    )

    with pytest.raises(ValueError, match="cwd escapes workspace_root"):
        build_docker_run_argv(spec)


@pytest.mark.asyncio
async def test_docker_executor_runs_docker_with_logs_and_expected_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, ...]] = []

    async def fake_create_subprocess_exec(*argv: str, **kwargs: Any) -> FakeDockerProcess:
        calls.append(tuple(argv))
        stdout = kwargs.get("stdout")
        stderr = kwargs.get("stderr")
        if stdout is not None:
            stdout.write(b"docker stdout\n")
        if stderr is not None:
            stderr.write(b"docker stderr\n")
        (tmp_path / "workspace" / "metrics.json").write_text("{}", encoding="utf-8")
        return FakeDockerProcess(0)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    spec = _job_spec(tmp_path)
    result = await DockerExperimentExecutor().run(spec)

    assert result.status == "completed"
    assert result.returncode == 0
    assert result.failure_reason is None
    assert result.stdout_log.read_text() == "docker stdout\n"
    assert result.stderr_log.read_text() == "docker stderr\n"
    assert result.expected_outputs_found == [tmp_path / "workspace" / "metrics.json"]
    assert result.missing_expected_outputs == []
    assert calls[0] == tuple(build_docker_run_argv(spec))


@pytest.mark.asyncio
async def test_docker_executor_times_out_and_terminates_process_group(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kill_calls: list[tuple[int, signal.Signals]] = []

    async def fake_create_subprocess_exec(*argv: str, **kwargs: Any) -> HangingDockerProcess:
        return HangingDockerProcess()

    async def fake_wait_for(awaitable: Any, timeout: float) -> Any:
        awaitable.close()
        if timeout == 2:
            return 143
        raise asyncio.TimeoutError

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr(asyncio, "wait_for", fake_wait_for)
    monkeypatch.setattr("os.killpg", lambda pid, sig: kill_calls.append((pid, sig)))

    spec = _job_spec(tmp_path, timeout_sec=0.1, expected_outputs=[])
    result = await DockerExperimentExecutor().run(spec)

    assert result.status == "timeout"
    assert result.failure_reason == "timeout"
    assert kill_calls == [(4321, signal.SIGTERM)]


@pytest.mark.asyncio
async def test_docker_executor_classifies_oom_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_create_subprocess_exec(*argv: str, **kwargs: Any) -> FakeDockerProcess:
        stderr = kwargs.get("stderr")
        if stderr is not None:
            stderr.write(b"CUDA out of memory on device 0\n")
        return FakeDockerProcess(137)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    spec = _job_spec(tmp_path, expected_outputs=[])
    result = await DockerExperimentExecutor().run(spec)

    assert result.status == "failed_oom"
    assert result.returncode == 137
    assert result.failure_reason == "oom"
    assert "out of memory" in result.stderr_log.read_text().lower()
