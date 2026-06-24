import asyncio
import os
import signal
import time
from dataclasses import dataclass
from pathlib import Path

from apps.worker.production.child_env import scrubbed_child_env


MAX_LOG_TAIL_BYTES = 65536
LOG_STREAM_FILES = {
    "stdout": "stdout.log",
    "stderr": "stderr.log",
}
OOM_RETURN_CODES = {137, -9}
OOM_TEXT_MARKERS = (
    "out of memory",
    "cuda error: out of memory",
    "cublas_status_alloc_failed",
    "oom killed",
    "oom-kill",
    "oom killer",
)


@dataclass(frozen=True)
class LocalJobSpec:
    job_id: str
    cwd: Path
    command: str
    log_dir: Path
    expected_outputs: list[Path]
    timeout_sec: float


@dataclass(frozen=True)
class LocalJobResult:
    job_id: str
    status: str
    returncode: int | None
    stdout_log: Path
    stderr_log: Path
    expected_outputs_found: list[Path]
    missing_expected_outputs: list[Path]
    failure_reason: str | None
    duration_ms: int


class LocalExperimentExecutor:
    async def run(self, spec: LocalJobSpec) -> LocalJobResult:
        spec.log_dir.mkdir(parents=True, exist_ok=True)
        stdout_log = spec.log_dir / "stdout.log"
        stderr_log = spec.log_dir / "stderr.log"

        started_at = time.monotonic()
        status = "completed"
        failure_reason: str | None = None
        returncode: int | None

        if not spec.cwd.is_dir():
            return _build_result(
                spec=spec,
                status="failed",
                returncode=None,
                stdout_log=stdout_log,
                stderr_log=stderr_log,
                expected_outputs_found=[],
                missing_expected_outputs=[],
                failure_reason="cwd_missing",
                started_at=started_at,
            )

        expected_outputs, invalid_expected_outputs = _resolve_expected_outputs(
            spec.cwd,
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

        with stdout_log.open("wb") as stdout_file, stderr_log.open("wb") as stderr_file:
            process = await asyncio.create_subprocess_exec(
                "/bin/bash",
                "-lc",
                spec.command,
                cwd=spec.cwd,
                env=scrubbed_child_env(),
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

        expected_outputs_found, missing_expected_outputs = _check_expected_outputs(expected_outputs)
        if status != "timeout":
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


def tail_log(
    log_dir: Path,
    stream: str,
    offset: int = 0,
    limit_bytes: int = MAX_LOG_TAIL_BYTES,
) -> tuple[str, int]:
    if stream not in LOG_STREAM_FILES:
        raise ValueError("invalid log stream")
    if offset < 0:
        raise ValueError("offset must be non-negative")
    if limit_bytes < 0:
        raise ValueError("limit_bytes must be non-negative")

    safe_limit = min(limit_bytes, MAX_LOG_TAIL_BYTES)
    resolved_log_dir = log_dir.resolve()
    candidate = (resolved_log_dir / LOG_STREAM_FILES[stream]).resolve()
    if not _is_relative_to(candidate, resolved_log_dir):
        raise ValueError("log path escapes log_dir")
    if not candidate.is_file():
        return "", 0

    with candidate.open("rb") as log_file:
        log_file.seek(offset)
        chunk = log_file.read(safe_limit)
        next_offset = log_file.tell()

    return chunk.decode("utf-8", errors="replace"), next_offset


def list_artifacts(base_dir: Path, patterns: list[str]) -> list[Path]:
    base = base_dir.resolve()
    artifacts: set[Path] = set()

    for pattern in patterns:
        pattern_path = Path(pattern)
        if not pattern or pattern_path.is_absolute() or ".." in pattern_path.parts:
            continue
        for candidate in base_dir.glob(pattern):
            if not candidate.is_file():
                continue
            resolved = candidate.resolve()
            if _is_relative_to(resolved, base):
                artifacts.add(resolved)

    return sorted(artifacts)


def looks_like_oom_failure(returncode: int | None, stderr_log: Path) -> bool:
    if returncode in OOM_RETURN_CODES:
        return True
    try:
        raw = stderr_log.read_bytes()[-MAX_LOG_TAIL_BYTES:]
    except OSError:
        raw = b""
    text = raw.decode("utf-8", errors="replace").lower()
    normalized_tokens = (
        text.replace("-", " ")
        .replace("_", " ")
        .replace(":", " ")
        .replace(".", " ")
        .split()
    )
    return any(marker in text for marker in OOM_TEXT_MARKERS) or "oom" in normalized_tokens


def _build_result(
    *,
    spec: LocalJobSpec,
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


async def _terminate_process_group(process: asyncio.subprocess.Process) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass

    try:
        await asyncio.wait_for(process.wait(), timeout=2)
        return
    except asyncio.TimeoutError:
        pass

    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    await process.wait()


def _resolve_expected_outputs(cwd: Path, outputs: list[Path]) -> tuple[list[Path], list[Path]]:
    resolved_cwd = cwd.resolve()
    resolved_outputs: list[Path] = []
    invalid_outputs: list[Path] = []

    for output in outputs:
        if output.is_absolute() or ".." in output.parts:
            invalid_outputs.append(output)
            continue

        candidate = (resolved_cwd / output).resolve()
        if _is_relative_to(candidate, resolved_cwd):
            resolved_outputs.append(candidate)
        else:
            invalid_outputs.append(output)

    return resolved_outputs, invalid_outputs


def _check_expected_outputs(outputs: list[Path]) -> tuple[list[Path], list[Path]]:
    found: list[Path] = []
    missing: list[Path] = []

    for output in outputs:
        if output.is_file():
            found.append(output)
        else:
            missing.append(output)

    return found, missing


def _is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
    except ValueError:
        return False
    return True
