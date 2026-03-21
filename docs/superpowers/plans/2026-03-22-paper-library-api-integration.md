# Paper Library API & Mode Integration — Implementation Plan (Plan B of 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Library CRUD API, vector+text hybrid search, library_prefetch, and research mode integration — making the library functional end-to-end from backend perspective.

**Architecture:** FastAPI router `apps/api/routes_library.py` provides CRUD and search endpoints. `services/library/prefetch.py` implements library_prefetch using vector search + rerank. Runner injects library_seeds into mode graph state before execution. Mode nodes skip re-reading papers found in library.

**Tech Stack:** FastAPI, asyncpg, pgvector (1024-dim cosine), Tongyi embedding+rerank, Pydantic v2

**Depends on:** Plan A (complete) — DB tables, tool functions, PaperTagAgent exist

---

## File Structure

```
apps/api/routes_library.py              — Library CRUD + search API router
services/library/prefetch.py            — library_prefetch function
apps/worker/runner.py                   — Modified: call prefetch before mode graph
apps/worker/modes/base.py               — Modified: add library_seeds to ModeGraphState
apps/worker/modes/frontier.py           — Modified: use library_seeds in candidate_retrieval
tests/test_library_api.py               — API endpoint tests (mocked)
tests/test_library_prefetch.py          — Prefetch function tests (mocked)
```

---

### Task 1: Library API Router

**Files:**
- Create: `apps/api/routes_library.py`
- Modify: `apps/api/main.py` — register router
- Create: `tests/test_library_api.py`

**Endpoints to implement:**

```
POST   /api/v1/library/papers              — Add paper to library
GET    /api/v1/library/papers              — List papers (with field/project_tag filters)
GET    /api/v1/library/papers/{id}         — Get single paper with analysis
DELETE /api/v1/library/papers/{id}         — Remove paper from library
PATCH  /api/v1/library/papers/{id}         — Update tags/project_tags
POST   /api/v1/library/papers/{id}/analyze — Trigger Level 2 deep analysis (stub for Plan C)
GET    /api/v1/library/search?q=...        — Hybrid text+vector search with rerank
GET    /api/v1/library/search/titles?q=... — Fast title ILIKE for seed paper picker
GET    /api/v1/library/stats               — Paper count, chunk count, field list
POST   /api/v1/library/upload              — Upload PDF or arXiv ID
```

**Implementation pattern:**

```python
from fastapi import APIRouter, HTTPException, UploadFile, File, Query
from uuid import UUID
from services.library.tools_db import (
    insert_library_paper, get_library_paper, list_library_papers,
    delete_library_paper, update_library_paper,
    search_library_vectors, search_library_text,
    count_library_papers, count_library_chunks,
)
from services.library.tools_embedding import embed_paper_chunks, rerank_papers

router = APIRouter(prefix="/api/v1/library", tags=["library"])
```

For `POST /papers` (add from research run):
1. Accept `{title, arxiv_id?, doi?, source_run_id?, keywords?, methods?, summary_json?, project_tags?}`
2. Call `insert_library_paper(data)`
3. If paper has sections in summary_json, call `embed_paper_chunks` then `insert_library_chunks`
4. Return created paper

For `GET /search?q=`:
1. Call `embed_paper_chunks([query])` to get query vector
2. Call `search_library_vectors(query_vec, limit*3)` for semantic matches
3. Call `rerank_papers(query, [titles], top_n=limit)` to rank results
4. Return reranked papers

For `GET /search/titles?q=`:
1. Call `search_library_text(query, limit)` — ILIKE on title
2. Return matches (fast, for typeahead)

For `POST /upload`:
1. Accept arXiv ID string or PDF file upload
2. If arXiv ID: download source, parse LaTeX, run PaperTagAgent, insert
3. If PDF: save to /data/, parse via GROBID, run PaperTagAgent, insert
4. Return created paper

**Tests** (mock DB): test each endpoint returns correct status code and structure.

- [ ] **Step 1: Write tests**
- [ ] **Step 2: Implement router**
- [ ] **Step 3: Register router in main.py**: `from apps.api.routes_library import router as library_router; app.include_router(library_router)`
- [ ] **Step 4: Run tests — verify pass**
- [ ] **Step 5: Commit**

---

### Task 2: Library Prefetch Function

**Files:**
- Create: `services/library/prefetch.py`
- Create: `tests/test_library_prefetch.py`

**Function:**

```python
async def library_prefetch(
    topic: str,
    keywords: list[str],
    limit: int = 10,
) -> list[dict]:
    """
    Search library for papers relevant to a research query.
    Uses vector search + rerank. Returns paper dicts with cached summaries.
    """
    from services.library.tools_embedding import embed_paper_chunks, rerank_papers
    from services.library.tools_db import search_library_vectors, count_library_papers

    # Skip if library is empty
    paper_count = await count_library_papers()
    if paper_count == 0:
        return []

    # 1. Embed the query
    query_text = f"{topic} {' '.join(keywords)}"
    vectors = await embed_paper_chunks([query_text])
    if not vectors:
        return []

    # 2. Vector search
    candidates = await search_library_vectors(vectors[0], limit=limit * 3)
    if not candidates:
        return []

    # 3. Rerank by title + abstract
    titles = [c.get("title", "") for c in candidates]
    reranked = await rerank_papers(query_text, titles, top_n=limit)

    # 4. Map reranked results back to candidates
    results = []
    for r in reranked:
        idx = r.get("index", 0)
        if idx < len(candidates):
            paper = candidates[idx]
            paper["relevance_score"] = r.get("relevance_score", 0)
            paper["source"] = "library"
            results.append(paper)

    return results
```

**Tests** (mock embedding + DB):
- Returns empty list when library has 0 papers
- Returns papers with relevance_score when library has matches
- Respects limit parameter

- [ ] **Step 1: Write tests**
- [ ] **Step 2: Implement function**
- [ ] **Step 3: Run tests — verify pass**
- [ ] **Step 4: Commit**

---

### Task 3: Add library_seeds to ModeGraphState

**Files:**
- Modify: `apps/worker/modes/base.py` — add `library_seeds` field to `ModeGraphState`

Add after existing fields:

```python
    # Library integration
    library_seeds: list[dict[str, Any]] = Field(default_factory=list)
```

- [ ] **Step 1: Add field**
- [ ] **Step 2: Verify syntax + tests pass**
- [ ] **Step 3: Commit**

---

### Task 4: Inject library_prefetch into Runner

**Files:**
- Modify: `apps/worker/runner.py` — call prefetch before `_run_mode_graph`

In `_execute_run`, after extracting `topic`, `keywords`, etc., and before calling `_run_mode_graph`:

```python
            # ── Library Prefetch ──
            try:
                from services.library.prefetch import library_prefetch
                library_seeds = await library_prefetch(topic, keywords, limit=10)
                if library_seeds:
                    from apps.worker.modes.base import emit_progress
                    await emit_progress(run_id, "library_prefetch", "matched",
                                        f"Found {len(library_seeds)} relevant papers in library")
            except Exception as exc:
                library_seeds = []
                logger.debug("library_prefetch_skipped", error=str(exc))
```

Then pass `library_seeds` to initial state in `_run_mode_graph`.

- [ ] **Step 1: Add prefetch call in _execute_run**
- [ ] **Step 2: Pass library_seeds to ModeGraphState initial state**
- [ ] **Step 3: Verify tests pass**
- [ ] **Step 4: Commit**

---

### Task 5: Use library_seeds in Frontier Mode

**Files:**
- Modify: `apps/worker/modes/frontier.py` — in `candidate_retrieval`, add library seeds to candidates and skip re-reading them in `deep_reading`

In `candidate_retrieval`, before the search call:

```python
    # ── Library seeds: add as priority candidates ──
    library_ids = []
    for seed in state.library_seeds:
        pid = seed.get("paper_id") or seed.get("id")
        if pid and str(pid) not in existing_ids:
            library_ids.append(str(pid))
            existing_ids.add(str(pid))
    if library_ids:
        await emit_progress(state.run_id, "candidate_retrieval", "library_seeds",
                            f"Added {len(library_ids)} papers from library (skipping re-analysis)")
```

In `deep_reading`, skip papers that are from library (their summaries are already in context_bundle):

```python
    # Skip library papers (already have cached summaries)
    library_paper_ids = {str(s.get("paper_id") or s.get("id")) for s in state.library_seeds}
    papers_to_read = [pid for pid in papers_to_read if pid not in library_paper_ids]

    # Add library paper summaries directly to context
    for seed in state.library_seeds:
        if seed.get("summary_json"):
            summaries.append(seed["summary_json"])
```

- [ ] **Step 1: Add library seeds in candidate_retrieval**
- [ ] **Step 2: Skip library papers in deep_reading + inject cached summaries**
- [ ] **Step 3: Verify syntax + tests pass**
- [ ] **Step 4: Commit**

---

## Summary

| Task | What | Files |
|------|------|-------|
| 1 | Library API Router (10 endpoints) | 3 files |
| 2 | Library Prefetch | 2 files |
| 3 | ModeGraphState.library_seeds | 1 file modified |
| 4 | Runner prefetch injection | 1 file modified |
| 5 | Frontier mode integration | 1 file modified |
| **Total** | | **8 files** |

After this plan, the library is fully functional from backend perspective. Plan C adds the frontend.
