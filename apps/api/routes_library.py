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


# POST /papers/{id}/analyze — Level 2 deep analysis
@router.post("/papers/{paper_id}/analyze")
async def trigger_analysis(paper_id: UUID) -> dict[str, Any]:
    """Run Level 2 deep analysis on a library paper."""
    paper = await get_library_paper(paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found")

    try:
        # Get paper text
        paper_text = ""
        arxiv_id = paper.get("arxiv_id")

        if arxiv_id:
            try:
                from services.parser import parse_paper
                parsed = await parse_paper(arxiv_id)
                if parsed.sections:
                    paper_text = "\n\n".join(
                        f"## {s.title}\n" + "\n".join(s.paragraphs or [])
                        for s in parsed.sections if s.title or s.paragraphs
                    )
                if not paper_text and parsed.abstract:
                    paper_text = parsed.abstract
            except Exception as exc:
                logger.debug("analyze.parse_failed", error=str(exc))

            # Fallback: read raw LaTeX source if parser failed
            if not paper_text:
                try:
                    from services.parser.arxiv_source import get_arxiv_latex_source
                    source_result = await get_arxiv_latex_source(arxiv_id)
                    if source_result:
                        main_tex = source_result[0] if isinstance(source_result, tuple) else source_result
                        from pathlib import Path
                        raw_latex = Path(str(main_tex)).read_text(errors="ignore")
                        # Strip LaTeX commands for readability but keep content
                        paper_text = raw_latex[:30000]
                except Exception as exc:
                    logger.debug("analyze.raw_latex_failed", error=str(exc))

        # Fallback to stored summary
        if not paper_text:
            summary = paper.get("summary_json", {})
            paper_text = summary.get("abstract", summary.get("summary", ""))

        if not paper_text:
            raise HTTPException(status_code=400, detail="No paper content available for analysis")

        # Run deep analysis
        from apps.worker.agents.paper_analysis_agent import PaperAnalysisAgent
        from apps.worker.llm_gateway import get_gateway

        agent = PaperAnalysisAgent(gateway=get_gateway())
        analysis = await agent.run(
            paper_text=paper_text,
            metadata={
                "title": paper.get("title", ""),
                "year": paper.get("year"),
                "venue": paper.get("venue", ""),
                "authors": paper.get("authors", []),
            },
        )

        # Save to DB
        from datetime import datetime
        await update_library_paper(paper_id, {
            "deep_analysis_json": analysis.model_dump(),
            "status": "deep_analyzed",
            "updated_at": datetime.utcnow(),
        })

        return {
            "status": "completed",
            "paper_id": str(paper_id),
            "analysis": analysis.model_dump(),
        }

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

        # Get LaTeX source — returns (main_tex, extract_dir, files) tuple or None
        source_result = await get_arxiv_latex_source(arxiv_id)
        stored_path = None
        source_dir = None
        if source_result:
            if isinstance(source_result, tuple):
                main_tex, source_dir, _ = source_result
            else:
                main_tex = source_result
                source_dir = None
            # Store the source directory (not the archive)
            if source_dir:
                stored_path = str(source_dir)

        # Parse paper
        parsed = await parse_paper(arxiv_id)

        title = parsed.title or ""
        authors = [
            a.name if hasattr(a, "name") else str(a)
            for a in (parsed.authors or [])
        ]

        # If LaTeX parsing failed to get title, fetch from Semantic Scholar
        if not title or title.startswith("arXiv"):
            try:
                from libs.adapters.semantic_scholar import SemanticScholarAdapter
                import os
                s2 = SemanticScholarAdapter(api_key=os.getenv("S2_API_KEY"))
                s2_paper = await s2.get_paper(f"ARXIV:{arxiv_id}")
                title = s2_paper.title or title
                if not authors and s2_paper.authors:
                    authors = [a.get("name", "") for a in s2_paper.authors if a.get("name")]
                if not parsed.year and s2_paper.year:
                    parsed.year = s2_paper.year
                await s2.close()
            except Exception as exc:
                logger.debug("library.s2_title_fetch_failed", error=str(exc))

        if not title:
            title = body.get("title", f"arXiv:{arxiv_id}")

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


# POST /upload-file — upload a .tar.gz / .gz / .zip file (LaTeX source)
@router.post("/upload-file", status_code=201)
async def upload_file(
    file: UploadFile = File(...),
    title: str = Form(""),
    project_tags: str = Form(""),
) -> dict[str, Any]:
    """Upload a LaTeX source archive (.tar.gz, .gz, .zip) to the library."""
    from services.library.tools_storage import ensure_library_dirs, UPLOADS_DIR
    import tarfile, gzip, shutil, tempfile
    from uuid import uuid4 as _uuid4

    ensure_library_dirs()

    try:
        # Save uploaded file
        upload_id = str(_uuid4())
        filename = file.filename or "upload.tar.gz"
        upload_path = UPLOADS_DIR / f"{upload_id}_{filename}"
        content = await file.read()
        upload_path.write_bytes(content)

        # Extract
        extract_dir = UPLOADS_DIR / upload_id
        extract_dir.mkdir(parents=True, exist_ok=True)

        if filename.endswith(".tar.gz") or filename.endswith(".tgz"):
            with tarfile.open(str(upload_path), "r:gz") as tar:
                tar.extractall(str(extract_dir))
        elif filename.endswith(".gz"):
            with gzip.open(str(upload_path), "rb") as gz_in:
                out_path = extract_dir / filename.replace(".gz", "")
                out_path.write_bytes(gz_in.read())
        elif filename.endswith(".zip"):
            import zipfile
            with zipfile.ZipFile(str(upload_path), "r") as zf:
                zf.extractall(str(extract_dir))
        else:
            # Treat as single file
            shutil.copy2(str(upload_path), str(extract_dir / filename))

        # Find main .tex file
        tex_files = list(extract_dir.rglob("*.tex"))
        if not tex_files:
            raise HTTPException(status_code=400, detail="No .tex files found in archive")

        # Pick main tex (prefer files with \documentclass)
        main_tex = tex_files[0]
        for tf in tex_files:
            try:
                if "\\documentclass" in tf.read_text(errors="ignore"):
                    main_tex = tf
                    break
            except Exception:
                continue

        # Parse with LaTeX parser
        from services.parser.latex_parser import parse_latex
        latex_content = main_tex.read_text(errors="ignore")
        parsed_doc = parse_latex(latex_content)

        paper_title = title.strip() or parsed_doc.title or filename
        authors = [a if isinstance(a, str) else str(a) for a in (parsed_doc.authors or [])]

        paper_data: dict[str, Any] = {
            "title": paper_title,
            "authors": authors,
            "status": "light_analyzed",
            "latex_source_path": str(extract_dir),
            "is_manually_uploaded": True,
            "project_tags": [t.strip() for t in project_tags.split(",") if t.strip()] if project_tags else [],
        }

        # Tag with LLM if we have content
        paper_text = parsed_doc.abstract or ""
        if parsed_doc.sections:
            paper_text = "\n\n".join(
                f"## {s.heading}\n{s.content}" for s in parsed_doc.sections
                if hasattr(s, "heading") and hasattr(s, "content")
            ) or paper_text

        if not paper_text and parsed_doc.chunks:
            paper_text = "\n\n".join(c.text for c in parsed_doc.chunks if c.text)

        if paper_text:
            try:
                from apps.worker.agents.paper_tag_agent import PaperTagAgent
                from apps.worker.llm_gateway import get_gateway
                agent = PaperTagAgent(gateway=get_gateway())
                tags = await agent.run(paper_text=paper_text, metadata={"title": paper_title})
                paper_data.update({
                    "field": tags.field, "sub_field": tags.sub_field,
                    "keywords": tags.keywords, "methods": tags.methods,
                    "datasets": tags.datasets, "benchmarks": tags.benchmarks,
                    "innovation_points": tags.innovation_points,
                })
            except Exception as exc:
                logger.warning("library.file_upload_tagging_failed", error=str(exc))

        paper = await insert_library_paper(paper_data)
        return paper

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
