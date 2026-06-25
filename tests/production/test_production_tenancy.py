from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import HTTPException

from apps.api.routes_production import _project_for_access
from apps.worker.production.workspaces import resolve_project_workspace_path


class FakeDb:
    def __init__(self, project):
        self.project = project

    async def get_project(self, project_id):
        if self.project and self.project["id"] == project_id:
            return self.project
        return None


@pytest.mark.asyncio
async def test_project_access_accepts_workspace_member(monkeypatch) -> None:
    workspace_id = uuid4()
    project_id = uuid4()
    user_id = uuid4()
    project = {"id": project_id, "workspace_id": workspace_id, "owner_user_id": uuid4()}
    ctx_user = {"id": user_id, "workspace_id": workspace_id, "role": "research_user"}

    import apps.api.routes_production as routes_production

    monkeypatch.setattr(routes_production, "db", FakeDb(project))

    result = await _project_for_access(project_id, ctx_user)

    assert result == project


@pytest.mark.asyncio
async def test_project_access_rejects_other_workspace(monkeypatch) -> None:
    project_id = uuid4()
    project = {"id": project_id, "workspace_id": uuid4(), "owner_user_id": uuid4()}
    ctx_user = {"id": uuid4(), "workspace_id": uuid4(), "role": "research_user"}

    import apps.api.routes_production as routes_production

    monkeypatch.setattr(routes_production, "db", FakeDb(project))

    with pytest.raises(HTTPException) as exc:
        await _project_for_access(project_id, ctx_user)

    assert exc.value.status_code == 403
    assert exc.value.detail == "Project access denied"


def test_workspace_path_includes_workspace_segment(monkeypatch, tmp_path: Path) -> None:
    workspace_id = uuid4()
    project_id = uuid4()
    monkeypatch.setenv("RESEARCH_OS_WORKSPACE_ROOT", str(tmp_path))

    path = resolve_project_workspace_path({
        "id": project_id,
        "workspace_id": workspace_id,
        "default_workspace_path": None,
    })

    assert path == tmp_path / "workspaces" / str(workspace_id) / "projects" / str(project_id)


def test_relative_default_workspace_path_is_project_workspace_scoped(
    monkeypatch,
    tmp_path: Path,
) -> None:
    first_workspace_id = uuid4()
    second_workspace_id = uuid4()
    first_project_id = uuid4()
    second_project_id = uuid4()
    monkeypatch.setenv("RESEARCH_OS_WORKSPACE_ROOT", str(tmp_path))

    first_path = resolve_project_workspace_path({
        "id": first_project_id,
        "workspace_id": first_workspace_id,
        "default_workspace_path": "shared",
    })
    second_path = resolve_project_workspace_path({
        "id": second_project_id,
        "workspace_id": second_workspace_id,
        "default_workspace_path": "shared",
    })

    assert first_path == (
        tmp_path
        / "workspaces"
        / str(first_workspace_id)
        / "projects"
        / str(first_project_id)
        / "shared"
    )
    assert second_path == (
        tmp_path
        / "workspaces"
        / str(second_workspace_id)
        / "projects"
        / str(second_project_id)
        / "shared"
    )
    assert first_path != second_path


def test_absolute_default_workspace_path_rejects_other_workspace_segment(
    monkeypatch,
    tmp_path: Path,
) -> None:
    project_workspace_id = uuid4()
    other_workspace_id = uuid4()
    project_id = uuid4()
    other_project_id = uuid4()
    monkeypatch.setenv("RESEARCH_OS_WORKSPACE_ROOT", str(tmp_path))
    other_workspace_path = (
        tmp_path
        / "workspaces"
        / str(other_workspace_id)
        / "projects"
        / str(other_project_id)
        / "shared"
    )

    with pytest.raises(ValueError, match="default_workspace_path escapes project workspace root"):
        resolve_project_workspace_path({
            "id": project_id,
            "workspace_id": project_workspace_id,
            "default_workspace_path": str(other_workspace_path),
        })


def test_legacy_project_explicit_workspace_path_uses_legacy_segment(
    monkeypatch,
    tmp_path: Path,
) -> None:
    project_id = uuid4()
    monkeypatch.setenv("RESEARCH_OS_WORKSPACE_ROOT", str(tmp_path))

    path = resolve_project_workspace_path({
        "id": project_id,
        "workspace_id": None,
        "default_workspace_path": "shared",
    })

    assert path == tmp_path / "shared"
    assert "workspaces" not in path.relative_to(tmp_path).parts
