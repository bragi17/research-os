from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from pathlib import Path

from apps.worker.production.experiments.local_executor import (
    LocalJobResult,
    _build_result,
    _check_expected_outputs,
    _terminate_process_group,
    looks_like_oom_failure,
)


@dataclass(frozen=True)
class DockerJobSpec:
    job_id: str
    workspace_root: Path
    cwd: Path
    command: str
    image: str
    log_dir: Path
    expected_outputs: list[Path]
    timeout_sec: float
    gpu_count: int = 1
    memory: str = "16g"
    cpus: str = "4"
    network: str = "none"


def _resolve_inside_workspace(workspace_root: Path, relative: Path, field_name: str) -> Path:
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"{field_name} escapes workspace_root")
    candidate = (workspace_root / relative).resolve()
    root = workspace_root.resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{field_name} escapes workspace_root") from exc
    return candidate


def build_docker_run_argv(spec: DockerJobSpec) -> list[str]:
    workspace_root = spec.workspace_root.resolve()
    cwd = _resolve_inside_workspace(workspace_root, spec.cwd, "cwd")
    gpu_value = (
        "all"
        if spec.gpu_count < 1
        else f"device={','.join(str(i) for i in range(spec.gpu_count))}"
    )
    return [
        "docker",
        "run",
        "--rm",
        "--gpus",
        gpu_value,
        "--network",
        spec.network,
        "--memory",
        spec.memory,
        "--cpus",
        spec.cpus,
        "-v",
        f"{workspace_root}:/workspace:rw",
        "-w",
        "/workspace/" + cwd.relative_to(workspace_root).as_posix(),
        spec.image,
        "/bin/bash",
        "-lc",
        spec.command,
    ]


class DockerExperimentExecutor:
    async def run(self, spec: DockerJobSpec) -> LocalJobResult:
        spec.log_dir.mkdir(parents=True, exist_ok=True)
        stdout_log = spec.log_dir / "stdout.log"
        stderr_log = spec.log_dir / "stderr.log"
        started_at = time.monotonic()
        argv = build_docker_run_argv(spec)

        expected_outputs = [
            _resolve_inside_workspace(spec.workspace_root, output, "expected_outputs_json")
            for output in spec.expected_outputs
        ]

        status = "completed"
        failure_reason: str | None = None
        returncode: int | None

        with stdout_log.open("wb") as stdout_file, stderr_log.open("wb") as stderr_file:
            process = await asyncio.create_subprocess_exec(
                *argv,
                stdout=stdout_file,
                stderr=stderr_file,
                start_new_session=True,
            )
            try:
                returncode = await asyncio.wait_for(process.wait(), timeout=spec.timeout_sec)
            except asyncio.TimeoutError:
                await _terminate_process_group(process)
                returncode = process.returncode
                status = "timeout"
                failure_reason = "timeout"
            except asyncio.CancelledError:
                await _terminate_process_group(process)
                raise

        expected_outputs_found: list[Path] = []
        missing_expected_outputs: list[Path] = []
        if status != "timeout":
            expected_outputs_found, missing_expected_outputs = _check_expected_outputs(
                expected_outputs
            )
            if returncode != 0:
                if looks_like_oom_failure(returncode, stderr_log):
                    status = "failed_oom"
                    failure_reason = "oom"
                else:
                    status = "failed"
                    failure_reason = "process_failed"
            elif missing_expected_outputs:
                status = "failed"
                failure_reason = "missing_expected_outputs"

        return _build_result(
            spec=spec,
            status=status,
            returncode=returncode,
            stdout_log=stdout_log,
            stderr_log=stderr_log,
            expected_outputs_found=expected_outputs_found,
            missing_expected_outputs=missing_expected_outputs,
            failure_reason=failure_reason,
            started_at=started_at,
        )
