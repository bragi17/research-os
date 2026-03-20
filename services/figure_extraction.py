"""
Research OS - Figure Extraction Service

Extracts figures, architecture diagrams, and result tables from academic papers.
Three-tier strategy:
1. arXiv LaTeX source -> extract original figure files
2. PDF page -> PyMuPDF image extraction + page crop
3. Caption-only fallback -> store just the caption text

Outputs are stored via StorageService and metadata saved to figure_asset table.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

import fitz  # PyMuPDF
from structlog import get_logger

from services.parser.arxiv_source import get_arxiv_latex_source, parse_arxiv_id
from services.parser.latex_parser import LatexParser
from services.storage import get_storage

logger = get_logger(__name__)


class FigureExtractionService:
    """
    Extracts figures from academic papers using a tiered strategy.
    """

    def __init__(self):
        self.storage = get_storage()

    async def extract_from_arxiv_source(
        self,
        arxiv_id: str,
        run_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Tier 1: Extract figures from arXiv LaTeX source package.

        Looks for image files referenced by \\includegraphics commands.
        Returns list of figure metadata dicts.
        """
        figures: list[dict[str, Any]] = []
        try:
            main_tex, extract_dir, all_files = await get_arxiv_latex_source(arxiv_id)

            # Parse LaTeX to find figure environments
            parser = LatexParser(base_dir=extract_dir)
            paper = parser.parse_file(main_tex)

            # Find actual image files in the source package
            image_extensions = {".png", ".jpg", ".jpeg", ".pdf", ".eps", ".svg"}
            image_files = {
                f.stem.lower(): f
                for f in all_files
                if f.suffix.lower() in image_extensions
            }

            for fig in paper.figures:
                figure_data: dict[str, Any] = {
                    "id": str(uuid4()),
                    "source_type": "arxiv_source",
                    "caption": fig.caption,
                    "figure_type": fig.fig_type or "figure",
                    "fig_id": fig.fig_id,
                    "related_section": None,
                    "extraction_confidence": 0.9,
                    "image_path": None,
                }

                # Try to find the actual image file
                if fig.label:  # label stores includegraphics path
                    img_name = Path(fig.label).stem.lower()
                    if img_name in image_files:
                        img_path = image_files[img_name]
                        # Upload to storage
                        try:
                            content = img_path.read_bytes()
                            suffix = img_path.suffix.lower()
                            content_type = {
                                ".png": "image/png",
                                ".jpg": "image/jpeg",
                                ".jpeg": "image/jpeg",
                                ".svg": "image/svg+xml",
                            }.get(suffix, "application/octet-stream")

                            meta = await self.storage.upload_file(
                                content=content,
                                filename=f"{arxiv_id.replace('/', '_')}_{img_path.name}",
                                content_type=content_type,
                                prefix=f"figures/{run_id}" if run_id else "figures",
                            )
                            figure_data["image_path"] = meta["object_key"]
                            figure_data["extraction_confidence"] = 0.95
                        except Exception as exc:
                            logger.warning(
                                "figure_upload_failed",
                                file=str(img_path),
                                error=str(exc),
                            )

                figures.append(figure_data)

            logger.info(
                "figures.arxiv_extracted", arxiv_id=arxiv_id, count=len(figures)
            )

        except Exception as exc:
            logger.warning(
                "figures.arxiv_extraction_failed",
                arxiv_id=arxiv_id,
                error=str(exc),
            )

        return figures

    async def extract_from_pdf(
        self,
        pdf_path: str | None = None,
        pdf_content: bytes | None = None,
        run_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Tier 2: Extract images from PDF using PyMuPDF.

        Extracts embedded images and crops figure regions.
        """
        figures: list[dict[str, Any]] = []

        try:
            if pdf_content:
                doc = fitz.open(stream=pdf_content, filetype="pdf")
            elif pdf_path:
                doc = fitz.open(pdf_path)
            else:
                return figures

            for page_num in range(len(doc)):
                page = doc[page_num]
                image_list = page.get_images(full=True)

                for img_idx, img_info in enumerate(image_list):
                    xref = img_info[0]
                    try:
                        base_image = doc.extract_image(xref)
                        if base_image and base_image.get("image"):
                            img_bytes = base_image["image"]
                            ext = base_image.get("ext", "png")

                            # Skip tiny images (likely icons/logos)
                            if len(img_bytes) < 5000:
                                continue

                            # Upload to storage
                            filename = f"page{page_num + 1}_img{img_idx + 1}.{ext}"
                            meta = await self.storage.upload_file(
                                content=img_bytes,
                                filename=filename,
                                content_type=f"image/{ext}",
                                prefix=f"figures/{run_id}" if run_id else "figures",
                            )

                            figures.append(
                                {
                                    "id": str(uuid4()),
                                    "source_type": "pdf_crop",
                                    "page_no": page_num + 1,
                                    "caption": None,  # PDF extraction doesn't easily get captions
                                    "image_path": meta["object_key"],
                                    "figure_type": "figure",
                                    "extraction_confidence": 0.6,
                                }
                            )
                    except Exception as exc:
                        logger.debug(
                            "figure_extraction_error",
                            page=page_num,
                            error=str(exc),
                        )

            doc.close()
            logger.info("figures.pdf_extracted", count=len(figures))

        except Exception as exc:
            logger.warning("figures.pdf_extraction_failed", error=str(exc))

        return figures

    async def extract_caption_only(
        self,
        paper_title: str,
        paper_figures: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        Tier 3: Caption-only fallback when image extraction fails.

        Just stores the caption text with no actual image.
        """
        figures: list[dict[str, Any]] = []
        for fig in paper_figures:
            figures.append(
                {
                    "id": str(uuid4()),
                    "source_type": "caption_only",
                    "caption": fig.get("caption"),
                    "figure_type": fig.get("fig_type", "figure"),
                    "fig_id": fig.get("fig_id"),
                    "image_path": None,
                    "extraction_confidence": 0.3,
                }
            )
        return figures

    async def extract_figures(
        self,
        paper_id: str | None = None,
        arxiv_id: str | None = None,
        pdf_path: str | None = None,
        pdf_content: bytes | None = None,
        run_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Main entry point: try all tiers in order.

        Returns list of figure metadata dicts ready for DB insertion.
        """
        # Tier 1: arXiv source
        if arxiv_id:
            try:
                parsed_id = parse_arxiv_id(arxiv_id)
                figures = await self.extract_from_arxiv_source(parsed_id, run_id)
                if figures:
                    for f in figures:
                        f["paper_id"] = paper_id
                    return figures
            except Exception:
                pass

        # Tier 2: PDF extraction
        if pdf_path or pdf_content:
            figures = await self.extract_from_pdf(pdf_path, pdf_content, run_id)
            if figures:
                for f in figures:
                    f["paper_id"] = paper_id
                return figures

        # Tier 3: Caption-only (needs parsed figures from LaTeX parser)
        logger.info("figures.caption_only_fallback", paper_id=paper_id)
        return []


# Singleton
_service: FigureExtractionService | None = None


def get_figure_service() -> FigureExtractionService:
    global _service
    if _service is None:
        _service = FigureExtractionService()
    return _service
