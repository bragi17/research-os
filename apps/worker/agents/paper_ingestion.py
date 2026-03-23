"""
PaperIngestionPipeline — Unified paper ingestion with deep analysis + multi-level RAG indexing.

Smart Agent, Dumb Tools pattern:
- TOOL: get_content, split_sections, embed, store (deterministic)
- AGENT: analyze_paper, tag_chunks (LLM calls)

Every paper entering the library goes through this pipeline regardless of source.
"""
from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field
from structlog import get_logger

from apps.worker.llm_gateway import LLMGateway, ModelTier, get_gateway
from libs.schemas.library import (
    DeepAnalysis, ExperimentalDesign, ExperimentalResults, CriticalReview,
)

logger = get_logger(__name__)


# ══════════════════════════════════════════════════════════════
# Pydantic models for structured output
# ══════════════════════════════════════════════════════════════

class PaperLevelAnalysis(BaseModel):
    """Full paper-level analysis — combines old L1 tags + L2 deep analysis."""
    # Hierarchical tags
    field: str = ""
    sub_field: str = ""
    core_problem: str = ""
    methods: list[str] = Field(default_factory=list)
    method_category: str = ""
    datasets: list[str] = Field(default_factory=list)
    benchmarks: list[str] = Field(default_factory=list)
    innovation_points: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    # Deep analysis
    motivation: str = ""
    mathematical_formulation: str = ""
    experimental_design: ExperimentalDesign = Field(default_factory=ExperimentalDesign)
    results: ExperimentalResults = Field(default_factory=ExperimentalResults)
    critical_review: CriticalReview = Field(default_factory=CriticalReview)
    one_more_thing: str = ""
    note: str = ""


class ChunkTag(BaseModel):
    """Tags for a single paragraph/section chunk."""
    section_type: str = "other"  # abstract|introduction|related_work|method|experiment|conclusion|other
    importance: str = "medium"   # high|medium|low
    keywords: list[str] = Field(default_factory=list)
    claim_type: str = ""         # contribution|limitation|finding|comparison|definition|""


class ChunkTagBatch(BaseModel):
    """Batch output for all chunks in a paper."""
    chunks: list[ChunkTag] = Field(default_factory=list)
    note: str = ""


# ══════════════════════════════════════════════════════════════
# System prompts (reviewer perspective)
# ══════════════════════════════════════════════════════════════

_PAPER_ANALYSIS_PROMPT = """\
You are a senior academic reviewer and research analyst. Analyze this paper systematically.

## Paper-Level Tags (hierarchical, for indexing)

- field: Broad research area (e.g., "Computer Vision", "NLP", "Robotics")
- sub_field: Specific direction (e.g., "3D Anomaly Detection", "Point Cloud Processing")
- core_problem: One-sentence summary of the problem this paper solves
- methods: List of specific algorithms/techniques used (e.g., ["PatchCore", "FPFH features", "k-NN"])
- method_category: Category of approach (e.g., "memory-bank", "reconstruction-based", "contrastive")
- datasets: List of datasets used (e.g., ["MVTec 3D-AD", "Eyecandies"])
- benchmarks: Evaluation metrics (e.g., ["image-level AUROC", "pixel-level PRO"])
- innovation_points: What is novel about this work (1 sentence each)
- limitations: Stated or implicit weaknesses
- keywords: All important technical terms for search indexing

## Deep Analysis

- motivation: Research motivation and significance (2-3 paragraphs)
- mathematical_formulation: Key equations in LaTeX ($$..$$). If none, leave empty.
- experimental_design: {models: [str], datasets: [str], hyperparams: str, reproducibility_notes: str}
- results: {baselines: [str], best_metrics: str, key_insights: [str]}
- critical_review: {strengths: [str] (3-5), weaknesses: [str] (3-5), improvements: [str]}
- one_more_thing: Any other noteworthy finding

IMPORTANT: If input is empty or insufficient, return valid JSON with empty fields and a note. Do NOT fabricate.
"""

_CHUNK_TAGGING_PROMPT = """\
You are an academic literature indexing expert. Tag each paragraph of this paper.

For each paragraph (numbered by index), provide:
- section_type: One of: abstract, introduction, related_work, method, experiment, conclusion, other
- importance: high (core contribution), medium (supporting), low (boilerplate/filler)
- keywords: Technical terms in this paragraph that are useful for search:
  - Method paragraphs: algorithm names, model components, loss functions, training strategies
  - Experiment paragraphs: dataset names, metric names, baseline methods, numerical results
  - Introduction paragraphs: problem keywords, application domains, existing approaches
  - Related work paragraphs: cited method names, comparison dimensions
- claim_type: contribution | limitation | finding | comparison | definition | "" (empty if none)

Return a list of chunk tags matching the paragraph indices.

IMPORTANT: If input is empty, return empty chunks list with a note. Do NOT fabricate.
"""


# ══════════════════════════════════════════════════════════════
# Deterministic tools (no LLM)
# ══════════════════════════════════════════════════════════════

async def tool_get_content(
    arxiv_id: str | None = None,
    latex_text: str | None = None,
) -> tuple[str, str]:
    """TOOL: Get paper content. Returns (paper_text, source_type)."""
    if latex_text:
        return latex_text[:30000], "direct"

    if arxiv_id:
        # Try LaTeX parsing
        try:
            from services.parser import parse_paper
            parsed = await parse_paper(arxiv_id)
            if parsed.sections:
                text = "\n\n".join(
                    f"## {s.title}\n" + "\n".join(s.paragraphs or [])
                    for s in parsed.sections if s.title or s.paragraphs
                )
                if text.strip():
                    return text[:30000], "latex_parsed"
        except Exception:
            pass

        # Fallback: raw LaTeX file
        try:
            from services.parser.arxiv_source import get_arxiv_latex_source
            result = await get_arxiv_latex_source(arxiv_id)
            if result:
                main_tex = result[0] if isinstance(result, tuple) else result
                from pathlib import Path
                raw = Path(str(main_tex)).read_text(errors="ignore")
                return raw[:30000], "raw_latex"
        except Exception:
            pass

    return "", "none"


def tool_split_sections(paper_text: str) -> list[dict[str, str]]:
    """TOOL: Split paper text into paragraph-level chunks. Deterministic."""
    if not paper_text:
        return []

    chunks: list[dict[str, str]] = []

    # Try splitting by ## headers (parsed LaTeX format)
    sections = re.split(r'\n##\s+', paper_text)
    if len(sections) > 1:
        for i, sec in enumerate(sections):
            sec = sec.strip()
            if not sec:
                continue
            lines = sec.split('\n', 1)
            title = lines[0].strip() if lines else ""
            body = lines[1].strip() if len(lines) > 1 else sec

            # Split body into paragraphs
            paragraphs = [p.strip() for p in body.split('\n\n') if p.strip()]
            if not paragraphs:
                paragraphs = [body] if body else []

            for j, para in enumerate(paragraphs):
                if len(para) < 20:
                    continue  # skip tiny fragments
                chunks.append({
                    "text": para[:2000],
                    "section_title": title,
                    "paragraph_index": len(chunks),
                })
    else:
        # Fallback: split by \section commands (raw LaTeX)
        latex_sections = re.split(r'\\(?:sub)*section\*?\{([^}]*)\}', paper_text)
        for i in range(0, len(latex_sections), 2):
            text = latex_sections[i].strip()
            if not text or len(text) < 30:
                continue
            title = latex_sections[i - 1].strip() if i > 0 else "preamble"
            # Split into paragraphs
            paragraphs = [p.strip() for p in text.split('\n\n') if p.strip() and len(p.strip()) > 20]
            for para in paragraphs:
                chunks.append({
                    "text": para[:2000],
                    "section_title": title,
                    "paragraph_index": len(chunks),
                })

    # Absolute fallback: split by double newlines
    if not chunks:
        paragraphs = [p.strip() for p in paper_text.split('\n\n') if p.strip() and len(p.strip()) > 30]
        for i, para in enumerate(paragraphs[:50]):
            chunks.append({
                "text": para[:2000],
                "section_title": "",
                "paragraph_index": i,
            })

    return chunks


# ══════════════════════════════════════════════════════════════
# Pipeline
# ══════════════════════════════════════════════════════════════

class PaperIngestionPipeline:
    """
    Unified ingestion: content → split → analyze → tag → embed → store.
    All papers go through this regardless of source.
    """

    def __init__(self, gateway: LLMGateway | None = None):
        self.gateway = gateway or get_gateway()

    async def ingest(
        self,
        *,
        arxiv_id: str | None = None,
        latex_text: str | None = None,
        title: str = "",
        metadata: dict[str, Any] | None = None,
        source_run_id: str | None = None,
        project_tags: list[str] | None = None,
        is_manually_uploaded: bool = False,
    ) -> dict[str, Any]:
        """
        Full ingestion pipeline. Returns the created library_paper dict.

        Args:
            arxiv_id: arXiv paper ID
            latex_text: Pre-loaded LaTeX/text content
            title: Paper title (fetched from S2 if not provided)
            metadata: Additional metadata {authors, year, venue, ...}
            source_run_id: UUID of the research run (if from run results)
            project_tags: Project tag labels
            is_manually_uploaded: Whether this is a manual upload
        """
        metadata = metadata or {}

        # ── Step 1: TOOL — Get content ──
        logger.info("ingestion.step1_content", arxiv_id=arxiv_id, has_text=bool(latex_text))
        paper_text, source_type = await tool_get_content(arxiv_id, latex_text)

        # ── Resolve title from S2 if needed ──
        if (not title or title.startswith("arXiv")) and arxiv_id:
            title = await self._fetch_title_from_s2(arxiv_id, title)

        # ── Step 2: TOOL — Split into sections ──
        logger.info("ingestion.step2_split", text_len=len(paper_text))
        chunks = tool_split_sections(paper_text)
        logger.info("ingestion.step2_done", chunks=len(chunks))

        # ── Step 3: AGENT — Paper-level analysis ──
        logger.info("ingestion.step3_analysis")
        analysis = await self._analyze_paper(paper_text, title, metadata)

        # ── Step 4: AGENT — Chunk-level tagging ──
        logger.info("ingestion.step4_tagging", chunks=len(chunks))
        chunk_tags = await self._tag_chunks(chunks, title)

        # ── Step 5: TOOL — Embed chunks ──
        logger.info("ingestion.step5_embedding", chunks=len(chunks))
        embeddings = await self._embed_chunks(chunks)

        # ── Step 6: TOOL — Store to DB ──
        logger.info("ingestion.step6_store")
        paper = await self._store(
            title=title,
            arxiv_id=arxiv_id,
            metadata=metadata,
            analysis=analysis,
            chunks=chunks,
            chunk_tags=chunk_tags,
            embeddings=embeddings,
            source_run_id=source_run_id,
            project_tags=project_tags or [],
            is_manually_uploaded=is_manually_uploaded,
            latex_source_path=None,  # TODO: store path if downloaded
        )

        logger.info("ingestion.complete",
                     paper_id=paper.get("id"),
                     title=title[:40],
                     chunks=len(chunks),
                     status=paper.get("status"))
        return paper

    # ── Agent calls ──

    async def _analyze_paper(
        self, paper_text: str, title: str, metadata: dict[str, Any]
    ) -> PaperLevelAnalysis:
        """AGENT: Full paper analysis (1 structured LLM call)."""
        if not paper_text:
            return PaperLevelAnalysis(note="No paper content available")

        user_content = (
            f"Paper title: {title}\n"
            f"Year: {metadata.get('year', 'Unknown')}\n"
            f"Venue: {metadata.get('venue', 'Unknown')}\n"
            f"Authors: {', '.join(metadata.get('authors', []))}\n\n"
            f"Paper content:\n{paper_text[:20000]}\n"
        )

        try:
            result = await self.gateway.chat_structured(
                output_schema=PaperLevelAnalysis,
                messages=[
                    {"role": "system", "content": _PAPER_ANALYSIS_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                tier=ModelTier.HIGH,
            )
            logger.info("ingestion.analysis_done",
                         field=result.field, methods=len(result.methods))
            return result
        except Exception as exc:
            logger.error("ingestion.analysis_failed", error=str(exc))
            return PaperLevelAnalysis(note=f"Analysis failed: {exc}")

    async def _tag_chunks(
        self, chunks: list[dict[str, str]], title: str
    ) -> list[ChunkTag]:
        """AGENT: Tag all chunks in one batched LLM call."""
        if not chunks:
            return []

        # Build numbered paragraph list for LLM
        para_list = "\n\n".join(
            f"[Paragraph {i}] (section: {c.get('section_title', '?')})\n{c['text'][:500]}"
            for i, c in enumerate(chunks[:40])  # Cap at 40 paragraphs
        )

        user_content = (
            f"Paper title: {title}\n\n"
            f"Paragraphs to tag:\n\n{para_list}\n"
        )

        try:
            result = await self.gateway.chat_structured(
                output_schema=ChunkTagBatch,
                messages=[
                    {"role": "system", "content": _CHUNK_TAGGING_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                tier=ModelTier.MEDIUM,
            )
            logger.info("ingestion.tagging_done", tagged=len(result.chunks))

            # Pad if LLM returned fewer tags than chunks
            while len(result.chunks) < len(chunks):
                result.chunks.append(ChunkTag())

            return result.chunks
        except Exception as exc:
            logger.error("ingestion.tagging_failed", error=str(exc))
            # Fallback: deterministic section classification
            return [
                ChunkTag(
                    section_type=self._classify_section(c.get("section_title", "")),
                    keywords=[],
                )
                for c in chunks
            ]

    # ── Tool calls ──

    async def _embed_chunks(self, chunks: list[dict[str, str]]) -> list[list[float]]:
        """TOOL: Embed all chunk texts using Tongyi text-embedding-v4."""
        if not chunks:
            return []
        try:
            from services.library.tools_embedding import embed_paper_chunks
            texts = [c["text"][:1000] for c in chunks]  # Cap per chunk
            return await embed_paper_chunks(texts)
        except Exception as exc:
            logger.error("ingestion.embedding_failed", error=str(exc))
            return []

    async def _store(
        self, *, title: str, arxiv_id: str | None, metadata: dict[str, Any],
        analysis: PaperLevelAnalysis, chunks: list[dict], chunk_tags: list[ChunkTag],
        embeddings: list[list[float]], source_run_id: str | None,
        project_tags: list[str], is_manually_uploaded: bool,
        latex_source_path: str | None,
    ) -> dict[str, Any]:
        """TOOL: Store paper + chunks to DB."""
        from services.library.tools_db import insert_library_paper, insert_library_chunks

        # Determine status
        has_analysis = bool(analysis.field or analysis.motivation)
        has_chunks = bool(chunks and embeddings)
        if has_analysis and has_chunks:
            status = "analyzed"
        elif has_analysis:
            status = "analyzed"  # no chunks but we have analysis
        else:
            status = "partial"

        # Build deep_analysis_json
        deep = DeepAnalysis(
            motivation=analysis.motivation,
            mathematical_formulation=analysis.mathematical_formulation,
            experimental_design=analysis.experimental_design,
            results=analysis.results,
            critical_review=analysis.critical_review,
            one_more_thing=analysis.one_more_thing,
        )

        paper_data = {
            "title": title,
            "arxiv_id": arxiv_id,
            "doi": metadata.get("doi"),
            "authors": metadata.get("authors", []),
            "year": metadata.get("year"),
            "venue": metadata.get("venue", ""),
            "status": status,
            "field": analysis.field,
            "sub_field": analysis.sub_field,
            "keywords": analysis.keywords,
            "methods": analysis.methods,
            "datasets": analysis.datasets,
            "benchmarks": analysis.benchmarks,
            "innovation_points": analysis.innovation_points,
            "summary_json": {
                "core_problem": analysis.core_problem,
                "method_category": analysis.method_category,
                "limitations": analysis.limitations,
            },
            "deep_analysis_json": deep.model_dump(),
            "source_run_id": source_run_id,
            "project_tags": project_tags,
            "is_manually_uploaded": is_manually_uploaded,
            "latex_source_path": latex_source_path,
        }

        paper = await insert_library_paper(paper_data)
        paper_id = UUID(str(paper["id"]))

        # Insert chunks with tags and embeddings
        if chunks:
            chunk_records = []
            for i, chunk in enumerate(chunks):
                tag = chunk_tags[i] if i < len(chunk_tags) else ChunkTag()
                emb = embeddings[i] if i < len(embeddings) else None
                chunk_records.append({
                    "section_type": tag.section_type,
                    "paragraph_index": chunk.get("paragraph_index", i),
                    "text": chunk["text"],
                    "token_count": len(chunk["text"].split()),
                    "tags": tag.keywords,
                    "claim_type": tag.claim_type or None,
                    "embedding": emb,
                })

            count = await insert_library_chunks(paper_id, chunk_records)
            logger.info("ingestion.chunks_stored", count=count)

        return paper

    # ── Helpers ──

    async def _fetch_title_from_s2(self, arxiv_id: str, fallback: str) -> str:
        """Fetch real title from Semantic Scholar."""
        try:
            import os
            from libs.adapters.semantic_scholar import SemanticScholarAdapter
            s2 = SemanticScholarAdapter(api_key=os.getenv("S2_API_KEY"))
            paper = await s2.get_paper(f"ARXIV:{arxiv_id}")
            await s2.close()
            return paper.title or fallback
        except Exception:
            return fallback or f"arXiv:{arxiv_id}"

    @staticmethod
    def _classify_section(title: str) -> str:
        """Deterministic fallback for section classification."""
        t = title.lower().strip()
        if "abstract" in t: return "abstract"
        if "intro" in t: return "introduction"
        if "related" in t: return "related_work"
        if "method" in t or "approach" in t or "model" in t: return "method"
        if "experiment" in t or "result" in t or "evaluation" in t: return "experiment"
        if "conclu" in t or "summary" in t or "discuss" in t: return "conclusion"
        return "other"
