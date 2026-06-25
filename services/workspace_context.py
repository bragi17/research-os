from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator
from uuid import UUID


DEFAULT_WORKSPACE_UUID = UUID("00000000-0000-0000-0000-000000000000")

_workspace_id: ContextVar[UUID] = ContextVar(
    "research_os_workspace_id",
    default=DEFAULT_WORKSPACE_UUID,
)


def current_workspace_id() -> UUID:
    return _workspace_id.get()


@contextmanager
def workspace_context(workspace_id: UUID | str) -> Iterator[None]:
    token = _workspace_id.set(UUID(str(workspace_id)))
    try:
        yield
    finally:
        _workspace_id.reset(token)
