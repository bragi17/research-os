# Paper Library — Feature Design Spec

**Date:** 2026-03-22
**Status:** Approved
**Scope:** Paper Library with multi-level vector index, analysis agents, research mode integration, and frontend UI

---

## 1. Overview

A persistent paper library that stores high-quality papers from research runs with hierarchical vector indexing. Users can search, preview PDFs, and see deep analysis. Papers in the library become "secondary seed papers" for future research runs, reducing online search time and token consumption.

## 2. Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Vector dimension | 1024 (Tongyi text-embedding-v4 default) | Best cost/precision balance |
| PDF preview | Local LaTeX compile (primary) + arXiv PDF link (fallback) | Best quality when source available |
| Analysis trigger | Two-level: light in research, deep on-demand | Balances cost and UX |
| Library scope | Global library + project tags for filtering | Maximizes paper reuse |
| Storage location | All data on `/data/research-os/library/` (vdb disk) | Keep system disk clean |
| Manual upload | Supported via arXiv ID or PDF file | Users bring their own papers |

## 3. Architecture Principle: Smart Agent, Dumb Tools

All agents in this system (and across the project) follow the **plan + execute** pattern:

- **Agent** = LLM-powered decision maker. Plans what to do, routes to tools, interprets results.
- **Tool** = Deterministic function. No LLM inside. Fixed input → fixed output. Pre-defined, tested, reliable.
- **Agent does NOT** generate scripts, write code at runtime, or make tool-internal decisions.
- **Agent DOES** call `plan()` to decide what tools to invoke, then calls tools in sequence, then calls `synthesize()` to interpret results.

### Tool Registry for Paper Library

```
Tools (deterministic, no LLM):
├── tools/arxiv.download_source(arxiv_id) → source_path
├── tools/arxiv.compile_pdf(source_path) → pdf_path
├── tools/latex.parse_to_sections(source_path) → ParsedPaper
├── tools/grobid.parse_pdf(pdf_path) → ParsedPaper
├── tools/embedding.embed_texts(texts[]) → vectors[]
├── tools/embedding.rerank(query, docs[]) → ranked_docs[]
├── tools/db.insert_library_paper(data) → library_paper_id
├── tools/db.insert_library_chunks(paper_id, chunks[]) → count
├── tools/db.search_library_vectors(query_vec, limit) → results[]
├── tools/db.search_library_text(query_str, limit) → results[]
├── tools/storage.save_file(content, path) → full_path
├── tools/storage.read_file(path) → content
└── tools/s2.fetch_paper_metadata(paper_id) → metadata

Agents (LLM-powered, call tools):
├── PaperTagAgent        — Level 1: extract field/keywords/methods/tags per paragraph
├── PaperAnalysisAgent   — Level 2: deep analysis (motivation/math/experiments/review)
├── LibraryPrefetchAgent — Match library papers to a research query
└── Existing mode agents (atlas/frontier/divergent) — consume library_seeds
```

### Agent Execution Pattern

```python
# Example: PaperTagAgent
class PaperTagAgent:
    async def run(self, paper_text: str, metadata: dict) -> TagResult:
        # Step 1: PLAN — LLM decides what to extract
        plan = await self.llm.chat_structured(TagPlan, [
            {"role": "system", "content": TAG_SYSTEM_PROMPT},
            {"role": "user", "content": paper_text[:8000]},
        ])

        # Step 2: EXECUTE — deterministic tools
        sections = tools.latex.parse_to_sections(paper_text)
        embeddings = await tools.embedding.embed_texts(
            [s.text for s in sections]
        )

        # Step 3: SYNTHESIZE — LLM interprets results
        return TagResult(
            paper_level=plan.paper_tags,
            paragraph_level=[
                ParagraphTag(section=s, embedding=e, tags=plan.paragraph_tags[i])
                for i, (s, e) in enumerate(zip(sections, embeddings))
            ],
        )
```

## 4. Data Model

### 4.1 `library_paper` (论文库主表)

```sql
CREATE TABLE library_paper (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    paper_id UUID REFERENCES paper(id),  -- link to existing paper table
    source_run_id UUID REFERENCES research_run(id),  -- which run discovered it
    status TEXT NOT NULL DEFAULT 'pending',  -- pending | light_analyzed | deep_analyzed

    -- Paper-level labels (Level 1 analysis)
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

    -- Metadata (denormalized for fast display)
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

CREATE INDEX idx_library_paper_keywords ON library_paper USING GIN (keywords);
CREATE INDEX idx_library_paper_methods ON library_paper USING GIN (methods);
CREATE INDEX idx_library_paper_project_tags ON library_paper USING GIN (project_tags);
CREATE INDEX idx_library_paper_title ON library_paper USING gin (to_tsvector('english', title));
CREATE INDEX idx_library_paper_field ON library_paper (field, sub_field);
```

### 4.2 `library_chunk` (段落级向量索引)

```sql
CREATE TABLE library_chunk (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    library_paper_id UUID NOT NULL REFERENCES library_paper(id) ON DELETE CASCADE,
    section_type TEXT NOT NULL,  -- abstract|introduction|method|experiment|related_work|conclusion|other
    paragraph_index INT NOT NULL DEFAULT 0,
    text TEXT NOT NULL,
    token_count INT DEFAULT 0,

    -- Paragraph-level labels
    tags TEXT[] DEFAULT '{}',
    claim_type TEXT,  -- contribution|limitation|future_work|finding|definition|comparison

    -- Vector (Tongyi text-embedding-v4, 1024-dim)
    embedding VECTOR(1024),

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_library_chunk_paper ON library_chunk (library_paper_id);
CREATE INDEX idx_library_chunk_tags ON library_chunk USING GIN (tags);
CREATE INDEX idx_library_chunk_embedding ON library_chunk USING hnsw (embedding vector_cosine_ops);
CREATE INDEX idx_library_chunk_section ON library_chunk (section_type);
```

## 5. API Endpoints

### Library CRUD

```
POST   /api/v1/library/papers              — Add paper to library (from run or manual)
POST   /api/v1/library/upload              — Upload PDF / arXiv ID manually
GET    /api/v1/library/papers              — List library papers (with filters)
GET    /api/v1/library/papers/{id}         — Get paper with analysis
DELETE /api/v1/library/papers/{id}         — Remove from library
PATCH  /api/v1/library/papers/{id}         — Update tags / project_tags
POST   /api/v1/library/papers/{id}/analyze — Trigger Level 2 deep analysis
GET    /api/v1/library/papers/{id}/pdf     — Serve compiled PDF or redirect to arXiv
```

### Library Search

```
GET    /api/v1/library/search?q=...        — Text + vector hybrid search with rerank
GET    /api/v1/library/search/titles?q=... — Fast title-only ILIKE search (for seed paper picker)
```

### Library Stats

```
GET    /api/v1/library/stats               — Total papers, fields, chunks indexed
```

## 6. Paper Analysis Agents

### 6.1 PaperTagAgent (Level 1 — during research)

**When**: Called in `resolve_and_read_paper` after summary + claim extraction.

**Input**: Parsed paper text (LaTeX sections) + existing summary.

**LLM call** (single structured output):

```
System: You are a research paper tagger. Given a paper's content,
extract hierarchical labels at paper-level and paragraph-level.

Output schema: PaperTagResult {
  field: str
  sub_field: str
  keywords: str[]          — methods + techniques + concepts
  methods: str[]           — specific methods/algorithms used
  datasets: str[]
  benchmarks: str[]
  innovation_points: str[] — what's novel about this paper
  paragraph_tags: [{
    section_type: str      — abstract|introduction|method|experiment|...
    paragraph_index: int
    tags: str[]            — fine-grained technique tags
    claim_type: str        — contribution|limitation|future_work|finding
  }]
}
```

**Tool calls** (deterministic, after LLM):
1. `tools.embedding.embed_texts(paragraph_texts)` → vectors
2. Results stored in `ModeGraphState.context_bundle["paper_tags"][paper_id]`

**Cost**: ~500 tokens per paper (incremental over existing summary call).

### 6.2 PaperAnalysisAgent (Level 2 — on demand)

**When**: User clicks "View Details" on a paper in results.

**Input**: Full LaTeX source text (up to 30k tokens).

**LLM call** (HIGH tier, single structured output):

```
System: You are a senior research paper reviewer. Analyze this paper
comprehensively. Support LaTeX math notation in your output.

Output schema: DeepAnalysis {
  motivation: str              — 研究动机与 significance
  mathematical_formulation: str — LaTeX 数学公式与推导
  experimental_design: {
    models: str[]
    datasets: str[]
    hyperparams: dict
    reproducibility_notes: str
  }
  results: {
    baselines: str[]
    best_metrics: dict
    key_insights: str[]
  }
  critical_review: {
    strengths: str[]
    weaknesses: str[]
    improvements: str[]
  }
  one_more_thing: str
}
```

**Tool calls** (after LLM):
1. `tools.storage.save_file(analysis_json, path)` → persist
2. `tools.db.update_library_paper(id, {deep_analysis_json, status: "deep_analyzed"})` → update DB

**Cost**: ~2000-4000 tokens per paper (one-time).

## 7. Research Mode Integration

### 7.1 Library Prefetch (new step before all modes)

```
runner._execute_run():
    ...
    # [NEW] Before running mode graph
    library_seeds = await library_prefetch(topic, keywords, limit=10)
    initial_state.library_seeds = library_seeds

    result_state = await self._run_mode_graph(...)
```

`library_prefetch` implementation:

```python
async def library_prefetch(topic, keywords, limit=10):
    # Tool: embed query
    query_text = f"{topic} {' '.join(keywords)}"
    query_vec = await tools.embedding.embed_texts([query_text])

    # Tool: vector search in library_chunk
    candidates = await tools.db.search_library_vectors(query_vec[0], limit=limit*3)

    # Tool: rerank by title+abstract
    titles = [c["title"] for c in candidates]
    reranked = await tools.embedding.rerank(query_text, titles, top_n=limit)

    # Return matched papers with their cached summaries
    return [{"paper_id": c["id"], "title": c["title"],
             "summary": c["summary_json"], "keywords": c["keywords"],
             "methods": c["methods"], "source": "library"}
            for c in reranked_candidates]
```

### 7.2 Mode-specific usage of library_seeds

**Frontier** (`candidate_retrieval`):
- Library seeds added to `candidate_paper_ids` with priority flag
- In `deep_reading`: library seeds use cached summary (skip re-reading)
- Emit progress: "Found 5 relevant papers in library (skipping re-analysis)"

**Atlas** (`retrieve_classics`):
- Library seeds with high citation count → foundational bucket
- Library seeds from recent years → frontier bucket

**Divergent** (`analogical_retrieval`):
- Library seeds from different fields → cross-domain candidates

## 8. Frontend

### 8.1 Paper Detail Page

Route: `/runs/[id]/papers/[paperId]` or `/library/papers/[paperId]`

Sections: Research Motivation → Mathematical Formulation (LaTeX rendered) → Experimental Design → Results → Critical Review → One More Thing

Actions: `[View PDF]` `[Add to Library]` / `[Already in Library ✓]`

LaTeX math rendering: Use KaTeX (lightweight, fast) loaded via CDN.

### 8.2 Library Page

Route: `/library`

Features:
- Search bar (hybrid text + vector search)
- Filter chips: field, sub_field, project tags
- Paper cards: title, venue, year, keywords, status badge
- Stats footer: total papers, fields, chunks

### 8.3 Sidebar Entry

Below "New Research" button:
```
[+ New Research]
[📚 Library (12)]
[📁 New Project]
```

### 8.4 Seed Paper Library Picker

In `/new` page seed paper section:
- Text input with typeahead search against `GET /api/v1/library/search/titles?q=...`
- Matched results show as clickable cards with `[+ Add as Seed]`
- Selected library papers tagged with `📚` icon in seed list

## 9. File Storage Layout

All on vdb disk (`/data/research-os/library/`):

```
/data/research-os/library/
├── sources/
│   └── {arxiv_id}/
│       ├── source.tar.gz         # Original download
│       ├── extracted/            # LaTeX source files
│       └── main.tex              # Detected main file
├── pdfs/
│   └── {arxiv_id}.pdf            # Compiled or downloaded PDF
├── figures/
│   └── {library_paper_id}/
│       └── arch_figure.png       # Extracted architecture diagram
└── uploads/
    └── {uuid}.pdf                # User-uploaded PDFs
```

## 10. Implementation Order

| Phase | What | Depends On | Est. |
|-------|------|------------|------|
| 1 | DB migration: library_paper + library_chunk tables | — | Small |
| 2 | Tool functions: db, embedding, storage, arxiv | Phase 1 | Medium |
| 3 | PaperTagAgent (Level 1) + integrate into resolve_and_read_paper | Phase 2 | Medium |
| 4 | Library CRUD API + add-from-run flow | Phase 2 | Medium |
| 5 | Vector search + rerank search API | Phase 2 | Medium |
| 6 | library_prefetch + mode integration | Phase 5 | Medium |
| 7 | Frontend: paper detail page + Add to Library | Phase 4 | Medium |
| 8 | Frontend: library page + search | Phase 5 | Medium |
| 9 | Frontend: seed paper library picker | Phase 5 | Small |
| 10 | PaperAnalysisAgent (Level 2) + PDF compile | Phase 7 | Medium |
| 11 | Manual upload flow (PDF + arXiv ID) | Phase 4 | Small |
