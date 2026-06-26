import asyncio
import os
import re
import shlex
import signal
import time
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from apps.worker.production.experiments.local_executor import (
    LocalJobResult,
    looks_like_oom_failure,
)


EXPECTED_OUTPUT_CHECK_TIMEOUT_SEC = 30
REMOTE_HOST_PATTERN = re.compile(r"^[A-Za-z0-9._:-]+$")
REMOTE_USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
ENV_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class SSHRemoteHost:
    host: str
    port: int = 22
    username: str | None = None
    auth_type: str = "agent"
    key_ref: str | None = None
    default_workdir: str | None = None
    default_env_json: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SSHJobSpec:
    job_id: str
    remote_host: SSHRemoteHost
    remote_cwd: str
    command: str
    log_dir: Path
    expected_outputs: list[Path]
    timeout_sec: float
    env: dict[str, Any] = field(default_factory=dict)
    local_artifact_dir: Path | None = None


class SSHSpecError(ValueError):
    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason


class SSHExperimentExecutor:
    def __init__(self, ssh_command: str = "ssh", scp_command: str = "scp") -> None:
        self.ssh_command = ssh_command
        self.scp_command = scp_command

    async def run(self, spec: SSHJobSpec) -> LocalJobResult:
        spec.log_dir.mkdir(parents=True, exist_ok=True)
        stdout_log = spec.log_dir / "stdout.log"
        stderr_log = spec.log_dir / "stderr.log"
        started_at = time.monotonic()

        try:
            base_argv = _ssh_base_argv(self.ssh_command, spec.remote_host)
            remote_cwd = _validate_remote_path(spec.remote_cwd, "remote_cwd")
            env = _validate_env({**spec.remote_host.default_env_json, **spec.env})
            remote_command = _remote_command(
                cwd=remote_cwd,
                env=env,
                command=spec.command,
            )
        except SSHSpecError as exc:
            return _build_result(
                spec=spec,
                status="failed",
                returncode=None,
                stdout_log=stdout_log,
                stderr_log=stderr_log,
                expected_outputs_found=[],
                missing_expected_outputs=[],
                failure_reason=exc.reason,
                started_at=started_at,
            )

        status = "completed"
        failure_reason: str | None = None
        returncode: int | None

        with stdout_log.open("wb") as stdout_file, stderr_log.open("wb") as stderr_file:
            process = await asyncio.create_subprocess_exec(
                *base_argv,
                remote_command,
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
            remote_outputs_found, missing_expected_outputs = await _check_expected_outputs(
                base_argv=base_argv,
                remote_cwd=remote_cwd,
                outputs=spec.expected_outputs,
            )
            copy_failures: list[Path] = []
            expected_outputs_found = remote_outputs_found
            if remote_outputs_found and spec.local_artifact_dir is not None:
                expected_outputs_found, copy_failures = await _copy_expected_outputs(
                    scp_command=self.scp_command,
                    remote_host=spec.remote_host,
                    remote_cwd=remote_cwd,
                    local_artifact_dir=spec.local_artifact_dir,
                    outputs=spec.expected_outputs,
                    remote_outputs=remote_outputs_found,
                )
                missing_expected_outputs.extend(copy_failures)
            if returncode != 0:
                if looks_like_oom_failure(returncode, stderr_log):
                    status = "failed_oom"
                    failure_reason = "oom"
                else:
                    status = "failed"
                    failure_reason = "process_failed"
            elif copy_failures:
                status = "failed"
                failure_reason = "artifact_copy_failed"
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


def resolve_remote_cwd(default_workdir: str | None, job_cwd: str | None) -> str:
    base = _optional_remote_path(default_workdir, "default_workdir")
    cwd = _optional_remote_path(job_cwd or ".", "cwd") or "."
    if cwd == ".":
        return base or "."
    cwd_path = PurePosixPath(cwd)
    if cwd_path.is_absolute() or not base:
        return cwd
    return str(PurePosixPath(base) / cwd_path)


def _ssh_base_argv(ssh_command: str, remote_host: SSHRemoteHost) -> list[str]:
    host = _validate_host(remote_host.host)
    username = _validate_username(remote_host.username)
    port = _validate_port(remote_host.port)
    auth_type = str(remote_host.auth_type or "agent")

    argv = [
        ssh_command,
        "-o",
        "BatchMode=yes",
        "-p",
        str(port),
    ]
    if auth_type == "key":
        key_ref = _validate_key_ref(remote_host.key_ref)
        argv.extend(["-i", key_ref])
    elif auth_type == "agent":
        pass
    else:
        raise SSHSpecError("unsupported_auth_type", f"unsupported ssh auth_type: {auth_type}")

    destination = f"{username}@{host}" if username else host
    argv.append(destination)
    return argv


def _scp_base_argv(scp_command: str, remote_host: SSHRemoteHost) -> list[str]:
    _validate_host(remote_host.host)
    _validate_username(remote_host.username)
    port = _validate_port(remote_host.port)
    auth_type = str(remote_host.auth_type or "agent")

    argv = [
        scp_command,
        "-P",
        str(port),
    ]
    if auth_type == "key":
        argv.extend(["-i", _validate_key_ref(remote_host.key_ref)])
    elif auth_type == "agent":
        pass
    else:
        raise SSHSpecError("unsupported_auth_type", f"unsupported ssh auth_type: {auth_type}")
    return argv


def _remote_destination(remote_host: SSHRemoteHost) -> str:
    host = _validate_host(remote_host.host)
    username = _validate_username(remote_host.username)
    return f"{username}@{host}" if username else host


def _remote_command(*, cwd: str, env: dict[str, str], command: str) -> str:
    command_part = f"sh -lc {shlex.quote(command)}"
    if env:
        env_part = " ".join(
            f"{name}={shlex.quote(value)}"
            for name, value in sorted(env.items())
        )
        command_part = f"env {env_part} {command_part}"
    if cwd and cwd != ".":
        return f"cd {shlex.quote(cwd)} && {command_part}"
    return command_part


async def _check_expected_outputs(
    *,
    base_argv: list[str],
    remote_cwd: str,
    outputs: list[Path],
) -> tuple[list[Path], list[Path]]:
    found: list[Path] = []
    missing: list[Path] = []

    for output in outputs:
        remote_output = _resolve_expected_output(remote_cwd, output)
        if remote_output is None:
            missing.append(output)
            continue

        process = await asyncio.create_subprocess_exec(
            *base_argv,
            f"test -f {shlex.quote(str(remote_output))}",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,
        )
        try:
            returncode = await asyncio.wait_for(
                process.wait(),
                timeout=EXPECTED_OUTPUT_CHECK_TIMEOUT_SEC,
            )
        except asyncio.TimeoutError:
            await _terminate_process_group(process)
            returncode = process.returncode
        except asyncio.CancelledError:
            await _terminate_process_group(process)
            raise

        if returncode == 0:
            found.append(remote_output)
        else:
            missing.append(remote_output)

    return found, missing


async def _copy_expected_outputs(
    *,
    scp_command: str,
    remote_host: SSHRemoteHost,
    remote_cwd: str,
    local_artifact_dir: Path,
    outputs: list[Path],
    remote_outputs: list[Path],
) -> tuple[list[Path], list[Path]]:
    local_artifact_dir.mkdir(parents=True, exist_ok=True)
    remote_output_paths = {str(path) for path in remote_outputs}
    copied: list[Path] = []
    failed: list[Path] = []
    base_argv = _scp_base_argv(scp_command, remote_host)
    destination = _remote_destination(remote_host)

    for output in outputs:
        remote_output = _resolve_expected_output(remote_cwd, output)
        if remote_output is None or str(remote_output) not in remote_output_paths:
            continue
        local_path = _local_artifact_path(local_artifact_dir, output)
        local_path.parent.mkdir(parents=True, exist_ok=True)
        process = await asyncio.create_subprocess_exec(
            *base_argv,
            f"{destination}:{shlex.quote(str(remote_output))}",
            str(local_path),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,
        )
        try:
            returncode = await asyncio.wait_for(
                process.wait(),
                timeout=EXPECTED_OUTPUT_CHECK_TIMEOUT_SEC,
            )
        except asyncio.TimeoutError:
            await _terminate_process_group(process)
            returncode = process.returncode
        except asyncio.CancelledError:
            await _terminate_process_group(process)
            raise

        if returncode == 0 and local_path.is_file():
            copied.append(local_path)
        else:
            failed.append(remote_output)

    return copied, failed


def _local_artifact_path(local_artifact_dir: Path, output: Path) -> Path:
    output_path = PurePosixPath(str(output).replace("\\", "/"))
    if output_path.is_absolute():
        return local_artifact_dir / output_path.name
    if ".." in output_path.parts:
        return local_artifact_dir / output_path.name
    return local_artifact_dir / Path(*output_path.parts)


def _resolve_expected_output(remote_cwd: str, output: Path) -> Path | None:
    raw = str(output)
    try:
        normalized = _validate_remote_path(raw, "expected_output")
    except SSHSpecError:
        return None

    output_path = PurePosixPath(normalized)
    if output_path.is_absolute():
        return Path(str(output_path))
    if remote_cwd == ".":
        return Path(str(output_path))
    return Path(str(PurePosixPath(remote_cwd) / output_path))


def _validate_host(host: str) -> str:
    if not host or _has_control_or_space(host) or host.startswith("-"):
        raise SSHSpecError("invalid_remote_host", "remote host contains unsafe characters")
    if "/" in host or not REMOTE_HOST_PATTERN.fullmatch(host):
        raise SSHSpecError("invalid_remote_host", "remote host contains unsafe characters")
    return host


def _validate_username(username: str | None) -> str | None:
    if username in (None, ""):
        return None
    if _has_control_or_space(username) or username.startswith("-"):
        raise SSHSpecError("invalid_remote_host", "remote username contains unsafe characters")
    if not REMOTE_USERNAME_PATTERN.fullmatch(username):
        raise SSHSpecError("invalid_remote_host", "remote username contains unsafe characters")
    return username


def _validate_port(port: int) -> int:
    try:
        value = int(port)
    except (TypeError, ValueError) as exc:
        raise SSHSpecError("invalid_remote_host", "remote port must be an integer") from exc
    if value < 1 or value > 65535:
        raise SSHSpecError("invalid_remote_host", "remote port is out of range")
    return value


def _validate_key_ref(key_ref: str | None) -> str:
    if not key_ref or _has_control_or_space(key_ref):
        raise SSHSpecError("invalid_remote_host", "key auth requires a safe key_ref")
    return key_ref


def _validate_remote_path(value: str, field_name: str) -> str:
    normalized = _optional_remote_path(value, field_name)
    if not normalized:
        raise SSHSpecError("invalid_remote_path", f"{field_name} is required")
    return normalized


def _optional_remote_path(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    raw = str(value).strip().replace("\\", "/")
    if raw == "":
        return "."
    if _has_control(raw):
        raise SSHSpecError("invalid_remote_path", f"{field_name} contains control characters")
    path = PurePosixPath(raw)
    if ".." in path.parts:
        raise SSHSpecError("invalid_remote_path", f"{field_name} contains parent traversal")
    return raw


def _validate_env(env: dict[str, Any]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for name, value in env.items():
        key = str(name)
        if not ENV_NAME_PATTERN.fullmatch(key):
            raise SSHSpecError("invalid_remote_env", f"invalid environment variable name: {key}")
        normalized[key] = "" if value is None else str(value)
    return normalized


def _has_control(value: str) -> bool:
    return any(ord(char) < 32 or ord(char) == 127 for char in value)


def _has_control_or_space(value: str) -> bool:
    return any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value)


async def _terminate_process_group(process: asyncio.subprocess.Process) -> None:
    with suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGTERM)

    try:
        await asyncio.wait_for(process.wait(), timeout=2)
        return
    except asyncio.TimeoutError:
        pass

    with suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGKILL)
    await process.wait()


def _build_result(
    *,
    spec: SSHJobSpec,
    status: str,
    returncode: int | None,
    stdout_log: Path,
    stderr_log: Path,
    expected_outputs_found: list[Path],
    missing_expected_outputs: list[Path],
    failure_reason: str | None,
    started_at: float,
) -> LocalJobResult:
    return LocalJobResult(
        job_id=spec.job_id,
        status=status,
        returncode=returncode,
        stdout_log=stdout_log,
        stderr_log=stderr_log,
        expected_outputs_found=expected_outputs_found,
        missing_expected_outputs=missing_expected_outputs,
        failure_reason=failure_reason,
        duration_ms=int((time.monotonic() - started_at) * 1000),
    )
