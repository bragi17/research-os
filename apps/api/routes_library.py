"""Paper Library API — CRUD, search, upload endpoints."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query
from structlog import get_logger

from services.library.tools_db import (
    insert_library_paper,
    get_library_paper,
    list_library_papers,
    delete_library_paper,
    update_library_paper,
    insert_library_chunks,
    search_library_vectors,
    search_library_text,
    count_library_papers,
    count_library_chunks,
)

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/library", tags=["library"])


# POST /papers — add paper to library
@router.post("/papers", status_code=201)
async def add_paper(body: dict[str, Any]) -> dict[str, Any]:
    """Add a paper to the library (from research run results)."""
    if not body.get("title"):
        raise HTTPException(status_code=400, detail="title is required")
    try:
        paper = await insert_library_paper(body)
        # If paper has sections data, embed and insert chunks
        sections = body.get("sections", [])
        if sections:
            from services.library.tools_embedding import embed_paper_chunks

            texts = [s.get("text", "") for s in sections if s.get("text")]
            if texts:
                try:
                    embeddings = await embed_paper_chunks(texts)
                    chunks = []
                    for i, sec in enumerate(sections):
                        if not sec.get("text"):
                            continue
                        emb = (
                            embeddings[len(chunks)]
                            if len(chunks) < len(embeddings)
                            else None
                        )
                        chunks.append({
                            "section_type": sec.get("section_type", "other"),
                            "paragraph_index": sec.get("paragraph_index", i),
                            "text": sec["text"],
                            "token_count": len(sec["text"].split()),
                            "tags": sec.get("tags", []),
                            "claim_type": sec.get("claim_type"),
                            "embedding": emb,
                        })
                    await insert_library_chunks(UUID(str(paper["id"])), chunks)
                except Exception as exc:
                    logger.warning(
                        "library.chunk_embedding_failed", error=str(exc)
                    )
        return paper
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("library.add_paper_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


# GET /papers — list with filters
@router.get("/papers")
async def list_papers(
    field: str | None = Query(None),
    project_tag: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    try:
        papers = await list_library_papers(
            field=field, project_tag=project_tag, limit=limit, offset=offset
        )
        total = await count_library_papers()
        return {"items": papers, "total": total}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# GET /papers/{id}
@router.get("/papers/{paper_id}")
async def get_paper(paper_id: UUID) -> dict[str, Any]:
    paper = await get_library_paper(paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found in library")
    return paper


# DELETE /papers/{id}
@router.delete("/papers/{paper_id}")
async def remove_paper(paper_id: UUID) -> dict[str, str]:
    deleted = await delete_library_paper(paper_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Paper not found")
    return {"status": "deleted", "id": str(paper_id)}


# PATCH /papers/{id}
@router.patch("/papers/{paper_id}")
async def patch_paper(paper_id: UUID, body: dict[str, Any]) -> dict[str, Any]:
    body["updated_at"] = datetime.utcnow()
    result = await update_library_paper(paper_id, body)
    if result is None:
        raise HTTPException(
            status_code=404, detail="Paper not found or no valid fields"
        )
    return result


# POST /papers/{id}/analyze — stub for Level 2 analysis (Plan C)
@router.post("/papers/{paper_id}/analyze")
async def trigger_analysis(paper_id: UUID) -> dict[str, str]:
    paper = await get_library_paper(paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found")
    # TODO: trigger PaperAnalysisAgent (Level 2) — implemented in Plan C
    return {"status": "queued", "paper_id": str(paper_id)}


# GET /search?q= — hybrid text+vector search with rerank
@router.get("/search")
async def search_papers(
    q: str = Query(..., min_length=2),
    field: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    try:
        from services.library.tools_embedding import embed_paper_chunks, rerank_papers

        # Vector search
        vectors = await embed_paper_chunks([q])
        candidates: list[dict[str, Any]] = []
        if vectors:
            candidates = await search_library_vectors(
                vectors[0], limit=limit * 3, field=field
            )

        # Also do text search and merge
        text_results = await search_library_text(q, limit=limit)
        seen_ids = {str(c["id"]) for c in candidates}
        for tr in text_results:
            if str(tr["id"]) not in seen_ids:
                candidates.append(tr)
                seen_ids.add(str(tr["id"]))

        # Rerank
        if candidates:
            titles = [c.get("title", "") for c in candidates]
            reranked = await rerank_papers(q, titles, top_n=limit)
            results: list[dict[str, Any]] = []
            for r in reranked:
                idx = r.get("index", 0)
                if idx < len(candidates):
                    paper = dict(candidates[idx])
                    paper["relevance_score"] = r.get("relevance_score", 0)
                    results.append(paper)
            return {"items": results, "total": len(results)}

        return {"items": candidates[:limit], "total": len(candidates[:limit])}
    except Exception as exc:
        logger.error("library.search_failed", error=str(exc))
        # Fallback to text-only search
        text_results = await search_library_text(q, limit=limit)
        return {"items": text_results, "total": len(text_results)}


# GET /search/titles?q= — fast ILIKE for seed paper picker
@router.get("/search/titles")
async def search_titles(
    q: str = Query(..., min_length=1),
    limit: int = Query(10, ge=1, le=50),
) -> dict[str, Any]:
    results = await search_library_text(q, limit=limit)
    return {"items": results, "total": len(results)}


# GET /stats
@router.get("/stats")
async def get_stats() -> dict[str, Any]:
    papers = await count_library_papers()
    chunks = await count_library_chunks()
    return {"papers": papers, "chunks": chunks}


# POST /upload — upload arXiv ID or PDF
@router.post("/upload", status_code=201)
async def upload_paper(body: dict[str, Any]) -> dict[str, Any]:
    """Upload a paper by arXiv ID. PDF upload to be added later."""
    arxiv_id = body.get("arxiv_id")
    if not arxiv_id:
        raise HTTPException(status_code=400, detail="arxiv_id is required")

    try:
        # Download and parse
        from services.parser import parse_paper
        from services.parser.arxiv_source import get_arxiv_latex_source
        from services.library.tools_storage import (
            save_latex_source,
            ensure_library_dirs,
        )

        ensure_library_dirs()

        # Get LaTeX source
        source_path = await get_arxiv_latex_source(arxiv_id)
        stored_path = None
        if source_path:
            stored_path = save_latex_source(arxiv_id, source_path)

        # Parse paper
        parsed = await parse_paper(arxiv_id)

        title = parsed.title or body.get("title", f"arXiv:{arxiv_id}")
        authors = [
            a.name if hasattr(a, "name") else str(a)
            for a in (parsed.authors or [])
        ]

        paper_data: dict[str, Any] = {
            "title": title,
            "arxiv_id": arxiv_id,
            "authors": authors,
            "year": parsed.year,
            "status": "light_analyzed",
            "latex_source_path": stored_path,
            "is_manually_uploaded": True,
            "project_tags": body.get("project_tags", []),
        }

        # Run PaperTagAgent if we have content
        paper_text = parsed.abstract or ""
        if parsed.sections:
            paper_text = "\n\n".join(
                f"## {s.title}\n" + "\n".join(s.paragraphs or [])
                for s in parsed.sections
                if s.title or s.paragraphs
            )

        if paper_text:
            try:
                from apps.worker.agents.paper_tag_agent import PaperTagAgent
                from apps.worker.llm_gateway import get_gateway

                agent = PaperTagAgent(gateway=get_gateway())
                tags = await agent.run(
                    paper_text=paper_text,
                    metadata={"title": title, "year": parsed.year},
                )
                paper_data.update({
                    "field": tags.field,
                    "sub_field": tags.sub_field,
                    "keywords": tags.keywords,
                    "methods": tags.methods,
                    "datasets": tags.datasets,
                    "benchmarks": tags.benchmarks,
                    "innovation_points": tags.innovation_points,
                })
            except Exception as exc:
                logger.warning(
                    "library.upload_tagging_failed", error=str(exc)
                )

        paper = await insert_library_paper(paper_data)

        # Embed and store chunks
        if parsed.sections:
            from services.library.tools_embedding import embed_paper_chunks

            chunk_texts: list[str] = []
            chunk_meta: list[dict[str, Any]] = []
            for sec in parsed.sections:
                for j, para in enumerate(sec.paragraphs or []):
                    if para.strip():
                        chunk_texts.append(para)
                        chunk_meta.append({
                            "section_type": _classify_section(sec.title or ""),
                            "paragraph_index": j,
                            "text": para,
                            "token_count": len(para.split()),
                        })
            if chunk_texts:
                try:
                    embeddings = await embed_paper_chunks(chunk_texts)
                    for i, meta in enumerate(chunk_meta):
                        if i < len(embeddings):
                            meta["embedding"] = embeddings[i]
                    await insert_library_chunks(
                        UUID(str(paper["id"])), chunk_meta
                    )
                except Exception as exc:
                    logger.warning(
                        "library.upload_embedding_failed", error=str(exc)
                    )

        return paper
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("library.upload_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


def _classify_section(title: str) -> str:
    """Classify section title to section_type."""
    t = title.lower().strip()
    if "abstract" in t:
        return "abstract"
    if "intro" in t:
        return "introduction"
    if "method" in t or "approach" in t or "model" in t:
        return "method"
    if "experiment" in t or "result" in t or "evaluation" in t:
        return "experiment"
    if "related" in t:
        return "related_work"
    if "conclu" in t or "summary" in t:
        return "conclusion"
    return "other"
