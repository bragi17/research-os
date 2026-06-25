from __future__ import annotations

import asyncio
import re
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


DOCKER_CLEANUP_TIMEOUT_SEC = 10
SAFE_CONTAINER_NAME_CHAR = re.compile(r"[^A-Za-z0-9_.-]")
SAFE_IMAGE_REFERENCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]*$")


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


def _container_name(job_id: str) -> str:
    return f"research-os-job-{SAFE_CONTAINER_NAME_CHAR.sub('-', job_id)}"


def _validate_image_reference(image: str) -> str:
    if (
        not image
        or image.startswith("-")
        or any(character.isspace() or ord(character) < 32 for character in image)
        or SAFE_IMAGE_REFERENCE.fullmatch(image) is None
    ):
        raise ValueError("docker image reference is unsafe")
    return image


def _resolve_expected_outputs(
    workspace_root: Path,
    cwd: Path,
    outputs: list[Path],
) -> tuple[list[Path], list[Path]]:
    resolved_workspace_root = workspace_root.resolve()
    resolved_outputs: list[Path] = []
    invalid_outputs: list[Path] = []

    for output in outputs:
        if output.is_absolute() or ".." in output.parts:
            invalid_outputs.append(output)
            continue

        candidate = (cwd / output).resolve()
        try:
            candidate.relative_to(resolved_workspace_root)
        except ValueError:
            invalid_outputs.append(output)
            continue
        resolved_outputs.append(candidate)

    return resolved_outputs, invalid_outputs


def build_docker_run_argv(spec: DockerJobSpec) -> list[str]:
    if spec.gpu_count < 1:
        raise ValueError("gpu_count must be at least 1")

    workspace_root = spec.workspace_root.resolve()
    cwd = _resolve_inside_workspace(workspace_root, spec.cwd, "cwd")
    image = _validate_image_reference(spec.image)
    return [
        "docker",
        "run",
        "--rm",
        "--name",
        _container_name(spec.job_id),
        "--gpus",
        str(spec.gpu_count),
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
        image,
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
        workspace_root = spec.workspace_root.resolve()
        cwd = _resolve_inside_workspace(workspace_root, spec.cwd, "cwd")

        expected_outputs, invalid_expected_outputs = _resolve_expected_outputs(
            workspace_root,
            cwd,
            spec.expected_outputs,
        )
        if invalid_expected_outputs:
            return _build_result(
                spec=spec,
                status="failed",
                returncode=None,
                stdout_log=stdout_log,
                stderr_log=stderr_log,
                expected_outputs_found=[],
                missing_expected_outputs=invalid_expected_outputs,
                failure_reason="invalid_expected_outputs",
                started_at=started_at,
            )

        argv = build_docker_run_argv(spec)
        container_name = _container_name(spec.job_id)

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
                await _cleanup_container(container_name)
                returncode = process.returncode
                status = "timeout"
                failure_reason = "timeout"
            except asyncio.CancelledError:
                await _terminate_process_group(process)
                await _cleanup_container(container_name)
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


async def _cleanup_container(container_name: str) -> None:
    try:
        process = await asyncio.create_subprocess_exec(
            "docker",
            "rm",
            "-f",
            container_name,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,
        )
        await asyncio.wait_for(process.wait(), timeout=DOCKER_CLEANUP_TIMEOUT_SEC)
    except (OSError, asyncio.TimeoutError):
        return
