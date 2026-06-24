"""Coding-agent runtime adapters for production research workflows."""

from apps.worker.production.coding_agents.base import (
    CodingAgentEvent,
    CodingAgentProvider,
    CodingAgentResult,
    CodingExecOptions,
    RuntimeDetection,
)
from apps.worker.production.coding_agents.codex_provider import CodexProvider
from apps.worker.production.coding_agents.errors import classify_agent_failure
from apps.worker.production.coding_agents.local_cli_provider import LocalCliProvider
from apps.worker.production.coding_agents.provider_factory import provider_for_name

__all__ = [
    "CodexProvider",
    "LocalCliProvider",
    "CodingAgentEvent",
    "CodingAgentProvider",
    "CodingAgentResult",
    "CodingExecOptions",
    "RuntimeDetection",
    "classify_agent_failure",
    "provider_for_name",
]
