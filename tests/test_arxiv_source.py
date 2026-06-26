"""Tests for arXiv source downloader (offline tests only)."""
from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from services.parser.arxiv_source import parse_arxiv_id, find_main_tex, extract_arxiv_source


class TestParseArxivId:
    def test_modern_format(self):
        assert parse_arxiv_id("2301.07041") == "2301.07041"

    def test_modern_with_version(self):
        assert parse_arxiv_id("2301.07041v2") == "2301.07041v2"

    def test_from_abs_url(self):
        assert parse_arxiv_id("https://arxiv.org/abs/2301.07041") == "2301.07041"

    def test_from_pdf_url(self):
        assert parse_arxiv_id("https://arxiv.org/pdf/2301.07041.pdf") == "2301.07041"

    def test_legacy_format(self):
        assert parse_arxiv_id("math.GT/0703024") == "math.GT/0703024"

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            parse_arxiv_id("not-an-id")

    def test_five_digit_id(self):
        assert parse_arxiv_id("2301.12345") == "2301.12345"


class TestFindMainTex:
    def test_finds_main_tex(self, tmp_path):
        (tmp_path / "main.tex").write_text(r"\documentclass{article}")
        (tmp_path / "appendix.tex").write_text("appendix content")
        files = list(tmp_path.iterdir())
        result = find_main_tex(files)
        assert result.name == "main.tex"

    def test_finds_by_documentclass(self, tmp_path):
        (tmp_path / "paper_v2.tex").write_text(r"\documentclass{article}\begin{document}\end{document}")
        (tmp_path / "macros.tex").write_text(r"\newcommand{\foo}{bar}")
        files = list(tmp_path.iterdir())
        result = find_main_tex(files)
        assert result.name == "paper_v2.tex"

    def test_finds_largest_as_fallback(self, tmp_path):
        (tmp_path / "small.tex").write_text("small")
        (tmp_path / "big.tex").write_text("x" * 1000)
        files = list(tmp_path.iterdir())
        result = find_main_tex(files)
        assert result.name == "big.tex"

    def test_no_tex_files_raises(self, tmp_path):
        (tmp_path / "readme.md").write_text("readme")
        files = list(tmp_path.iterdir())
        with pytest.raises(ValueError):
            find_main_tex(files)


class TestExtractArxivSource:
    def test_extract_single_tex(self, tmp_path):
        import gzip
        content = r"\documentclass{article}\begin{document}Hello\end{document}"
        gz_path = tmp_path / "paper.gz"
        with gzip.open(gz_path, "wb") as f:
            f.write(content.encode())

        extract_dir = tmp_path / "extracted"
        files = extract_arxiv_source(gz_path, extract_dir)
        assert len(files) == 1
        assert files[0].suffix == ".tex"


def test_extract_source_rejects_tar_path_traversal(tmp_path: Path) -> None:
    import io
    import tarfile

    from services.parser.arxiv_source import extract_source_archive

    archive_path = tmp_path / "evil.tar.gz"
    with tarfile.open(archive_path, "w:gz") as tar:
        payload = b"owned"
        info = tarfile.TarInfo("../../escape.tex")
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))

    extract_dir = tmp_path / "extract"

    with pytest.raises(ValueError, match="unsafe archive member"):
        extract_source_archive(archive_path, extract_dir)

    assert not (tmp_path / "escape.tex").exists()


def test_extract_source_rejects_tar_special_member(tmp_path: Path) -> None:
    import tarfile

    from services.parser.arxiv_source import extract_source_archive

    archive_path = tmp_path / "evil.tar.gz"
    with tarfile.open(archive_path, "w:gz") as tar:
        info = tarfile.TarInfo("link.tex")
        info.type = tarfile.SYMTYPE
        info.linkname = "main.tex"
        tar.addfile(info)

    extract_dir = tmp_path / "extract"

    with pytest.raises(ValueError, match="unsafe archive member"):
        extract_source_archive(archive_path, extract_dir)

    assert not (extract_dir / "link.tex").exists()


def test_extract_source_rejects_tar_file_parent_conflict(tmp_path: Path) -> None:
    import io
    import tarfile

    from services.parser.arxiv_source import extract_source_archive

    archive_path = tmp_path / "conflict.tar.gz"
    with tarfile.open(archive_path, "w:gz") as tar:
        parent_payload = b"not a directory"
        parent = tarfile.TarInfo("a")
        parent.size = len(parent_payload)
        tar.addfile(parent, io.BytesIO(parent_payload))

        child_payload = b"\\documentclass{article}"
        child = tarfile.TarInfo("a/b.tex")
        child.size = len(child_payload)
        tar.addfile(child, io.BytesIO(child_payload))

    extract_dir = tmp_path / "extract"

    with pytest.raises(ValueError, match="unsafe archive member"):
        extract_source_archive(archive_path, extract_dir)


def test_extract_source_rejects_tar_member_count_over_limit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import io
    import tarfile

    import services.parser.arxiv_source as arxiv_source

    archive_path = tmp_path / "too-many.tar.gz"
    with tarfile.open(archive_path, "w:gz") as tar:
        for index in range(2):
            payload = b"\\documentclass{article}"
            info = tarfile.TarInfo(f"paper-{index}.tex")
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))

    monkeypatch.setattr(arxiv_source, "MAX_ARCHIVE_MEMBERS", 1, raising=False)

    with pytest.raises(ValueError, match="member count"):
        arxiv_source.extract_source_archive(archive_path, tmp_path / "extract")


def test_extract_source_rejects_tar_total_size_over_limit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import io
    import tarfile

    import services.parser.arxiv_source as arxiv_source

    archive_path = tmp_path / "too-large.tar.gz"
    with tarfile.open(archive_path, "w:gz") as tar:
        for index in range(2):
            payload = b"12345678"
            info = tarfile.TarInfo(f"paper-{index}.tex")
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))

    monkeypatch.setattr(arxiv_source, "MAX_ARCHIVE_MEMBER_BYTES", 100, raising=False)
    monkeypatch.setattr(arxiv_source, "MAX_EXTRACTED_BYTES", 12, raising=False)

    with pytest.raises(ValueError, match="extracted"):
        arxiv_source.extract_source_archive(archive_path, tmp_path / "extract")


def test_extract_arxiv_source_rejects_gzip_decompression_over_limit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import gzip

    import services.parser.arxiv_source as arxiv_source

    gz_path = tmp_path / "paper.gz"
    gz_path.write_bytes(gzip.compress(b"\\documentclass{article}\nhello"))

    monkeypatch.setattr(arxiv_source, "MAX_ARCHIVE_MEMBER_BYTES", 12, raising=False)
    monkeypatch.setattr(arxiv_source, "MAX_EXTRACTED_BYTES", 1024, raising=False)

    with pytest.raises(ValueError, match="member"):
        arxiv_source.extract_arxiv_source(gz_path, tmp_path / "extract")


@pytest.mark.asyncio
async def test_download_arxiv_source_rejects_response_over_limit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import services.parser.arxiv_source as arxiv_source

    class FakeResponse:
        status_code = 200
        headers = {"content-type": "application/gzip"}
        content = b"123456789"

        async def aiter_bytes(self):
            yield b"12345"
            yield b"6789"

    class FakeStream:
        async def __aenter__(self) -> FakeResponse:
            return FakeResponse()

        async def __aexit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            traceback: object | None,
        ) -> None:
            return None

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            traceback: object | None,
        ) -> None:
            return None

        async def get(self, url: str) -> FakeResponse:
            return FakeResponse()

        def stream(self, method: str, url: str) -> FakeStream:
            return FakeStream()

    monkeypatch.setattr(arxiv_source, "MAX_DOWNLOAD_BYTES", 8, raising=False)
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    with pytest.raises(ValueError, match="download"):
        await arxiv_source.download_arxiv_source("2301.07041", cache_dir=tmp_path)

    assert not (tmp_path / "2301.07041.tar.gz").exists()
