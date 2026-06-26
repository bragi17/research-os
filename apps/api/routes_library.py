"""Paper Library API — CRUD, search, upload endpoints."""
from __future__ import annotations


import gzip
import os
import shutil
import tarfile
import zipfile
import zlib
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, UploadFile, File, Form
from structlog import get_logger

from libs.schemas.library import LibraryPoolCreate, LibraryPoolUpdate
from services.library.pools_db import (
    copy_library_paper,
    create_library_pool,
    delete_library_pool as delete_pool_record,
    get_pool_duplicate_candidates,
    list_library_pools,
    move_library_paper,
    remove_paper_from_pool,
    update_library_pool,
)
from services.library.tools_db import (
    get_library_paper,
    list_library_papers,
    delete_library_paper,
    update_library_paper,
    search_library_vectors,
    search_library_text,
    count_library_papers,
    count_library_chunks,
)

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/library", tags=["library"])
NO_ARXIV_DETAIL = (
    "Cannot re-analyze: no arXiv ID found. Try adding the paper again with an arXiv ID."
)
INVALID_ARCHIVE_DETAIL = "Invalid or unsafe archive input"


def _parse_pool_ids(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _archive_member_target(extract_dir: Path, member_name: str) -> Path:
    extract_root = extract_dir.resolve()
    target = (extract_root / member_name).resolve()
    try:
        target.relative_to(extract_root)
    except ValueError as exc:
        raise ValueError(f"unsafe archive member: {member_name}") from exc
    return target


def _archive_target_parent_paths(extract_root: Path, target: Path) -> list[Path]:
    relative_target = target.relative_to(extract_root)
    parent_paths: list[Path] = []
    parent_path = extract_root
    for part in relative_target.parts[:-1]:
        parent_path = parent_path / part
        parent_paths.append(parent_path)
    return parent_paths


def _check_archive_member_layout(
    extract_root: Path,
    target: Path,
    member_name: str,
    is_dir: bool,
    archive_files: set[Path],
    archive_dirs: set[Path],
) -> None:
    parent_paths = _archive_target_parent_paths(extract_root, target)
    for parent_path in parent_paths:
        if parent_path in archive_files or (
            parent_path.exists() and not parent_path.is_dir()
        ):
            raise ValueError(f"unsafe archive member: {member_name}")

    if is_dir:
        if target in archive_files or (target.exists() and not target.is_dir()):
            raise ValueError(f"unsafe archive member: {member_name}")
        archive_dirs.update(parent_paths)
        archive_dirs.add(target)
        return

    if target in archive_dirs or (target.exists() and target.is_dir()):
        raise ValueError(f"unsafe archive member: {member_name}")
    archive_dirs.update(parent_paths)
    archive_files.add(target)


def _safe_extract_archive(archive_path: Path, extract_dir: Path) -> None:
    archive_path = Path(archive_path)
    extract_dir = Path(extract_dir)
    extract_dir.mkdir(parents=True, exist_ok=True)
    extract_root = extract_dir.resolve()

    if archive_path.name.endswith((".tar.gz", ".tgz")):
        with tarfile.open(archive_path, "r:gz") as tar:
            members = tar.getmembers()
            archive_files: set[Path] = set()
            archive_dirs: set[Path] = {extract_root}
            for member in members:
                target = _archive_member_target(extract_dir, member.name)
                if not (member.isdir() or member.isfile()):
                    raise ValueError(f"unsafe archive member: {member.name}")
                _check_archive_member_layout(
                    extract_root,
                    target,
                    member.name,
                    member.isdir(),
                    archive_files,
                    archive_dirs,
                )

            for member in members:
                target = _archive_member_target(extract_dir, member.name)
                if member.isdir():
                    try:
                        target.mkdir(parents=True, exist_ok=True)
                    except (FileExistsError, NotADirectoryError) as exc:
                        raise ValueError(
                            f"unsafe archive member: {member.name}"
                        ) from exc
                    continue

                try:
                    target.parent.mkdir(parents=True, exist_ok=True)
                except (FileExistsError, NotADirectoryError) as exc:
                    raise ValueError(f"unsafe archive member: {member.name}") from exc
                source = tar.extractfile(member)
                if source is None:
                    raise ValueError(f"unsafe archive member: {member.name}")
                try:
                    with source, target.open("wb") as output:
                        shutil.copyfileobj(source, output)
                except IsADirectoryError as exc:
                    raise ValueError(f"unsafe archive member: {member.name}") from exc
        return

    if archive_path.suffix.lower() == ".zip":
        with zipfile.ZipFile(archive_path, "r") as zf:
            infos = zf.infolist()
            archive_files = set()
            archive_dirs = {extract_root}
            for info in infos:
                target = _archive_member_target(extract_dir, info.filename)
                _check_archive_member_layout(
                    extract_root,
                    target,
                    info.filename,
                    info.is_dir(),
                    archive_files,
                    archive_dirs,
                )

            for info in infos:
                target = _archive_member_target(extract_dir, info.filename)
                if info.is_dir():
                    try:
                        target.mkdir(parents=True, exist_ok=True)
                    except (FileExistsError, NotADirectoryError) as exc:
                        raise ValueError(
                            f"unsafe archive member: {info.filename}"
                        ) from exc
                    continue

                try:
                    target.parent.mkdir(parents=True, exist_ok=True)
                except (FileExistsError, NotADirectoryError) as exc:
                    raise ValueError(
                        f"unsafe archive member: {info.filename}"
                    ) from exc
                try:
                    with zf.open(info, "r") as source, target.open("wb") as output:
                        shutil.copyfileobj(source, output)
                except IsADirectoryError as exc:
                    raise ValueError(
                        f"unsafe archive member: {info.filename}"
                    ) from exc
        return

    raise ValueError(f"Unsupported archive type: {archive_path.name}")


# GET /pools — list knowledge-base pools
@router.get("/pools")
async def list_pools() -> dict[str, Any]:
    try:
        items = await list_library_pools()
        return {"items": items, "total": len(items)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# POST /pools — create knowledge-base pool
@router.post("/pools", status_code=201)
async def create_pool(body: LibraryPoolCreate) -> dict[str, Any]:
    try:
        return await create_library_pool(
            body.name,
            description=body.description,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# PATCH /pools/{pool_id}
@router.patch("/pools/{pool_id}")
async def patch_pool(pool_id: UUID, body: LibraryPoolUpdate) -> dict[str, Any]:
    try:
        result = await update_library_pool(
            pool_id,
            body.model_dump(exclude_unset=True),
        )
        if result is None:
            raise HTTPException(status_code=404, detail="Pool not found")
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# DELETE /pools/{pool_id}
@router.delete("/pools/{pool_id}")
async def delete_pool(
    pool_id: UUID,
    delete_papers: bool = Query(False),
) -> dict[str, Any]:
    try:
        result = await delete_pool_record(pool_id, delete_papers=delete_papers)
        if result.get("status") == "missing":
            raise HTTPException(status_code=404, detail="Pool not found")
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# POST /pools/{pool_id}/papers/{paper_id}/copy
@router.post("/pools/{pool_id}/papers/{paper_id}/copy")
async def copy_paper_to_pool(pool_id: UUID, paper_id: UUID) -> dict[str, str]:
    paper = await get_library_paper(paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found")
    return await copy_library_paper(paper_id, pool_id)


# POST /pools/{pool_id}/papers/{paper_id}/move
@router.post("/pools/{pool_id}/papers/{paper_id}/move")
async def move_paper_between_pools(
    pool_id: UUID,
    paper_id: UUID,
    body: dict[str, Any],
) -> dict[str, str]:
    paper = await get_library_paper(paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found")
    target_pool_id = body.get("target_pool_id")
    if not target_pool_id:
        raise HTTPException(status_code=400, detail="target_pool_id is required")
    return await move_library_paper(paper_id, pool_id, UUID(str(target_pool_id)))


# DELETE /pools/{pool_id}/papers/{paper_id}
@router.delete("/pools/{pool_id}/papers/{paper_id}")
async def remove_paper_membership(pool_id: UUID, paper_id: UUID) -> dict[str, str]:
    paper = await get_library_paper(paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found")
    return await remove_paper_from_pool(paper_id, pool_id)


# GET /pools/{pool_id}/duplicates
@router.get("/pools/{pool_id}/duplicates")
async def pool_duplicates(pool_id: UUID) -> dict[str, Any]:
    try:
        items = await get_pool_duplicate_candidates(pool_id)
        return {"items": items, "total": len(items)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


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
            pool_ids=body.get("pool_ids", []),
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
    pool_ids: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    try:
        parsed_pool_ids = _parse_pool_ids(pool_ids)
        papers = await list_library_papers(
            field=field,
            project_tag=project_tag,
            pool_ids=parsed_pool_ids,
            limit=limit,
            offset=offset,
        )
        total = await count_library_papers(
            field=field,
            project_tag=project_tag,
            pool_ids=parsed_pool_ids,
        )
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
        arxiv_id = await _resolve_arxiv_id_for_paper(paper)

        if not arxiv_id:
            raise HTTPException(status_code=400, detail=NO_ARXIV_DETAIL)

        new_paper = await _reingest_library_paper(paper_id, paper, arxiv_id)
        return {
            "status": "completed",
            "paper_id": str(new_paper.get("id")),
            "paper": new_paper,
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("analyze.failed", paper_id=str(paper_id), error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


async def _resolve_arxiv_id_for_paper(paper: dict[str, Any]) -> str | None:
    arxiv_id = paper.get("arxiv_id")
    if arxiv_id:
        return str(arxiv_id)

    title = str(paper.get("title") or "").strip()
    if not title:
        return None

    from libs.adapters.semantic_scholar import SemanticScholarAdapter

    s2: SemanticScholarAdapter | None = None
    try:
        s2 = SemanticScholarAdapter(api_key=os.getenv("S2_API_KEY") or None)
        match = await s2.match_paper(title)
        paper_id = match.get("paperId")
        if not paper_id:
            return None
        full = await s2.get_paper(paper_id)
        external_ids = getattr(full, "external_ids", None) or {}
        if isinstance(external_ids, dict) and external_ids.get("ArXiv"):
            return str(external_ids["ArXiv"])
    except Exception as exc:
        logger.warning("library.resolve_arxiv_failed", title=title, error=str(exc))
    finally:
        if s2 is not None:
            with suppress(Exception):
                await s2.close()
    return None


async def _reingest_library_paper(
    paper_id: UUID,
    paper: dict[str, Any],
    arxiv_id: str,
) -> dict[str, Any]:
    await delete_library_paper(paper_id)

    from apps.worker.agents.paper_ingestion import PaperIngestionPipeline

    pipeline = PaperIngestionPipeline()
    return await pipeline.ingest(
        arxiv_id=arxiv_id,
        title=str(paper.get("title") or ""),
        metadata={
            "authors": paper.get("authors", []),
            "year": paper.get("year"),
            "venue": paper.get("venue", ""),
            "doi": paper.get("doi"),
        },
        source_run_id=paper.get("source_run_id"),
        project_tags=paper.get("project_tags", []),
        pool_ids=paper.get("pool_ids", []),
        is_manually_uploaded=paper.get("is_manually_uploaded", False),
    )


# GET /search?q= — hybrid text+vector search with rerank
@router.get("/search")
async def search_papers(
    q: str = Query(..., min_length=2),
    field: str | None = Query(None),
    pool_ids: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    try:
        from services.library.tools_embedding import embed_paper_chunks, rerank_papers

        parsed_pool_ids = _parse_pool_ids(pool_ids)
        # Vector search
        vectors = await embed_paper_chunks([q])
        candidates: list[dict[str, Any]] = []
        if vectors:
            candidates = await search_library_vectors(
                vectors[0],
                limit=limit * 3,
                field=field,
                pool_ids=parsed_pool_ids,
            )

        # Also do text search and merge
        text_results = await search_library_text(
            q,
            limit=limit,
            pool_ids=parsed_pool_ids,
        )
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
        text_results = await search_library_text(
            q,
            limit=limit,
            pool_ids=_parse_pool_ids(pool_ids),
        )
        return {"items": text_results, "total": len(text_results)}


# GET /search/titles?q= — fast ILIKE for seed paper picker
@router.get("/search/titles")
async def search_titles(
    q: str = Query(..., min_length=1),
    pool_ids: str | None = Query(None),
    limit: int = Query(10, ge=1, le=50),
) -> dict[str, Any]:
    results = await search_library_text(
        q,
        limit=limit,
        pool_ids=_parse_pool_ids(pool_ids),
    )
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
            pool_ids=body.get("pool_ids", []),
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
    pool_ids: str = Form(""),
) -> dict[str, Any]:
    """Upload LaTeX source archive with full deep analysis + RAG indexing."""
    from services.library.tools_storage import ensure_library_dirs, UPLOADS_DIR
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
            try:
                _safe_extract_archive(upload_path, extract_dir)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            except (tarfile.TarError, EOFError, gzip.BadGzipFile, zlib.error) as exc:
                raise HTTPException(
                    status_code=400, detail=INVALID_ARCHIVE_DETAIL
                ) from exc
        elif filename.endswith(".gz"):
            try:
                with gzip.open(str(upload_path), "rb") as gz_in:
                    (extract_dir / filename.replace(".gz", "")).write_bytes(
                        gz_in.read()
                    )
            except (gzip.BadGzipFile, EOFError, zlib.error) as exc:
                raise HTTPException(
                    status_code=400, detail=INVALID_ARCHIVE_DETAIL
                ) from exc
        elif filename.endswith(".zip"):
            try:
                _safe_extract_archive(upload_path, extract_dir)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            except zipfile.BadZipFile as exc:
                raise HTTPException(
                    status_code=400, detail=INVALID_ARCHIVE_DETAIL
                ) from exc
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
            pool_ids=_parse_pool_ids(pool_ids),
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
