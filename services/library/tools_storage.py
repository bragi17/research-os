"""
Deterministic file storage tools for Paper Library.
All paths under /data/research-os/library/ (vdb disk).
No LLM calls.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

LIBRARY_ROOT = Path(os.getenv("LIBRARY_STORAGE_DIR", "/data/research-os/library"))
SOURCES_DIR = LIBRARY_ROOT / "sources"
PDFS_DIR = LIBRARY_ROOT / "pdfs"
FIGURES_DIR = LIBRARY_ROOT / "figures"
UPLOADS_DIR = LIBRARY_ROOT / "uploads"


def ensure_library_dirs() -> None:
    for d in [SOURCES_DIR, PDFS_DIR, FIGURES_DIR, UPLOADS_DIR]:
        d.mkdir(parents=True, exist_ok=True)


def get_paper_source_dir(arxiv_id: str) -> Path:
    return SOURCES_DIR / arxiv_id.replace("/", "_")


def save_latex_source(arxiv_id: str, source_archive_path: str) -> str:
    dest_dir = get_paper_source_dir(arxiv_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "source.tar.gz"
    shutil.copy2(source_archive_path, dest)
    return str(dest)


def get_paper_pdf_path(arxiv_id: str) -> Path:
    return PDFS_DIR / f"{arxiv_id.replace('/', '_')}.pdf"


def save_uploaded_pdf(file_bytes: bytes, filename: str) -> str:
    ensure_library_dirs()
    from uuid import uuid4

    dest = UPLOADS_DIR / f"{uuid4()}_{filename}"
    dest.write_bytes(file_bytes)
    return str(dest)


def get_figure_dir(library_paper_id: str) -> Path:
    d = FIGURES_DIR / library_paper_id
    d.mkdir(parents=True, exist_ok=True)
    return d
