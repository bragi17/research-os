"""
Research OS - GROBID PDF Parser Client

Client for interacting with GROBID service for academic PDF parsing.
"""

from __future__ import annotations

import asyncio
import io
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import httpx
from pydantic import BaseModel, Field
from structlog import get_logger

logger = get_logger(__name__)


class GROBIDEndpoint(str, Enum):
    """GROBID API endpoints."""

    FULLTEXT = "/api/processFulltextDocument"
    HEADER = "/api/processHeaderDocument"
    REFERENCES = "/api/processReferences"
    CITATION = "/api/processCitation"
    AFFILIATION = "/api/processAffiliations"
    DATE = "/api/processDate"
    NAME = "/api/processNames"
    ISALIVE = "/api/isalive"


@dataclass
class ParsedSection:
    """A parsed section from a paper."""

    title: str
    number: str | None = None
    paragraphs: list[str] = field(default_factory=list)
    subsections: list["ParsedSection"] = field(default_factory=list)


@dataclass
class ParsedReference:
    """A parsed reference from the bibliography."""

    ref_id: str | None = None
    title: str | None = None
    authors: list[str] = field(default_factory=list)
    journal: str | None = None
    year: str | None = None
    volume: str | None = None
    pages: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    raw_text: str | None = None


@dataclass
class ParsedFigure:
    """A parsed figure or table."""

    fig_id: str | None = None
    fig_type: str | None = None  # "figure" or "table"
    label: str | None = None
    caption: str | None = None


@dataclass
class ParsedPaper:
    """Complete parsed paper structure."""

    # Metadata
    title: str | None = None
    authors: list[dict[str, str]] = field(default_factory=list)
    abstract: str | None = None
    keywords: list[str] = field(default_factory=list)

    # Publication info
    journal: str | None = None
    publisher: str | None = None
    year: str | None = None
    volume: str | None = None
    issue: str | None = None
    pages: str | None = None
    doi: str | None = None

    # Content
    sections: list[ParsedSection] = field(default_factory=list)
    references: list[ParsedReference] = field(default_factory=list)
    figures: list[ParsedFigure] = field(default_factory=list)

    # Raw data
    tei_xml: str | None = None
    parse_timestamp: datetime = field(default_factory=datetime.utcnow)

    # Quality indicators
    parse_quality: str = "unknown"  # high, medium, low, unknown
    error_message: str | None = None


class GROBIDClient:
    """
    Client for GROBID PDF parsing service.

    Features:
    - Async HTTP client
    - Retry logic
    - TEI XML parsing
    - Structured output
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8070",
        timeout: float = 300.0,
        max_retries: int = 3,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(self.timeout, connect=30.0),
            )
        return self._client

    async def is_alive(self) -> bool:
        """Check if GROBID service is running."""
        try:
            client = await self._get_client()
            response = await client.get(GROBIDEndpoint.ISALIVE)
            return response.status_code == 200
        except Exception as e:
            logger.warning("grobid_health_check_failed", error=str(e))
            return False

    async def parse_fulltext(
        self,
        pdf_content: bytes | None = None,
        pdf_path: str | None = None,
        consolidate_citations: bool = True,
        include_raw_citations: bool = False,
        segment_sentences: bool = True,
    ) -> ParsedPaper:
        """
        Parse a PDF document and extract full text structure.

        Args:
            pdf_content: Raw PDF bytes
            pdf_path: Path to PDF file (alternative to pdf_content)
            consolidate_citations: Whether to consolidate citations
            include_raw_citations: Include raw citation strings
            segment_sentences: Segment text into sentences

        Returns:
            ParsedPaper with structured content
        """
        if pdf_content is None and pdf_path is None:
            raise ValueError("Either pdf_content or pdf_path must be provided")

        if pdf_content is None:
            with open(pdf_path, "rb") as f:
                pdf_content = f.read()

        client = await self._get_client()

        # Build form data
        files = {"input": ("paper.pdf", pdf_content, "application/pdf")}
        data = {
            "consolidateCitations": "1" if consolidate_citations else "0",
            "includeRawCitations": "1" if include_raw_citations else "0",
            "segmentSentences": "1" if segment_sentences else "0",
        }

        last_error = None
        for attempt in range(self.max_retries):
            try:
                response = await client.post(
                    GROBIDEndpoint.FULLTEXT,
                    files=files,
                    data=data,
                )

                if response.status_code == 200:
                    tei_xml = response.text
                    return self._parse_tei_xml(tei_xml)

                elif response.status_code == 503:
                    # Service busy, retry
                    logger.warning("grobid_busy", attempt=attempt)
                    await asyncio.sleep(5 * (attempt + 1))
                    continue

                else:
                    error_msg = f"GROBID error: {response.status_code}"
                    logger.error("grobid_parse_failed", status=response.status_code)
                    return ParsedPaper(error_message=error_msg)

            except httpx.TimeoutException as e:
                last_error = e
                logger.warning("grobid_timeout", attempt=attempt)
                await asyncio.sleep(10)

            except Exception as e:
                last_error = e
                logger.error("grobid_request_failed", error=str(e), attempt=attempt)
                await asyncio.sleep(5)

        return ParsedPaper(error_message=str(last_error))

    async def parse_header(
        self,
        pdf_content: bytes | None = None,
        pdf_path: str | None = None,
    ) -> ParsedPaper:
        """
        Parse only the header (title, authors, abstract) of a PDF.

        Faster than fulltext parsing.
        """
        if pdf_content is None and pdf_path is None:
            raise ValueError("Either pdf_content or pdf_path must be provided")

        if pdf_content is None:
            with open(pdf_path, "rb") as f:
                pdf_content = f.read()

        client = await self._get_client()
        files = {"input": ("paper.pdf", pdf_content, "application/pdf")}

        response = await client.post(GROBIDEndpoint.HEADER, files=files)

        if response.status_code == 200:
            return self._parse_tei_xml(response.text)

        return ParsedPaper(error_message=f"GROBID header error: {response.status_code}")

    async def parse_references(
        self,
        pdf_content: bytes | None = None,
        pdf_path: str | None = None,
        consolidate: bool = True,
    ) -> list[ParsedReference]:
        """
        Extract and parse references from a PDF.
        """
        if pdf_content is None and pdf_path is None:
            raise ValueError("Either pdf_content or pdf_path must be provided")

        if pdf_content is None:
            with open(pdf_path, "rb") as f:
                pdf_content = f.read()

        client = await self._get_client()
        files = {"input": ("paper.pdf", pdf_content, "application/pdf")}
        data = {"consolidateCitations": "1" if consolidate else "0"}

        response = await client.post(
            GROBIDEndpoint.REFERENCES,
            files=files,
            data=data,
        )

        if response.status_code == 200:
            paper = self._parse_tei_xml(response.text)
            return paper.references

        return []

    def _parse_tei_xml(self, tei_xml: str) -> ParsedPaper:
        """
        Parse TEI XML output from GROBID into structured data.
        """
        paper = ParsedPaper(tei_xml=tei_xml)

        try:
            root = ElementTree.fromstring(tei_xml)

            # Define namespace
            ns = {"tei": "http://www.tei-c.org/ns/1.0"}

            # Parse header
            tei_header = root.find(".//tei:teiHeader", ns)
            if tei_header is not None:
                # Title
                title_elem = tei_header.find(".//tei:titleStmt/tei:title", ns)
                if title_elem is not None and title_elem.text:
                    paper.title = title_elem.text.strip()

                # Authors
                for author in tei_header.findall(".//tei:author", ns):
                    author_data = {}
                    pers_name = author.find("tei:persName", ns)
                    if pers_name is not None:
                        forename = pers_name.find("tei:forename", ns)
                        surname = pers_name.find("tei:surname", ns)
                        if forename is not None and forename.text:
                            author_data["first_name"] = forename.text.strip()
                        if surname is not None and surname.text:
                            author_data["last_name"] = surname.text.strip()

                    affiliation = author.find(".//tei:affiliation", ns)
                    if affiliation is not None and affiliation.text:
                        author_data["affiliation"] = affiliation.text.strip()

                    if author_data:
                        paper.authors.append(author_data)

                # Abstract
                abstract = tei_header.find(".//tei:abstract", ns)
                if abstract is not None:
                    abstract_text = " ".join(abstract.itertext())
                    paper.abstract = abstract_text.strip()

                # Keywords
                keywords = tei_header.find(".//tei:keywords", ns)
                if keywords is not None:
                    for term in keywords.findall(".//tei:term", ns):
                        if term.text:
                            paper.keywords.append(term.text.strip())

                # Publication info
                source_desc = tei_header.find(".//tei:sourceDesc", ns)
                if source_desc is not None:
                    monogr = source_desc.find(".//tei:monogr", ns)
                    if monogr is not None:
                        # Journal/venue
                        title_elem = monogr.find("tei:title", ns)
                        if title_elem is not None and title_elem.text:
                            paper.journal = title_elem.text.strip()

                        # Date/year
                        imprint = monogr.find("tei:imprint", ns)
                        if imprint is not None:
                            date = imprint.find("tei:date", ns)
                            if date is not None:
                                paper.year = date.get("when", "")

                            volume = imprint.find("tei:biblScope[@unit='volume']", ns)
                            if volume is not None and volume.text:
                                paper.volume = volume.text.strip()

                            pages = imprint.find("tei:biblScope[@unit='page']", ns)
                            if pages is not None:
                                paper.pages = pages.get("from", "")
                                if pages.get("to"):
                                    paper.pages += f"-{pages.get('to')}"

                # DOI
                idno = tei_header.find(".//tei:idno[@type='DOI']", ns)
                if idno is not None and idno.text:
                    paper.doi = idno.text.strip()

            # Parse text body
            body = root.find(".//tei:text/tei:body", ns)
            if body is not None:
                paper.sections = self._parse_sections(body, ns)

            # Parse references
            list_bibl = root.find(".//tei:listBibl", ns)
            if list_bibl is not None:
                for bibl in list_bibl.findall("tei:biblStruct", ns):
                    ref = self._parse_reference(bibl, ns)
                    if ref:
                        paper.references.append(ref)

            # Parse figures
            for figure in root.findall(".//tei:figure", ns):
                fig = ParsedFigure()
                fig.fig_id = figure.get("{http://www.w3.org/XML/1998/namespace}id")
                fig.fig_type = figure.get("type", "figure")

                label = figure.find("tei:head", ns)
                if label is not None and label.text:
                    fig.label = label.text.strip()

                caption = figure.find("tei:figDesc", ns)
                if caption is not None and caption.text:
                    fig.caption = caption.text.strip()

                paper.figures.append(fig)

            paper.parse_quality = "high"

        except ElementTree.ParseError as e:
            logger.error("xml_parse_error", error=str(e))
            paper.parse_quality = "low"
            paper.error_message = f"XML parsing failed: {e}"

        return paper

    def _parse_sections(
        self,
        element: ElementTree.Element,
        ns: dict[str, str],
    ) -> list[ParsedSection]:
        """Parse sections from body element."""
        sections = []

        for div in element.findall("tei:div", ns):
            section = ParsedSection()

            # Section head
            head = div.find("tei:head", ns)
            if head is not None and head.text:
                section.title = head.text.strip()
                # Try to extract section number
                match = re.match(r"^(\d+\.?\d*)\s*", section.title)
                if match:
                    section.number = match.group(1)

            # Paragraphs
            for p in div.findall("tei:p", ns):
                text = " ".join(p.itertext()).strip()
                if text:
                    section.paragraphs.append(text)

            # Subsections (recursive)
            section.subsections = self._parse_sections(div, ns)

            if section.title or section.paragraphs:
                sections.append(section)

        return sections

    def _parse_reference(
        self,
        bibl: ElementTree.Element,
        ns: dict[str, str],
    ) -> ParsedReference | None:
        """Parse a single reference entry."""
        ref = ParsedReference()

        ref.ref_id = bibl.get("{http://www.w3.org/XML/1998/namespace}id")

        # Analytic (article info)
        analytic = bibl.find("tei:analytic", ns)
        if analytic is not None:
            title = analytic.find("tei:title", ns)
            if title is not None and title.text:
                ref.title = title.text.strip()

            for author in analytic.findall("tei:author", ns):
                pers_name = author.find("tei:persName", ns)
                if pers_name is not None:
                    forename = pers_name.find("tei:forename", ns)
                    surname = pers_name.find("tei:surname", ns)
                    name_parts = []
                    if forename is not None and forename.text:
                        name_parts.append(forename.text.strip())
                    if surname is not None and surname.text:
                        name_parts.append(surname.text.strip())
                    if name_parts:
                        ref.authors.append(" ".join(name_parts))

        # Monogr (journal/book info)
        monogr = bibl.find("tei:monogr", ns)
        if monogr is not None:
            if not ref.title:
                title = monogr.find("tei:title", ns)
                if title is not None and title.text:
                    ref.title = title.text.strip()

            imprint = monogr.find("tei:imprint", ns)
            if imprint is not None:
                date = imprint.find("tei:date", ns)
                if date is not None:
                    ref.year = date.get("when", "")

                volume = imprint.find("tei:biblScope[@unit='volume']", ns)
                if volume is not None and volume.text:
                    ref.volume = volume.text.strip()

                pages = imprint.find("tei:biblScope[@unit='page']", ns)
                if pages is not None:
                    page_from = pages.get("from", "")
                    page_to = pages.get("to", "")
                    if page_from and page_to:
                        ref.pages = f"{page_from}-{page_to}"
                    elif page_from:
                        ref.pages = page_from

        # DOI
        idno = bibl.find(".//tei:idno[@type='DOI']", ns)
        if idno is not None and idno.text:
            ref.doi = idno.text.strip()

        # arXiv
        idno = bibl.find(".//tei:idno[@type='arXiv']", ns)
        if idno is not None and idno.text:
            ref.arxiv_id = idno.text.strip()

        return ref if ref.title or ref.authors else None

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None


# ============================================
# Convenience Functions
# ============================================


async def parse_pdf(
    pdf_path: str | Path,
    grobid_url: str = "http://localhost:8070",
    fulltext: bool = True,
) -> ParsedPaper:
    """
    Parse a PDF file using GROBID.

    Args:
        pdf_path: Path to PDF file
        grobid_url: GROBID service URL
        fulltext: Whether to parse full text (slower) or just header

    Returns:
        ParsedPaper with structured content
    """
    client = GROBIDClient(base_url=grobid_url)

    if fulltext:
        return await client.parse_fulltext(pdf_path=str(pdf_path))
    else:
        return await client.parse_header(pdf_path=str(pdf_path))
