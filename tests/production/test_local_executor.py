import asyncio
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from apps.worker.production.experiments.local_executor import (
    LocalExperimentExecutor,
    LocalJobSpec,
    list_artifacts,
    tail_log,
)


class FakeEnvProcess:
    returncode = 0
    pid = 123

    async def wait(self) -> int:
        return 0


@pytest.mark.asyncio
async def test_local_executor_completes_successful_job_and_captures_logs(
    tmp_path: Path,
) -> None:
    cwd = tmp_path / "workspace"
    cwd.mkdir()
    log_dir = tmp_path / "logs" / "job-success"

    spec = LocalJobSpec(
        job_id="job-success",
        cwd=cwd,
        command=(
            "mkdir -p artifacts && "
            "echo stdout-line && "
            "echo stderr-line >&2 && "
            "printf '{\"accuracy\": 0.9}' > artifacts/metrics.json"
        ),
        log_dir=log_dir,
        expected_outputs=[Path("artifacts/metrics.json")],
        timeout_sec=5,
    )

    result = await LocalExperimentExecutor().run(spec)

    assert result.job_id == "job-success"
    assert result.status == "completed"
    assert result.returncode == 0
    assert result.failure_reason is None
    assert result.stdout_log == log_dir / "stdout.log"
    assert result.stderr_log == log_dir / "stderr.log"
    assert result.stdout_log.read_text() == "stdout-line\n"
    assert result.stderr_log.read_text() == "stderr-line\n"
    assert result.expected_outputs_found == [cwd / "artifacts" / "metrics.json"]
    assert result.missing_expected_outputs == []
    assert result.duration_ms >= 0


@pytest.mark.asyncio
async def test_local_executor_fails_when_expected_artifact_is_missing(
    tmp_path: Path,
) -> None:
    cwd = tmp_path / "workspace"
    cwd.mkdir()

    spec = LocalJobSpec(
        job_id="job-missing",
        cwd=cwd,
        command="true",
        log_dir=tmp_path / "logs" / "job-missing",
        expected_outputs=[Path("artifacts/metrics.json")],
        timeout_sec=5,
    )

    result = await LocalExperimentExecutor().run(spec)

    assert result.status == "failed"
    assert result.returncode == 0
    assert result.failure_reason == "missing_expected_outputs"
    assert result.expected_outputs_found == []
    assert result.missing_expected_outputs == [cwd / "artifacts" / "metrics.json"]


@pytest.mark.asyncio
async def test_local_executor_reports_nonzero_process_failure(tmp_path: Path) -> None:
    cwd = tmp_path / "workspace"
    cwd.mkdir()

    spec = LocalJobSpec(
        job_id="job-failed",
        cwd=cwd,
        command="echo failed >&2; exit 7",
        log_dir=tmp_path / "logs" / "job-failed",
        expected_outputs=[],
        timeout_sec=5,
    )

    result = await LocalExperimentExecutor().run(spec)

    assert result.status == "failed"
    assert result.returncode == 7
    assert result.failure_reason == "process_failed"
    assert result.stderr_log.read_text() == "failed\n"


@pytest.mark.asyncio
async def test_local_executor_classifies_oom_failure(tmp_path: Path) -> None:
    cwd = tmp_path / "workspace"
    cwd.mkdir()

    spec = LocalJobSpec(
        job_id="job-oom",
        cwd=cwd,
        command="echo 'CUDA out of memory' >&2; exit 137",
        log_dir=tmp_path / "logs" / "job-oom",
        expected_outputs=[],
        timeout_sec=5,
    )

    result = await LocalExperimentExecutor().run(spec)

    assert result.status == "failed_oom"
    assert result.returncode == 137
    assert result.failure_reason == "oom"
    assert "out of memory" in result.stderr_log.read_text().lower()


@pytest.mark.asyncio
async def test_local_executor_scrubs_service_secret_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cwd = tmp_path / "workspace"
    cwd.mkdir()
    captured_env: dict[str, str] | None = None
    monkeypatch.setenv("DATABASE_URL", "postgresql://secret")
    monkeypatch.setenv("MINIO_SECRET_KEY", "secret")
    monkeypatch.setenv("PATH", "/usr/bin")

    async def fake_create_subprocess_exec(*argv: str, **kwargs: Any) -> FakeEnvProcess:
        nonlocal captured_env
        captured_env = kwargs.get("env")
        return FakeEnvProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    result = await LocalExperimentExecutor().run(
        LocalJobSpec(
            job_id="job-env",
            cwd=cwd,
            command="true",
            log_dir=tmp_path / "logs" / "job-env",
            expected_outputs=[],
            timeout_sec=5,
        )
    )

    assert result.status == "completed"
    assert captured_env is not None
    assert captured_env.get("PATH") == "/usr/bin"
    assert "DATABASE_URL" not in captured_env
    assert "MINIO_SECRET_KEY" not in captured_env


@pytest.mark.asyncio
async def test_local_executor_times_out_and_kills_process_group(tmp_path: Path) -> None:
    cwd = tmp_path / "workspace"
    cwd.mkdir()

    spec = LocalJobSpec(
        job_id="job-timeout",
        cwd=cwd,
        command="trap '' TERM; sleep 10",
        log_dir=tmp_path / "logs" / "job-timeout",
        expected_outputs=[],
        timeout_sec=0.2,
    )

    result = await LocalExperimentExecutor().run(spec)

    assert result.status == "timeout"
    assert result.failure_reason == "timeout"
    assert result.returncode is not None
    assert result.duration_ms < 5000


@pytest.mark.asyncio
async def test_local_executor_cleans_process_group_on_cancellation(tmp_path: Path) -> None:
    cwd = tmp_path / "workspace"
    cwd.mkdir()
    marker = tmp_path / "cancelled-marker"

    spec = LocalJobSpec(
        job_id="job-cancel",
        cwd=cwd,
        command=f"trap '' TERM; sleep 5; touch {marker}",
        log_dir=tmp_path / "logs" / "job-cancel",
        expected_outputs=[],
        timeout_sec=30,
    )

    task = asyncio.create_task(LocalExperimentExecutor().run(spec))
    await asyncio.sleep(0.2)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    await asyncio.sleep(0.2)
    assert not marker.exists()


def test_local_pty_close_waits_then_kills_and_reaps(monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.worker.production.terminal import LocalPtySession

    calls: list[tuple[str, int]] = []

    class FakeProcess:
        pid = 12345

        def __init__(self) -> None:
            self.returncode = None
            self.wait_calls = 0

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            self.wait_calls += 1
            if self.wait_calls == 1:
                raise subprocess.TimeoutExpired(cmd="fake", timeout=timeout)
            self.returncode = -9
            return self.returncode

    fake_process = FakeProcess()
    monkeypatch.setattr("os.killpg", lambda pid, sig: calls.append((str(sig), pid)))
    monkeypatch.setattr("os.close", lambda fd: None)
    monkeypatch.setattr("os.set_blocking", lambda fd, blocking: None)
    session = LocalPtySession(session_id=SimpleNamespace(), process=fake_process, master_fd=99)  # type: ignore[arg-type]

    session.close()

    assert len(calls) == 2
    assert fake_process.wait_calls == 2


def test_local_pty_open_scrubs_service_secret_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.worker.production.terminal import LocalPtySession

    captured_env: dict[str, str] | None = None
    monkeypatch.setenv("DATABASE_URL", "postgresql://secret")
    monkeypatch.setenv("MINIO_SECRET_KEY", "secret")
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setattr("pty.openpty", lambda: (10, 11))
    monkeypatch.setattr("os.close", lambda fd: None)
    monkeypatch.setattr("os.set_blocking", lambda fd, blocking: None)
    monkeypatch.setattr(LocalPtySession, "resize", lambda self, rows, cols: None)

    class FakePopen:
        pid = 123

        def __init__(self, *args, **kwargs) -> None:
            nonlocal captured_env
            captured_env = kwargs.get("env")

        def poll(self):
            return None

    monkeypatch.setattr(subprocess, "Popen", FakePopen)

    LocalPtySession.open(session_id=SimpleNamespace(), cwd=tmp_path, shell="/bin/bash")  # type: ignore[arg-type]

    assert captured_env is not None
    assert captured_env.get("PATH") == "/usr/bin"
    assert "DATABASE_URL" not in captured_env
    assert "MINIO_SECRET_KEY" not in captured_env


@pytest.mark.asyncio
async def test_tail_log_returns_text_and_next_offset(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    log_path = log_dir / "stdout.log"
    log_path.write_text("first\nsecond\nthird\n")

    first_text, first_offset = tail_log(log_dir, "stdout", offset=0, limit_bytes=12)
    second_text, second_offset = tail_log(
        log_dir,
        "stdout",
        offset=first_offset,
        limit_bytes=65536,
    )

    assert first_text == "first\nsecond"
    assert first_offset == 12
    assert second_text == "\nthird\n"
    assert second_offset == log_path.stat().st_size


def test_tail_log_rejects_invalid_stream_name(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()

    with pytest.raises(ValueError, match="invalid log stream"):
        tail_log(log_dir, "../secret")


def test_tail_log_handles_missing_stream_without_arbitrary_read(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("secret")

    text, next_offset = tail_log(log_dir, "stderr", offset=100, limit_bytes=1024)

    assert text == ""
    assert next_offset == 0


def test_tail_log_caps_limit_bytes(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "stdout.log").write_text("x" * 70000)

    text, next_offset = tail_log(log_dir, "stdout", limit_bytes=70000)

    assert len(text) == 65536
    assert next_offset == 65536


@pytest.mark.asyncio
async def test_local_executor_rejects_absolute_expected_output(tmp_path: Path) -> None:
    cwd = tmp_path / "workspace"
    cwd.mkdir()
    marker = cwd / "ran"

    spec = LocalJobSpec(
        job_id="job-invalid-output",
        cwd=cwd,
        command=f"touch {marker.name}",
        log_dir=tmp_path / "logs" / "job-invalid-output",
        expected_outputs=[tmp_path / "outside.txt"],
        timeout_sec=5,
    )

    result = await LocalExperimentExecutor().run(spec)

    assert result.status == "failed"
    assert result.returncode is None
    assert result.failure_reason == "invalid_expected_outputs"
    assert not marker.exists()


@pytest.mark.asyncio
async def test_local_executor_rejects_parent_expected_output(tmp_path: Path) -> None:
    cwd = tmp_path / "workspace"
    cwd.mkdir()
    marker = cwd / "ran"

    spec = LocalJobSpec(
        job_id="job-parent-output",
        cwd=cwd,
        command=f"touch {marker.name}",
        log_dir=tmp_path / "logs" / "job-parent-output",
        expected_outputs=[Path("../outside.txt")],
        timeout_sec=5,
    )

    result = await LocalExperimentExecutor().run(spec)

    assert result.status == "failed"
    assert result.returncode is None
    assert result.failure_reason == "invalid_expected_outputs"
    assert not marker.exists()


@pytest.mark.asyncio
async def test_local_executor_returns_failed_when_cwd_is_missing(tmp_path: Path) -> None:
    cwd = tmp_path / "missing-workspace"

    spec = LocalJobSpec(
        job_id="job-missing-cwd",
        cwd=cwd,
        command="true",
        log_dir=tmp_path / "logs" / "job-missing-cwd",
        expected_outputs=[],
        timeout_sec=5,
    )

    result = await LocalExperimentExecutor().run(spec)

    assert result.status == "failed"
    assert result.returncode is None
    assert result.failure_reason == "cwd_missing"


def test_list_artifacts_returns_matches_and_guards_traversal(tmp_path: Path) -> None:
    base_dir = tmp_path / "artifacts"
    base_dir.mkdir()
    (base_dir / "metrics.json").write_text("{}")
    (base_dir / "plot.png").write_bytes(b"png")
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")

    artifacts = list_artifacts(base_dir, ["*.json", "**/*.png", "../outside.txt", str(outside)])

    assert artifacts == [base_dir / "metrics.json", base_dir / "plot.png"]


def test_list_artifacts_rejects_parent_patterns_before_globbing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_dir = tmp_path / "artifacts"
    base_dir.mkdir()
    (base_dir / "metrics.json").write_text("{}")
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    (outside_dir / "secret.json").write_text("{}")

    globbed_patterns: list[str] = []
    original_glob = Path.glob

    def recording_glob(path: Path, pattern: str):
        globbed_patterns.append(pattern)
        return original_glob(path, pattern)

    monkeypatch.setattr(Path, "glob", recording_glob)

    artifacts = list_artifacts(base_dir, ["../**/*", "*.json"])

    assert "../**/*" not in globbed_patterns
    assert globbed_patterns == ["*.json"]
    assert artifacts == [base_dir / "metrics.json"]
