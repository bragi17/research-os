"""Tests for services.library.tools_storage — file storage tools."""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _patch_library_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Redirect all storage paths to a temp directory for every test."""
    import services.library.tools_storage as mod

    monkeypatch.setattr(mod, "LIBRARY_ROOT", tmp_path)
    monkeypatch.setattr(mod, "SOURCES_DIR", tmp_path / "sources")
    monkeypatch.setattr(mod, "PDFS_DIR", tmp_path / "pdfs")
    monkeypatch.setattr(mod, "FIGURES_DIR", tmp_path / "figures")
    monkeypatch.setattr(mod, "UPLOADS_DIR", tmp_path / "uploads")


def test_ensure_library_dirs(tmp_path: Path) -> None:
    from services.library.tools_storage import (
        ensure_library_dirs,
        SOURCES_DIR,
        PDFS_DIR,
        FIGURES_DIR,
        UPLOADS_DIR,
    )

    ensure_library_dirs()

    assert SOURCES_DIR.is_dir()
    assert PDFS_DIR.is_dir()
    assert FIGURES_DIR.is_dir()
    assert UPLOADS_DIR.is_dir()


def test_get_paper_source_dir() -> None:
    from services.library.tools_storage import get_paper_source_dir, SOURCES_DIR

    # Simple ID
    result = get_paper_source_dir("2301.12345")
    assert result == SOURCES_DIR / "2301.12345"

    # ID with slash gets sanitized
    result = get_paper_source_dir("hep-th/9901001")
    assert result == SOURCES_DIR / "hep-th_9901001"


def test_save_latex_source(tmp_path: Path) -> None:
    from services.library.tools_storage import save_latex_source, SOURCES_DIR

    # Create a fake source archive
    src_file = tmp_path / "archive.tar.gz"
    src_file.write_bytes(b"fake tar content")

    dest = save_latex_source("2301.12345", str(src_file))

    expected = SOURCES_DIR / "2301.12345" / "source.tar.gz"
    assert dest == str(expected)
    assert expected.exists()
    assert expected.read_bytes() == b"fake tar content"


def test_get_paper_pdf_path() -> None:
    from services.library.tools_storage import get_paper_pdf_path, PDFS_DIR

    result = get_paper_pdf_path("2301.12345")
    assert result == PDFS_DIR / "2301.12345.pdf"

    result = get_paper_pdf_path("hep-th/9901001")
    assert result == PDFS_DIR / "hep-th_9901001.pdf"


def test_save_uploaded_pdf() -> None:
    from services.library.tools_storage import save_uploaded_pdf, UPLOADS_DIR

    content = b"%%PDF-1.4 fake pdf"
    dest = save_uploaded_pdf(content, "my_paper.pdf")

    dest_path = Path(dest)
    assert dest_path.exists()
    assert dest_path.parent == UPLOADS_DIR
    assert dest_path.name.endswith("_my_paper.pdf")
    assert dest_path.read_bytes() == content


def test_get_figure_dir() -> None:
    from services.library.tools_storage import get_figure_dir, FIGURES_DIR

    paper_id = "abcd-1234"
    result = get_figure_dir(paper_id)

    assert result == FIGURES_DIR / paper_id
    assert result.is_dir()
