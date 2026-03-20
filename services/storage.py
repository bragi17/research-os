"""
Research OS - Object Storage Service

Provides async file upload/download via MinIO (S3-compatible).
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any, BinaryIO
from uuid import UUID, uuid4

import httpx
from structlog import get_logger

logger = get_logger(__name__)

# MinIO configuration from environment
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "localhost:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "research-os")
MINIO_USE_SSL = os.getenv("MINIO_USE_SSL", "false").lower() == "true"

# For MVP, use local filesystem as fallback when MinIO is not available
STORAGE_BACKEND = os.getenv("STORAGE_BACKEND", "local")  # "local" or "minio"
LOCAL_STORAGE_DIR = os.getenv("LOCAL_STORAGE_DIR", "/tmp/research-os-storage")


class StorageService:
    """
    Object storage service for Research OS.

    Supports:
    - Local filesystem (default for development)
    - MinIO/S3 (for production)
    """

    def __init__(self, backend: str | None = None):
        self.backend = backend or STORAGE_BACKEND
        if self.backend == "local":
            self.base_dir = Path(LOCAL_STORAGE_DIR)
            self.base_dir.mkdir(parents=True, exist_ok=True)

    async def upload_file(
        self,
        content: bytes,
        filename: str,
        content_type: str = "application/octet-stream",
        prefix: str = "uploads",
    ) -> dict[str, str]:
        """
        Upload a file and return storage metadata.

        Returns:
            Dict with keys: object_key, sha256, size, content_type
        """
        sha256 = hashlib.sha256(content).hexdigest()
        ext = Path(filename).suffix
        object_key = f"{prefix}/{sha256[:8]}/{uuid4().hex[:8]}_{filename}"

        if self.backend == "local":
            file_path = self.base_dir / object_key
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_bytes(content)
            logger.info("storage.uploaded_local", key=object_key, size=len(content))
        else:
            # MinIO upload via httpx (minimal S3-compatible PUT)
            # For production, use boto3 or minio-py
            await self._minio_put(object_key, content, content_type)
            logger.info("storage.uploaded_minio", key=object_key, size=len(content))

        return {
            "object_key": object_key,
            "sha256": sha256,
            "size": len(content),
            "content_type": content_type,
        }

    async def download_file(self, object_key: str) -> bytes | None:
        """Download a file by its object key."""
        if self.backend == "local":
            file_path = self.base_dir / object_key
            if file_path.exists():
                return file_path.read_bytes()
            return None
        else:
            return await self._minio_get(object_key)

    async def delete_file(self, object_key: str) -> bool:
        """Delete a file by its object key."""
        if self.backend == "local":
            file_path = self.base_dir / object_key
            if file_path.exists():
                file_path.unlink()
                return True
            return False
        else:
            return await self._minio_delete(object_key)

    async def file_exists(self, object_key: str) -> bool:
        """Check if a file exists."""
        if self.backend == "local":
            return (self.base_dir / object_key).exists()
        else:
            return await self._minio_exists(object_key)

    async def _minio_put(self, key: str, content: bytes, content_type: str) -> None:
        """Upload to MinIO via HTTP PUT."""
        scheme = "https" if MINIO_USE_SSL else "http"
        url = f"{scheme}://{MINIO_ENDPOINT}/{MINIO_BUCKET}/{key}"
        async with httpx.AsyncClient() as client:
            response = await client.put(
                url,
                content=content,
                headers={"Content-Type": content_type},
                auth=(MINIO_ACCESS_KEY, MINIO_SECRET_KEY),
                timeout=60.0,
            )
            if response.status_code not in (200, 204):
                raise ValueError(f"MinIO upload failed: {response.status_code}")

    async def _minio_get(self, key: str) -> bytes | None:
        """Download from MinIO via HTTP GET."""
        scheme = "https" if MINIO_USE_SSL else "http"
        url = f"{scheme}://{MINIO_ENDPOINT}/{MINIO_BUCKET}/{key}"
        async with httpx.AsyncClient() as client:
            response = await client.get(
                url,
                auth=(MINIO_ACCESS_KEY, MINIO_SECRET_KEY),
                timeout=60.0,
            )
            if response.status_code == 200:
                return response.content
            return None

    async def _minio_delete(self, key: str) -> bool:
        scheme = "https" if MINIO_USE_SSL else "http"
        url = f"{scheme}://{MINIO_ENDPOINT}/{MINIO_BUCKET}/{key}"
        async with httpx.AsyncClient() as client:
            response = await client.delete(
                url,
                auth=(MINIO_ACCESS_KEY, MINIO_SECRET_KEY),
                timeout=30.0,
            )
            return response.status_code in (200, 204)

    async def _minio_exists(self, key: str) -> bool:
        scheme = "https" if MINIO_USE_SSL else "http"
        url = f"{scheme}://{MINIO_ENDPOINT}/{MINIO_BUCKET}/{key}"
        async with httpx.AsyncClient() as client:
            response = await client.head(
                url,
                auth=(MINIO_ACCESS_KEY, MINIO_SECRET_KEY),
                timeout=10.0,
            )
            return response.status_code == 200


# Singleton
_storage: StorageService | None = None

def get_storage() -> StorageService:
    global _storage
    if _storage is None:
        _storage = StorageService()
    return _storage
