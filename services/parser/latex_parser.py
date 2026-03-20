"""
Research OS - LaTeX Paper Parser

Parses LaTeX source files into structured paper objects compatible with
the GROBID ParsedPaper format. Port of core parsing logic from
latex-paper-mirror's latexChunker.ts, adapted for research paper
analysis rather than translation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from structlog import get_logger

from services.parser.grobid_client import (
    ParsedFigure,
    ParsedPaper,
    ParsedReference,
    ParsedSection,
)

logger = get_logger(__name__)


# Protected environments (math, code, algorithms) - content preserved but not
# parsed as regular text.
PROTECTED_ENVIRONMENTS = (
    "equation",
    "align",
    "gather",
    "split",
    "eqnarray",
    "multline",
    "equation*",
    "align*",
    "gather*",
    "eqnarray*",
    "multline*",
    "tikzpicture",
    "lstlisting",
    "verbatim",
    "minted",
    "algorithm",
    "algorithm2e",
    "algorithmic",
)

# Section-level commands in hierarchy order (broadest to narrowest).
SECTION_COMMANDS = (
    "part",
    "chapter",
    "section",
    "subsection",
    "subsubsection",
    "paragraph",
    "subparagraph",
)

# Verbatim-like environments where comment stripping must be skipped.
_VERBATIM_ENVS = frozenset({"verbatim", "lstlisting", "minted", "comment"})

# Minimum paragraph length (characters) to keep after cleaning.
_MIN_PARAGRAPH_LENGTH = 10


# ---------------------------------------------------------------------------
# Internal data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _BalancedResult:
    """Result from balanced-group parsing."""

    inner: str
    end: int


@dataclass
class LatexChunk:
    """A parsed chunk from the LaTeX document."""

    id: str
    kind: str  # abstract, section, subsection, paragraph, caption, footnote, figure, table, equation, ...
    title: str | None = None
    content: str = ""  # Text content (commands stripped)
    raw_latex: str = ""  # Original LaTeX source
    section_path: list[str] = field(default_factory=list)
    page_start: int | None = None
    page_end: int | None = None


@dataclass
class LatexDocument:
    """Complete parsed LaTeX document (intermediate representation)."""

    title: str | None = None
    authors: list[dict[str, str]] = field(default_factory=list)
    abstract: str | None = None
    preamble: str = ""
    chunks: list[LatexChunk] = field(default_factory=list)
    sections: list[ParsedSection] = field(default_factory=list)
    references: list[ParsedReference] = field(default_factory=list)
    figures: list[ParsedFigure] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)

    # Metadata from preamble
    document_class: str | None = None
    journal: str | None = None
    year: str | None = None
    doi: str | None = None


# ---------------------------------------------------------------------------
# Balanced-group / environment helpers
# ---------------------------------------------------------------------------


def _parse_balanced_group(
    text: str,
    start: int,
    open_char: str = "{",
    close_char: str = "}",
) -> _BalancedResult | None:
    """Parse a balanced group of braces/brackets.

    Returns ``_BalancedResult(inner_content, end_position)`` or ``None``
    when the group cannot be matched.
    """
    if start >= len(text) or text[start] != open_char:
        return None
    depth = 1
    i = start + 1
    while i < len(text):
        ch = text[i]
        if ch == "\\":
            i += 2  # skip escaped character
            continue
        if ch == open_char:
            depth += 1
        elif ch == close_char:
            depth -= 1
            if depth == 0:
                return _BalancedResult(inner=text[start + 1 : i], end=i + 1)
        i += 1
    return None


def _find_environment_end(text: str, start: int, env_name: str) -> int | None:
    """Find the matching ``\\end{env_name}`` handling nesting."""
    depth = 1
    i = start
    begin_str = f"\\begin{{{env_name}}}"
    end_str = f"\\end{{{env_name}}}"
    while i < len(text):
        if text[i:].startswith(begin_str):
            depth += 1
            i += len(begin_str)
        elif text[i:].startswith(end_str):
            depth -= 1
            if depth == 0:
                return i + len(end_str)
            i += len(end_str)
        else:
            i += 1
    return None


# ---------------------------------------------------------------------------
# Text cleaning helpers
# ---------------------------------------------------------------------------


_RE_TEXTUAL_CMDS = re.compile(
    r"\\(?:textbf|textit|emph|textrm|texttt|textsf|textsc|underline|mbox)"
    r"\{([^}]*)\}"
)
_RE_DISCARD_CMDS = re.compile(
    r"\\(?:thanks|inst|orcidID|email|affiliation|address"
    r"|footnote|footnotemark|footnotetext)"
    r"(?:\[[^\]]*\])?\{[^}]*\}"
)
_RE_SIMPLE_CMDS = re.compile(r"\\[a-zA-Z]+\*?\s*")


def _strip_latex_commands(text: str) -> str:
    """Remove LaTeX commands, keeping only readable text content."""
    result = _RE_TEXTUAL_CMDS.sub(r"\1", text)
    result = _RE_DISCARD_CMDS.sub("", result)
    # Remove remaining simple commands (e.g. \vspace, \hfill, ...)
    result = _RE_SIMPLE_CMDS.sub("", result)
    # Remove stray braces
    result = result.replace("{", "").replace("}", "")
    # Normalise whitespace
    result = re.sub(r"\s+", " ", result)
    return result.strip()


def _strip_inline_math(text: str) -> str:
    """Replace inline math ``$...$`` with a placeholder token."""
    # Replace $...$ (but not $$...$$) with [math]
    result = re.sub(r"(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)", "[math]", text)
    # Replace $$...$$ with [equation]
    result = re.sub(r"\$\$.*?\$\$", "[equation]", result, flags=re.DOTALL)
    # Replace \(...\) and \[...\]
    result = re.sub(r"\\\(.*?\\\)", "[math]", result, flags=re.DOTALL)
    result = re.sub(r"\\\[.*?\\\]", "[equation]", result, flags=re.DOTALL)
    return result


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


class LatexParser:
    """Parser for LaTeX academic papers.

    Extracts structured content: sections, paragraphs, figures, tables,
    equations, references, and metadata.  Output is a ``ParsedPaper``
    compatible with the GROBID pipeline.
    """

    def __init__(self, base_dir: str | Path | None = None) -> None:
        self.base_dir = Path(base_dir) if base_dir else Path.cwd()
        self._chunk_counter = 0

    def _next_chunk_id(self) -> str:
        self._chunk_counter += 1
        return f"LC{self._chunk_counter}"

    # ------------------------------------------------------------------
    # Preprocessing
    # ------------------------------------------------------------------

    def flatten_includes(
        self,
        content: str,
        base_dir: Path,
        visited: set[str] | None = None,
    ) -> str:
        """Recursively resolve ``\\input{}`` and ``\\include{}`` commands."""
        if visited is None:
            visited = set()

        def _replacer(match: re.Match[str]) -> str:
            prefix = match.group(1)
            filename = match.group(3)

            candidates = [filename]
            if not filename.lower().endswith(".tex"):
                candidates.append(f"{filename}.tex")

            for candidate in candidates:
                file_path = base_dir / candidate
                abs_path = str(file_path.resolve())
                if file_path.exists() and abs_path not in visited:
                    try:
                        visited.add(abs_path)
                        sub_content = file_path.read_text(
                            encoding="utf-8", errors="replace"
                        )
                        sub_dir = file_path.parent
                        return prefix + self.flatten_includes(
                            sub_content, sub_dir, visited
                        )
                    except Exception:
                        logger.debug(
                            "latex_parser.include_read_failed",
                            path=str(file_path),
                        )
            return match.group(0)

        # Match \input{file} or \include{file}, not preceded by %
        pattern = re.compile(
            r"(^|[^%])\\(?:input|include)\{([^}]+)\}", re.MULTILINE
        )
        return pattern.sub(_replacer, content)

    @staticmethod
    def remove_comments(content: str) -> str:
        """Remove LaTeX comments while preserving verbatim environments."""
        lines = content.split("\n")
        out: list[str] = []
        in_verbatim = False

        for line in lines:
            for env in _VERBATIM_ENVS:
                if f"\\begin{{{env}}}" in line:
                    in_verbatim = True
                if f"\\end{{{env}}}" in line:
                    in_verbatim = False

            if in_verbatim:
                out.append(line)
                continue

            stripped = line.lstrip()
            # Preserve %! directives (e.g. %!TEX)
            if stripped.startswith("%!"):
                out.append(line)
                continue
            # Skip full-line comments
            if stripped.startswith("%"):
                continue
            # Remove inline comments but not escaped \%
            cleaned = re.sub(r"(?<!\\)%.*$", "", line)
            if cleaned.strip() or not line.strip():
                out.append(cleaned.rstrip())

        return "\n".join(out)

    @staticmethod
    def _resolve_bibliography(text: str, base_dir: Path) -> str:
        r"""Resolve ``\bibliography{name}`` to ``\input{name.bbl}`` when only ``.bbl`` exists.

        Technique borrowed from ieeA: when arXiv submissions include a
        pre-compiled ``.bbl`` but no ``.bib``, replace the bibliography command
        with a direct input of the ``.bbl`` so that flattening can inline it.
        """

        def _replace(match: re.Match[str]) -> str:
            names_str = match.group(1)
            names = [n.strip() for n in names_str.split(",") if n.strip()]
            if not names:
                return match.group(0)

            has_bib = any((base_dir / f"{n}.bib").exists() for n in names)
            has_bbl = any((base_dir / f"{n}.bbl").exists() for n in names)

            # If any .bib exists, keep original (will run bibtex normally)
            if has_bib:
                return match.group(0)

            # If only .bbl, replace with \input{name.bbl}
            if has_bbl:
                return "\n".join(f"\\input{{{n}.bbl}}" for n in names)

            # Neither found – keep original as fallback
            return match.group(0)

        result = re.sub(r"\\bibliography\{([^}]+)\}", _replace, text)

        # Remove \bibliographystyle if we replaced the bibliography command
        if result != text:
            result = re.sub(r"\\bibliographystyle\{[^}]+\}\n?", "", result)

        return result

    @staticmethod
    def split_preamble_body(content: str) -> tuple[str, str]:
        """Split LaTeX into preamble and body at ``\\begin{document}``."""
        match = re.search(r"\\begin\{document\}", content)
        if not match:
            return "", content
        end_idx = match.end()
        return content[:end_idx], content[end_idx:]

    # ------------------------------------------------------------------
    # Metadata extraction
    # ------------------------------------------------------------------

    def extract_metadata(self, preamble: str, body: str) -> dict[str, Any]:
        """Extract title, authors, keywords, and other metadata."""
        metadata: dict[str, Any] = {}
        full = preamble + body

        # Document class
        dc_match = re.search(
            r"\\documentclass(?:\[([^\]]*)\])?\{([^}]+)\}", preamble
        )
        if dc_match:
            metadata["document_class"] = dc_match.group(2)

        # Title
        title_match = re.search(r"\\title\s*(?:\[[^\]]*\])?\s*\{", full)
        if title_match:
            result = _parse_balanced_group(full, title_match.end() - 1)
            if result is not None:
                metadata["title"] = _strip_latex_commands(result.inner).strip()

        # Authors
        author_match = re.search(r"\\author\s*\{", full)
        if author_match:
            result = _parse_balanced_group(full, author_match.end() - 1)
            if result is not None:
                metadata["authors"] = self._parse_authors(result.inner)

        # Keywords – try multiple command variants
        for kw_cmd in (r"\\keywords\s*\{", r"\\begin\{keywords\}"):
            kw_match = re.search(kw_cmd, full)
            if kw_match:
                if kw_cmd.endswith(r"\{"):
                    result = _parse_balanced_group(full, kw_match.end() - 1)
                    raw = result.inner if result else ""
                else:
                    end = full.find("\\end{keywords}", kw_match.end())
                    raw = full[kw_match.end() : end] if end > 0 else ""
                keywords = [
                    _strip_latex_commands(k).strip()
                    for k in re.split(r"[,;·]", raw)
                    if k.strip()
                ]
                if keywords:
                    metadata["keywords"] = keywords
                break

        # DOI
        doi_match = re.search(r"\\doi\s*\{([^}]+)\}", full)
        if doi_match:
            metadata["doi"] = doi_match.group(1).strip()

        # Year – try \date{...}
        date_match = re.search(r"\\date\s*\{([^}]+)\}", full)
        if date_match:
            year_inner = re.search(r"\b(19|20)\d{2}\b", date_match.group(1))
            if year_inner:
                metadata["year"] = year_inner.group(0)

        return metadata

    @staticmethod
    def _parse_authors(raw: str) -> list[dict[str, str]]:
        """Parse author block into structured author list."""
        authors: list[dict[str, str]] = []
        # Split by \and, \\, \AND, or \newauthor etc.
        parts = re.split(r"\\and\b|\\AND\b|\\\\|\\newauthor", raw)
        for part in parts:
            name = _strip_latex_commands(part).strip()
            name = re.sub(r"\s+", " ", name)
            # Skip very short tokens (typically artefacts)
            if not name or len(name) < 2:
                continue
            # Drop lines that look like affiliations / emails
            if "@" in name or re.match(r"^\d+$", name):
                continue
            # Heuristic: if name contains a newline remainder with digits,
            # take only the first line.
            first_line = name.split("\n")[0].strip()
            if not first_line:
                continue
            name_parts = first_line.split()
            if len(name_parts) >= 2:
                authors.append(
                    {
                        "first_name": " ".join(name_parts[:-1]),
                        "last_name": name_parts[-1],
                    }
                )
            elif name_parts:
                authors.append({"last_name": name_parts[0]})
        return authors

    # ------------------------------------------------------------------
    # Abstract
    # ------------------------------------------------------------------

    def extract_abstract(self, body: str) -> tuple[str | None, str]:
        """Extract abstract from body.

        Returns ``(abstract_text, remaining_body)``.
        """
        match = re.search(r"\\begin\{abstract\}", body)
        if not match:
            return None, body

        start = match.end()
        end_pos = _find_environment_end(body, start, "abstract")
        if end_pos is None:
            return None, body

        raw_abstract = body[start : end_pos - len("\\end{abstract}")]
        abstract_text = _strip_inline_math(raw_abstract)
        abstract_text = _strip_latex_commands(abstract_text).strip()

        remaining = body[: match.start()] + body[end_pos:]
        return abstract_text if abstract_text else None, remaining

    # ------------------------------------------------------------------
    # Section extraction
    # ------------------------------------------------------------------

    def extract_sections(self, body: str) -> list[ParsedSection]:
        """Extract hierarchical sections from document body."""
        # Pattern to match section-level commands
        section_pattern = re.compile(
            r"\\(part|chapter|section|subsection|subsubsection"
            r"|paragraph|subparagraph)\*?\s*\{",
            re.MULTILINE,
        )

        # Collect all section positions: (start, title_end, level, title)
        positions: list[tuple[int, int, str, str]] = []
        for match in section_pattern.finditer(body):
            level = match.group(1)
            brace_start = match.end() - 1
            result = _parse_balanced_group(body, brace_start)
            if result is not None:
                title_text = _strip_latex_commands(result.inner).strip()
                positions.append(
                    (match.start(), result.end, level, title_text)
                )

        if not positions:
            text = self._extract_text_content(body)
            if text.strip():
                return [
                    ParsedSection(
                        title="Body",
                        paragraphs=[
                            p
                            for p in self._split_paragraphs(text)
                            if p.strip()
                        ],
                    )
                ]
            return []

        sections: list[ParsedSection] = []

        # Content before the first section heading
        pre_content = body[: positions[0][0]]
        pre_text = self._extract_text_content(pre_content)
        if pre_text.strip() and len(pre_text.strip()) > 50:
            sections.append(
                ParsedSection(
                    title="Introduction",
                    paragraphs=[
                        p
                        for p in self._split_paragraphs(pre_text)
                        if p.strip()
                    ],
                )
            )

        level_depth = {cmd: idx for idx, cmd in enumerate(SECTION_COMMANDS)}

        for idx, (start, title_end, level, title) in enumerate(positions):
            # Content runs from title_end to start of next section
            if idx + 1 < len(positions):
                content_end = positions[idx + 1][0]
            else:
                end_doc = body.rfind("\\end{document}")
                content_end = end_doc if end_doc > title_end else len(body)

            raw_content = body[title_end:content_end]
            text = self._extract_text_content(raw_content)
            paragraphs = [
                p for p in self._split_paragraphs(text) if p.strip()
            ]

            # Attempt to extract a section number from the title
            number_match = re.match(r"^(\d+(?:\.\d+)*)\s*", title)
            number = number_match.group(1) if number_match else None

            # Find immediate subsections within this range
            subsections = self._extract_subsections(
                body, title_end, content_end, level, level_depth
            )

            section = ParsedSection(
                title=title,
                number=number,
                paragraphs=paragraphs,
                subsections=subsections,
            )
            sections.append(section)

        return sections

    def _extract_subsections(
        self,
        body: str,
        range_start: int,
        range_end: int,
        parent_level: str,
        level_depth: dict[str, int],
    ) -> list[ParsedSection]:
        """Extract child sections within a given range of the body."""
        parent_depth = level_depth.get(parent_level, -1)
        subsection_pattern = re.compile(
            r"\\(part|chapter|section|subsection|subsubsection"
            r"|paragraph|subparagraph)\*?\s*\{",
            re.MULTILINE,
        )

        children: list[tuple[int, int, str, str]] = []
        for match in subsection_pattern.finditer(body, range_start, range_end):
            child_level = match.group(1)
            child_depth = level_depth.get(child_level, -1)
            # Only direct children (one level deeper)
            if child_depth == parent_depth + 1:
                brace_start = match.end() - 1
                result = _parse_balanced_group(body, brace_start)
                if result is not None:
                    title_text = _strip_latex_commands(result.inner).strip()
                    children.append(
                        (match.start(), result.end, child_level, title_text)
                    )

        subsections: list[ParsedSection] = []
        for i, (start, title_end, level, title) in enumerate(children):
            if i + 1 < len(children):
                content_end = children[i + 1][0]
            else:
                content_end = range_end

            raw = body[title_end:content_end]
            text = self._extract_text_content(raw)
            paragraphs = [
                p for p in self._split_paragraphs(text) if p.strip()
            ]
            number_match = re.match(r"^(\d+(?:\.\d+)*)\s*", title)
            number = number_match.group(1) if number_match else None
            subsections.append(
                ParsedSection(
                    title=title,
                    number=number,
                    paragraphs=paragraphs,
                )
            )
        return subsections

    # ------------------------------------------------------------------
    # Text content extraction
    # ------------------------------------------------------------------

    def _extract_text_content(self, latex: str) -> str:
        """Extract readable text from LaTeX, removing protected environments."""
        text = latex

        # Remove protected environments entirely
        for env in PROTECTED_ENVIRONMENTS:
            pattern = re.compile(
                rf"\\begin\{{{re.escape(env)}\}}.*?\\end\{{{re.escape(env)}\}}",
                re.DOTALL,
            )
            text = pattern.sub("", text)

        # Remove figure/table environments but keep caption text
        text = self._extract_and_remove_floats(text)

        # Replace inline math with tokens before stripping commands
        text = _strip_inline_math(text)

        # Strip remaining commands
        text = _strip_latex_commands(text)

        # Collapse excessive blank lines
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _extract_and_remove_floats(self, text: str) -> str:
        """Remove figure/table environments but keep caption text inline."""
        for env in ("figure", "figure*", "table", "table*"):
            pattern = re.compile(
                rf"\\begin\{{{re.escape(env)}\}}(.*?)\\end\{{{re.escape(env)}\}}",
                re.DOTALL,
            )
            for match in pattern.finditer(text):
                inner = match.group(1)
                caption_text = ""
                cap_match = re.search(r"\\caption\s*(?:\[[^\]]*\])?\s*\{", inner)
                if cap_match:
                    result = _parse_balanced_group(inner, cap_match.end() - 1)
                    if result is not None:
                        clean_caption = _strip_latex_commands(result.inner)
                        env_label = env.rstrip("*")
                        caption_text = f"[{env_label} caption: {clean_caption}]"
                text = text.replace(match.group(0), caption_text, 1)
        return text

    @staticmethod
    def _split_paragraphs(text: str) -> list[str]:
        """Split text into paragraphs on double-newlines / blank lines."""
        paragraphs = re.split(r"\n\s*\n", text)
        result: list[str] = []
        for p in paragraphs:
            cleaned = re.sub(r"\s+", " ", p).strip()
            if cleaned and len(cleaned) >= _MIN_PARAGRAPH_LENGTH:
                result.append(cleaned)
        return result

    # ------------------------------------------------------------------
    # Figure & table extraction
    # ------------------------------------------------------------------

    def extract_figures(self, body: str) -> list[ParsedFigure]:
        """Extract figures and tables from LaTeX body."""
        figures: list[ParsedFigure] = []

        for env in ("figure", "figure*"):
            pattern = re.compile(
                rf"\\begin\{{{re.escape(env)}\}}(.*?)\\end\{{{re.escape(env)}\}}",
                re.DOTALL,
            )
            for match in pattern.finditer(body):
                content = match.group(1)
                fig = ParsedFigure()
                fig.fig_type = "figure"
                fig.fig_id = f"fig-{len(figures) + 1}"

                # Caption (handle optional short-caption: \caption[short]{long})
                cap_match = re.search(
                    r"\\caption\s*(?:\[[^\]]*\])?\s*\{", content
                )
                if cap_match:
                    result = _parse_balanced_group(
                        content, cap_match.end() - 1
                    )
                    if result is not None:
                        fig.caption = _strip_latex_commands(result.inner)

                # Label
                label_match = re.search(r"\\label\{([^}]+)\}", content)
                if label_match:
                    fig.fig_id = label_match.group(1)

                # Image path
                img_match = re.search(
                    r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}", content
                )
                if img_match:
                    fig.label = img_match.group(1)

                figures.append(fig)

        for env in ("table", "table*"):
            pattern = re.compile(
                rf"\\begin\{{{re.escape(env)}\}}(.*?)\\end\{{{re.escape(env)}\}}",
                re.DOTALL,
            )
            for match in pattern.finditer(body):
                content = match.group(1)
                fig = ParsedFigure()
                fig.fig_type = "table"
                fig.fig_id = f"tab-{len(figures) + 1}"

                cap_match = re.search(
                    r"\\caption\s*(?:\[[^\]]*\])?\s*\{", content
                )
                if cap_match:
                    result = _parse_balanced_group(
                        content, cap_match.end() - 1
                    )
                    if result is not None:
                        fig.caption = _strip_latex_commands(result.inner)

                label_match = re.search(r"\\label\{([^}]+)\}", content)
                if label_match:
                    fig.fig_id = label_match.group(1)

                figures.append(fig)

        return figures

    # ------------------------------------------------------------------
    # Reference extraction
    # ------------------------------------------------------------------

    def extract_references(
        self, content: str, base_dir: Path | None = None
    ) -> list[ParsedReference]:
        """Extract references from bibliography or .bib files."""
        references: list[ParsedReference] = []

        # Method 1: \bibitem entries in thebibliography environment
        bib_env_match = re.search(
            r"\\begin\{thebibliography\}.*?\n(.*?)\\end\{thebibliography\}",
            content,
            re.DOTALL,
        )
        if bib_env_match:
            references = self._parse_thebibliography(bib_env_match.group(1))

        # Method 2: .bbl file (compiled bibliography)
        if base_dir and not references:
            for bbl_file in base_dir.glob("*.bbl"):
                try:
                    bbl_content = bbl_file.read_text(
                        encoding="utf-8", errors="replace"
                    )
                    bbl_refs = self.extract_references(bbl_content)
                    if bbl_refs:
                        references.extend(bbl_refs)
                        break
                except Exception:
                    pass

        # Method 3: .bib files (BibTeX source)
        if base_dir and not references:
            # Also check \bibliography{...} for specific filenames
            bib_names: list[str] = []
            bib_cmd = re.search(r"\\bibliography\{([^}]+)\}", content)
            if bib_cmd:
                bib_names = [
                    n.strip() for n in bib_cmd.group(1).split(",") if n.strip()
                ]

            bib_files_to_try: list[Path] = []
            for name in bib_names:
                candidate = base_dir / f"{name}.bib"
                if candidate.exists():
                    bib_files_to_try.append(candidate)
            if not bib_files_to_try:
                bib_files_to_try = list(base_dir.glob("*.bib"))

            for bib_file in bib_files_to_try:
                try:
                    bib_content = bib_file.read_text(
                        encoding="utf-8", errors="replace"
                    )
                    bib_refs = self._parse_bibtex(bib_content)
                    references.extend(bib_refs)
                except Exception:
                    pass

        return references

    @staticmethod
    def _parse_thebibliography(bib_content: str) -> list[ParsedReference]:
        """Parse ``\\bibitem`` entries into ParsedReference objects."""
        references: list[ParsedReference] = []
        items = re.split(r"\\bibitem(?:\[[^\]]*\])?\{([^}]+)\}", bib_content)
        # items: [pre, key1, text1, key2, text2, ...]
        for i in range(1, len(items) - 1, 2):
            ref_key = items[i]
            ref_text = items[i + 1].strip() if i + 1 < len(items) else ""
            if not ref_text:
                continue

            ref = ParsedReference()
            ref.ref_id = ref_key
            ref.raw_text = _strip_latex_commands(ref_text)

            # Title – look for \textit{}, \emph{}, or quoted strings
            title_match = re.search(
                r"\\(?:textit|emph|it)\{([^}]+)\}", ref_text
            )
            if title_match:
                ref.title = _strip_latex_commands(title_match.group(1)).strip()
            else:
                # Try ``title'' or "title"
                quote_match = re.search(
                    r'(?:``([^\']+)\'\'|"([^"]+)")', ref_text
                )
                if quote_match:
                    ref.title = (
                        quote_match.group(1) or quote_match.group(2)
                    ).strip()

            # Year
            year_match = re.search(r"\b((?:19|20)\d{2})\b", ref_text)
            if year_match:
                ref.year = year_match.group(1)

            # DOI
            doi_match = re.search(
                r"(?:doi:\s*|https?://doi\.org/)(10\.\d{4,}/[^\s,}]+)",
                ref_text,
                re.IGNORECASE,
            )
            if not doi_match:
                doi_match = re.search(
                    r"\b(10\.\d{4,}/[^\s,}]+)", ref_text
                )
            if doi_match:
                ref.doi = doi_match.group(1).rstrip(".")

            references.append(ref)
        return references

    @staticmethod
    def _parse_bibtex(content: str) -> list[ParsedReference]:
        """Parse BibTeX entries into ParsedReference objects."""
        references: list[ParsedReference] = []
        # Match @type{key, ... } – the closing brace at start of line
        entry_pattern = re.compile(
            r"@(\w+)\{([^,]+),\s*(.*?)\n\}", re.DOTALL
        )

        for match in entry_pattern.finditer(content):
            ref = ParsedReference()
            ref.ref_id = match.group(2).strip()
            fields_text = match.group(3)

            # Extract key = {value} fields
            fields: dict[str, str] = {}
            # Handle both {value} and "value" forms
            field_pattern = re.compile(
                r"(\w+)\s*=\s*(?:\{([^}]*)\}|\"([^\"]*)\")"
            )
            for fm in field_pattern.finditer(fields_text):
                key = fm.group(1).lower()
                value = (fm.group(2) or fm.group(3) or "").strip()
                if value:
                    fields[key] = value

            ref.title = fields.get("title")
            ref.journal = fields.get("journal") or fields.get("booktitle")
            ref.year = fields.get("year")
            ref.volume = fields.get("volume")
            ref.pages = fields.get("pages")
            ref.doi = fields.get("doi")

            if "author" in fields:
                authors = re.split(r"\band\b", fields["author"])
                ref.authors = [
                    _strip_latex_commands(a).strip()
                    for a in authors
                    if a.strip()
                ]

            if "eprint" in fields:
                ref.arxiv_id = fields["eprint"]

            if ref.title:
                references.append(ref)

        return references

    # ------------------------------------------------------------------
    # Main parse method
    # ------------------------------------------------------------------

    def parse(
        self,
        content: str,
        base_dir: Path | None = None,
    ) -> ParsedPaper:
        """Parse LaTeX content into a structured ``ParsedPaper``.

        Args:
            content: Raw LaTeX content (main ``.tex`` file).
            base_dir: Base directory for resolving includes and bib files.

        Returns:
            ``ParsedPaper`` with structured sections, references, figures.
        """
        if base_dir is None:
            base_dir = self.base_dir

        self._chunk_counter = 0

        # Step 1: Preprocess
        working = self.flatten_includes(content, base_dir)
        working = self._resolve_bibliography(working, base_dir)
        # Second flatten pass to inline any .bbl files produced by bibliography resolution
        working = self.flatten_includes(working, base_dir)
        working = self.remove_comments(working)

        # Step 2: Split preamble / body
        preamble, body = self.split_preamble_body(working)

        # Step 3: Metadata
        metadata = self.extract_metadata(preamble, body)

        # Step 4: Abstract
        abstract, body = self.extract_abstract(body)

        # Step 5: Figures and tables
        figures = self.extract_figures(body)

        # Step 6: Sections
        sections = self.extract_sections(body)

        # Step 7: References
        references = self.extract_references(working, base_dir)

        # Step 8: Assemble ParsedPaper
        paper = ParsedPaper()
        paper.title = metadata.get("title")
        paper.authors = metadata.get("authors", [])
        paper.abstract = abstract
        paper.keywords = metadata.get("keywords", [])
        paper.doi = metadata.get("doi")
        paper.year = metadata.get("year")
        paper.journal = metadata.get("document_class")
        paper.sections = sections
        paper.references = references
        paper.figures = figures
        paper.tei_xml = None  # Not from GROBID
        paper.parse_quality = "high"  # LaTeX source is generally high quality

        title_preview = (
            paper.title[:80] if paper.title else "unknown"
        )
        logger.info(
            "latex_parser.parsed",
            title=title_preview,
            sections=len(sections),
            references=len(references),
            figures=len(figures),
        )

        return paper

    def parse_file(self, tex_path: str | Path) -> ParsedPaper:
        """Parse a ``.tex`` file into a structured ``ParsedPaper``."""
        tex_path = Path(tex_path)
        if not tex_path.exists():
            raise FileNotFoundError(f"LaTeX file not found: {tex_path}")
        content = tex_path.read_text(encoding="utf-8", errors="replace")
        return self.parse(content, base_dir=tex_path.parent)


# ---------------------------------------------------------------------------
# Convenience functions
# ---------------------------------------------------------------------------


def parse_latex(
    content: str,
    base_dir: str | Path | None = None,
) -> ParsedPaper:
    """Parse LaTeX content into a structured ``ParsedPaper``."""
    resolved_dir = Path(base_dir) if base_dir else None
    parser = LatexParser(base_dir=resolved_dir)
    return parser.parse(content, base_dir=resolved_dir)


def parse_latex_file(tex_path: str | Path) -> ParsedPaper:
    """Parse a ``.tex`` file into a structured ``ParsedPaper``."""
    parser = LatexParser()
    return parser.parse_file(tex_path)
