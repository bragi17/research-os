"""Runtime detection helpers for local coding-agent providers."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess

from apps.worker.production.coding_agents.base import RuntimeDetection
from apps.worker.production.coding_agents.errors import AGENT_RUNTIME_MISSING_EXECUTABLE


PROVIDER_COMMANDS: dict[str, str] = {
    "codex": "codex",
    "claude": "claude",
    "copilot": "copilot",
    "cursor": "cursor",
    "opencode": "opencode",
}


def _env_prefix(provider: str) -> str:
    return f"RESEARCH_OS_{provider.upper()}"


def _support_flags(provider: str) -> dict[str, bool]:
    if provider == "codex":
        return {
            "supports_json_events": True,
            "supports_app_server": True,
            "supports_resume": True,
            "supports_mcp": True,
        }
    if provider == "claude":
        return {
            "supports_json_events": True,
            "supports_app_server": False,
            "supports_resume": True,
            "supports_mcp": True,
        }
    return {
        "supports_json_events": False,
        "supports_app_server": False,
        "supports_resume": False,
        "supports_mcp": False,
    }


def detect_runtime_from_env(
    provider: str,
    env: dict[str, str] | None = None,
) -> RuntimeDetection | None:
    """Detect an explicit provider runtime configured through Research OS env vars."""

    environ = env if env is not None else os.environ
    normalized_provider = provider.lower()
    prefix = _env_prefix(normalized_provider)
    command = environ.get(f"{prefix}_PATH")
    if not command:
        return None

    return RuntimeDetection(
        provider=normalized_provider,
        command=command,
        source="env",
        model=environ.get(f"{prefix}_MODEL"),
        status="available",
        **_support_flags(normalized_provider),
    )


def resolve_command_from_login_shell(command: str, timeout_sec: int = 5) -> str | None:
    """Resolve a command using a login shell for service environments with a sparse PATH."""

    shell = os.environ.get("SHELL") or "/bin/bash"
    try:
        completed = subprocess.run(
            [shell, "-lc", f"command -v {shlex.quote(command)}"],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None

    if completed.returncode != 0:
        return None

    resolved = completed.stdout.strip().splitlines()
    return resolved[0] if resolved else None


def detect_runtime(provider: str, *, use_login_shell: bool = True) -> RuntimeDetection:
    """Detect a local runtime from explicit env config, PATH, then login shell."""

    normalized_provider = provider.lower()
    from_env = detect_runtime_from_env(normalized_provider)
    if from_env is not None:
        return from_env

    command_name = PROVIDER_COMMANDS.get(normalized_provider, normalized_provider)
    path = shutil.which(command_name)
    if path:
        return RuntimeDetection(
            provider=normalized_provider,
            command=path,
            source="path",
            model=os.environ.get(f"{_env_prefix(normalized_provider)}_MODEL"),
            status="available",
            **_support_flags(normalized_provider),
        )

    if use_login_shell:
        shell_path = resolve_command_from_login_shell(command_name)
        if shell_path:
            return RuntimeDetection(
                provider=normalized_provider,
                command=shell_path,
                source="login_shell",
                model=os.environ.get(f"{_env_prefix(normalized_provider)}_MODEL"),
                status="available",
                **_support_flags(normalized_provider),
            )

    return RuntimeDetection(
        provider=normalized_provider,
        command=command_name,
        source="missing",
        status="unavailable",
        failure_reason=AGENT_RUNTIME_MISSING_EXECUTABLE,
        detail=f"{command_name} executable was not found",
    )
