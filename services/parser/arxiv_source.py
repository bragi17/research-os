"""
Research OS - arXiv LaTeX Source Downloader

Downloads and extracts LaTeX source files from arXiv for structured parsing.
"""

from __future__ import annotations

import asyncio
import gzip
import os
import re
import shutil
import tarfile
from pathlib import Path
from typing import Any

import httpx
from structlog import get_logger

logger = get_logger(__name__)

ARXIV_EPRINT_URL = "https://arxiv.org/e-print/{arxiv_id}"
CACHE_DIR_NAME = ".arxiv-cache"


def parse_arxiv_id(input_str: str) -> str:
    """
    Parse arXiv ID from various input formats.

    Supports:
    - Modern: "2301.07041" or "2301.07041v2"
    - Legacy: "math.GT/0703024"
    - Full URLs: "https://arxiv.org/abs/2301.07041"
    - PDF URLs: "https://arxiv.org/pdf/2301.07041.pdf"
    """
    clean = input_str.strip()

    # Modern format
    modern = re.search(r'(\d{4}\.\d{4,5}(?:v\d+)?)', clean)
    if modern:
        return modern.group(1)

    # Legacy format
    old = re.search(r'([a-zA-Z\-\.]+/\d{7})', clean)
    if old:
        return old.group(1)

    raise ValueError(f"Could not parse arXiv ID from: {input_str}")


async def download_arxiv_source(
    arxiv_id: str,
    cache_dir: str | Path | None = None,
    timeout: float = 120.0,
) -> Path:
    """
    Download arXiv LaTeX source (.tar.gz or .gz) to local cache.

    Args:
        arxiv_id: Parsed arXiv ID (e.g., "2301.07041")
        cache_dir: Directory to cache downloads (default: /tmp/.arxiv-cache)
        timeout: Download timeout in seconds

    Returns:
        Path to downloaded archive file

    Raises:
        ValueError: If source not available (PDF-only submissions)
        httpx.HTTPError: On download failure
    """
    if cache_dir is None:
        cache_dir = Path("/tmp") / CACHE_DIR_NAME
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Sanitize arxiv_id for filename
    safe_id = arxiv_id.replace("/", "_")
    archive_path = cache_dir / f"{safe_id}.tar.gz"

    # Check cache
    if archive_path.exists() and archive_path.stat().st_size > 0:
        logger.info("arxiv_source.cache_hit", arxiv_id=arxiv_id)
        return archive_path

    url = ARXIV_EPRINT_URL.format(arxiv_id=arxiv_id)
    logger.info("arxiv_source.downloading", arxiv_id=arxiv_id, url=url)

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(timeout),
        follow_redirects=True,
    ) as client:
        response = await client.get(url)

        if response.status_code >= 400:
            raise ValueError(
                f"arXiv download failed with status {response.status_code} for {arxiv_id}"
            )

        content_type = response.headers.get("content-type", "")
        if "application/pdf" in content_type:
            raise ValueError(
                f"LaTeX source not available for {arxiv_id} (got PDF - submission is PDF-only)"
            )

        archive_path.write_bytes(response.content)
        logger.info(
            "arxiv_source.downloaded",
            arxiv_id=arxiv_id,
            size=len(response.content),
        )

    return archive_path


def extract_arxiv_source(
    archive_path: str | Path,
    extract_dir: str | Path,
) -> list[Path]:
    """
    Extract arXiv source archive to directory.

    Handles:
    - .tar.gz archives (most common)
    - .gz single files (some submissions)
    - Plain text (rare single-file submissions)

    Returns:
        List of extracted file paths
    """
    archive_path = Path(archive_path)
    extract_dir = Path(extract_dir)
    extract_dir.mkdir(parents=True, exist_ok=True)

    # Try tar.gz first
    try:
        with tarfile.open(archive_path, "r:gz") as tar:
            # Security: prevent path traversal
            for member in tar.getmembers():
                member_path = Path(extract_dir / member.name)
                if not str(member_path.resolve()).startswith(
                    str(extract_dir.resolve())
                ):
                    raise ValueError(
                        f"Path traversal detected in archive: {member.name}"
                    )
            tar.extractall(path=extract_dir)
            files = [f for f in extract_dir.rglob("*") if f.is_file()]
            logger.info("arxiv_source.extracted_tar", file_count=len(files))
            return files
    except tarfile.TarError:
        pass

    # Try gzip single file
    try:
        with gzip.open(archive_path, "rb") as gz:
            content = gz.read()
            # Detect if it's LaTeX
            text = content.decode("utf-8", errors="replace")
            if "\\documentclass" in text or "\\begin{document}" in text:
                output_file = extract_dir / "main.tex"
                output_file.write_text(text, encoding="utf-8")
                logger.info("arxiv_source.extracted_single_tex")
                return [output_file]
            else:
                # Write as generic file
                output_file = extract_dir / "paper.tex"
                output_file.write_bytes(content)
                return [output_file]
    except Exception:
        pass

    # Try as plain text
    try:
        content = archive_path.read_text(encoding="utf-8")
        if "\\documentclass" in content or "\\begin{document}" in content:
            output_file = extract_dir / "main.tex"
            output_file.write_text(content, encoding="utf-8")
            return [output_file]
    except Exception:
        pass

    raise ValueError(f"Could not extract arXiv source from {archive_path}")


def find_main_tex(files: list[Path]) -> Path:
    """
    Find the main .tex file from extracted arXiv source.

    Priority:
    1. Known names: main.tex, paper.tex, arxiv.tex, ms.tex, article.tex
    2. File containing \\documentclass
    3. Largest .tex file
    """
    tex_files = [f for f in files if f.suffix.lower() == ".tex"]

    if not tex_files:
        raise ValueError("No .tex files found in arXiv source")

    # Priority 1: known names
    priority_names = [
        "main.tex",
        "paper.tex",
        "arxiv.tex",
        "ms.tex",
        "article.tex",
    ]
    for name in priority_names:
        for f in tex_files:
            if f.name.lower() == name:
                return f

    # Priority 2: contains \documentclass
    for f in tex_files:
        try:
            content = f.read_text(encoding="utf-8", errors="replace")[:5000]
            # Remove comments
            content_no_comments = re.sub(r"%.*", "", content)
            if "\\documentclass" in content_no_comments:
                return f
        except Exception:
            continue

    # Priority 3: largest file
    return max(tex_files, key=lambda f: f.stat().st_size)


async def get_arxiv_latex_source(
    arxiv_id_or_url: str,
    work_dir: str | Path | None = None,
    cache_dir: str | Path | None = None,
) -> tuple[Path, Path, list[Path]]:
    """
    Download, extract, and locate main .tex file for an arXiv paper.

    Args:
        arxiv_id_or_url: arXiv ID or URL
        work_dir: Working directory for extraction (default: /tmp/arxiv-work/<id>)
        cache_dir: Cache directory for downloads

    Returns:
        Tuple of (main_tex_path, extract_dir, all_files)
    """
    arxiv_id = parse_arxiv_id(arxiv_id_or_url)

    if work_dir is None:
        safe_id = arxiv_id.replace("/", "_")
        work_dir = Path("/tmp") / "arxiv-work" / safe_id
    work_dir = Path(work_dir)

    # Clean existing extraction
    if work_dir.exists():
        shutil.rmtree(work_dir)

    # Download
    archive_path = await download_arxiv_source(arxiv_id, cache_dir=cache_dir)

    # Extract
    files = extract_arxiv_source(archive_path, work_dir)

    # Find main tex
    main_tex = find_main_tex(files)

    logger.info(
        "arxiv_source.ready",
        arxiv_id=arxiv_id,
        main_tex=str(main_tex.name),
        total_files=len(files),
    )

    return main_tex, work_dir, files
