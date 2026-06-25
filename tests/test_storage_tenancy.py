from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from services.storage import workspace_object_prefix


WORKSPACE_ID = UUID("11111111-1111-1111-1111-111111111111")
USER_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


def test_workspace_object_prefix_is_safe_and_stable() -> None:
    workspace_id = UUID("11111111-1111-1111-1111-111111111111")

    assert workspace_object_prefix(workspace_id, "pdfs") == (
        "workspaces/11111111-1111-1111-1111-111111111111/pdfs"
    )


def test_workspace_object_prefix_rejects_unsafe_prefix() -> None:
    workspace_id = UUID("11111111-1111-1111-1111-111111111111")

    try:
        workspace_object_prefix(workspace_id, "../pdfs")
    except ValueError as exc:
        assert str(exc) == "storage prefix must be relative and safe"
    else:
        raise AssertionError("unsafe prefix accepted")


def test_upload_uses_authenticated_workspace_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import apps.api.database as database
    import apps.api.redis_queue as redis_queue
    import apps.api.routes_files as routes_files
    from apps.api.app import create_app

    captured: dict[str, Any] = {}

    async def fake_get_current_user() -> dict[str, Any]:
        return {
            "id": USER_ID,
            "workspace_id": WORKSPACE_ID,
            "role": "research_user",
        }

    class FakeStorage:
        async def upload_file(
            self,
            *,
            content: bytes,
            filename: str,
            content_type: str,
            prefix: str,
        ) -> dict[str, Any]:
            captured["prefix"] = prefix
            return {
                "object_key": f"{prefix}/abc12345/upload.pdf",
                "sha256": "abc123",
                "size": len(content),
                "content_type": content_type,
            }

    monkeypatch.setattr(database, "init_pool", AsyncMock())
    monkeypatch.setattr(database, "close_pool", AsyncMock())
    monkeypatch.setattr(redis_queue, "init_redis", AsyncMock())
    monkeypatch.setattr(redis_queue, "close_redis", AsyncMock())
    monkeypatch.setattr(routes_files, "get_storage", lambda: FakeStorage())

    app = create_app()
    app.dependency_overrides[routes_files.get_current_user] = fake_get_current_user
    client = TestClient(app)

    response = client.post(
        "/api/v1/files/upload",
        files={"file": ("upload.pdf", b"%PDF-1.7\n", "application/pdf")},
    )

    assert response.status_code == 200
    assert captured["prefix"] == (
        "workspaces/11111111-1111-1111-1111-111111111111/pdfs"
    )
