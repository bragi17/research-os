"""Paper Library API — CRUD, search, upload endpoints."""
from __future__ import annotations


from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, UploadFile, File, Form
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


# POST /papers — add paper to library (full ingestion pipeline)
@router.post("/papers", status_code=201)
async def add_paper(body: dict[str, Any]) -> dict[str, Any]:
    """Add a paper to the library with full deep analysis + multi-level RAG indexing."""
    if not body.get("title") and not body.get("arxiv_id"):
        raise HTTPException(status_code=400, detail="title or arxiv_id is required")
    try:
        from apps.worker.agents.paper_ingestion import PaperIngestionPipeline
        pipeline = PaperIngestionPipeline()
        return await pipeline.ingest(
            arxiv_id=body.get("arxiv_id"),
            title=body.get("title", ""),
            metadata={
                "authors": body.get("authors", []),
                "year": body.get("year"),
                "venue": body.get("venue", ""),
                "doi": body.get("doi"),
            },
            source_run_id=body.get("source_run_id"),
            project_tags=body.get("project_tags", []),
        )
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


# POST /papers/{id}/analyze — re-run full analysis pipeline
@router.post("/papers/{paper_id}/analyze")
async def trigger_analysis(paper_id: UUID) -> dict[str, Any]:
    """Re-run deep analysis on an existing library paper."""
    paper = await get_library_paper(paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found")

    try:
        # Delete existing paper and re-ingest
        arxiv_id = paper.get("arxiv_id")
        await delete_library_paper(paper_id)

        from apps.worker.agents.paper_ingestion import PaperIngestionPipeline
        pipeline = PaperIngestionPipeline()
        new_paper = await pipeline.ingest(
            arxiv_id=arxiv_id,
            title=paper.get("title", ""),
            metadata={
                "authors": paper.get("authors", []),
                "year": paper.get("year"),
                "venue": paper.get("venue", ""),
                "doi": paper.get("doi"),
            },
            source_run_id=paper.get("source_run_id"),
            project_tags=paper.get("project_tags", []),
            is_manually_uploaded=paper.get("is_manually_uploaded", False),
        )
        return {"status": "completed", "paper_id": str(new_paper.get("id")), "paper": new_paper}

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("analyze.failed", paper_id=str(paper_id), error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


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


# POST /upload — upload by arXiv ID (full ingestion pipeline)
@router.post("/upload", status_code=201)
async def upload_paper(body: dict[str, Any]) -> dict[str, Any]:
    """Upload a paper by arXiv ID with full deep analysis + RAG indexing."""
    arxiv_id = body.get("arxiv_id")
    if not arxiv_id:
        raise HTTPException(status_code=400, detail="arxiv_id is required")
    try:
        from apps.worker.agents.paper_ingestion import PaperIngestionPipeline
        pipeline = PaperIngestionPipeline()
        return await pipeline.ingest(
            arxiv_id=arxiv_id,
            title=body.get("title", ""),
            metadata={"authors": body.get("authors", []), "year": body.get("year")},
            project_tags=body.get("project_tags", []),
            is_manually_uploaded=True,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("library.upload_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


# POST /upload-file — upload .tar.gz / .gz / .zip (full ingestion pipeline)
@router.post("/upload-file", status_code=201)
async def upload_file(
    file: UploadFile = File(...),
    title: str = Form(""),
    project_tags: str = Form(""),
) -> dict[str, Any]:
    """Upload LaTeX source archive with full deep analysis + RAG indexing."""
    from services.library.tools_storage import ensure_library_dirs, UPLOADS_DIR
    import tarfile, gzip, shutil
    from uuid import uuid4 as _uuid4

    ensure_library_dirs()

    try:
        # Save + extract uploaded file
        upload_id = str(_uuid4())
        filename = file.filename or "upload.tar.gz"
        upload_path = UPLOADS_DIR / f"{upload_id}_{filename}"
        raw_content = await file.read()
        upload_path.write_bytes(raw_content)

        extract_dir = UPLOADS_DIR / upload_id
        extract_dir.mkdir(parents=True, exist_ok=True)

        if filename.endswith((".tar.gz", ".tgz")):
            with tarfile.open(str(upload_path), "r:gz") as tar:
                tar.extractall(str(extract_dir))
        elif filename.endswith(".gz"):
            with gzip.open(str(upload_path), "rb") as gz_in:
                (extract_dir / filename.replace(".gz", "")).write_bytes(gz_in.read())
        elif filename.endswith(".zip"):
            import zipfile
            with zipfile.ZipFile(str(upload_path), "r") as zf:
                zf.extractall(str(extract_dir))
        else:
            shutil.copy2(str(upload_path), str(extract_dir / filename))

        # Find main .tex and read content
        tex_files = list(extract_dir.rglob("*.tex"))
        if not tex_files:
            raise HTTPException(status_code=400, detail="No .tex files found in archive")

        main_tex = tex_files[0]
        for tf in tex_files:
            try:
                if "\\documentclass" in tf.read_text(errors="ignore"):
                    main_tex = tf
                    break
            except Exception:
                continue

        latex_content = main_tex.read_text(errors="ignore")

        # Feed to unified pipeline
        from apps.worker.agents.paper_ingestion import PaperIngestionPipeline
        pipeline = PaperIngestionPipeline()
        tags_list = [t.strip() for t in project_tags.split(",") if t.strip()] if project_tags else []
        return await pipeline.ingest(
            latex_text=latex_content,
            title=title.strip() or "",
            project_tags=tags_list,
            is_manually_uploaded=True,
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("library.file_upload_failed", error=str(exc))
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
