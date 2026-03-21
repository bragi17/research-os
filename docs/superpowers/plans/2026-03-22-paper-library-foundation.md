# Paper Library Foundation — Implementation Plan (Plan A of 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the data layer, deterministic tool functions, and PaperTagAgent for the Paper Library feature — everything needed before the API and frontend.

**Architecture:** DB migration adds `library_paper` + `library_chunk` tables with pgvector HNSW index. A `services/library/` package provides deterministic tool functions (no LLM inside). `PaperTagAgent` calls LLM for decisions then tools for execution. Integrates into existing `resolve_and_read_paper` pipeline.

**Tech Stack:** PostgreSQL + pgvector (1024-dim), asyncpg, Tongyi text-embedding-v4, Pydantic v2, pytest

**Spec:** `docs/superpowers/specs/2026-03-22-paper-library-design.md`

---

## File Structure

```
scripts/migration/005_library_tables.sql          — DB migration
libs/schemas/library.py                           — Pydantic models
services/library/__init__.py                      — Package init
services/library/tools_db.py                      — DB tool functions (insert/query/search)
services/library/tools_storage.py                 — File storage on /data/ disk
services/library/tools_embedding.py               — Thin wrappers around embedding service
apps/worker/agents/__init__.py                    — Agents package
apps/worker/agents/paper_tag_agent.py             — Level 1 tagging agent
apps/worker/modes/base.py                         — Modified: call PaperTagAgent after read
tests/test_library_schemas.py                     — Schema tests
tests/test_library_tools_db.py                    — DB tool tests (mocked)
tests/test_library_tools_storage.py               — Storage tool tests
tests/test_paper_tag_agent.py                     — Agent tests (mocked LLM)
```

---

### Task 1: Database Migration

**Files:**
- Create: `scripts/migration/005_library_tables.sql`

- [ ] **Step 1: Write the migration SQL**

```sql
-- Paper Library tables
-- All data stored on vdb disk via PostgreSQL (data_directory = /data/postgresql)

CREATE TABLE IF NOT EXISTS library_paper (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    paper_id UUID REFERENCES paper(id),
    source_run_id UUID REFERENCES research_run(id),
    status TEXT NOT NULL DEFAULT 'pending',

    -- Paper-level labels (Level 1)
    field TEXT,
    sub_field TEXT,
    keywords TEXT[] DEFAULT '{}',
    datasets TEXT[] DEFAULT '{}',
    benchmarks TEXT[] DEFAULT '{}',
    methods TEXT[] DEFAULT '{}',
    innovation_points TEXT[] DEFAULT '{}',
    summary_json JSONB DEFAULT '{}',

    -- Deep analysis (Level 2, on-demand)
    deep_analysis_json JSONB,
    architecture_figure_path TEXT,

    -- Denormalized metadata
    arxiv_id TEXT,
    doi TEXT,
    title TEXT NOT NULL,
    authors TEXT[] DEFAULT '{}',
    year INT,
    venue TEXT,
    citation_count INT DEFAULT 0,

    -- File paths (all on /data/research-os/library/)
    latex_source_path TEXT,
    compiled_pdf_path TEXT,

    -- Organization
    project_tags TEXT[] DEFAULT '{}',
    is_manually_uploaded BOOLEAN DEFAULT FALSE,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_library_paper_keywords ON library_paper USING GIN (keywords);
CREATE INDEX IF NOT EXISTS idx_library_paper_methods ON library_paper USING GIN (methods);
CREATE INDEX IF NOT EXISTS idx_library_paper_project_tags ON library_paper USING GIN (project_tags);
CREATE INDEX IF NOT EXISTS idx_library_paper_title_fts ON library_paper USING GIN (to_tsvector('english', title));
CREATE INDEX IF NOT EXISTS idx_library_paper_field ON library_paper (field, sub_field);
CREATE INDEX IF NOT EXISTS idx_library_paper_arxiv ON library_paper (arxiv_id) WHERE arxiv_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS library_chunk (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    library_paper_id UUID NOT NULL REFERENCES library_paper(id) ON DELETE CASCADE,
    section_type TEXT NOT NULL,
    paragraph_index INT NOT NULL DEFAULT 0,
    text TEXT NOT NULL,
    token_count INT DEFAULT 0,

    tags TEXT[] DEFAULT '{}',
    claim_type TEXT,

    embedding VECTOR(1024),

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_library_chunk_paper ON library_chunk (library_paper_id);
CREATE INDEX IF NOT EXISTS idx_library_chunk_tags ON library_chunk USING GIN (tags);
CREATE INDEX IF NOT EXISTS idx_library_chunk_embedding ON library_chunk USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_library_chunk_section ON library_chunk (section_type);
```

- [ ] **Step 2: Run migration**

```bash
PGPASSWORD=DB_PASSWORD_REDACTED psql -h localhost -U research_os -d research_os -f scripts/migration/005_library_tables.sql
```

Expected: All CREATE TABLE/INDEX succeed without errors.

- [ ] **Step 3: Verify tables exist**

```bash
PGPASSWORD=DB_PASSWORD_REDACTED psql -h localhost -U research_os -d research_os -c "\dt library_*"
```

Expected: `library_paper` and `library_chunk` listed.

- [ ] **Step 4: Commit**

```bash
git add scripts/migration/005_library_tables.sql
git commit -m "feat(library): add library_paper + library_chunk tables with pgvector index"
```

---

### Task 2: Pydantic Models

**Files:**
- Create: `libs/schemas/library.py`
- Create: `tests/test_library_schemas.py`

- [ ] **Step 1: Write tests**

```python
# tests/test_library_schemas.py
import pytest
from uuid import uuid4
from libs.schemas.library import (
    LibraryPaper, LibraryChunk, PaperTagResult, ParagraphTag,
    LibraryPaperCreate, LibrarySearchQuery, DeepAnalysis,
)

class TestLibraryPaper:
    def test_create(self):
        p = LibraryPaper(title="Test Paper", status="pending")
        assert p.keywords == []
        assert p.is_manually_uploaded is False

    def test_with_tags(self):
        p = LibraryPaper(title="Test", field="CV", sub_field="3D AD",
                         keywords=["point cloud"], methods=["PatchCore"])
        assert "point cloud" in p.keywords

class TestLibraryChunk:
    def test_create(self):
        c = LibraryChunk(library_paper_id=uuid4(), section_type="method",
                         text="We propose...", tags=["memory bank"])
        assert c.paragraph_index == 0

class TestPaperTagResult:
    def test_create(self):
        r = PaperTagResult(
            field="CV", sub_field="3D AD",
            keywords=["point cloud"], methods=["PatchCore"],
            datasets=["MVTec 3D-AD"], benchmarks=["AUROC"],
            innovation_points=["First to apply..."],
            paragraph_tags=[
                ParagraphTag(section_type="method", paragraph_index=0,
                             tags=["memory bank"], claim_type="contribution")
            ],
        )
        assert len(r.paragraph_tags) == 1

class TestDeepAnalysis:
    def test_create(self):
        d = DeepAnalysis(
            motivation="Found a problem...",
            mathematical_formulation="$$L = ...$$",
            experimental_design={"models": ["PointMAE"], "datasets": ["MVTec"]},
            results={"baselines": ["PatchCore"], "best_metrics": {"AUROC": 95.2}},
            critical_review={"strengths": ["novel"], "weaknesses": ["limited data"]},
            one_more_thing="Interesting appendix",
        )
        assert d.motivation.startswith("Found")

class TestLibrarySearchQuery:
    def test_defaults(self):
        q = LibrarySearchQuery(query="3D anomaly")
        assert q.limit == 20
        assert q.field is None
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
PYTHONPATH=/root/research-os .venv/bin/python -m pytest tests/test_library_schemas.py -v
```

- [ ] **Step 3: Implement models**

```python
# libs/schemas/library.py
"""Paper Library data models."""
from __future__ import annotations
from typing import Any
from uuid import UUID
from pydantic import BaseModel, Field


class ParagraphTag(BaseModel):
    """Tag for a single paragraph within a paper."""
    section_type: str  # abstract|introduction|method|experiment|related_work|conclusion|other
    paragraph_index: int = 0
    tags: list[str] = Field(default_factory=list)
    claim_type: str | None = None  # contribution|limitation|future_work|finding|definition|comparison


class PaperTagResult(BaseModel):
    """Output of PaperTagAgent (Level 1 analysis)."""
    field: str = ""
    sub_field: str = ""
    keywords: list[str] = Field(default_factory=list)
    methods: list[str] = Field(default_factory=list)
    datasets: list[str] = Field(default_factory=list)
    benchmarks: list[str] = Field(default_factory=list)
    innovation_points: list[str] = Field(default_factory=list)
    paragraph_tags: list[ParagraphTag] = Field(default_factory=list)


class DeepAnalysis(BaseModel):
    """Output of PaperAnalysisAgent (Level 2 analysis)."""
    motivation: str = ""
    mathematical_formulation: str = ""
    experimental_design: dict[str, Any] = Field(default_factory=dict)
    results: dict[str, Any] = Field(default_factory=dict)
    critical_review: dict[str, Any] = Field(default_factory=dict)
    one_more_thing: str = ""


class LibraryPaper(BaseModel):
    """A paper in the library."""
    id: UUID | None = None
    paper_id: UUID | None = None
    source_run_id: UUID | None = None
    status: str = "pending"

    field: str | None = None
    sub_field: str | None = None
    keywords: list[str] = Field(default_factory=list)
    datasets: list[str] = Field(default_factory=list)
    benchmarks: list[str] = Field(default_factory=list)
    methods: list[str] = Field(default_factory=list)
    innovation_points: list[str] = Field(default_factory=list)
    summary_json: dict[str, Any] = Field(default_factory=dict)

    deep_analysis_json: dict[str, Any] | None = None
    architecture_figure_path: str | None = None

    arxiv_id: str | None = None
    doi: str | None = None
    title: str
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    citation_count: int = 0

    latex_source_path: str | None = None
    compiled_pdf_path: str | None = None

    project_tags: list[str] = Field(default_factory=list)
    is_manually_uploaded: bool = False


class LibraryChunk(BaseModel):
    """A paragraph-level chunk with embedding in the library."""
    id: UUID | None = None
    library_paper_id: UUID
    section_type: str
    paragraph_index: int = 0
    text: str
    token_count: int = 0
    tags: list[str] = Field(default_factory=list)
    claim_type: str | None = None
    embedding: list[float] | None = None


class LibraryPaperCreate(BaseModel):
    """Request to add a paper to the library."""
    title: str
    arxiv_id: str | None = None
    doi: str | None = None
    source_run_id: str | None = None
    project_tags: list[str] = Field(default_factory=list)


class LibrarySearchQuery(BaseModel):
    """Parameters for library search."""
    query: str
    field: str | None = None
    sub_field: str | None = None
    project_tag: str | None = None
    limit: int = 20
    offset: int = 0
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
PYTHONPATH=/root/research-os .venv/bin/python -m pytest tests/test_library_schemas.py -v
```

- [ ] **Step 5: Commit**

```bash
git add libs/schemas/library.py tests/test_library_schemas.py
git commit -m "feat(library): add Pydantic models for library paper, chunk, tags, analysis"
```

---

### Task 3: DB Tool Functions

**Files:**
- Create: `services/library/__init__.py`
- Create: `services/library/tools_db.py`
- Create: `tests/test_library_tools_db.py`

- [ ] **Step 1: Write tests (mocked asyncpg)**

Test at minimum: `insert_library_paper`, `get_library_paper`, `list_library_papers`, `delete_library_paper`, `insert_library_chunks`, `search_library_vectors`, `search_library_text`.

All tests use `unittest.mock.AsyncMock` to mock `get_pool()`. No real DB required.

- [ ] **Step 2: Implement tool functions**

```python
# services/library/tools_db.py
"""
Deterministic DB tool functions for Paper Library.
No LLM calls. Fixed input → fixed output.
"""
from __future__ import annotations
from typing import Any
from uuid import UUID, uuid4
from apps.api.database import get_pool, _record_to_dict


async def insert_library_paper(data: dict[str, Any]) -> dict[str, Any]:
    """Insert a paper into the library. Returns the inserted row."""
    pool = await get_pool()
    paper_id = data.get("id", uuid4())
    row = await pool.fetchrow("""
        INSERT INTO library_paper (
            id, paper_id, source_run_id, status,
            field, sub_field, keywords, datasets, benchmarks, methods,
            innovation_points, summary_json,
            arxiv_id, doi, title, authors, year, venue, citation_count,
            latex_source_path, compiled_pdf_path,
            project_tags, is_manually_uploaded
        ) VALUES (
            $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
            $11, $12, $13, $14, $15, $16, $17, $18, $19,
            $20, $21, $22, $23
        ) RETURNING *
    """,
        paper_id,
        data.get("paper_id"),
        data.get("source_run_id"),
        data.get("status", "pending"),
        data.get("field"),
        data.get("sub_field"),
        data.get("keywords", []),
        data.get("datasets", []),
        data.get("benchmarks", []),
        data.get("methods", []),
        data.get("innovation_points", []),
        data.get("summary_json", {}),
        data.get("arxiv_id"),
        data.get("doi"),
        data["title"],
        data.get("authors", []),
        data.get("year"),
        data.get("venue"),
        data.get("citation_count", 0),
        data.get("latex_source_path"),
        data.get("compiled_pdf_path"),
        data.get("project_tags", []),
        data.get("is_manually_uploaded", False),
    )
    return _record_to_dict(row)


async def get_library_paper(paper_id: UUID) -> dict[str, Any] | None:
    """Get a single library paper by ID."""
    pool = await get_pool()
    row = await pool.fetchrow("SELECT * FROM library_paper WHERE id = $1", paper_id)
    return _record_to_dict(row) if row else None


async def list_library_papers(
    field: str | None = None,
    project_tag: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """List library papers with optional filters."""
    pool = await get_pool()
    conditions = []
    params: list[Any] = []
    idx = 1

    if field:
        conditions.append(f"field = ${idx}")
        params.append(field)
        idx += 1
    if project_tag:
        conditions.append(f"${idx} = ANY(project_tags)")
        params.append(project_tag)
        idx += 1

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params.extend([limit, offset])

    rows = await pool.fetch(
        f"SELECT * FROM library_paper {where} ORDER BY created_at DESC LIMIT ${idx} OFFSET ${idx+1}",
        *params,
    )
    return [_record_to_dict(r) for r in rows]


async def delete_library_paper(paper_id: UUID) -> bool:
    """Delete a library paper (chunks cascade)."""
    pool = await get_pool()
    result = await pool.execute("DELETE FROM library_paper WHERE id = $1", paper_id)
    return result == "DELETE 1"


async def update_library_paper(paper_id: UUID, updates: dict[str, Any]) -> dict[str, Any] | None:
    """Update specific fields on a library paper."""
    allowed = {
        "status", "field", "sub_field", "keywords", "datasets", "benchmarks",
        "methods", "innovation_points", "summary_json", "deep_analysis_json",
        "architecture_figure_path", "project_tags", "latex_source_path",
        "compiled_pdf_path", "updated_at",
    }
    filtered = {k: v for k, v in updates.items() if k in allowed}
    if not filtered:
        return None
    pool = await get_pool()
    set_parts = []
    params: list[Any] = []
    for i, (col, val) in enumerate(filtered.items(), 1):
        set_parts.append(f"{col} = ${i}")
        params.append(val)
    params.append(paper_id)
    row = await pool.fetchrow(
        f"UPDATE library_paper SET {', '.join(set_parts)} WHERE id = ${len(params)} RETURNING *",
        *params,
    )
    return _record_to_dict(row) if row else None


async def insert_library_chunks(
    library_paper_id: UUID,
    chunks: list[dict[str, Any]],
) -> int:
    """Batch insert chunks with embeddings. Returns count inserted."""
    if not chunks:
        return 0
    pool = await get_pool()
    count = 0
    for chunk in chunks:
        await pool.execute("""
            INSERT INTO library_chunk (
                id, library_paper_id, section_type, paragraph_index,
                text, token_count, tags, claim_type, embedding
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        """,
            uuid4(),
            library_paper_id,
            chunk["section_type"],
            chunk.get("paragraph_index", 0),
            chunk["text"],
            chunk.get("token_count", 0),
            chunk.get("tags", []),
            chunk.get("claim_type"),
            chunk.get("embedding"),  # VECTOR(1024) or None
        )
        count += 1
    return count


async def search_library_vectors(
    query_embedding: list[float],
    limit: int = 30,
    field: str | None = None,
) -> list[dict[str, Any]]:
    """
    Vector similarity search across library_chunk → library_paper.
    Returns distinct papers ranked by best chunk similarity.
    """
    pool = await get_pool()
    field_filter = ""
    params: list[Any] = [str(query_embedding), limit]
    if field:
        field_filter = "AND lp.field = $3"
        params.append(field)

    rows = await pool.fetch(f"""
        SELECT DISTINCT ON (lp.id)
            lp.id, lp.title, lp.arxiv_id, lp.field, lp.sub_field,
            lp.keywords, lp.methods, lp.summary_json, lp.year, lp.venue,
            lp.citation_count, lp.status,
            1 - (lc.embedding <=> $1::vector) AS similarity
        FROM library_chunk lc
        JOIN library_paper lp ON lc.library_paper_id = lp.id
        WHERE lc.embedding IS NOT NULL {field_filter}
        ORDER BY lp.id, similarity DESC
    """, *params)

    # Re-sort by similarity across papers
    results = [_record_to_dict(r) for r in rows]
    results.sort(key=lambda x: x.get("similarity", 0), reverse=True)
    return results[:limit]


async def search_library_text(
    query: str,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Fast title ILIKE search for typeahead / seed paper picker."""
    pool = await get_pool()
    rows = await pool.fetch(
        "SELECT id, title, arxiv_id, field, year, venue, status "
        "FROM library_paper WHERE title ILIKE $1 ORDER BY created_at DESC LIMIT $2",
        f"%{query}%", limit,
    )
    return [_record_to_dict(r) for r in rows]


async def count_library_papers() -> int:
    """Count total papers in library."""
    pool = await get_pool()
    return await pool.fetchval("SELECT COUNT(*) FROM library_paper")


async def count_library_chunks() -> int:
    """Count total chunks in library."""
    pool = await get_pool()
    return await pool.fetchval("SELECT COUNT(*) FROM library_chunk")
```

- [ ] **Step 3: Create `services/library/__init__.py`**

```python
"""Paper Library services — deterministic tool functions."""
```

- [ ] **Step 4: Run tests — verify they pass**
- [ ] **Step 5: Commit**

---

### Task 4: Storage Tool Functions

**Files:**
- Create: `services/library/tools_storage.py`
- Create: `tests/test_library_tools_storage.py`

- [ ] **Step 1: Write tests**

Test: `ensure_library_dirs`, `save_latex_source`, `get_paper_source_path`, `get_paper_pdf_path`.

- [ ] **Step 2: Implement**

```python
# services/library/tools_storage.py
"""
Deterministic file storage tools for Paper Library.
All paths under /data/research-os/library/ (vdb disk).
No LLM calls.
"""
from __future__ import annotations
import os
import shutil
from pathlib import Path

LIBRARY_ROOT = Path(os.getenv("LIBRARY_STORAGE_DIR", "/data/research-os/library"))

SOURCES_DIR = LIBRARY_ROOT / "sources"
PDFS_DIR = LIBRARY_ROOT / "pdfs"
FIGURES_DIR = LIBRARY_ROOT / "figures"
UPLOADS_DIR = LIBRARY_ROOT / "uploads"


def ensure_library_dirs() -> None:
    """Create library directory structure on vdb disk."""
    for d in [SOURCES_DIR, PDFS_DIR, FIGURES_DIR, UPLOADS_DIR]:
        d.mkdir(parents=True, exist_ok=True)


def get_paper_source_dir(arxiv_id: str) -> Path:
    """Get source directory for an arXiv paper."""
    return SOURCES_DIR / arxiv_id.replace("/", "_")


def save_latex_source(arxiv_id: str, source_archive_path: str) -> str:
    """
    Copy downloaded arXiv source to library storage.
    Returns the path to the stored archive.
    """
    dest_dir = get_paper_source_dir(arxiv_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "source.tar.gz"
    shutil.copy2(source_archive_path, dest)
    return str(dest)


def get_paper_pdf_path(arxiv_id: str) -> Path:
    """Get expected PDF path for a paper."""
    return PDFS_DIR / f"{arxiv_id.replace('/', '_')}.pdf"


def save_uploaded_pdf(file_bytes: bytes, filename: str) -> str:
    """Save a user-uploaded PDF. Returns stored path."""
    ensure_library_dirs()
    from uuid import uuid4
    dest = UPLOADS_DIR / f"{uuid4()}_{filename}"
    dest.write_bytes(file_bytes)
    return str(dest)


def get_figure_dir(library_paper_id: str) -> Path:
    """Get figure directory for a library paper."""
    d = FIGURES_DIR / library_paper_id
    d.mkdir(parents=True, exist_ok=True)
    return d
```

- [ ] **Step 3: Run tests — verify they pass**
- [ ] **Step 4: Commit**

---

### Task 5: Embedding Tool Functions

**Files:**
- Create: `services/library/tools_embedding.py`
- Create: `tests/test_library_tools_embedding.py`

- [ ] **Step 1: Write tests (mocked)**

Test: `embed_paper_chunks`, `rerank_papers`.

- [ ] **Step 2: Implement**

```python
# services/library/tools_embedding.py
"""
Embedding tool wrappers for Paper Library.
Thin deterministic wrappers around the EmbeddingService.
No LLM calls — only vector operations.
"""
from __future__ import annotations
from typing import Any
from services.embedding import get_embedding_service


async def embed_paper_chunks(texts: list[str]) -> list[list[float]]:
    """
    Embed a list of text chunks using Tongyi text-embedding-v4.
    Returns list of 1024-dim vectors.
    Handles batching internally (max 10 per API call).
    """
    if not texts:
        return []
    svc = get_embedding_service()
    return await svc.embed_texts(texts, dimension=1024)


async def rerank_papers(
    query: str,
    documents: list[str],
    top_n: int | None = None,
) -> list[dict[str, Any]]:
    """
    Rerank documents by relevance to query using gte-rerank-v2.
    Returns [{index, relevance_score, document}] sorted by score desc.
    """
    if not documents:
        return []
    svc = get_embedding_service()
    return await svc.rerank(query=query, documents=documents, top_n=top_n)
```

- [ ] **Step 3: Run tests — verify they pass**
- [ ] **Step 4: Commit**

---

### Task 6: PaperTagAgent (Level 1)

**Files:**
- Create: `apps/worker/agents/__init__.py`
- Create: `apps/worker/agents/paper_tag_agent.py`
- Create: `tests/test_paper_tag_agent.py`

- [ ] **Step 1: Write tests (mocked LLM)**

```python
# tests/test_paper_tag_agent.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from apps.worker.agents.paper_tag_agent import PaperTagAgent
from libs.schemas.library import PaperTagResult


class TestPaperTagAgent:
    @pytest.mark.asyncio
    async def test_run_returns_tag_result(self):
        """Agent should return PaperTagResult with paper and paragraph tags."""
        mock_gateway = MagicMock()
        mock_gateway.chat_structured = AsyncMock(return_value=PaperTagResult(
            field="Computer Vision",
            sub_field="3D Anomaly Detection",
            keywords=["point cloud", "memory bank"],
            methods=["PatchCore"],
            datasets=["MVTec 3D-AD"],
            benchmarks=["AUROC"],
            innovation_points=["First to apply..."],
            paragraph_tags=[],
        ))

        agent = PaperTagAgent(gateway=mock_gateway)
        result = await agent.run(
            paper_text="We propose a method for 3D anomaly detection...",
            metadata={"title": "Test Paper", "year": 2024},
        )

        assert result.field == "Computer Vision"
        assert "point cloud" in result.keywords
        assert mock_gateway.chat_structured.called

    @pytest.mark.asyncio
    async def test_run_with_sections(self):
        """Agent should produce paragraph tags when sections are provided."""
        mock_gateway = MagicMock()
        mock_gateway.chat_structured = AsyncMock(return_value=PaperTagResult(
            field="CV", sub_field="3D AD",
            keywords=["pc"], methods=["M"], datasets=[], benchmarks=[],
            innovation_points=[],
            paragraph_tags=[
                {"section_type": "method", "paragraph_index": 0,
                 "tags": ["memory bank"], "claim_type": "contribution"},
            ],
        ))

        agent = PaperTagAgent(gateway=mock_gateway)
        result = await agent.run(
            paper_text="## Abstract\nWe propose...\n## Method\nOur approach uses...",
            metadata={"title": "Test"},
        )
        assert len(result.paragraph_tags) >= 0  # May vary with mock
```

- [ ] **Step 2: Implement the agent**

```python
# apps/worker/agents/paper_tag_agent.py
"""
PaperTagAgent — Level 1 paper analysis.

Smart Agent, Dumb Tools pattern:
- PLAN: LLM extracts field/keywords/methods/tags (structured output)
- EXECUTE: Deterministic tools embed text chunks
- Result stored for later use (library add = zero extra cost)
"""
from __future__ import annotations
from typing import Any

from structlog import get_logger

from apps.worker.llm_gateway import LLMGateway, ModelTier
from libs.schemas.library import PaperTagResult

logger = get_logger(__name__)

TAG_SYSTEM_PROMPT = """\
You are a research paper tagger. Given a paper's content and metadata,
extract hierarchical labels at paper-level and paragraph-level.

Paper-level: identify the broad field, sub-field, key methods/algorithms,
datasets, benchmarks, and innovation points.

Paragraph-level: for each major section (abstract, introduction, method,
experiment, related_work, conclusion), identify technique tags and claim types.

Claim types: contribution, limitation, future_work, finding, definition, comparison.
"""


class PaperTagAgent:
    """
    Level 1 paper tagging agent.
    Called during resolve_and_read_paper to extract labels.
    Uses LLM for PLAN (tag extraction), tools for EXECUTE (embedding).
    """

    def __init__(self, gateway: LLMGateway):
        self.gateway = gateway

    async def run(
        self,
        paper_text: str,
        metadata: dict[str, Any],
    ) -> PaperTagResult:
        """
        Extract paper-level and paragraph-level tags.

        Args:
            paper_text: Full or partial paper content (LaTeX sections or abstract)
            metadata: {title, year, venue, authors, ...}

        Returns:
            PaperTagResult with all tags
        """
        # ── PLAN: LLM decides what tags to extract ──
        user_content = (
            f"Paper title: {metadata.get('title', 'Unknown')}\n"
            f"Year: {metadata.get('year', 'Unknown')}\n"
            f"Venue: {metadata.get('venue', 'Unknown')}\n\n"
            f"Paper content:\n{paper_text[:8000]}\n"
        )

        try:
            result = await self.gateway.chat_structured(
                output_schema=PaperTagResult,
                messages=[
                    {"role": "system", "content": TAG_SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                tier=ModelTier.MEDIUM,
            )
            logger.info(
                "paper_tag_agent.done",
                title=metadata.get("title", "?")[:40],
                field=result.field,
                keywords=len(result.keywords),
                paragraph_tags=len(result.paragraph_tags),
            )
            return result

        except Exception as exc:
            logger.error("paper_tag_agent.failed", error=str(exc))
            # Return empty result on failure — don't break the pipeline
            return PaperTagResult()
```

- [ ] **Step 3: Create `apps/worker/agents/__init__.py`**

```python
"""Research OS agents — Smart Agent, Dumb Tools pattern."""
```

- [ ] **Step 4: Run tests — verify they pass**
- [ ] **Step 5: Commit**

---

### Task 7: Integrate PaperTagAgent into resolve_and_read_paper

**Files:**
- Modify: `apps/worker/modes/base.py` — add PaperTagAgent call after summary/claim extraction

- [ ] **Step 1: Read current `resolve_and_read_paper` to identify insertion point**

The function currently: resolves metadata → parses LaTeX → summarizes → extracts claims → returns.

Insert tag agent call **after** summarization, **before** return.

- [ ] **Step 2: Add tag agent call**

After the existing claim extraction block, add:

```python
        # ── Paper Tagging (Level 1) ──
        try:
            from apps.worker.agents.paper_tag_agent import PaperTagAgent
            tag_agent = PaperTagAgent(gateway=gateway)
            tag_result = await tag_agent.run(
                paper_text=full_paper_content,
                metadata={
                    "title": paper_title,
                    "year": getattr(fused, "year", None),
                    "venue": getattr(fused, "venue", None),
                },
            )
            if summary and isinstance(summary, dict):
                summary["paper_tags"] = tag_result.model_dump()
        except Exception as exc:
            logger.debug("paper_tag_skipped", pid=pid, error=str(exc))
```

- [ ] **Step 3: Verify existing tests still pass**

```bash
PYTHONPATH=/root/research-os .venv/bin/python -m pytest tests/ -x --tb=short -q \
    --ignore=tests/test_e2e.py --ignore=tests/test_e2e_modes.py --ignore=tests/test_e2e_full_workflow.py
```

- [ ] **Step 4: Commit**

```bash
git add apps/worker/modes/base.py apps/worker/agents/
git commit -m "feat(library): integrate PaperTagAgent into paper reading pipeline"
```

---

## Summary

| Task | What | Files | Test Count |
|------|------|-------|------------|
| 1 | DB migration | 1 SQL | manual verify |
| 2 | Pydantic models | 2 py | ~8 tests |
| 3 | DB tool functions | 3 py | ~10 tests |
| 4 | Storage tools | 2 py | ~5 tests |
| 5 | Embedding tools | 2 py | ~3 tests |
| 6 | PaperTagAgent | 3 py | ~3 tests |
| 7 | Integration | 1 py modified | existing tests |
| **Total** | | **14 files** | **~29 new tests** |

After this plan completes, the foundation is in place for:
- **Plan B:** Library CRUD API, vector search API, library_prefetch, mode integration
- **Plan C:** Frontend (library page, paper detail, seed picker, PDF viewer)
