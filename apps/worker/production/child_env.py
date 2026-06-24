"""Constrained child-process environment for local execution surfaces."""

from __future__ import annotations

import os


DEFAULT_INHERITED_ENV_KEYS = (
    "PATH",
    "HOME",
    "USER",
    "LOGNAME",
    "LANG",
    "LC_ALL",
    "TERM",
    "TMPDIR",
    "VIRTUAL_ENV",
)


def scrubbed_child_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Return a small environment without service credentials."""

    env: dict[str, str] = {}
    for key in DEFAULT_INHERITED_ENV_KEYS:
        value = os.environ.get(key)
        if value is not None:
            env[key] = value
    if extra:
        env.update({str(key): str(value) for key, value in extra.items()})
    return env
