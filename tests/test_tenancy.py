from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from apps.api.tenancy import WorkspaceContext, require_same_workspace, same_id


def test_same_id_compares_uuid_and_string_values() -> None:
    value = uuid4()

    assert same_id(value, str(value)) is True
    assert same_id(value, uuid4()) is False


def test_same_id_compares_uuid_strings_case_insensitively() -> None:
    value = uuid4()

    assert same_id(value, str(value).upper()) is True


def test_workspace_context_from_user_requires_workspace_id() -> None:
    user_id = uuid4()

    ctx = WorkspaceContext.from_user({
        "id": user_id,
        "workspace_id": UUID("11111111-1111-1111-1111-111111111111"),
        "role": "research_user",
    })

    assert ctx.user_id == user_id
    assert ctx.workspace_id == UUID("11111111-1111-1111-1111-111111111111")
    assert ctx.role == "research_user"


def test_workspace_context_from_user_rejects_missing_workspace_id() -> None:
    with pytest.raises(HTTPException) as exc:
        WorkspaceContext.from_user({"id": uuid4(), "role": "research_user"})

    assert exc.value.status_code == 403
    assert exc.value.detail == "Workspace membership required"


def test_workspace_context_from_user_rejects_missing_user_id() -> None:
    with pytest.raises(HTTPException) as exc:
        WorkspaceContext.from_user({"workspace_id": uuid4(), "role": "research_user"})

    assert exc.value.status_code == 403
    assert exc.value.detail == "Workspace membership required"


@pytest.mark.parametrize(
    "user",
    [
        {"id": "not-a-uuid", "workspace_id": uuid4(), "role": "research_user"},
        {"id": uuid4(), "workspace_id": "not-a-uuid", "role": "research_user"},
    ],
)
def test_workspace_context_from_user_rejects_malformed_ids(user: dict[str, object]) -> None:
    with pytest.raises(HTTPException) as exc:
        WorkspaceContext.from_user(user)

    assert exc.value.status_code == 403
    assert exc.value.detail == "Workspace membership required"


def test_require_same_workspace_allows_matching_rows() -> None:
    workspace_id = uuid4()
    ctx = WorkspaceContext(user_id=uuid4(), workspace_id=workspace_id, role="research_user")

    require_same_workspace({"workspace_id": str(workspace_id)}, ctx)


def test_require_same_workspace_rejects_mismatched_rows() -> None:
    ctx = WorkspaceContext(user_id=uuid4(), workspace_id=uuid4(), role="research_user")

    with pytest.raises(HTTPException) as exc:
        require_same_workspace({"workspace_id": uuid4()}, ctx)

    assert exc.value.status_code == 404
    assert exc.value.detail == "Resource not found"
