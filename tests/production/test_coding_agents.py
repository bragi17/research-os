"""Tests for the production coding-agent runtime layer."""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from apps.worker.production.coding_agents.base import (
    CodingAgentEvent,
    CodingAgentResult,
    CodingExecOptions,
)
from apps.worker.production.coding_agents.codex_provider import (
    CodexProvider,
    parse_codex_json_event,
)
from apps.worker.production.coding_agents.errors import classify_agent_failure
from apps.worker.production.coding_agents.runtime_detection import (
    detect_runtime,
    detect_runtime_from_env,
    resolve_command_from_login_shell,
)


FAILURE_CASES = [
    ("Context length exceeded before token quota was checked", "agent_context_overflow"),
    ("No API key configured for provider", "agent_missing_config"),
    ("401 unauthorized access denied", "agent_provider_auth_or_access"),
    ("quota exceeded for this billing period", "agent_provider_quota_limit"),
    ("429 rate limit exceeded, please retry later", "agent_provider_capacity_or_rate_limit"),
    ("500 internal server error from provider", "agent_provider_server_error"),
    ("network connection refused while contacting API", "agent_provider_network"),
    ("model gpt-missing not found", "agent_model_not_found_or_unavailable"),
    ("empty output from agent", "agent_empty_or_unparseable_output"),
    ("operation timed out", "agent_timeout"),
    ("No such file or directory: codex", "agent_runtime_missing_executable"),
    ("unsupported codex version 0.1", "agent_runtime_version_unsupported"),
    ("process exited with status 2", "agent_process_failure"),
    ("something surprising happened", "agent_unknown"),
]


def test_base_models_have_required_fields_and_independent_defaults() -> None:
    event = CodingAgentEvent(type="tool_use", tool="shell", call_id="c1", input={"cmd": "pwd"})
    result = CodingAgentResult(status="completed", output="ok", duration_ms=12)
    options = CodingExecOptions(cwd="/tmp/work")

    assert event.type == "tool_use"
    assert result.error is None
    assert result.usage == {}
    assert CodingExecOptions(cwd="/tmp/work", sandbox="read-only").sandbox == "read-only"
    assert options.extra_args == []
    assert options.custom_args == []
    assert options.env == {}

    another = CodingExecOptions(cwd="/tmp/other")
    assert options.extra_args is not another.extra_args
    assert options.custom_args is not another.custom_args
    assert options.env is not another.env


def test_coding_agent_result_status_does_not_accept_aborted() -> None:
    with pytest.raises(ValidationError):
        CodingAgentResult(status="aborted")


@pytest.mark.parametrize(("message", "expected"), FAILURE_CASES)
def test_failure_classifier_returns_exact_reason_strings(message: str, expected: str) -> None:
    assert classify_agent_failure(message) == expected


def test_context_overflow_wins_before_quota_or_limit() -> None:
    assert (
        classify_agent_failure("context length exceeded and quota limit exceeded")
        == "agent_context_overflow"
    )


def test_detect_runtime_from_env_uses_explicit_path_without_filesystem_check(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RESEARCH_OS_CODEX_PATH", "/missing/bin/codex")
    monkeypatch.setenv("RESEARCH_OS_CODEX_MODEL", "gpt-5-codex")

    detection = detect_runtime_from_env("codex")

    assert detection.provider == "codex"
    assert detection.command == "/missing/bin/codex"
    assert detection.source == "env"
    assert detection.model == "gpt-5-codex"
    assert detection.status == "available"
    assert detection.supports_json_events is True


def test_detect_runtime_uses_which_and_reports_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RESEARCH_OS_CODEX_PATH", raising=False)
    monkeypatch.setattr(
        "apps.worker.production.coding_agents.runtime_detection.shutil.which",
        lambda command: "/usr/local/bin/codex" if command == "codex" else None,
    )

    available = detect_runtime("codex")

    assert available.command == "/usr/local/bin/codex"
    assert available.source == "path"
    assert available.status == "available"

    monkeypatch.setattr(
        "apps.worker.production.coding_agents.runtime_detection.shutil.which",
        lambda command: None,
    )
    monkeypatch.setattr(
        "apps.worker.production.coding_agents.runtime_detection.resolve_command_from_login_shell",
        lambda command: None,
    )

    unavailable = detect_runtime("codex")

    assert unavailable.status == "unavailable"
    assert unavailable.failure_reason == "agent_runtime_missing_executable"


def test_detect_runtime_uses_login_shell_fallback_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RESEARCH_OS_CODEX_PATH", raising=False)
    monkeypatch.setattr(
        "apps.worker.production.coding_agents.runtime_detection.shutil.which",
        lambda command: None,
    )
    monkeypatch.setattr(
        "apps.worker.production.coding_agents.runtime_detection.resolve_command_from_login_shell",
        lambda command: "/login/bin/codex" if command == "codex" else None,
    )

    detection = detect_runtime("codex")

    assert detection.command == "/login/bin/codex"
    assert detection.source == "login_shell"
    assert detection.status == "available"


def test_login_shell_fallback_can_be_unit_tested(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured["args"] = args
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="/shell/bin/codex\n", stderr="")

    monkeypatch.setattr(
        "apps.worker.production.coding_agents.runtime_detection.subprocess.run",
        fake_run,
    )

    assert resolve_command_from_login_shell("codex") == "/shell/bin/codex"
    assert "command -v codex" in captured["args"][0]


def test_login_shell_resolver_quotes_command(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured["args"] = args
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(
        "apps.worker.production.coding_agents.runtime_detection.subprocess.run",
        fake_run,
    )

    assert resolve_command_from_login_shell("codex; touch /tmp/pwned") is None
    shell_command = captured["args"][0][2]
    assert shell_command == "command -v 'codex; touch /tmp/pwned'"


def test_parse_codex_json_event_maps_known_jsonl_events() -> None:
    started = parse_codex_json_event('{"type":"thread.started","thread_id":"sess-1"}')
    running = parse_codex_json_event('{"type":"turn.started"}')
    text = parse_codex_json_event(
        json.dumps(
            {
                "type": "item.completed",
                "item": {"type": "agent_message", "text": "implementation complete"},
            }
        )
    )
    tool_use = parse_codex_json_event(
        json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "type": "tool_call",
                    "tool": "shell",
                    "call_id": "call-1",
                    "input": {"cmd": "pytest"},
                },
            }
        )
    )
    tool_result = parse_codex_json_event(
        json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "type": "tool_result",
                    "call_id": "call-1",
                    "output": "passed",
                    "status": "completed",
                },
            }
        )
    )
    completed = parse_codex_json_event(
        json.dumps({"type": "turn.completed", "usage": {"input_tokens": 10}})
    )

    assert started == CodingAgentEvent(
        type="status", status="started", session_id="sess-1", raw=started.raw
    )
    assert running is not None and running.status == "running"
    assert text is not None and text.type == "text" and text.content == "implementation complete"
    assert tool_use is not None and tool_use.type == "tool_use" and tool_use.tool == "shell"
    assert tool_result is not None and tool_result.type == "tool_result" and tool_result.output == "passed"
    assert completed is not None and completed.status == "completed"
    assert completed.raw == {"usage": {"input_tokens": 10}}
    assert parse_codex_json_event("") is None
    assert parse_codex_json_event("not json") is None


def test_codex_provider_builds_exec_command_and_allows_sandbox_override() -> None:
    provider = CodexProvider(command="/bin/codex")
    options = CodingExecOptions(
        cwd="/tmp/work",
        model="gpt-5-codex",
        sandbox="read-only",
        custom_args=["--skip-git-repo-check"],
    )

    command = provider.build_command("Return ok", options)

    assert command[:5] == ["/bin/codex", "-a", "never", "exec", "--json"]
    assert command.count("--sandbox") == 1
    assert command[command.index("--sandbox") + 1] == "read-only"
    assert "-C" in command
    assert command[command.index("-C") + 1] == "/tmp/work"
    assert command[-1] == "Return ok"
    assert "-m" in command
    assert command[command.index("-m") + 1] == "gpt-5-codex"


def test_codex_provider_rejects_non_empty_mcp_config() -> None:
    provider = CodexProvider(command="/bin/codex")
    options = CodingExecOptions(
        cwd="/tmp/work",
        mcp_config={"evil": {"command": "sh", "args": ["-c", "touch /tmp/pwned"]}},
    )

    with pytest.raises(ValueError, match="mcp_config"):
        provider.build_command("Return ok", options)


@pytest.mark.parametrize(
    "dangerous_args",
    [
        ["--dangerously-bypass-approvals-and-sandbox"],
        ["--dangerously-bypass-hook-trust"],
        ["--add-dir", "/tmp"],
        ["--sandbox", "danger-full-access"],
        ["-s", "danger-full-access"],
        ["--config", "shell_environment_policy.inherit=all"],
        ["-c", "mcp_servers.evil.command=sh"],
        ["--profile", "production"],
        ["--profile=production"],
    ],
)
def test_codex_provider_rejects_dangerous_args(dangerous_args: list[str]) -> None:
    provider = CodexProvider(command="/bin/codex")
    options = CodingExecOptions(cwd="/tmp/work", custom_args=dangerous_args)

    with pytest.raises(ValueError):
        provider.build_command("Return ok", options)


class _FakeStream:
    def __init__(self, lines: list[str]) -> None:
        self._lines = [line.encode() for line in lines]

    async def readline(self) -> bytes:
        await asyncio.sleep(0)
        if self._lines:
            return self._lines.pop(0)
        return b""

    async def read(self, limit: int = -1) -> bytes:
        await asyncio.sleep(0)
        if self._lines:
            return self._lines.pop(0)
        return b""


class _FakeProcess:
    def __init__(self) -> None:
        self.stdout = _FakeStream(
            [
                '{"type":"thread.started","thread_id":"sess-1"}\n',
                '{"type":"turn.started"}\n',
                '{"type":"item.completed","item":{"type":"agent_message","text":"codex-ok"}}\n',
                '{"type":"turn.completed","usage":{"input_tokens":1,"output_tokens":2}}\n',
            ]
        )
        self.stderr = _FakeStream(["warning\n"])
        self.returncode = 0
        self.terminated = False

    async def wait(self) -> int:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = -15

    def kill(self) -> None:
        self.returncode = -9


class _ChunkedStdoutStream:
    def __init__(self, content: bytes, chunk_size: int = 1024) -> None:
        self._content = bytearray(content)
        self._chunk_size = chunk_size

    async def read(self, limit: int = -1) -> bytes:
        await asyncio.sleep(0)
        if not self._content:
            return b""
        size = min(limit if limit > 0 else self._chunk_size, self._chunk_size, len(self._content))
        chunk = bytes(self._content[:size])
        del self._content[:size]
        return chunk

    async def readline(self) -> bytes:
        raise AssertionError("provider must not use readline() for stdout JSONL")


class _ChunkedStdoutProcess:
    def __init__(self, stdout: bytes) -> None:
        self.stdout = _ChunkedStdoutStream(stdout)
        self.stderr = _FakeStream([])
        self.returncode = 0

    async def wait(self) -> int:
        return self.returncode

    def terminate(self) -> None:
        self.returncode = -15

    def kill(self) -> None:
        self.returncode = -9


class _BlockingProcess:
    def __init__(self) -> None:
        self.stdout = _NeverEndingStream()
        self.stderr = _NeverEndingStream()
        self.returncode: int | None = None
        self.pid = 4321
        self.wait_calls = 0
        self.terminate_calls = 0
        self.kill_calls = 0

    async def wait(self) -> int:
        self.wait_calls += 1
        await asyncio.sleep(3600)
        return self.returncode or -9

    def terminate(self) -> None:
        self.terminate_calls += 1

    def kill(self) -> None:
        self.kill_calls += 1
        self.returncode = -9


class _LongStderrStream:
    def __init__(self, chunk: bytes) -> None:
        self._chunk = chunk

    async def read(self, limit: int = -1) -> bytes:
        await asyncio.sleep(0)
        chunk = self._chunk
        self._chunk = b""
        return chunk


class _FailingProcessWithLongStderr:
    def __init__(self, stderr_chunk: bytes) -> None:
        self.stdout = _FakeStream([])
        self.stderr = _LongStderrStream(stderr_chunk)
        self.returncode = 7

    async def wait(self) -> int:
        await asyncio.sleep(0)
        return self.returncode

    def terminate(self) -> None:
        self.returncode = -15

    def kill(self) -> None:
        self.returncode = -9


class _NeverEndingStream:
    async def readline(self) -> bytes:
        await asyncio.sleep(3600)
        return b""

    async def read(self, limit: int = -1) -> bytes:
        await asyncio.sleep(3600)
        return b""


class _NeverEndingProcess:
    def __init__(self) -> None:
        self.stdout = _NeverEndingStream()
        self.stderr = _NeverEndingStream()
        self.returncode: int | None = None
        self.terminated = False
        self.killed = False

    async def wait(self) -> int:
        await asyncio.sleep(3600)
        return self.returncode or -9

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = -15

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9


@pytest.mark.asyncio
async def test_codex_provider_streams_events_and_returns_final_result(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, object] = {}

    async def fake_create_subprocess_exec(*cmd: str, **kwargs: object) -> _FakeProcess:
        captured["cmd"] = cmd
        captured["env"] = kwargs["env"]
        captured["start_new_session"] = kwargs["start_new_session"]
        return _FakeProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setenv("PATH", "/trusted/bin")
    monkeypatch.setenv("HOME", "/trusted/home")
    monkeypatch.setenv("USER", "trusted-user")
    monkeypatch.setenv("BROWSER", "should-not-inherit")
    monkeypatch.setenv("HTTP_PROXY", "http://trusted-proxy")
    monkeypatch.setenv("OPENAI_API_KEY", "service-key")
    monkeypatch.setenv("RESEARCH_OS_CODEX_OPENAI_API_KEY", "scoped-agent-key")
    monkeypatch.setenv("CODEX_HOME", "/trusted/codex-home")

    provider = CodexProvider(command="/bin/codex")
    options = CodingExecOptions(
        cwd=str(tmp_path),
        env={
            "RESEARCH_OS_TEST": "1",
            "CUDA_VISIBLE_DEVICES": "0",
            "lowercase": "blocked",
            "HTTP_PROXY": "http://evil-proxy",
            "PATH": "/evil/bin",
            "OPENAI_API_KEY": "evil-key",
            "NODE_OPTIONS": "--require /tmp/pwned.js",
            "BASH_ENV": "/tmp/pwned.sh",
            "GIT_CONFIG_GLOBAL": "/tmp/gitconfig",
            "PYTHONPATH": "/tmp/pythonpath",
            "SHELL": "/tmp/shell",
            "CODEX_HOME": "/evil/codex-home",
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "safe.directory",
            "GIT_CONFIG_VALUE_0": "*",
            "NODE_EXTRA_CA_CERTS": "/tmp/ca.pem",
            "SSL_CERT_DIR": "/tmp/certs",
            "NPM_CONFIG_USERCONFIG": "/tmp/npmrc",
        },
    )

    events = [event async for event in provider.execute("Return ok", options)]
    result = await provider.run("Return ok", options)

    assert [event.type for event in events] == ["status", "status", "text", "status"]
    assert events[0].session_id == "sess-1"
    assert result.status == "completed"
    assert result.output == "codex-ok"
    assert result.session_id == "sess-1"
    assert result.usage == {"input_tokens": 1, "output_tokens": 2}
    assert result.error is None
    assert captured["cmd"][0] == "/bin/codex"
    assert captured["start_new_session"] is True
    assert captured["env"]["RESEARCH_OS_TEST"] == "1"
    assert captured["env"]["CUDA_VISIBLE_DEVICES"] == "0"
    assert captured["env"]["HTTP_PROXY"] == "http://trusted-proxy"
    assert captured["env"]["PATH"] == "/trusted/bin"
    assert captured["env"]["OPENAI_API_KEY"] == "scoped-agent-key"
    assert captured["env"]["CODEX_HOME"] == "/trusted/codex-home"
    assert "BROWSER" not in captured["env"]
    assert "lowercase" not in captured["env"]
    assert "NODE_OPTIONS" not in captured["env"]
    assert "BASH_ENV" not in captured["env"]
    assert "GIT_CONFIG_GLOBAL" not in captured["env"]
    assert "GIT_CONFIG_COUNT" not in captured["env"]
    assert "GIT_CONFIG_KEY_0" not in captured["env"]
    assert "GIT_CONFIG_VALUE_0" not in captured["env"]
    assert "NODE_EXTRA_CA_CERTS" not in captured["env"]
    assert "SSL_CERT_DIR" not in captured["env"]
    assert "NPM_CONFIG_USERCONFIG" not in captured["env"]
    assert "PYTHONPATH" not in captured["env"]
    assert "SHELL" not in captured["env"]


@pytest.mark.asyncio
async def test_codex_provider_reads_long_stdout_jsonl_without_readline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    long_text = "x" * 70000
    stdout = (
        json.dumps({"type": "thread.started", "thread_id": "sess-1"}).encode()
        + b"\n"
        + json.dumps(
            {"type": "item.completed", "item": {"type": "agent_message", "text": long_text}}
        ).encode()
        + b"\n"
        + json.dumps({"type": "turn.completed", "usage": {"input_tokens": 1}}).encode()
        + b"\n"
    )

    async def fake_create_subprocess_exec(
        *cmd: str, **kwargs: object
    ) -> _ChunkedStdoutProcess:
        return _ChunkedStdoutProcess(stdout)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    provider = CodexProvider(command="/bin/codex")
    result = await provider.run("Return ok", CodingExecOptions(cwd=str(tmp_path)))

    assert result.status == "completed"
    assert result.output == long_text
    assert result.session_id == "sess-1"


@pytest.mark.asyncio
async def test_codex_provider_uses_byte_bounded_stderr_tail_for_long_records(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    stderr_chunk = b"prefix-" + (b"a" * 9000) + b"-tail-marker"

    async def fake_create_subprocess_exec(
        *cmd: str, **kwargs: object
    ) -> _FailingProcessWithLongStderr:
        return _FailingProcessWithLongStderr(stderr_chunk)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    provider = CodexProvider(command="/bin/codex")
    result = await provider.run("Return ok", CodingExecOptions(cwd=str(tmp_path)))

    assert result.status == "failed"
    assert result.error is not None
    assert "tail-marker" in result.error
    assert "prefix-" not in result.error
    assert len(result.error.encode()) <= 8192


@pytest.mark.asyncio
async def test_codex_provider_cancel_stops_process_group(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    process = _BlockingProcess()
    signals: list[tuple[int, int]] = []

    async def fake_create_subprocess_exec(*cmd: str, **kwargs: object) -> _BlockingProcess:
        return process

    def fake_killpg(pgid: int, sig: int) -> None:
        signals.append((pgid, sig))
        if len(signals) >= 2:
            process.returncode = -9

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr("apps.worker.production.coding_agents.codex_provider.os.getpgid", lambda pid: 9876)
    monkeypatch.setattr("apps.worker.production.coding_agents.codex_provider.os.killpg", fake_killpg)

    provider = CodexProvider(command="/bin/codex")
    iterator = provider.execute(
        "Return ok",
        CodingExecOptions(cwd=str(tmp_path), thread_name="task-1"),
    )
    task = asyncio.create_task(iterator.__anext__())
    await asyncio.sleep(0)

    await provider.cancel("task-1")
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await iterator.aclose()

    assert [sig for _, sig in signals] == [15, 9]


@pytest.mark.asyncio
async def test_codex_provider_early_iterator_close_stops_process_group(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    process = _BlockingProcess()
    signals: list[int] = []

    async def fake_create_subprocess_exec(*cmd: str, **kwargs: object) -> _BlockingProcess:
        return process

    def fake_killpg(pgid: int, sig: int) -> None:
        signals.append(sig)
        process.returncode = -15

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr("apps.worker.production.coding_agents.codex_provider.os.getpgid", lambda pid: 2468)
    monkeypatch.setattr("apps.worker.production.coding_agents.codex_provider.os.killpg", fake_killpg)

    provider = CodexProvider(command="/bin/codex")
    iterator = provider.execute("Return ok", CodingExecOptions(cwd=str(tmp_path)))
    task = asyncio.create_task(iterator.__anext__())
    await asyncio.sleep(0)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await iterator.aclose()

    assert signals == [15]


@pytest.mark.asyncio
async def test_codex_provider_overall_timeout_stops_never_ending_process(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    process = _NeverEndingProcess()

    async def fake_create_subprocess_exec(*cmd: str, **kwargs: object) -> _NeverEndingProcess:
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    provider = CodexProvider(command="/bin/codex")
    options = CodingExecOptions(cwd=str(tmp_path), timeout_sec=1)

    result = await asyncio.wait_for(provider.run("Return ok", options), timeout=2)

    assert result.status == "timeout"
    assert result.error is not None
    assert classify_agent_failure(result.error) == "agent_timeout"
    assert process.terminated or process.killed
