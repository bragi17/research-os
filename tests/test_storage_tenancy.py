from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

import services.storage as storage_module
from services.storage import StorageService, workspace_object_prefix


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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "filename",
    [
        "../evil.pdf",
        "..\\evil.pdf",
        "",
        ".",
        "..",
    ],
)
async def test_local_upload_rejects_unsafe_filename(
    tmp_path,
    filename: str,
) -> None:
    storage = StorageService(backend="local")
    storage.base_dir = tmp_path / "storage"
    storage.base_dir.mkdir()
    prefix = workspace_object_prefix(WORKSPACE_ID, "pdfs")

    with pytest.raises(ValueError, match="filename must be a safe basename"):
        await storage.upload_file(
            content=b"%PDF-1.7\n",
            filename=filename,
            content_type="application/pdf",
            prefix=prefix,
        )

    assert not (tmp_path / "evil.pdf").exists()


@pytest.mark.asyncio
async def test_local_upload_with_workspace_prefix_writes_under_base_dir(
    tmp_path,
) -> None:
    storage = StorageService(backend="local")
    storage.base_dir = tmp_path / "storage"
    storage.base_dir.mkdir()
    prefix = workspace_object_prefix(WORKSPACE_ID, "pdfs")

    metadata = await storage.upload_file(
        content=b"%PDF-1.7\n",
        filename="paper.pdf",
        content_type="application/pdf",
        prefix=prefix,
    )

    base_dir = storage.base_dir.resolve()
    uploaded_path = (storage.base_dir / metadata["object_key"]).resolve()

    assert uploaded_path.is_relative_to(base_dir)
    assert uploaded_path.read_bytes() == b"%PDF-1.7\n"
    assert metadata["object_key"].startswith(
        "workspaces/11111111-1111-1111-1111-111111111111/pdfs/"
    )


@pytest.mark.asyncio
async def test_local_upload_rejects_object_key_that_escapes_base_dir(
    tmp_path,
) -> None:
    storage = StorageService(backend="local")
    storage.base_dir = tmp_path / "storage"
    storage.base_dir.mkdir()

    with pytest.raises(ValueError, match="storage path escapes base directory"):
        await storage.upload_file(
            content=b"%PDF-1.7\n",
            filename="paper.pdf",
            content_type="application/pdf",
            prefix="../../../outside",
        )

    assert not (tmp_path / "outside").exists()


@pytest.mark.asyncio
async def test_minio_upload_uses_s3_signature_instead_of_basic_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class FakeResponse:
        status_code = 200
        content = b""

    class FakeAsyncClient:
        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def put(
            self,
            url: str,
            *,
            content: bytes,
            headers: dict[str, str],
            auth: object | None = None,
            timeout: float,
        ) -> FakeResponse:
            captured.update({
                "url": url,
                "content": content,
                "headers": headers,
                "auth": auth,
                "timeout": timeout,
            })
            return FakeResponse()

    monkeypatch.setattr(storage_module.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(storage_module, "MINIO_ENDPOINT", "minio:9000")
    monkeypatch.setattr(storage_module, "MINIO_BUCKET", "research-os")
    monkeypatch.setattr(storage_module, "MINIO_ACCESS_KEY", "test-access")
    monkeypatch.setattr(storage_module, "MINIO_SECRET_KEY", "test-secret")
    monkeypatch.setattr(storage_module, "MINIO_USE_SSL", False)

    metadata = await StorageService(backend="minio").upload_file(
        content=b"%PDF-1.7\n",
        filename="paper.pdf",
        content_type="application/pdf",
        prefix=workspace_object_prefix(WORKSPACE_ID, "pdfs"),
    )

    assert captured["auth"] is None
    assert captured["headers"]["Authorization"].startswith("AWS4-HMAC-SHA256 ")
    assert "Credential=test-access/" in captured["headers"]["Authorization"]
    assert captured["headers"]["x-amz-content-sha256"]
    assert captured["headers"]["x-amz-date"]
    assert captured["headers"]["Content-Type"] == "application/pdf"
    assert captured["url"].startswith("http://minio:9000/research-os/workspaces/")
    assert metadata["object_key"].startswith(
        "workspaces/11111111-1111-1111-1111-111111111111/pdfs/"
    )


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
