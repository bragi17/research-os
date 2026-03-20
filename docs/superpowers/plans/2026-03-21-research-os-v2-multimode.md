# Research OS v2: Multi-Mode Research System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade Research OS from a single-workflow research tool to a multi-mode research operating system with 5 modes (Intake Router, Atlas, Frontier, Divergent, Review), structured context passing between modes, and a three-panel workspace UI.

**Architecture:** The upgrade is layered: (1) new data models and DB migration, (2) multi-mode workflow engine replacing the single LangGraph graph, (3) updated API with mode-aware endpoints and context bundles, (4) complete frontend rewrite as a three-panel research workspace. Each mode shares the existing adapter/parser/LLM infrastructure but has its own node graph and scoring logic.

**Tech Stack:** Python 3.10+, FastAPI, LangGraph (multi-graph), PostgreSQL+pgvector, Redis, Next.js 15, Tailwind CSS, React Flow (mind map), SSE

---

## Scope Decomposition

This plan covers 6 subsystems, each independently deliverable and testable. **Recommended execution order:**

| # | Subsystem | Priority | Depends On | Est. Tasks |
|---|-----------|----------|------------|------------|
| 1 | Data Model & Migration | P0 | — | 5 |
| 2 | Multi-Mode Workflow Engine | P0 | #1 | 8 |
| 3 | Mode-Aware API & Context Bundles | P0 | #1, #2 | 6 |
| 4 | Frontend: Workspace Shell & Research Tree | P0 | #3 | 7 |
| 5 | Frontend: Mode A/B/C Result Pages | P1 | #4 | 9 |
| 6 | Figure Extraction & Mind Map | P1 | #1, #2 | 5 |

**Total: ~40 tasks, estimated 3-4 implementation sessions**

---

## Subsystem 1: Data Model & Database Migration

### Task 1.1: Create migration 003 — new v2 tables

**Files:**
- Create: `scripts/migration/003_v2_multimode.sql`

- [ ] **Step 1: Write the migration SQL**

```sql
-- Research Domain hierarchy
CREATE TABLE IF NOT EXISTS research_domain (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name TEXT NOT NULL,
    aliases TEXT[] DEFAULT '{}',
    parent_domain_id UUID REFERENCES research_domain(id),
    description_short TEXT,
    description_detailed TEXT,
    keywords TEXT[] DEFAULT '{}',
    representative_venues TEXT[] DEFAULT '{}',
    representative_datasets TEXT[] DEFAULT '{}',
    representative_methods TEXT[] DEFAULT '{}',
    canonical_paper_ids UUID[] DEFAULT '{}',
    recent_frontier_paper_ids UUID[] DEFAULT '{}',
    prerequisite_domain_ids UUID[] DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Figure assets extracted from papers
CREATE TABLE IF NOT EXISTS figure_asset (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    paper_id UUID NOT NULL REFERENCES paper(id) ON DELETE CASCADE,
    source_type TEXT NOT NULL DEFAULT 'pdf_crop',
    page_no INT,
    caption TEXT,
    image_path TEXT,
    figure_type TEXT,
    related_section TEXT,
    license_note TEXT,
    extraction_confidence NUMERIC(4,3),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_figure_asset_paper ON figure_asset(paper_id);

-- Reading paths for Mode A
CREATE TABLE IF NOT EXISTS reading_path (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    run_id UUID REFERENCES research_run(id) ON DELETE CASCADE,
    domain_id UUID REFERENCES research_domain(id),
    difficulty_level TEXT DEFAULT 'beginner',
    ordered_units JSONB NOT NULL DEFAULT '[]'::jsonb,
    estimated_hours NUMERIC(5,1),
    goal TEXT,
    generated_rationale TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Pain points for Mode B
CREATE TABLE IF NOT EXISTS pain_point (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    run_id UUID REFERENCES research_run(id) ON DELETE CASCADE,
    cluster_id UUID REFERENCES topic_cluster(id),
    statement TEXT NOT NULL,
    pain_type TEXT,
    supporting_paper_ids UUID[] DEFAULT '{}',
    counter_evidence_paper_ids UUID[] DEFAULT '{}',
    severity_score NUMERIC(4,3),
    novelty_potential NUMERIC(4,3),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_pain_point_run ON pain_point(run_id);

-- Idea cards for Mode C (richer than hypothesis)
CREATE TABLE IF NOT EXISTS idea_card (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    run_id UUID REFERENCES research_run(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    problem_statement TEXT,
    source_pain_point_ids UUID[] DEFAULT '{}',
    borrowed_methods TEXT[] DEFAULT '{}',
    source_domains TEXT[] DEFAULT '{}',
    mechanism_of_transfer TEXT,
    expected_benefit TEXT,
    risks TEXT[] DEFAULT '{}',
    required_experiments TEXT[] DEFAULT '{}',
    prior_art_check_status TEXT DEFAULT 'pending',
    novelty_score NUMERIC(4,3),
    feasibility_score NUMERIC(4,3),
    status TEXT NOT NULL DEFAULT 'candidate',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_idea_card_run ON idea_card(run_id);

-- Context bundles for inter-mode passing
CREATE TABLE IF NOT EXISTS context_bundle (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_run_id UUID REFERENCES research_run(id),
    source_mode TEXT NOT NULL,
    summary_text TEXT,
    selected_paper_ids UUID[] DEFAULT '{}',
    cluster_ids UUID[] DEFAULT '{}',
    figure_ids UUID[] DEFAULT '{}',
    pain_point_ids UUID[] DEFAULT '{}',
    idea_card_ids UUID[] DEFAULT '{}',
    benchmark_data JSONB DEFAULT '{}'::jsonb,
    mindmap_json JSONB DEFAULT '{}'::jsonb,
    user_annotations JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Extend research_run with mode fields
ALTER TABLE research_run ADD COLUMN IF NOT EXISTS mode TEXT DEFAULT 'atlas';
ALTER TABLE research_run ADD COLUMN IF NOT EXISTS parent_run_id UUID REFERENCES research_run(id);
ALTER TABLE research_run ADD COLUMN IF NOT EXISTS source_run_ids UUID[] DEFAULT '{}';
ALTER TABLE research_run ADD COLUMN IF NOT EXISTS context_bundle_id UUID REFERENCES context_bundle(id);
ALTER TABLE research_run ADD COLUMN IF NOT EXISTS output_bundle_id UUID REFERENCES context_bundle(id);
ALTER TABLE research_run ADD COLUMN IF NOT EXISTS current_stage TEXT;

-- Extend topic_cluster with Mode B fields
ALTER TABLE topic_cluster ADD COLUMN IF NOT EXISTS domain_id UUID REFERENCES research_domain(id);
ALTER TABLE topic_cluster ADD COLUMN IF NOT EXISTS entry_keywords TEXT[] DEFAULT '{}';
ALTER TABLE topic_cluster ADD COLUMN IF NOT EXISTS methods JSONB DEFAULT '[]'::jsonb;
ALTER TABLE topic_cluster ADD COLUMN IF NOT EXISTS datasets JSONB DEFAULT '[]'::jsonb;
ALTER TABLE topic_cluster ADD COLUMN IF NOT EXISTS metrics JSONB DEFAULT '[]'::jsonb;
ALTER TABLE topic_cluster ADD COLUMN IF NOT EXISTS pain_point_ids UUID[] DEFAULT '{}';
ALTER TABLE topic_cluster ADD COLUMN IF NOT EXISTS future_work_mentions JSONB DEFAULT '[]'::jsonb;
ALTER TABLE topic_cluster ADD COLUMN IF NOT EXISTS coverage_score NUMERIC(4,3);
```

- [ ] **Step 2: Run migration against local database**

```bash
PGPASSWORD=DB_PASSWORD_REDACTED psql -h localhost -U research_os -d research_os -f scripts/migration/003_v2_multimode.sql
```

Expected: All CREATE/ALTER succeed

- [ ] **Step 3: Commit**

```bash
git add scripts/migration/003_v2_multimode.sql
git commit -m "feat: add v2 multi-mode tables (domain, figure, reading_path, pain_point, idea_card, context_bundle)"
```

---

### Task 1.2: Create Pydantic models for new entities

**Files:**
- Create: `libs/schemas/multimode.py`
- Test: `tests/test_multimode_schemas.py`

- [ ] **Step 1: Write test for new models**

```python
# tests/test_multimode_schemas.py
import pytest
from uuid import uuid4
from libs.schemas.multimode import (
    ResearchMode, RunStage, PainPoint, IdeaCard, ContextBundle,
    ModeConfig, SpawnRunRequest,
)

class TestResearchMode:
    def test_all_modes(self):
        for m in ("intake", "atlas", "frontier", "divergent", "review"):
            assert ResearchMode(m) == m

class TestPainPoint:
    def test_creation(self):
        pp = PainPoint(statement="3D AD generalization is poor", pain_type="generalization")
        assert pp.severity_score == 0.0

class TestIdeaCard:
    def test_creation(self):
        ic = IdeaCard(title="Transfer contrastive learning to 3D AD", problem_statement="test")
        assert ic.status == "candidate"
        assert ic.prior_art_check_status == "pending"

class TestContextBundle:
    def test_creation(self):
        cb = ContextBundle(source_mode="frontier")
        assert cb.selected_paper_ids == []
        assert cb.mindmap_json == {}

class TestSpawnRunRequest:
    def test_creation(self):
        req = SpawnRunRequest(target_mode=ResearchMode.DIVERGENT, context_bundle_id=uuid4())
        assert req.target_mode == "divergent"
```

- [ ] **Step 2: Run test — verify it fails**

```bash
pytest tests/test_multimode_schemas.py -v
```

- [ ] **Step 3: Implement models in `libs/schemas/multimode.py`**

```python
"""Research OS v2 - Multi-mode data models."""
from __future__ import annotations
from enum import Enum
from typing import Any
from uuid import UUID
from pydantic import BaseModel, Field


class ResearchMode(str, Enum):
    INTAKE = "intake"
    ATLAS = "atlas"
    FRONTIER = "frontier"
    DIVERGENT = "divergent"
    REVIEW = "review"


class RunStage(str, Enum):
    PLAN = "plan"
    RETRIEVE = "retrieve"
    INGEST = "ingest"
    ANALYZE = "analyze"
    SYNTHESIZE = "synthesize"
    REVIEW = "review"
    EXPORT = "export"


class PainPoint(BaseModel):
    id: UUID | None = None
    run_id: UUID | None = None
    cluster_id: UUID | None = None
    statement: str
    pain_type: str | None = None
    supporting_paper_ids: list[UUID] = Field(default_factory=list)
    counter_evidence_paper_ids: list[UUID] = Field(default_factory=list)
    severity_score: float = 0.0
    novelty_potential: float = 0.0


class IdeaCard(BaseModel):
    id: UUID | None = None
    run_id: UUID | None = None
    title: str
    problem_statement: str = ""
    source_pain_point_ids: list[UUID] = Field(default_factory=list)
    borrowed_methods: list[str] = Field(default_factory=list)
    source_domains: list[str] = Field(default_factory=list)
    mechanism_of_transfer: str | None = None
    expected_benefit: str | None = None
    risks: list[str] = Field(default_factory=list)
    required_experiments: list[str] = Field(default_factory=list)
    prior_art_check_status: str = "pending"
    novelty_score: float = 0.0
    feasibility_score: float = 0.0
    status: str = "candidate"


class ContextBundle(BaseModel):
    id: UUID | None = None
    source_run_id: UUID | None = None
    source_mode: str
    summary_text: str | None = None
    selected_paper_ids: list[UUID] = Field(default_factory=list)
    cluster_ids: list[UUID] = Field(default_factory=list)
    figure_ids: list[UUID] = Field(default_factory=list)
    pain_point_ids: list[UUID] = Field(default_factory=list)
    idea_card_ids: list[UUID] = Field(default_factory=list)
    benchmark_data: dict[str, Any] = Field(default_factory=dict)
    mindmap_json: dict[str, Any] = Field(default_factory=dict)
    user_annotations: dict[str, Any] = Field(default_factory=dict)


class ModeConfig(BaseModel):
    mode: ResearchMode
    topic: str
    keywords: list[str] = Field(default_factory=list)
    seed_paper_ids: list[str] = Field(default_factory=list)
    constraints: dict[str, Any] = Field(default_factory=dict)
    parent_run_id: UUID | None = None
    context_bundle_id: UUID | None = None


class SpawnRunRequest(BaseModel):
    target_mode: ResearchMode
    context_bundle_id: UUID | None = None
    selection: dict[str, Any] = Field(default_factory=dict)
```

- [ ] **Step 4: Run test — verify it passes**

```bash
pytest tests/test_multimode_schemas.py -v
```

- [ ] **Step 5: Commit**

```bash
git add libs/schemas/multimode.py tests/test_multimode_schemas.py
git commit -m "feat: add v2 multi-mode Pydantic models"
```

---

### Task 1.3: Add database CRUD for new tables

**Files:**
- Create: `apps/api/database_v2.py`
- Test: `tests/test_database_v2.py`

- [ ] **Step 1: Write tests for new CRUD operations** (mock-based, no real DB)

Test at minimum: `create_pain_point`, `list_pain_points`, `create_idea_card`, `list_idea_cards`, `create_context_bundle`, `get_context_bundle`, `create_figure_asset`, `list_figures_by_paper`.

- [ ] **Step 2: Implement CRUD in `apps/api/database_v2.py`**

Following the same pattern as `database.py` — asyncpg parameterized queries, `_record_to_dict` helper.

- [ ] **Step 3: Run tests — verify pass**
- [ ] **Step 4: Commit**

---

## Subsystem 2: Multi-Mode Workflow Engine

### Task 2.1: Create Mode Router (Mode 0)

**Files:**
- Create: `apps/worker/modes/router.py`
- Test: `tests/test_mode_router.py`

The router takes user input and returns a `ModeConfig` with the recommended mode. Uses keyword matching first, then LLM for ambiguous cases.

- [ ] **Step 1: Write tests**

```python
# Key test cases:
# "I'm new to this field" → atlas
# "Find recent papers on 3D AD" → frontier
# "Help me find innovation points" → divergent
# "Summarize the results" → review
```

- [ ] **Step 2: Implement `router.py`**

Rule-based first pass (keyword matching from Doc 06 section 5.4), LLM fallback for ambiguous input.

- [ ] **Step 3: Run tests — verify pass**
- [ ] **Step 4: Commit**

---

### Task 2.2: Refactor workflow into mode-specific graphs

**Files:**
- Create: `apps/worker/modes/__init__.py`
- Create: `apps/worker/modes/base.py` — shared node functions (search, read, extract)
- Create: `apps/worker/modes/atlas.py` — Mode A graph (8 stages from Doc 07)
- Create: `apps/worker/modes/frontier.py` — Mode B graph (7 stages)
- Create: `apps/worker/modes/divergent.py` — Mode C graph (7 stages)
- Create: `apps/worker/modes/review.py` — Mode X graph
- Modify: `apps/worker/runner.py` — dispatch to correct mode graph

Each mode graph follows the `StateGraph` pattern from the existing `graph_state.py` but with mode-specific nodes. Shared capabilities (LLM calls, search, figure extraction) are in `base.py`.

**Mode A (Atlas) stages:** PlanAtlas → RetrieveClassics → BuildTimeline → BuildTaxonomy → ReadRepresentativePapers → ExtractFigures → GenerateReadingPath → SynthesizeAtlas

**Mode B (Frontier) stages:** ScopeDefinition → CandidateRetrieval → ScopePruning → DeepReading → ComparisonBuild → PainMining → FrontierSummary

**Mode C (Divergent) stages:** NormalizePainPackage → AnalogicalRetrieval → MethodTransferScreening → IdeaComposition → PriorArtCheck → FeasibilityReview → IdeaPortfolio

- [ ] **Step 1: Create `base.py` with shared node functions**

Extract from current `graph_state.py`: `search_sources`, `deep_read`, `_estimate_cost`, `_normalize_title` into reusable functions.

- [ ] **Step 2: Create `atlas.py` Mode A graph with stub nodes**
- [ ] **Step 3: Create `frontier.py` Mode B graph — adapt existing graph_state.py**

The current single workflow is closest to Mode B. Refactor it with additional stages (ScopeDefinition, ComparisonBuild, PainMining).

- [ ] **Step 4: Create `divergent.py` Mode C graph with stub nodes**
- [ ] **Step 5: Create `review.py` Mode X graph**
- [ ] **Step 6: Update `runner.py` to dispatch by mode**

```python
async def _execute_run(self, run_id, job):
    mode = job.get("mode", "frontier")
    if mode == "atlas":
        from apps.worker.modes.atlas import create_atlas_graph
        graph = create_atlas_graph()
    elif mode == "frontier":
        from apps.worker.modes.frontier import create_frontier_graph
        graph = create_frontier_graph()
    # ... etc
```

- [ ] **Step 7: Write integration test for mode dispatch**
- [ ] **Step 8: Commit**

---

### Task 2.3: Implement Mode A (Atlas) core nodes

Implement the 8 real nodes for Mode A using LLM + adapters. Key differentiator from Mode B: emphasis on pedagogical clarity, timeline, taxonomy tree, reading path.

- [ ] Steps follow TDD pattern for each node

---

### Task 2.4: Implement Mode B (Frontier) — adapt from v1

Refactor existing `graph_state.py` nodes into Mode B specific graph. Add: ScopeGuard, ComparisonBuild, PainMining stages.

---

### Task 2.5: Implement Mode C (Divergent) core nodes

Implement pain abstraction, analogical retrieval, idea composition, prior-art check. This is the most novel mode.

---

## Subsystem 3: Mode-Aware API

### Task 3.1: Update `POST /api/v1/runs` to accept mode

Add `mode` field to `CreateRunRequest`. Default to `"atlas"`.

### Task 3.2: Add `POST /api/v1/runs/{id}/spawn` endpoint

Create child run from parent run's context bundle. Enables A→B→C chaining.

### Task 3.3: Add CRUD endpoints for new entities

- `GET /api/v1/runs/{id}/pain-points`
- `GET /api/v1/runs/{id}/idea-cards`
- `GET /api/v1/runs/{id}/figures`
- `GET /api/v1/runs/{id}/reading-path`
- `GET /api/v1/runs/{id}/context-bundle`
- `POST /api/v1/runs/{id}/interrupt` (with action dictionary)

### Task 3.4: Update SSE events for mode-specific events

Add new event types: `paper.added`, `figure.extracted`, `pain_point.created`, `idea.created`, `timeline.updated`, `mindmap.updated`, `mode.transition.suggested`.

### Task 3.5: Add user action endpoints

- `POST /api/v1/runs/{id}/actions/{action}` — unified action endpoint
- Actions: `pin_paper`, `exclude_paper`, `tighten_scope`, `expand_scope`, `switch_mode`, `send_to_mode_c`, etc.

### Task 3.6: Tests for all new endpoints

---

## Subsystem 4: Frontend Workspace Shell

### Task 4.1: Create three-panel layout

**Files:**
- Create: `apps/web/src/app/workspaces/[id]/layout.tsx`
- Create: `apps/web/src/components/LeftResearchTree.tsx`
- Create: `apps/web/src/components/RightDrawer.tsx`

Three-panel: left tree (280px) + center content (flex) + right drawer (360px, collapsible).

### Task 4.2: Implement LeftResearchTree

Sections: Research Atlas, Runs, Assets, Personal Notes. Tree nodes are clickable and lead to appropriate views.

### Task 4.3: Implement RightDrawer with 3 tabs

Tabs: Chat/Ask, Evidence, Controls. Evidence shows citations and source text. Controls shows pause/resume/scope adjustments.

### Task 4.4: Implement WorkspaceHeader

Mode indicator (A/B/C/X), global search, current run status, mode switch button.

### Task 4.5: Implement mode-aware routing

- `/workspaces/[id]` — workspace home
- `/workspaces/[id]/runs/[runId]` — run view (auto-selects mode page)
- `/workspaces/[id]/papers/[paperId]` — paper detail drawer
- `/workspaces/[id]/ideas/[ideaId]` — idea card detail

### Task 4.6: Update API client for new endpoints

Add types and functions for new entities (PainPoint, IdeaCard, ContextBundle, etc.)

### Task 4.7: Build verification

```bash
cd apps/web && npx next build
```

---

## Subsystem 5: Mode-Specific Result Pages

### Task 5.1: Mode A — Atlas page

Components: DomainHeroCard, TimelineRail, TaxonomySwitchTabs, RepresentativePaperGrid, FigureGallery, ReadingPathBoard, NextStepRecommendations. CTA: "Deep dive into this sub-direction" → spawn Mode B.

### Task 5.2: Mode B — Frontier page

Components: ScopeChipBar, CorePaperStrip, BenchmarkPanel, MethodComparisonTable, PainPointBoard, FutureWorkPanel, EntryPointCards. CTA: "Explore innovations for this pain point" → spawn Mode C.

### Task 5.3: Mode C — Divergent Innovation page

Components: ProblemSignaturePanel, AnalogicalMapCanvas, TransferMethodGallery, IdeaCardBoard, PriorArtWarningList, ExperimentSketchPanel.

### Task 5.4: Mode X — Review page

Chat-like interface for refining results, with structured export options.

### Task 5.5: Paper detail drawer

Title, authors, venue, one-line summary, innovation, key figures, method, datasets/metrics, limitations, future work, action buttons.

### Task 5.6: Mode transition CTAs

"Deep dive" buttons on Mode A → B, "Find innovations" on Mode B → C, "Check prior art" on Mode C → B.

### Task 5.7-5.9: Tests and build verification

---

## Subsystem 6: Figure Extraction & Mind Map

### Task 6.1: Implement FigureExtractionService

**Files:**
- Create: `services/figure_extraction.py`

Priority: (1) arXiv source package, (2) PDF page crop via PyMuPDF, (3) caption-only fallback.

### Task 6.2: Integrate figure extraction into workflow nodes

Call `FigureExtractionService` in Mode A's `ExtractFigures` stage and Mode B's `DeepReading` stage.

### Task 6.3: Implement mind map data generation

Output `mindmap_json` from Mode A's `SynthesizeAtlas` and Mode B's `ComparisonBuild`. Structure: `{root_topic, nodes: [{id, label, type, children}], edges: [{source, target, relation}]}`.

### Task 6.4: Frontend MindMapCanvas component

Use React Flow or D3 to render the mind map JSON. Support zoom, pan, click-to-navigate.

### Task 6.5: Frontend FigureViewer component

Large preview, caption, paper source, teaching explanation, download/cite.

---

## Execution Order Recommendation

**Phase 1 (Critical Path):**
1. Task 1.1 → 1.2 → 1.3 (Data model)
2. Task 2.1 → 2.2 (Mode router + graph refactor)
3. Task 3.1 → 3.2 → 3.3 (API updates)

**Phase 2 (Mode Implementation):**
4. Task 2.3 (Mode A nodes)
5. Task 2.4 (Mode B refactor)
6. Task 2.5 (Mode C nodes)

**Phase 3 (Frontend):**
7. Task 4.1 → 4.2 → 4.3 → 4.4 → 4.5 (Workspace shell)
8. Task 5.1 → 5.2 → 5.3 (Mode pages)

**Phase 4 (Polish):**
9. Task 6.1 → 6.2 → 6.3 → 6.4 → 6.5 (Figures + mind map)
10. Task 5.4 → 5.5 → 5.6 (Review + detail + transitions)

---

## Risk Notes

1. **Mode C is the hardest** — analogical retrieval across domains requires careful prompt engineering and broad search. Implement Mode A and B first.
2. **Figure extraction quality varies** — arXiv source is best but not always available. Always have a caption-only fallback.
3. **Context bundle size** — bundles can grow large. Use IDs and lazy loading, not inline content.
4. **Mind map rendering** — React Flow is the pragmatic choice. D3 is more flexible but harder to maintain.
