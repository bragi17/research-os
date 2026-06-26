"""Codex CLI provider backed by `codex exec --json` JSONL events."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
import time
from collections.abc import AsyncIterator
from typing import Any

from apps.worker.production.coding_agents.base import (
    CodingAgentEvent,
    CodingAgentResult,
    CodingExecOptions,
    RuntimeDetection,
)
from apps.worker.production.coding_agents.errors import classify_agent_failure
from apps.worker.production.coding_agents.runtime_detection import detect_runtime


SAFE_CODEX_NO_VALUE_ARGS = frozenset(
    {
        "--skip-git-repo-check",
        "--no-color",
    }
)
SAFE_CODEX_VALUE_ARGS = frozenset()
DANGEROUS_CODEX_FLAGS = frozenset(
    {
        "--dangerously-bypass-approvals-and-sandbox",
        "--dangerously-bypass-hook-trust",
        "--add-dir",
        "--sandbox",
        "-s",
        "--config",
        "-c",
    }
)
TRUSTED_INHERITED_ENV_KEYS = (
    "PATH",
    "HOME",
    "USER",
    "LOGNAME",
    "LANG",
    "LC_ALL",
    "TERM",
    "TMPDIR",
    "CODEX_HOME",
    "http_proxy",
    "https_proxy",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "no_proxy",
    "NO_PROXY",
)
USER_ENV_ALLOWED_KEYS = frozenset(
    {
        "CUDA_VISIBLE_DEVICES",
        "HIP_VISIBLE_DEVICES",
        "ROCR_VISIBLE_DEVICES",
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "TOKENIZERS_PARALLELISM",
        "PYTHONUNBUFFERED",
        "PIP_DISABLE_PIP_VERSION_CHECK",
        "RESEARCH_OS_TEST",
    }
)
STDERR_READ_CHUNK_BYTES = 4096
STDERR_TAIL_BYTES = 8192
STDOUT_READ_CHUNK_BYTES = 16384
STDOUT_EVENT_BYTES = 10 * 1024 * 1024


class _ByteTail:
    def __init__(self, max_bytes: int = STDERR_TAIL_BYTES) -> None:
        self.max_bytes = max_bytes
        self._buffer = bytearray()

    def append(self, chunk: bytes) -> None:
        self._buffer.extend(chunk)
        if len(self._buffer) > self.max_bytes:
            del self._buffer[: len(self._buffer) - self.max_bytes]

    def text(self) -> str:
        return bytes(self._buffer).decode(errors="replace").strip()


def _item_text(item: dict[str, Any]) -> str | None:
    for key in ("text", "content", "message"):
        value = item.get(key)
        if isinstance(value, str):
            return value
    content = item.get("content")
    if isinstance(content, list):
        parts = [
            part.get("text")
            for part in content
            if isinstance(part, dict) and isinstance(part.get("text"), str)
        ]
        return "".join(parts) if parts else None
    return None


def _event_type(payload: dict[str, Any]) -> str | None:
    value = payload.get("type") or payload.get("event")
    return value if isinstance(value, str) else None


def parse_codex_json_event(line: str) -> CodingAgentEvent | None:
    """Parse one Codex JSONL line into a normalized coding-agent event."""

    raw_line = line.strip()
    if not raw_line:
        return None

    try:
        payload = json.loads(raw_line)
    except json.JSONDecodeError:
        return None

    if not isinstance(payload, dict):
        return None

    event_type = _event_type(payload)
    if event_type == "thread.started":
        session_id = payload.get("thread_id") or payload.get("session_id")
        if not isinstance(session_id, str):
            session_id = None
        return CodingAgentEvent(
            type="status",
            status="started",
            session_id=session_id,
            raw=payload,
        )

    if event_type == "turn.started":
        return CodingAgentEvent(type="status", status="running", raw=payload)

    if event_type == "turn.completed":
        usage = payload.get("usage")
        raw = {"usage": usage} if isinstance(usage, dict) else payload
        return CodingAgentEvent(type="status", status="completed", raw=raw)

    if event_type != "item.completed":
        return None

    item = payload.get("item")
    if not isinstance(item, dict):
        return None

    item_type = item.get("type")
    if item_type == "agent_message":
        return CodingAgentEvent(type="text", content=_item_text(item), raw=payload)

    if item_type in {"tool_call", "function_call"}:
        tool = item.get("tool") or item.get("name")
        call_id = item.get("call_id") or item.get("id")
        tool_input = item.get("input") if isinstance(item.get("input"), dict) else None
        return CodingAgentEvent(
            type="tool_use",
            tool=tool if isinstance(tool, str) else None,
            call_id=call_id if isinstance(call_id, str) else None,
            input=tool_input,
            raw=payload,
        )

    if item_type in {"tool_result", "function_call_output"}:
        call_id = item.get("call_id") or item.get("id")
        output = item.get("output") or item.get("content")
        status = item.get("status")
        return CodingAgentEvent(
            type="tool_result",
            call_id=call_id if isinstance(call_id, str) else None,
            output=output if isinstance(output, str) else None,
            status=status if isinstance(status, str) else None,
            raw=payload,
        )

    return None


def _is_blocked_config_value(value: str) -> bool:
    normalized = value.strip().lower()
    return normalized.startswith("shell_environment_policy.") or normalized.startswith(
        "mcp_servers."
    )


def _is_allowed_user_env_key(key: str) -> bool:
    return key in USER_ENV_ALLOWED_KEYS


class CodexProvider:
    """v1 Codex provider using `codex -a never exec --json`."""

    provider_name = "codex"

    def __init__(self, command: str | None = None) -> None:
        self.command = command or "codex"
        self._processes: dict[str, Any] = {}

    async def detect(self) -> RuntimeDetection:
        return detect_runtime(self.provider_name)

    async def version(self) -> str:
        process = await asyncio.create_subprocess_exec(
            self.command,
            "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        output = (stdout or stderr).decode(errors="replace").strip()
        return output

    def build_env(self, user_env: dict[str, str]) -> dict[str, str]:
        """Build a constrained child environment for Codex."""

        env: dict[str, str] = {}
        for key in TRUSTED_INHERITED_ENV_KEYS:
            if key in os.environ:
                env[key] = os.environ[key]
        scoped_openai_key = os.environ.get("RESEARCH_OS_CODEX_OPENAI_API_KEY")
        if scoped_openai_key:
            env["OPENAI_API_KEY"] = scoped_openai_key

        for key, value in user_env.items():
            if not _is_allowed_user_env_key(key):
                continue
            env[key] = value

        return env

    def _validate_args(self, args: list[str]) -> list[str]:
        safe_args: list[str] = []
        index = 0
        while index < len(args):
            arg = args[index]
            flag, has_inline_value, inline_value = arg.partition("=")

            if arg in DANGEROUS_CODEX_FLAGS or flag in DANGEROUS_CODEX_FLAGS:
                raise ValueError(f"unsafe Codex argument is not allowed: {flag}")
            if _is_blocked_config_value(arg) or (
                has_inline_value and _is_blocked_config_value(inline_value)
            ):
                raise ValueError(f"unsafe Codex config override is not allowed: {arg}")

            if arg in SAFE_CODEX_NO_VALUE_ARGS:
                safe_args.append(arg)
                index += 1
                continue

            if has_inline_value and flag in SAFE_CODEX_VALUE_ARGS:
                safe_args.append(arg)
                index += 1
                continue

            if arg in SAFE_CODEX_VALUE_ARGS:
                if index + 1 >= len(args):
                    raise ValueError(f"missing value for Codex argument: {arg}")
                value = args[index + 1]
                if value.startswith("-") or _is_blocked_config_value(value):
                    raise ValueError(f"unsafe value for Codex argument: {arg}")
                safe_args.extend([arg, value])
                index += 2
                continue

            raise ValueError(f"unsupported Codex argument is not allowed: {arg}")

        return safe_args

    def build_command(self, prompt: str, options: CodingExecOptions) -> list[str]:
        """Build the Codex CLI argv from typed options and allowlisted args."""

        safe_extra_args = self._validate_args(list(options.extra_args))
        safe_custom_args = self._validate_args(list(options.custom_args))
        command = [
            self.command,
            "-a",
            "never",
            "exec",
            "--json",
            "--sandbox",
            options.sandbox,
        ]

        if options.model:
            command.extend(["-m", options.model])
        if options.system_prompt:
            command.extend(["--system-prompt", options.system_prompt])
        if options.resume_session_id:
            command.extend(["resume", options.resume_session_id])
        else:
            command.append("--ephemeral")
        if options.mcp_config:
            raise ValueError("mcp_config is not supported by CodexProvider v1")
        if options.thinking_level:
            command.extend(["--reasoning-effort", options.thinking_level])

        command.extend(safe_extra_args)
        command.extend(safe_custom_args)
        command.extend(["-C", options.cwd, prompt])
        return command

    async def _stderr_tail(
        self,
        stream: asyncio.StreamReader | None,
        tail: _ByteTail,
    ) -> None:
        if stream is None:
            return
        while True:
            try:
                chunk = await stream.read(STDERR_READ_CHUNK_BYTES)
            except Exception:
                return
            if not chunk:
                break
            tail.append(chunk)

    async def _read_stdout_line(
        self,
        stream: asyncio.StreamReader | None,
        buffer: bytearray,
    ) -> bytes:
        if stream is None:
            return b""

        while True:
            newline_index = buffer.find(b"\n")
            if newline_index >= 0:
                line = bytes(buffer[: newline_index + 1])
                del buffer[: newline_index + 1]
                return line

            if len(buffer) > STDOUT_EVENT_BYTES:
                raise ValueError("Codex stdout JSONL event exceeded byte limit")

            chunk = await stream.read(STDOUT_READ_CHUNK_BYTES)
            if not chunk:
                if not buffer:
                    return b""
                line = bytes(buffer)
                buffer.clear()
                return line
            buffer.extend(chunk)

    async def _drain_stderr_task(
        self,
        stderr_task: asyncio.Task[None],
        timeout_sec: float = 0.2,
    ) -> None:
        if stderr_task.done():
            with contextlib.suppress(Exception, asyncio.CancelledError):
                await stderr_task
            return

        with contextlib.suppress(Exception, asyncio.CancelledError, asyncio.TimeoutError):
            await asyncio.wait_for(asyncio.shield(stderr_task), timeout=timeout_sec)

    async def _stop_process(
        self,
        process: Any,
        graceful_timeout_sec: float = 0.1,
    ) -> None:
        if process.returncode is not None:
            return

        pid = getattr(process, "pid", None)
        sent_group_signal = False
        if pid is not None:
            with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
                os.killpg(os.getpgid(pid), signal.SIGTERM)
                sent_group_signal = True

        if not sent_group_signal:
            with contextlib.suppress(ProcessLookupError):
                process.terminate()

        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(process.wait(), timeout=graceful_timeout_sec)
            return

        if process.returncode is None:
            sent_group_kill = False
            if pid is not None:
                with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
                    os.killpg(os.getpgid(pid), signal.SIGKILL)
                    sent_group_kill = True
            if not sent_group_kill:
                with contextlib.suppress(ProcessLookupError):
                    process.kill()
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(process.wait(), timeout=graceful_timeout_sec)

    def _timeout_event(self, detail: str) -> CodingAgentEvent:
        reason = classify_agent_failure(detail)
        return CodingAgentEvent(type="error", content=detail, status=reason)

    def _initial_process_keys(self, options: CodingExecOptions) -> set[str]:
        keys: set[str] = set()
        if options.thread_name:
            keys.add(options.thread_name)
        if options.resume_session_id:
            keys.add(options.resume_session_id)
        return keys

    def _register_process_key(self, key: str | None, process: Any, keys: set[str]) -> None:
        if key:
            self._processes[key] = process
            keys.add(key)

    def _unregister_process_keys(self, keys: set[str], process: Any) -> None:
        for key in keys:
            if self._processes.get(key) is process:
                self._processes.pop(key, None)

    async def execute(
        self,
        prompt: str,
        options: CodingExecOptions,
    ) -> AsyncIterator[CodingAgentEvent]:
        command = self.build_command(prompt, options)
        env = self.build_env(options.env)
        stderr_tail = _ByteTail()
        process_keys: set[str] = set()
        stdout_buffer = bytearray()

        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=options.cwd,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
        except OSError as exc:
            yield CodingAgentEvent(
                type="error",
                content=str(exc),
                status=classify_agent_failure(str(exc)),
            )
            return

        process_keys = self._initial_process_keys(options)
        if not process_keys:
            process_keys.add(f"pid:{id(process)}")
        for key in process_keys:
            self._processes[key] = process
        stderr_task = asyncio.create_task(self._stderr_tail(process.stderr, stderr_tail))
        deadline = (
            asyncio.get_running_loop().time() + options.timeout_sec
            if options.timeout_sec
            else None
        )

        try:
            while True:
                try:
                    read_timeout = options.semantic_inactivity_timeout_sec
                    if deadline is not None:
                        remaining = deadline - asyncio.get_running_loop().time()
                        if remaining <= 0:
                            await self._stop_process(process)
                            yield self._timeout_event("process timeout")
                            return
                        read_timeout = (
                            min(read_timeout, remaining)
                            if read_timeout is not None
                            else remaining
                        )

                    if options.semantic_inactivity_timeout_sec:
                        line = await asyncio.wait_for(
                            self._read_stdout_line(process.stdout, stdout_buffer),
                            timeout=read_timeout,
                        )
                    elif read_timeout is not None:
                        line = await asyncio.wait_for(
                            self._read_stdout_line(process.stdout, stdout_buffer),
                            timeout=read_timeout,
                        )
                    else:
                        line = await self._read_stdout_line(process.stdout, stdout_buffer)
                except asyncio.TimeoutError:
                    await self._stop_process(process)
                    detail = (
                        "process timeout"
                        if deadline is not None and asyncio.get_running_loop().time() >= deadline
                        else "semantic inactivity timeout"
                    )
                    yield self._timeout_event(detail)
                    return
                except ValueError as exc:
                    await self._stop_process(process)
                    detail = str(exc)
                    yield CodingAgentEvent(
                        type="error",
                        content=detail,
                        status=classify_agent_failure(detail),
                    )
                    return

                if not line:
                    break
                event = parse_codex_json_event(line.decode(errors="replace"))
                if event is not None:
                    if event.session_id:
                        self._register_process_key(event.session_id, process, process_keys)
                    yield event

            try:
                if options.timeout_sec:
                    remaining = (
                        max(deadline - asyncio.get_running_loop().time(), 0)
                        if deadline is not None
                        else options.timeout_sec
                    )
                    returncode = await asyncio.wait_for(process.wait(), timeout=remaining)
                else:
                    returncode = await process.wait()
            except asyncio.TimeoutError:
                await self._stop_process(process)
                yield self._timeout_event("process timeout")
                return

            if returncode != 0:
                await self._drain_stderr_task(stderr_task)
                error_text = stderr_tail.text() or f"process exited with status {returncode}"
                yield CodingAgentEvent(
                    type="error",
                    content=error_text,
                    status=classify_agent_failure(error_text, returncode=returncode),
                )
        finally:
            await self._stop_process(process)
            await self._drain_stderr_task(stderr_task)
            stderr_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await stderr_task
            self._unregister_process_keys(process_keys, process)

    async def run(self, prompt: str, options: CodingExecOptions) -> CodingAgentResult:
        """Collect an execution stream into a final result object."""

        started = time.monotonic()
        output_parts: list[str] = []
        session_id: str | None = None
        usage: dict[str, Any] = {}
        error: str | None = None
        status = "failed"

        async for event in self.execute(prompt, options):
            if event.session_id:
                session_id = event.session_id
            if event.type == "text" and event.content:
                output_parts.append(event.content)
            if event.type == "status" and event.status == "completed":
                status = "completed"
                if isinstance(event.raw, dict) and isinstance(event.raw.get("usage"), dict):
                    usage = event.raw["usage"]
            if event.type == "error":
                error = event.content
                status = "timeout" if event.status == "agent_timeout" else "failed"

        return CodingAgentResult(
            status=status,
            output="".join(output_parts),
            error=error,
            duration_ms=int((time.monotonic() - started) * 1000),
            session_id=session_id,
            usage=usage,
        )

    async def cancel(self, task_id: str) -> None:
        process = self._processes.get(task_id)
        if process is not None:
            await self._stop_process(process)

    async def resume(
        self,
        session_id: str,
        prompt: str,
        options: CodingExecOptions,
    ) -> AsyncIterator[CodingAgentEvent]:
        resume_options = options.model_copy(update={"resume_session_id": session_id})
        async for event in self.execute(prompt, resume_options):
            yield event
