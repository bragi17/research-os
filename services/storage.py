"""
Research OS - Object Storage Service

Provides async file upload/download via MinIO (S3-compatible).
"""

from __future__ import annotations

import hashlib
import hmac
import os
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, urlparse
from uuid import UUID, uuid4

import httpx
from structlog import get_logger

logger = get_logger(__name__)

# MinIO configuration from environment
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "localhost:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "research-os")
MINIO_REGION = os.getenv("MINIO_REGION", "us-east-1")
MINIO_USE_SSL = os.getenv("MINIO_USE_SSL", "false").lower() == "true"

# For MVP, use local filesystem as fallback when MinIO is not available
STORAGE_BACKEND = os.getenv("STORAGE_BACKEND", "local")  # "local" or "minio"
LOCAL_STORAGE_DIR = os.getenv("LOCAL_STORAGE_DIR", "/tmp/research-os-storage")


def workspace_object_prefix(workspace_id: UUID | str, prefix: str) -> str:
    relative = Path(prefix)
    if (
        relative.is_absolute()
        or not relative.parts
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise ValueError("storage prefix must be relative and safe")
    return f"workspaces/{UUID(str(workspace_id))}/{relative.as_posix()}"


def _safe_filename(filename: str) -> str:
    if not filename or filename in {".", ".."} or "/" in filename or "\\" in filename:
        raise ValueError("filename must be a safe basename")
    return filename


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
        safe_filename = _safe_filename(filename)
        sha256 = hashlib.sha256(content).hexdigest()
        object_key = f"{prefix}/{sha256[:8]}/{uuid4().hex[:8]}_{safe_filename}"

        if self.backend == "local":
            base_dir = self.base_dir.resolve()
            file_path = (base_dir / object_key).resolve()
            try:
                file_path.relative_to(base_dir)
            except ValueError as exc:
                raise ValueError("storage path escapes base directory") from exc
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_bytes(content)
            logger.info("storage.uploaded_local", key=object_key, size=len(content))
        else:
            # MinIO/S3 path-style upload with AWS Signature V4 headers.
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
        """Upload to MinIO via signed S3 HTTP PUT."""
        url, canonical_uri, host = _minio_object_url(key)
        headers = _minio_signed_headers(
            "PUT",
            canonical_uri=canonical_uri,
            host=host,
            content=content,
            content_type=content_type,
        )
        async with httpx.AsyncClient() as client:
            response = await client.put(
                url,
                content=content,
                headers=headers,
                timeout=60.0,
            )
            if response.status_code not in (200, 204):
                raise ValueError(f"MinIO upload failed: {response.status_code}")

    async def _minio_get(self, key: str) -> bytes | None:
        """Download from MinIO via HTTP GET."""
        url, canonical_uri, host = _minio_object_url(key)
        headers = _minio_signed_headers(
            "GET",
            canonical_uri=canonical_uri,
            host=host,
            content=b"",
        )
        async with httpx.AsyncClient() as client:
            response = await client.get(
                url,
                headers=headers,
                timeout=60.0,
            )
            if response.status_code == 200:
                return response.content
            return None

    async def _minio_delete(self, key: str) -> bool:
        url, canonical_uri, host = _minio_object_url(key)
        headers = _minio_signed_headers(
            "DELETE",
            canonical_uri=canonical_uri,
            host=host,
            content=b"",
        )
        async with httpx.AsyncClient() as client:
            response = await client.delete(
                url,
                headers=headers,
                timeout=30.0,
            )
            return response.status_code in (200, 204)

    async def _minio_exists(self, key: str) -> bool:
        url, canonical_uri, host = _minio_object_url(key)
        headers = _minio_signed_headers(
            "HEAD",
            canonical_uri=canonical_uri,
            host=host,
            content=b"",
        )
        async with httpx.AsyncClient() as client:
            response = await client.head(
                url,
                headers=headers,
                timeout=10.0,
            )
            return response.status_code == 200


def _minio_base() -> tuple[str, str]:
    endpoint = MINIO_ENDPOINT.rstrip("/")
    if "://" in endpoint:
        parsed = urlparse(endpoint)
        base = f"{parsed.scheme}://{parsed.netloc}{parsed.path.rstrip('/')}"
        return base, parsed.netloc
    scheme = "https" if MINIO_USE_SSL else "http"
    return f"{scheme}://{endpoint}", endpoint


def _minio_object_url(key: str) -> tuple[str, str, str]:
    base, host = _minio_base()
    bucket = quote(MINIO_BUCKET, safe="")
    escaped_key = quote(key, safe="/")
    canonical_uri = f"/{bucket}/{escaped_key}"
    return f"{base}{canonical_uri}", canonical_uri, host


def _signing_key(secret_key: str, date_stamp: str) -> bytes:
    date_key = hmac.new(f"AWS4{secret_key}".encode(), date_stamp.encode(), hashlib.sha256).digest()
    region_key = hmac.new(date_key, MINIO_REGION.encode(), hashlib.sha256).digest()
    service_key = hmac.new(region_key, b"s3", hashlib.sha256).digest()
    return hmac.new(service_key, b"aws4_request", hashlib.sha256).digest()


def _minio_signed_headers(
    method: str,
    *,
    canonical_uri: str,
    host: str,
    content: bytes,
    content_type: str | None = None,
) -> dict[str, str]:
    payload_hash = hashlib.sha256(content).hexdigest()
    now = datetime.utcnow()
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")

    headers = {
        "Host": host,
        "x-amz-content-sha256": payload_hash,
        "x-amz-date": amz_date,
    }
    if content_type:
        headers["Content-Type"] = content_type

    canonical_header_values = {
        name.lower(): " ".join(value.strip().split())
        for name, value in headers.items()
    }
    signed_header_names = sorted(canonical_header_values)
    canonical_headers = "".join(
        f"{name}:{canonical_header_values[name]}\n"
        for name in signed_header_names
    )
    signed_headers = ";".join(signed_header_names)
    canonical_request = "\n".join([
        method,
        canonical_uri,
        "",
        canonical_headers,
        signed_headers,
        payload_hash,
    ])

    credential_scope = f"{date_stamp}/{MINIO_REGION}/s3/aws4_request"
    string_to_sign = "\n".join([
        "AWS4-HMAC-SHA256",
        amz_date,
        credential_scope,
        hashlib.sha256(canonical_request.encode()).hexdigest(),
    ])
    signature = hmac.new(
        _signing_key(MINIO_SECRET_KEY, date_stamp),
        string_to_sign.encode(),
        hashlib.sha256,
    ).hexdigest()
    headers["Authorization"] = (
        "AWS4-HMAC-SHA256 "
        f"Credential={MINIO_ACCESS_KEY}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, "
        f"Signature={signature}"
    )
    return headers


# Singleton
_storage: StorageService | None = None

def get_storage() -> StorageService:
    global _storage
    if _storage is None:
        _storage = StorageService()
    return _storage
