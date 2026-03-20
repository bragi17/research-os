"""
Research OS - Paper Parsing Service

Unified interface for parsing academic papers via GROBID (PDF) or LaTeX source.
For arXiv papers, LaTeX parsing is preferred as it produces higher quality results.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from structlog import get_logger

from services.parser.arxiv_source import (
    get_arxiv_latex_source,
    parse_arxiv_id,
)
from services.parser.grobid_client import GROBIDClient, ParsedPaper, parse_pdf
from services.parser.latex_parser import LatexParser, parse_latex_file

logger = get_logger(__name__)


def detect_arxiv_id(identifier: str) -> str | None:
    """Try to extract an arXiv ID from a paper identifier. Returns None if not arXiv."""
    try:
        return parse_arxiv_id(identifier)
    except ValueError:
        return None


async def parse_paper(
    identifier: str,
    pdf_content: bytes | None = None,
    pdf_path: str | None = None,
    prefer_latex: bool = True,
    grobid_url: str | None = None,
) -> ParsedPaper:
    """
    Parse an academic paper using the best available method.

    Strategy:
    1. If the paper has an arXiv ID and prefer_latex is True, download LaTeX
       source and parse it for higher quality extraction.
    2. If LaTeX parsing fails or is not available, fall back to GROBID PDF parsing.
    3. If no PDF is available, return a minimal ParsedPaper with an error.

    Args:
        identifier: Paper identifier (DOI, arXiv ID, S2 ID, etc.)
        pdf_content: Raw PDF bytes (optional)
        pdf_path: Path to PDF file (optional)
        prefer_latex: Whether to prefer LaTeX parsing for arXiv papers
        grobid_url: GROBID service URL (default from env)

    Returns:
        ParsedPaper with structured content
    """
    grobid_url = grobid_url or os.getenv("GROBID_URL", "http://localhost:8070")
    arxiv_id = detect_arxiv_id(identifier) if prefer_latex else None

    # Strategy 1: Try LaTeX parsing for arXiv papers
    if arxiv_id:
        try:
            paper = await _parse_via_latex(arxiv_id)
            if paper and paper.parse_quality != "low":
                logger.info(
                    "parse_paper.latex_success",
                    arxiv_id=arxiv_id,
                    sections=len(paper.sections),
                )
                return paper
        except Exception as exc:
            logger.warning(
                "parse_paper.latex_failed_falling_back",
                arxiv_id=arxiv_id,
                error=str(exc),
            )

    # Strategy 2: Try GROBID PDF parsing
    if pdf_content or pdf_path:
        try:
            paper = await _parse_via_grobid(
                pdf_content=pdf_content,
                pdf_path=pdf_path,
                grobid_url=grobid_url,
            )
            if paper and paper.parse_quality != "low":
                logger.info("parse_paper.grobid_success", title=paper.title[:60] if paper.title else "?")
                return paper
        except Exception as exc:
            logger.warning("parse_paper.grobid_failed", error=str(exc))

    # Strategy 3: Return minimal paper
    logger.warning("parse_paper.no_parser_available", identifier=identifier)
    return ParsedPaper(
        error_message=f"No parsing method available for {identifier}",
        parse_quality="low",
    )


async def _parse_via_latex(arxiv_id: str) -> ParsedPaper:
    """Download arXiv LaTeX source and parse it."""
    main_tex, extract_dir, all_files = await get_arxiv_latex_source(arxiv_id)

    parser = LatexParser(base_dir=extract_dir)
    paper = parser.parse_file(main_tex)

    # Enrich with arXiv metadata if not extracted from LaTeX
    if not paper.doi:
        paper.doi = None  # arXiv papers may not have DOIs

    return paper


async def _parse_via_grobid(
    pdf_content: bytes | None = None,
    pdf_path: str | None = None,
    grobid_url: str = "http://localhost:8070",
) -> ParsedPaper:
    """Parse PDF via GROBID service."""
    client = GROBIDClient(base_url=grobid_url)
    try:
        return await client.parse_fulltext(pdf_content=pdf_content, pdf_path=pdf_path)
    finally:
        await client.close()
