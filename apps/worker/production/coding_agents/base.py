"""Shared contracts for local coding-agent runtime adapters."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field


CodingAgentEventType = Literal[
    "text",
    "thinking",
    "tool_use",
    "tool_result",
    "status",
    "error",
    "log",
]


class CodingAgentEvent(BaseModel):
    """Normalized event emitted by a local coding-agent provider."""

    type: CodingAgentEventType
    content: str | None = None
    tool: str | None = None
    call_id: str | None = None
    input: dict[str, Any] | None = None
    output: str | None = None
    status: str | None = None
    level: str | None = None
    session_id: str | None = None
    raw: dict[str, Any] | None = None


class CodingAgentResult(BaseModel):
    """Final result for a coding-agent invocation."""

    status: Literal["completed", "failed", "timeout", "cancelled", "blocked"]
    output: str = ""
    error: str | None = None
    duration_ms: int = 0
    session_id: str | None = None
    usage: dict[str, Any] = Field(default_factory=dict)


class CodingExecOptions(BaseModel):
    """Execution options for one coding-agent invocation."""

    cwd: str
    model: str | None = None
    system_prompt: str | None = None
    thread_name: str | None = None
    timeout_sec: int | None = None
    semantic_inactivity_timeout_sec: int | None = None
    resume_session_id: str | None = None
    extra_args: list[str] = Field(default_factory=list)
    custom_args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    mcp_config: dict[str, Any] | None = None
    thinking_level: str | None = None
    sandbox: Literal["read-only", "workspace-write"] = "workspace-write"


class RuntimeDetection(BaseModel):
    """Detected local runtime metadata for one provider."""

    provider: str
    command: str | None = None
    source: str | None = None
    model: str | None = None
    version: str | None = None
    status: Literal["available", "unavailable", "unsupported"] = "unavailable"
    supports_json_events: bool = False
    supports_app_server: bool = False
    supports_resume: bool = False
    supports_mcp: bool = False
    auth: str | None = None
    failure_reason: str | None = None
    detail: str | None = None


class CodingAgentProvider(Protocol):
    """Protocol implemented by local coding-agent providers."""

    provider_name: str

    async def detect(self) -> RuntimeDetection: ...

    async def version(self) -> str: ...

    async def execute(
        self,
        prompt: str,
        options: CodingExecOptions,
    ) -> AsyncIterator[CodingAgentEvent]: ...

    async def cancel(self, task_id: str) -> None: ...

    async def resume(
        self,
        session_id: str,
        prompt: str,
        options: CodingExecOptions,
    ) -> AsyncIterator[CodingAgentEvent]: ...
