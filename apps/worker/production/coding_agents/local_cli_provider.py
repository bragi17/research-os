"""Generic local CLI provider for non-Codex coding agents."""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
from collections.abc import AsyncIterator
from typing import Any

from apps.worker.production.coding_agents.base import (
    CodingAgentEvent,
    CodingExecOptions,
    RuntimeDetection,
)
from apps.worker.production.coding_agents.errors import classify_agent_failure
from apps.worker.production.coding_agents.runtime_detection import detect_runtime


TRUSTED_LOCAL_AGENT_ENV_KEYS = (
    "PATH",
    "HOME",
    "USER",
    "LOGNAME",
    "LANG",
    "LC_ALL",
    "TERM",
    "TMPDIR",
    "CODEX_HOME",
    "CLAUDE_CONFIG_DIR",
    "http_proxy",
    "https_proxy",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "no_proxy",
    "NO_PROXY",
)
LOCAL_AGENT_ENV_ALLOWED_KEYS = frozenset(
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


class LocalCliProvider:
    """Best-effort adapter for installed coding-agent CLIs with prompt mode."""

    def __init__(self, provider_name: str, command: str | None = None) -> None:
        self.provider_name = provider_name.lower()
        detected = detect_runtime(self.provider_name)
        self.command = command or detected.command or self.provider_name
        self._processes: dict[str, Any] = {}

    async def detect(self) -> RuntimeDetection:
        return detect_runtime(self.provider_name)

    async def version(self) -> str:
        process = await asyncio.create_subprocess_exec(
            self.command,
            "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self.build_env({}),
        )
        stdout, stderr = await process.communicate()
        return (stdout or stderr).decode(errors="replace").strip()

    def build_env(self, user_env: dict[str, str]) -> dict[str, str]:
        env: dict[str, str] = {}
        for key in TRUSTED_LOCAL_AGENT_ENV_KEYS:
            if key in os.environ:
                env[key] = os.environ[key]
        prefix = f"RESEARCH_OS_{self.provider_name.upper()}"
        scoped_keys = {
            "OPENAI_API_KEY": os.environ.get(f"{prefix}_OPENAI_API_KEY"),
            "ANTHROPIC_API_KEY": os.environ.get(f"{prefix}_ANTHROPIC_API_KEY"),
        }
        for key, value in scoped_keys.items():
            if value:
                env[key] = value
        for key, value in user_env.items():
            if key in LOCAL_AGENT_ENV_ALLOWED_KEYS:
                env[key] = value
        return env

    def build_command(self, prompt: str, options: CodingExecOptions) -> list[str]:
        args = [self.command]
        if self.provider_name == "claude":
            args.extend(["-p", prompt])
            if options.model:
                args.extend(["--model", options.model])
        elif self.provider_name == "opencode":
            args.extend(["run", prompt])
            if options.model:
                args.extend(["--model", options.model])
        else:
            args.append(prompt)
        return args

    async def _stop_process(self, process: Any) -> None:
        if process.returncode is not None:
            return
        pid = getattr(process, "pid", None)
        if pid is not None:
            with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
                os.killpg(os.getpgid(pid), signal.SIGTERM)
        else:
            with contextlib.suppress(ProcessLookupError):
                process.terminate()
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(process.wait(), timeout=0.2)
            return
        if process.returncode is None:
            if pid is not None:
                with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
                    os.killpg(os.getpgid(pid), signal.SIGKILL)
            else:
                with contextlib.suppress(ProcessLookupError):
                    process.kill()
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(process.wait(), timeout=0.2)

    async def execute(
        self,
        prompt: str,
        options: CodingExecOptions,
    ) -> AsyncIterator[CodingAgentEvent]:
        command = self.build_command(prompt, options)
        process_key = options.thread_name or options.resume_session_id or f"local:{id(options)}"
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=options.cwd,
                env=self.build_env(options.env),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
        except OSError as exc:
            yield CodingAgentEvent(type="error", content=str(exc), status=classify_agent_failure(str(exc)))
            return

        self._processes[process_key] = process
        yield CodingAgentEvent(type="status", status="started", raw={"provider": self.provider_name})
        try:
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=options.timeout_sec,
                )
            except asyncio.TimeoutError:
                await self._stop_process(process)
                yield CodingAgentEvent(type="error", content="process timeout", status="agent_timeout")
                return
            output = stdout.decode(errors="replace")
            error_output = stderr.decode(errors="replace").strip()
            if output:
                yield CodingAgentEvent(type="text", content=output)
            if error_output:
                yield CodingAgentEvent(type="log", content=error_output, level="warning")
            if process.returncode == 0:
                yield CodingAgentEvent(type="status", status="completed")
                return
            detail = error_output or f"{self.provider_name} exited with code {process.returncode}"
            yield CodingAgentEvent(
                type="error",
                content=detail,
                status=classify_agent_failure(detail),
            )
        finally:
            if self._processes.get(process_key) is process:
                self._processes.pop(process_key, None)

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
        async for event in self.execute(prompt, options.model_copy(update={"resume_session_id": session_id})):
            yield event
