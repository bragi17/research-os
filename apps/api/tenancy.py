from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from fastapi import HTTPException


def same_id(left: Any, right: Any) -> bool:
    return str(left) == str(right)


@dataclass(frozen=True)
class WorkspaceContext:
    user_id: UUID
    workspace_id: UUID
    role: str

    @classmethod
    def from_user(cls, user: dict[str, Any]) -> "WorkspaceContext":
        workspace_id = user.get("workspace_id")
        user_id = user.get("id")
        if workspace_id is None or user_id is None:
            raise HTTPException(status_code=403, detail="Workspace membership required")
        return cls(
            user_id=UUID(str(user_id)),
            workspace_id=UUID(str(workspace_id)),
            role=str(user.get("role") or "research_user"),
        )


def require_same_workspace(
    row: dict[str, Any],
    ctx: WorkspaceContext,
    *,
    field_name: str = "workspace_id",
) -> None:
    if not same_id(row.get(field_name), ctx.workspace_id):
        raise HTTPException(status_code=404, detail="Resource not found")
