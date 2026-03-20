"""Tests for arXiv source downloader (offline tests only)."""
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
