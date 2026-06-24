"""Failure classification for local coding-agent runtime errors."""

from __future__ import annotations


AGENT_CONTEXT_OVERFLOW = "agent_context_overflow"
AGENT_MISSING_CONFIG = "agent_missing_config"
AGENT_PROVIDER_AUTH_OR_ACCESS = "agent_provider_auth_or_access"
AGENT_PROVIDER_QUOTA_LIMIT = "agent_provider_quota_limit"
AGENT_PROVIDER_CAPACITY_OR_RATE_LIMIT = "agent_provider_capacity_or_rate_limit"
AGENT_PROVIDER_SERVER_ERROR = "agent_provider_server_error"
AGENT_PROVIDER_NETWORK = "agent_provider_network"
AGENT_MODEL_NOT_FOUND_OR_UNAVAILABLE = "agent_model_not_found_or_unavailable"
AGENT_EMPTY_OR_UNPARSEABLE_OUTPUT = "agent_empty_or_unparseable_output"
AGENT_TIMEOUT = "agent_timeout"
AGENT_RUNTIME_MISSING_EXECUTABLE = "agent_runtime_missing_executable"
AGENT_RUNTIME_VERSION_UNSUPPORTED = "agent_runtime_version_unsupported"
AGENT_PROCESS_FAILURE = "agent_process_failure"
AGENT_UNKNOWN = "agent_unknown"


def _contains_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(needle in text for needle in needles)


def classify_agent_failure(message: str | None, *, returncode: int | None = None) -> str:
    """Classify provider/runtime failure text into a stable Research OS reason."""

    text = (message or "").strip().lower()
    if not text:
        return AGENT_EMPTY_OR_UNPARSEABLE_OUTPUT

    # Context overflow must win before broad quota/limit phrases.
    if _contains_any(
        text,
        (
            "context length",
            "context_length",
            "maximum context",
            "max context",
            "context window",
            "too many tokens",
            "token limit exceeded",
            "reduce the length",
        ),
    ):
        return AGENT_CONTEXT_OVERFLOW

    if _contains_any(
        text,
        (
            "missing config",
            "not configured",
            "no api key",
            "api key not set",
            "missing api key",
            "configuration required",
            "configure",
        ),
    ):
        return AGENT_MISSING_CONFIG

    if _contains_any(
        text,
        (
            "unauthorized",
            "forbidden",
            "permission denied",
            "access denied",
            "invalid api key",
            "401",
            "403",
            "login required",
            "not logged in",
            "authentication",
        ),
    ):
        return AGENT_PROVIDER_AUTH_OR_ACCESS

    if _contains_any(
        text,
        (
            "quota exceeded",
            "insufficient quota",
            "billing",
            "credit balance",
            "hard limit",
        ),
    ):
        return AGENT_PROVIDER_QUOTA_LIMIT

    if _contains_any(
        text,
        (
            "rate limit",
            "rate_limit",
            "429",
            "too many requests",
            "capacity",
            "overloaded",
            "temporarily unavailable",
            "try again later",
        ),
    ):
        return AGENT_PROVIDER_CAPACITY_OR_RATE_LIMIT

    if _contains_any(
        text,
        (
            "internal server error",
            "server error",
            "bad gateway",
            "service unavailable",
            "gateway timeout",
            "500",
            "502",
            "503",
            "504",
        ),
    ):
        return AGENT_PROVIDER_SERVER_ERROR

    if _contains_any(
        text,
        (
            "network",
            "connection refused",
            "connection reset",
            "dns",
            "econnreset",
            "enotfound",
            "socket",
            "tls",
            "ssl",
        ),
    ):
        return AGENT_PROVIDER_NETWORK

    if ("model" in text and "not found" in text) or _contains_any(
        text,
        (
            "model not found",
            "unknown model",
            "model unavailable",
            "does not exist",
            "unsupported model",
        ),
    ):
        return AGENT_MODEL_NOT_FOUND_OR_UNAVAILABLE

    if _contains_any(
        text,
        (
            "empty output",
            "unparseable output",
            "invalid json",
            "json parse",
            "no output",
        ),
    ):
        return AGENT_EMPTY_OR_UNPARSEABLE_OUTPUT

    if _contains_any(text, ("timed out", "timeout", "deadline exceeded")):
        return AGENT_TIMEOUT

    if _contains_any(
        text,
        (
            "no such file or directory",
            "executable not found",
            "command not found",
            "not found: codex",
            "enoent",
        ),
    ):
        return AGENT_RUNTIME_MISSING_EXECUTABLE

    if ("unsupported" in text and "version" in text) or _contains_any(
        text,
        (
            "unsupported version",
            "version unsupported",
            "version too old",
            "requires version",
        ),
    ):
        return AGENT_RUNTIME_VERSION_UNSUPPORTED

    if returncode is not None and returncode != 0:
        return AGENT_PROCESS_FAILURE

    if _contains_any(text, ("process exited", "exit status", "non-zero", "return code")):
        return AGENT_PROCESS_FAILURE

    return AGENT_UNKNOWN
