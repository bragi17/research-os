# Research OS — Project Instructions

## Python Environment

This project uses a **virtual environment**. Always use it for running code.

```
Path: /root/research-os/.venv/
Python: /root/research-os/.venv/bin/python (3.10)
Pip: /root/research-os/.venv/bin/pip
```

### Running Commands

```bash
# Unit tests (fast, ~5s)
PYTHONPATH=/root/research-os .venv/bin/python -m pytest tests/ -v --ignore=tests/test_e2e.py --ignore=tests/test_e2e_full_workflow.py

# E2E mode tests (requires API running, ~2s)
PYTHONPATH=/root/research-os .venv/bin/python -m pytest tests/test_e2e_modes.py -v

# Full workflow E2E test (requires API + Worker, ~8-10 min)
PYTHONPATH=/root/research-os .venv/bin/python -m pytest tests/test_e2e_full_workflow.py -v -x -s

# API server
PYTHONPATH=/root/research-os .venv/bin/uvicorn apps.api.main:app --host 0.0.0.0 --port 8000

# Worker process
PYTHONPATH=/root/research-os .venv/bin/python -m apps.worker.runner

# Install new dependency
.venv/bin/pip install <package>

# Frontend (must run from apps/web/)
cd apps/web && npm run dev -- -H 0.0.0.0 -p 3001
```

### Important: NEVER use system python (`/usr/bin/python3`) for this project.

## Starting All Services

```bash
# 1. API
PYTHONPATH=/root/research-os nohup .venv/bin/uvicorn apps.api.main:app --host 0.0.0.0 --port 8000 > /tmp/ros-api.log 2>&1 &

# 2. Worker
PYTHONPATH=/root/research-os nohup .venv/bin/python -m apps.worker.runner > /tmp/ros-worker.log 2>&1 &

# 3. Frontend (must cd first)
cd /root/research-os/apps/web && nohup npx next dev -H 0.0.0.0 -p 3001 > /tmp/ros-web.log 2>&1 &

# Verify
curl --noproxy '*' -s http://localhost:8000/health  # API
curl --noproxy '*' -s http://localhost:3001/          # Frontend
```

## Database

- PostgreSQL data on **vdb** (`/data/postgresql/16/main`) — NOT on system disk
- Connection: `localhost:5432`, database `research_os`, user `research_os`, password in `.env`
- Redis at `localhost:6379`, password in `.env`
- Migrations: `scripts/migration/001-004`
- Run migration: `PGPASSWORD=DB_PASSWORD_REDACTED psql -h localhost -U research_os -d research_os -f scripts/migration/<file>.sql`

## Project Structure

```
apps/
  api/              # FastAPI (port 8000)
    main.py         # API entry + v1 routes
    routes_v2.py    # Multi-mode endpoints (unified under /api/v1)
    auth.py         # JWT auth
    database.py     # All async PostgreSQL CRUD (single file)
  worker/           # Background task execution
    runner.py       # Worker process (Redis consumer, WORKER_CONCURRENCY=2)
    llm_gateway.py  # LLM calls — uses LangChain with_structured_output for JSON
    modes/          # Multi-mode workflow engine
      router.py     # Mode 0: intent classification
      base.py       # Shared state + emit_progress() + utilities
      atlas.py      # Mode A: 8-stage field exploration
      frontier.py   # Mode B: 7-stage sub-field analysis
      divergent.py  # Mode C: 7-stage cross-domain innovation
      review.py     # Mode X: 3-stage synthesis
  web/              # Next.js frontend (port 3001, Tailwind v3)
    src/app/        # Pages (dashboard, new, runs/[id], atlas, frontier, divergent)
    src/components/ # Sidebar, ThinkingStream, ResearchPlan, StatusBadge, etc.
    src/lib/api.ts  # API client
libs/
  schemas/          # Pydantic models (run.py, multimode.py)
  adapters/         # Academic APIs (S2, OpenAlex, Crossref, Unpaywall)
  prompts/          # LLM prompt templates
  config.py         # Centralized pydantic-settings config
services/
  parser/           # Paper parsing (GROBID + LaTeX + arXiv source)
  embedding.py      # Tongyi embedding + rerank (text-embedding-v4, gte-rerank-v2)
  storage.py        # Object storage
  export.py         # Report generation
tests/              # pytest test suite
```

## Key Conventions

- All API routes under `/api/v1/`
- Pydantic models in `libs/schemas/`
- Database CRUD in `apps/api/database.py` (single file)
- LLM calls through `apps/worker/llm_gateway.py` via `get_gateway()`
- **Structured output**: `chat_json()` uses LangChain `with_structured_output` (function calling) first, falls back to prompt+regex
- **Progress events**: Worker nodes call `emit_progress(run_id, stage, action, detail)` for fine-grained UI updates
- Config via `libs/config.py` (pydantic-settings) or `os.getenv()` with `.env`
- Structured logging via `structlog`
- Immutable data patterns (new objects, never mutate)

## Testing Strategy

### Test files

| File | Type | Requires | Duration |
|------|------|----------|----------|
| `tests/test_schemas.py` | Unit | Nothing | <1s |
| `tests/test_multimode_schemas.py` | Unit | Nothing | <1s |
| `tests/test_mode_router.py` | Unit | Nothing | <1s |
| `tests/test_database_v2.py` | Unit (mocked) | Nothing | <1s |
| `tests/test_api_v2.py` | Unit (mocked) | Nothing | <1s |
| `tests/test_embedding.py` | Unit (mocked) | Nothing | <1s |
| `tests/test_e2e_modes.py` | Integration | API running | ~2s |
| `tests/test_e2e_full_workflow.py` | Full E2E | API + Worker | **8-10 min** |

### Full workflow E2E test (`test_e2e_full_workflow.py`)

Tests the complete Frontier mode lifecycle:

1. **Create** run with topic, keywords, seed paper → verify 201, mode=frontier
2. **Start** run → verify enqueued to Redis
3. **Sidebar** → verify appears in run list
4. **Events** → verify run.created and run.started exist
5. **Wait** for completion → poll every 30s, max 10 min
6. **Progress events** → verify all 7 stages emitted events (scope_definition through frontier_summary)
7. **Sub-endpoints** → verify pain-points, idea-cards, timeline, taxonomy, mindmap, comparison all return 200
8. **Final state** → verify status=completed, progress=100%, timestamps set
9. **Sidebar persistence** → verify still in list after completion
10. **Spawn** → verify can create Divergent child from completed Frontier

### When to run E2E

- After modifying `apps/worker/modes/frontier.py` or any mode node
- After modifying `apps/worker/runner.py` (task dispatch)
- After modifying `apps/api/routes_v2.py` (API contract changes)
- After modifying `apps/worker/llm_gateway.py` (LLM call changes)
- Before merging to main

## Git

- Remote: https://github.com/bragi17/research-os
- Branch: `main`
- `.env` and `research_os_docs/` are in `.gitignore` — never commit them

## Known Issues

- `yunwu.ai` proxy frequently returns 429 (rate limit) — structured output auto-falls back to prompt-based extraction
- S2 API sometimes returns CorpusId as int (not str) — `external_ids` typed as `dict[str, Any]` to handle this
- Some arXiv IDs from OpenAlex are malformed (e.g., `2017.26707`) — parser gracefully skips with warning
- Frontend uses Tailwind **v3** (not v4) — v4's `@import "tailwindcss"` doesn't work with Next.js Turbopack
