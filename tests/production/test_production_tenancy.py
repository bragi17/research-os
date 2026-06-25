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
