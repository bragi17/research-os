# Research OS

> Autonomous Multi-Mode Research Operating System

Research OS is an AI-powered research orchestration platform that automates academic literature discovery, structured analysis, and innovation hypothesis generation. It operates as a **multi-mode research operating system** — not a chatbot — with long-running autonomous workflows, real-time observability, and evidence-traceable outputs.

---

## Key Features

- **Multi-Mode Research Workflows** — Four specialized modes for different research stages:
  - **Atlas** (Mode A): Field onboarding with timeline, taxonomy tree, and reading paths
  - **Frontier** (Mode B): Focused sub-field analysis with method comparison and pain point mining
  - **Divergent** (Mode C): Cross-domain innovation with analogical retrieval and idea cards
  - **Review** (Mode X): Result synthesis, refinement, and structured export
- **Intelligent Mode Router** — Automatically classifies user intent and recommends the appropriate research mode
- **Multi-Source Academic Search** — Semantic Scholar, OpenAlex, Crossref, Unpaywall integration with cross-source deduplication
- **LaTeX-First Paper Parsing** — Downloads arXiv LaTeX source for high-fidelity section extraction; falls back to GROBID PDF parsing
- **Figure Extraction** — Three-tier strategy: arXiv source images > PDF crop via PyMuPDF > caption-only fallback
- **Evidence-Traceable Outputs** — Every claim, hypothesis, and insight links back to source papers and text spans
- **Real-Time Progress** — Server-Sent Events (SSE) stream workflow events to the frontend in real time
- **Checkpoint & Resume** — Long-running tasks can be paused, modified, and resumed without data loss

## Architecture

```
User --> Next.js Frontend --> FastAPI API --> Redis Queue --> Worker Process
              |                   |                             |
         3-Panel UI          PostgreSQL              LangGraph Workflows
         (Workspace)              |                    |           |
                             run_event <--      Adapters      LLM Gateway
                                  |          (S2/OA/CR/UW)        |
                             SSE Stream       LaTeX Parser    Prompt Engine
                                  |                           (10 templates)
                          Real-time UI               Claim / Gap / Innovation
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **API** | FastAPI + Pydantic v2 |
| **Workflow** | LangGraph (25 nodes across 4 mode graphs) |
| **Database** | PostgreSQL 16 + pgvector |
| **Cache/Queue** | Redis |
| **Object Storage** | MinIO / Local filesystem |
| **PDF Parsing** | GROBID + PyMuPDF |
| **LaTeX Parsing** | Custom parser (ported from latex-paper-mirror) |
| **LLM** | OpenAI-compatible API (configurable) |
| **Academic Data** | Semantic Scholar, OpenAlex, Crossref, Unpaywall |
| **Frontend** | Next.js 15 + Tailwind CSS |
| **Auth** | JWT (bcrypt + PyJWT) |
| **Observability** | structlog + OpenTelemetry (instrumentation ready) |

## Project Structure

```
research-os/
  apps/
    api/                  # FastAPI application
      main.py             # API entry point + v1 routes
      routes_v2.py        # Multi-mode endpoints (unified under /api/v1)
      auth.py             # JWT authentication
      database.py         # Async PostgreSQL CRUD (asyncpg)
    worker/               # Background task execution
      runner.py           # Worker process (Redis consumer)
      task_queue.py       # Redis task queue
      llm_gateway.py      # LLM call management
      modes/              # Multi-mode workflow engine
        router.py         # Mode 0: Intent classification
        base.py           # Shared state + utilities
        atlas.py          # Mode A: Field Onboarding (8 stages)
        frontier.py       # Mode B: Gap Analysis (7 stages)
        divergent.py      # Mode C: Cross-Domain Innovation (7 stages)
        review.py         # Mode X: Synthesis & Export (3 stages)
    web/                  # Next.js frontend
      src/app/            # Pages (dashboard, new, runs, atlas, frontier, divergent)
      src/components/     # Reusable UI components
      src/lib/api.ts      # API client
  libs/
    schemas/              # Pydantic data models
    adapters/             # Academic API adapters (S2, OpenAlex, Crossref, Unpaywall)
    prompts/              # LLM prompt templates + JSON schemas
    config.py             # Centralized settings (pydantic-settings)
  services/
    parser/               # Paper parsing (GROBID + LaTeX + arXiv source)
    storage.py            # Object storage (MinIO / local)
    export.py             # Report generation (Markdown, JSON, CSV, BibTeX)
    figure_extraction.py  # Figure extraction service
  scripts/
    migration/            # PostgreSQL migrations (001-004)
  infra/
    docker/               # Docker Compose + Dockerfile
  tests/                  # 151 tests (pytest)
```

## Quick Start

### Prerequisites

- Python 3.10+
- PostgreSQL 16 (with pgvector extension)
- Redis
- Node.js 18+ (for frontend)
- GROBID (optional, for PDF parsing)

### 1. Environment Setup

```bash
cp .env.example .env
# Edit .env with your database, Redis, and API credentials
```

### 2. Database Setup

```bash
# Create database and run migrations
psql -U postgres -c "CREATE DATABASE research_os;"
psql -U postgres -d research_os -f scripts/migration/001_init_schema.sql
psql -U postgres -d research_os -f scripts/migration/002_add_users.sql
psql -U postgres -d research_os -f scripts/migration/003_v2_multimode.sql
psql -U postgres -d research_os -f scripts/migration/004_add_trace_id.sql
```

### 3. Install Dependencies

```bash
pip install fastapi uvicorn pydantic pydantic-settings httpx asyncpg redis \
    langgraph langchain-core openai pymupdf structlog orjson bcrypt PyJWT tenacity
```

### 4. Start Services

```bash
# API Server
PYTHONPATH=. uvicorn apps.api.main:app --host 0.0.0.0 --port 8000

# Worker Process (separate terminal)
PYTHONPATH=. python -m apps.worker.runner

# Frontend (separate terminal)
cd apps/web && npm install && npm run dev
```

### 5. Access

- **Frontend**: http://localhost:3001
- **API Docs**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

### Docker Compose (Alternative)

```bash
cd infra/docker && docker compose up -d
```

## API Overview

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/auth/register` | POST | User registration |
| `/api/v1/auth/login` | POST | Login (returns JWT) |
| `/api/v1/runs` | POST | Create research run |
| `/api/v1/runs` | GET | List runs |
| `/api/v1/runs/{id}/start` | POST | Start run (enqueues to Redis) |
| `/api/v1/runs/{id}/pause` | POST | Pause running task |
| `/api/v1/runs/{id}/resume` | POST | Resume paused task |
| `/api/v1/runs/{id}/events/stream` | GET | SSE event stream |
| `/api/v1/runs/multimode` | POST | Create run with mode selection |
| `/api/v1/runs/{id}/spawn` | POST | Spawn child run (mode chaining) |
| `/api/v1/runs/{id}/pain-points` | GET | List pain points (Mode B) |
| `/api/v1/runs/{id}/idea-cards` | GET | List innovation cards (Mode C) |
| `/api/v1/runs/{id}/timeline` | GET | Research timeline (Mode A) |
| `/api/v1/runs/{id}/taxonomy` | GET | Classification tree (Mode A) |
| `/api/v1/runs/{id}/mindmap` | GET | Mind map JSON |
| `/api/v1/runs/{id}/downloads/{fmt}` | GET | Export (markdown/json/csv/bibtex) |

## Research Modes

### Mode A: Atlas (Field Onboarding)

For researchers **entering a new field**. Produces a structured cognitive map:
- Research timeline with paradigm shifts
- Multi-view taxonomy (by method, task, modality)
- Representative paper cards with key figures
- Graduated reading path (week-by-week)
- Entry points for deeper investigation

### Mode B: Frontier (Focused Gap Analysis)

For researchers **analyzing a specific sub-field**. Produces actionable intelligence:
- Scope-guarded paper pool (venue + benchmark constrained)
- Method comparison matrix
- Benchmark performance panel
- Pain point board with severity scores
- Future work extraction and entry point suggestions

### Mode C: Divergent (Cross-Domain Innovation)

For researchers **seeking novel ideas**. Produces innovation candidates:
- Pain point abstraction into problem signatures
- Analogical retrieval across domains
- Method transfer feasibility screening
- Innovation cards with novelty/feasibility scores
- Prior-art risk assessment

### Mode Chaining

Modes are designed to feed into each other:
```
Atlas --> "Deep dive this direction" --> Frontier
Frontier --> "Explore innovations for this pain point" --> Divergent
Divergent --> "Check prior art further" --> Frontier
```

## Testing

```bash
PYTHONPATH=. pytest tests/ -v
```

151 tests covering: LaTeX parser, arXiv source downloader, figure extraction, data models, mode router, database CRUD, API endpoints, export generation.

## Configuration

All settings are centralized in `libs/config.py` using pydantic-settings. Key environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL connection | `postgresql://...` |
| `REDIS_URL` | Redis connection | `redis://localhost:6379/0` |
| `OPENAI_API_KEY` | LLM API key | (required) |
| `OPENAI_BASE_URL` | LLM endpoint | `https://api.openai.com/v1` |
| `S2_API_KEY` | Semantic Scholar API key | (optional) |
| `JWT_SECRET` | JWT signing secret | (required in production) |
| `GROBID_URL` | GROBID service URL | `http://localhost:8070` |
| `CORS_ORIGINS` | Allowed CORS origins | `http://localhost:3000,http://localhost:3001` |

## License

MIT
