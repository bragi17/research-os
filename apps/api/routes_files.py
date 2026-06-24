"""File upload API routes."""

from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from structlog import get_logger

from services.storage import get_storage

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/files", tags=["files"])

MAX_UPLOAD_SIZE = 50 * 1024 * 1024


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(..., description="PDF file to upload"),
) -> dict[str, Any]:
    """Upload a PDF file to object storage."""
    if file.content_type and file.content_type != "application/pdf":
        raise HTTPException(
            status_code=400,
            detail=f"Only PDF files are accepted. Got: {file.content_type}",
        )

    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required")

    content = await file.read()

    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Max size: {MAX_UPLOAD_SIZE // (1024 * 1024)} MB",
        )

    storage = get_storage()
    try:
        metadata = await storage.upload_file(
            content=content,
            filename=file.filename,
            content_type=file.content_type or "application/pdf",
            prefix="pdfs",
        )
    except Exception as exc:
        logger.error("file_upload_failed", filename=file.filename, error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to upload file")

    logger.info(
        "file_uploaded",
        filename=file.filename,
        size=metadata["size"],
        key=metadata["object_key"],
    )

    return {
        "status": "uploaded",
        "filename": file.filename,
        "object_key": metadata["object_key"],
        "sha256": metadata["sha256"],
        "size": metadata["size"],
        "content_type": metadata["content_type"],
    }
