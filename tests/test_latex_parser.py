"""Tests for the LaTeX paper parser."""
import pytest
from pathlib import Path
from services.parser.latex_parser import LatexParser, parse_latex


class TestLatexParserPreprocessing:
    """Test preprocessing functions."""

    def test_remove_comments_basic(self):
        content = "Hello % this is a comment\nWorld"
        result = LatexParser.remove_comments(content)
        assert "this is a comment" not in result
        assert "Hello" in result
        assert "World" in result

    def test_remove_comments_preserves_escaped_percent(self):
        content = r"15\% improvement"
        result = LatexParser.remove_comments(content)
        assert r"15\%" in result

    def test_remove_comments_preserves_verbatim(self):
        content = "\\begin{verbatim}\n% not a comment\n\\end{verbatim}"
        result = LatexParser.remove_comments(content)
        assert "% not a comment" in result

    def test_remove_comments_preserves_directives(self):
        content = "%!TEX engine = xelatex\n% regular comment"
        result = LatexParser.remove_comments(content)
        assert "%!TEX" in result
        assert "regular comment" not in result

    def test_split_preamble_body(self):
        content = r"\documentclass{article}\begin{document}Hello\end{document}"
        preamble, body = LatexParser.split_preamble_body(content)
        assert r"\begin{document}" in preamble
        assert "Hello" in body

    def test_split_preamble_body_no_document(self):
        content = "Just some text"
        preamble, body = LatexParser.split_preamble_body(content)
        assert preamble == ""
        assert body == "Just some text"


class TestLatexParserMetadata:
    """Test metadata extraction."""

    def test_extract_title(self, sample_latex_content):
        parser = LatexParser()
        preamble, body = parser.split_preamble_body(sample_latex_content)
        meta = parser.extract_metadata(preamble, body)
        assert meta.get("title") is not None
        assert "Multi-Agent" in meta["title"]

    def test_extract_authors(self, sample_latex_content):
        parser = LatexParser()
        preamble, body = parser.split_preamble_body(sample_latex_content)
        meta = parser.extract_metadata(preamble, body)
        authors = meta.get("authors", [])
        assert len(authors) >= 2

    def test_extract_document_class(self):
        content = r"\documentclass[twocolumn]{article}\begin{document}\end{document}"
        parser = LatexParser()
        preamble, body = parser.split_preamble_body(content)
        meta = parser.extract_metadata(preamble, body)
        assert meta.get("document_class") == "article"


class TestLatexParserSections:
    """Test section extraction."""

    def test_extract_sections(self, sample_latex_content):
        parser = LatexParser()
        working = parser.remove_comments(sample_latex_content)
        _, body = parser.split_preamble_body(working)
        _, body = parser.extract_abstract(body)
        sections = parser.extract_sections(body)
        # Should find Introduction, Method, Experiments, Conclusion
        titles = [s.title for s in sections]
        assert any("Introduction" in t for t in titles)
        assert any("Method" in t for t in titles)
        assert any("Experiments" in t for t in titles)
        assert any("Conclusion" in t for t in titles)

    def test_extract_subsections(self, sample_latex_content):
        parser = LatexParser()
        working = parser.remove_comments(sample_latex_content)
        _, body = parser.split_preamble_body(working)
        _, body = parser.extract_abstract(body)
        sections = parser.extract_sections(body)
        # The parser extracts all headings into a flat list of positions.
        # "Related Work" should appear either as a subsection of Introduction
        # or as its own top-level entry in the sections list.
        titles = [s.title for s in sections]
        has_related_as_subsection = False
        intro = next((s for s in sections if "Introduction" in (s.title or "")), None)
        assert intro is not None
        if intro.subsections:
            has_related_as_subsection = any(
                "Related Work" in (ss.title or "") for ss in intro.subsections
            )
        has_related_as_section = any("Related Work" in (t or "") for t in titles)
        assert has_related_as_subsection or has_related_as_section, (
            "Related Work should be found either as a subsection or a section entry"
        )

    def test_extract_abstract(self, sample_latex_content):
        parser = LatexParser()
        working = parser.remove_comments(sample_latex_content)
        _, body = parser.split_preamble_body(working)
        abstract, remaining = parser.extract_abstract(body)
        assert abstract is not None
        assert "multi-agent" in abstract.lower()
        assert "\\begin{abstract}" not in remaining


class TestLatexParserFigures:
    """Test figure and table extraction."""

    def test_extract_figures(self, sample_latex_content):
        parser = LatexParser()
        working = parser.remove_comments(sample_latex_content)
        _, body = parser.split_preamble_body(working)
        figures = parser.extract_figures(body)
        # Should find 1 figure and 1 table
        fig_types = [f.fig_type for f in figures]
        assert "figure" in fig_types
        assert "table" in fig_types

    def test_figure_caption(self, sample_latex_content):
        parser = LatexParser()
        working = parser.remove_comments(sample_latex_content)
        _, body = parser.split_preamble_body(working)
        figures = parser.extract_figures(body)
        fig = next((f for f in figures if f.fig_type == "figure"), None)
        assert fig is not None
        assert fig.caption is not None
        assert "architecture" in fig.caption.lower()

    def test_figure_label(self, sample_latex_content):
        parser = LatexParser()
        working = parser.remove_comments(sample_latex_content)
        _, body = parser.split_preamble_body(working)
        figures = parser.extract_figures(body)
        fig = next((f for f in figures if f.fig_type == "figure"), None)
        assert fig is not None
        assert fig.fig_id == "fig:arch"


class TestLatexParserReferences:
    """Test reference extraction."""

    def test_parse_bibtex(self, sample_bibtex):
        refs = LatexParser._parse_bibtex(sample_bibtex)
        assert len(refs) == 2
        assert any(r.ref_id == "smith2020" for r in refs)
        assert any(r.ref_id == "jones2021" for r in refs)

    def test_bibtex_fields(self, sample_bibtex):
        refs = LatexParser._parse_bibtex(sample_bibtex)
        smith = next(r for r in refs if r.ref_id == "smith2020")
        assert smith.title == "Memory Sharing in Multi-Agent Systems"
        assert smith.year == "2020"
        assert smith.doi == "10.1234/jair.2020.001"
        assert smith.journal == "Journal of AI Research"

    def test_bibtex_arxiv(self, sample_bibtex):
        refs = LatexParser._parse_bibtex(sample_bibtex)
        jones = next(r for r in refs if r.ref_id == "jones2021")
        assert jones.arxiv_id == "2101.12345"


class TestLatexParserFullParse:
    """Test the complete parse pipeline."""

    def test_full_parse(self, sample_latex_content):
        paper = parse_latex(sample_latex_content)
        assert paper is not None
        assert paper.parse_quality == "high"
        assert paper.title is not None
        assert paper.abstract is not None
        assert len(paper.sections) >= 3
        assert len(paper.figures) >= 2  # 1 figure + 1 table

    def test_full_parse_empty_document(self):
        paper = parse_latex(r"\documentclass{article}\begin{document}\end{document}")
        assert paper is not None
        assert paper.parse_quality == "high"

    def test_paragraphs_contain_text(self, sample_latex_content):
        paper = parse_latex(sample_latex_content)
        all_paragraphs = []
        for sec in paper.sections:
            all_paragraphs.extend(sec.paragraphs)
        assert len(all_paragraphs) > 0
        # Paragraphs should not contain raw LaTeX commands
        for p in all_paragraphs:
            assert "\\section" not in p
            assert "\\begin{equation}" not in p


class TestBibliographyResolution:
    """Test bibliography resolution logic."""

    def test_resolve_with_no_files(self, tmp_path):
        content = r"\bibliography{refs}"
        parser = LatexParser()
        result = parser._resolve_bibliography(content, tmp_path)
        # No bib or bbl file, keep original
        assert r"\bibliography{refs}" in result

    def test_resolve_with_bbl_only(self, tmp_path):
        (tmp_path / "refs.bbl").write_text("\\bibitem{test} Test reference")
        content = r"\bibliography{refs}"
        parser = LatexParser()
        result = parser._resolve_bibliography(content, tmp_path)
        assert r"\input{refs.bbl}" in result
        assert r"\bibliography{refs}" not in result

    def test_resolve_with_bib_present(self, tmp_path):
        (tmp_path / "refs.bib").write_text("@article{test, title={Test}}")
        content = r"\bibliography{refs}"
        parser = LatexParser()
        result = parser._resolve_bibliography(content, tmp_path)
        # Keep original when .bib exists
        assert r"\bibliography{refs}" in result
