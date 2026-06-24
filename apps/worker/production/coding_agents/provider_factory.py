"""Provider selection helpers for local coding-agent CLIs."""

from __future__ import annotations

from apps.worker.production.coding_agents.base import CodingAgentProvider
from apps.worker.production.coding_agents.codex_provider import CodexProvider
from apps.worker.production.coding_agents.local_cli_provider import LocalCliProvider


def provider_for_name(provider_name: str | None) -> CodingAgentProvider:
    normalized = (provider_name or "codex").lower()
    if normalized == "codex":
        return CodexProvider()
    return LocalCliProvider(normalized)
