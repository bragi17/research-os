"""Tests for the figure extraction service."""

from __future__ import annotations

import struct
import zlib
from unittest.mock import AsyncMock, MagicMock, patch

import fitz  # PyMuPDF
import pytest

from services.figure_extraction import FigureExtractionService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_service() -> FigureExtractionService:
    """Create a FigureExtractionService with a mocked storage backend."""
    svc = FigureExtractionService.__new__(FigureExtractionService)
    svc.storage = MagicMock()
    svc.storage.upload_file = AsyncMock(
        return_value={
            "object_key": "figures/test/abc123_img.png",
            "sha256": "deadbeef",
            "size": 12345,
            "content_type": "image/png",
        }
    )
    return svc


def _build_png(width: int, height: int) -> bytes:
    """Build a minimal in-memory PNG image (RGB, no alpha)."""

    def _chunk(chunk_type: bytes, data: bytes) -> bytes:
        c = chunk_type + data
        crc = struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
        return struct.pack(">I", len(data)) + c + crc

    raw_rows = []
    for y in range(height):
        row = bytearray([0])  # PNG filter byte (None)
        for x in range(width):
            row.extend([x * 2 % 256, y * 2 % 256, 128])
        raw_rows.append(bytes(row))

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    compressed = zlib.compress(b"".join(raw_rows))
    return sig + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", compressed) + _chunk(b"IEND", b"")


def _create_test_pdf_with_image() -> bytes:
    """Create a minimal PDF containing an embedded image large enough to pass the 5 KB filter."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)

    png_bytes = _build_png(100, 100)
    rect = fitz.Rect(50, 50, 250, 250)
    page.insert_image(rect, stream=png_bytes)

    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def _create_test_pdf_no_images() -> bytes:
    """Create a minimal PDF with no embedded images."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 72), "Hello World - no images here")
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


# ---------------------------------------------------------------------------
# TestCaptionOnly
# ---------------------------------------------------------------------------


class TestCaptionOnly:
    @pytest.mark.asyncio
    async def test_returns_figures(self):
        svc = _make_service()
        figs = await svc.extract_caption_only(
            "Test Paper",
            [
                {"caption": "Architecture overview", "fig_type": "figure", "fig_id": "fig1"},
                {"caption": "Results table", "fig_type": "table", "fig_id": "tab1"},
            ],
        )
        assert len(figs) == 2
        assert figs[0]["source_type"] == "caption_only"
        assert figs[0]["caption"] == "Architecture overview"
        assert figs[0]["figure_type"] == "figure"
        assert figs[0]["fig_id"] == "fig1"
        assert figs[0]["image_path"] is None
        assert figs[0]["extraction_confidence"] == 0.3
        assert figs[1]["figure_type"] == "table"
        assert figs[1]["fig_id"] == "tab1"

    @pytest.mark.asyncio
    async def test_empty_input(self):
        svc = _make_service()
        figs = await svc.extract_caption_only("Test", [])
        assert figs == []

    @pytest.mark.asyncio
    async def test_missing_fields_use_defaults(self):
        svc = _make_service()
        figs = await svc.extract_caption_only("Test", [{"caption": "Only caption"}])
        assert len(figs) == 1
        assert figs[0]["figure_type"] == "figure"  # default
        assert figs[0]["fig_id"] is None
        assert figs[0]["caption"] == "Only caption"


# ---------------------------------------------------------------------------
# TestExtractFromPdf
# ---------------------------------------------------------------------------


class TestExtractFromPdf:
    @pytest.mark.asyncio
    async def test_extracts_image_from_pdf(self):
        svc = _make_service()
        pdf_bytes = _create_test_pdf_with_image()
        figs = await svc.extract_from_pdf(pdf_content=pdf_bytes, run_id="run-1")

        assert len(figs) >= 1
        fig = figs[0]
        assert fig["source_type"] == "pdf_crop"
        assert fig["page_no"] == 1
        assert fig["image_path"] == "figures/test/abc123_img.png"
        assert fig["extraction_confidence"] == 0.6
        assert fig["figure_type"] == "figure"
        # Verify storage was called
        svc.storage.upload_file.assert_called()

    @pytest.mark.asyncio
    async def test_no_images_returns_empty(self):
        svc = _make_service()
        pdf_bytes = _create_test_pdf_no_images()
        figs = await svc.extract_from_pdf(pdf_content=pdf_bytes)
        assert figs == []

    @pytest.mark.asyncio
    async def test_no_input_returns_empty(self):
        svc = _make_service()
        figs = await svc.extract_from_pdf()
        assert figs == []

    @pytest.mark.asyncio
    async def test_run_id_prefix(self):
        svc = _make_service()
        pdf_bytes = _create_test_pdf_with_image()
        await svc.extract_from_pdf(pdf_content=pdf_bytes, run_id="my-run")

        if svc.storage.upload_file.called:
            call_kwargs = svc.storage.upload_file.call_args
            assert "figures/my-run" == call_kwargs.kwargs.get(
                "prefix", call_kwargs[1].get("prefix")
            )


# ---------------------------------------------------------------------------
# TestExtractFigures (orchestrator)
# ---------------------------------------------------------------------------


class TestExtractFigures:
    @pytest.mark.asyncio
    async def test_returns_empty_when_nothing_available(self):
        svc = _make_service()
        figs = await svc.extract_figures(paper_id="p1")
        assert figs == []

    @pytest.mark.asyncio
    async def test_tier1_arxiv_tried_first(self):
        """When arxiv_id is provided, Tier 1 is attempted."""
        svc = _make_service()
        mock_figures = [
            {
                "id": "f1",
                "source_type": "arxiv_source",
                "caption": "Fig 1",
                "figure_type": "figure",
                "fig_id": "fig1",
                "image_path": "figures/img.png",
                "extraction_confidence": 0.95,
            }
        ]
        with patch.object(
            svc, "extract_from_arxiv_source", new_callable=AsyncMock
        ) as mock_arxiv:
            mock_arxiv.return_value = mock_figures
            figs = await svc.extract_figures(
                paper_id="paper-1", arxiv_id="2301.07041"
            )

        assert len(figs) == 1
        assert figs[0]["paper_id"] == "paper-1"
        assert figs[0]["source_type"] == "arxiv_source"
        mock_arxiv.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_falls_back_to_pdf_when_arxiv_fails(self):
        """When Tier 1 returns empty, Tier 2 PDF extraction is tried."""
        svc = _make_service()
        pdf_figures = [
            {
                "id": "f2",
                "source_type": "pdf_crop",
                "page_no": 1,
                "caption": None,
                "image_path": "figures/page1.png",
                "figure_type": "figure",
                "extraction_confidence": 0.6,
            }
        ]
        with (
            patch.object(
                svc, "extract_from_arxiv_source", new_callable=AsyncMock
            ) as mock_arxiv,
            patch.object(
                svc, "extract_from_pdf", new_callable=AsyncMock
            ) as mock_pdf,
        ):
            mock_arxiv.return_value = []  # Tier 1 empty
            mock_pdf.return_value = pdf_figures
            figs = await svc.extract_figures(
                paper_id="paper-2",
                arxiv_id="2301.07041",
                pdf_content=b"fake-pdf",
            )

        assert len(figs) == 1
        assert figs[0]["source_type"] == "pdf_crop"
        assert figs[0]["paper_id"] == "paper-2"
        mock_arxiv.assert_awaited_once()
        mock_pdf.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_paper_id_attached_to_all_figures(self):
        svc = _make_service()
        mock_figures = [
            {"id": "f1", "source_type": "arxiv_source"},
            {"id": "f2", "source_type": "arxiv_source"},
        ]
        with patch.object(
            svc, "extract_from_arxiv_source", new_callable=AsyncMock
        ) as mock_arxiv:
            mock_arxiv.return_value = mock_figures
            figs = await svc.extract_figures(
                paper_id="p99", arxiv_id="2301.07041"
            )

        for f in figs:
            assert f["paper_id"] == "p99"


# ---------------------------------------------------------------------------
# TestParseArxivIdIntegration
# ---------------------------------------------------------------------------


class TestParseArxivIdIntegration:
    def test_modern_id(self):
        from services.parser.arxiv_source import parse_arxiv_id

        assert parse_arxiv_id("2301.07041") == "2301.07041"
        assert parse_arxiv_id("2301.07041v2") == "2301.07041v2"

    def test_url_format(self):
        from services.parser.arxiv_source import parse_arxiv_id

        assert parse_arxiv_id("https://arxiv.org/abs/2301.07041") == "2301.07041"
        assert parse_arxiv_id("https://arxiv.org/pdf/2301.07041.pdf") == "2301.07041"

    def test_invalid_raises(self):
        from services.parser.arxiv_source import parse_arxiv_id

        with pytest.raises(ValueError):
            parse_arxiv_id("not-an-arxiv-id")


# ---------------------------------------------------------------------------
# TestGetFigureService singleton
# ---------------------------------------------------------------------------


class TestGetFigureService:
    def test_returns_instance(self):
        import services.figure_extraction as mod

        mod._service = None  # reset singleton
        svc = mod.get_figure_service()
        assert isinstance(svc, FigureExtractionService)
        # Same instance on second call
        assert mod.get_figure_service() is svc
        mod._service = None  # cleanup
