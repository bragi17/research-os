# Aggressive Architecture Cleanup Design

## Goal

Make the repository easier to maintain by removing generated clutter, normalizing module boundaries, and breaking large API, worker, and frontend files into smaller units without changing public API behavior.

## Scope

This cleanup is intentionally aggressive, but it is still behavior-preserving unless a change is clearly dead or generated code cleanup.

In scope:

- Remove generated files from git and ignore future generated output, especially `apps/web/tsconfig.tsbuildinfo`.
- Decide the existing uncommitted library changes case by case. Keep useful behavior only if it has a clear API/UI path and test coverage; remove or rewrite fragile code.
- Split `apps/api/main.py` into focused routers for app setup, auth, runs, files, queue/status, and exports while preserving current URL paths.
- Keep `apps/api/routes_library.py`, `apps/api/routes_settings.py`, and `apps/api/routes_v2.py` as feature routers, but move shared helpers out of route files where they are not request-specific.
- Split the database layer into domain modules while keeping existing public database function imports working during the transition.
- Move worker graph code toward mode-local packages or helper modules so large mode files stop owning prompts, retrieval, reading, synthesis, and graph wiring all at once.
- Keep DeepSeek-only LLM behavior from the prior work and keep DashScope embedding/rerank paths unchanged.
- Split large frontend pages into route-level page files plus reusable components/hooks under `apps/web/src/features` or `apps/web/src/lib`.
- Ensure repository cleanliness: no untracked generated files, no tracked build artifacts, no stale temporary plan docs unless intentionally committed.

Out of scope:

- Changing API routes, request/response contracts, database schema, or UI workflows except where tests prove the old behavior was dead or broken.
- Rewriting the research algorithms or LangGraph workflows for new behavior.
- Replacing the storage, Redis, database, or frontend framework.
- Deleting historical design/spec docs that are already tracked and useful.

## Current Findings

- `apps/api/main.py` is over 1100 lines and mixes app construction, auth routes, run CRUD, queue/event helpers, SSE, file upload, export, and status endpoints.
- `apps/api/database.py` is over 800 lines and mixes connection lifecycle with run, event, paper, pain point, idea card, context bundle, figure, domain, and reading path data access.
- Worker mode files such as `apps/worker/modes/frontier.py` and `apps/worker/modes/atlas.py` exceed 1000 lines and combine prompts, retrieval, reading, synthesis, and graph construction.
- Frontend route files such as `apps/web/src/app/library/page.tsx` and `apps/web/src/app/settings/page.tsx` contain page rendering, API orchestration, constants, and workflow state in one file.
- `apps/web/tsconfig.tsbuildinfo` is tracked and changes after builds; it should be removed from git and ignored.
- The existing uncommitted library changes add a favicon, re-analysis UI, and backend re-analysis behavior. They should not be blindly discarded, but need validation and tests before being kept.
- The previous DeepSeek migration plan file is untracked and should not be committed unless converted into a useful maintained doc.

## Target Architecture

### API

`apps/api/main.py` should become a small composition root:

- Create the `FastAPI` app and lifespan.
- Include routers.
- Configure CORS and health/status endpoints only if they are not moved into a router.

New or reorganized API files:

- `apps/api/app.py`: app factory and middleware wiring.
- `apps/api/routes_auth.py`: register, login, current user.
- `apps/api/routes_runs.py`: run CRUD and run lifecycle endpoints.
- `apps/api/routes_events.py`: event listing and SSE streaming.
- `apps/api/routes_exports.py`: export and download endpoints.
- `apps/api/routes_files.py`: file upload endpoints.
- `apps/api/routes_queue.py`: queue/status endpoints.
- `apps/api/queue.py`: Redis queue and event publishing helpers.

The external URL paths remain the same.

### Database

`apps/api/database.py` should be kept as a compatibility facade while implementation moves into smaller files:

- `apps/api/db/pool.py`: pool lifecycle and codecs.
- `apps/api/db/records.py`: record conversion and JSON serialization helpers.
- `apps/api/db/runs.py`: run CRUD and run counts.
- `apps/api/db/events.py`: event create/list/count.
- `apps/api/db/multimode.py`: pain points, idea cards, context bundles, figures, domains, reading paths.

Existing imports from `apps.api.database` remain valid by re-exporting functions until the rest of the codebase is migrated.

### Worker

Worker cleanup should be incremental because the mode files encode business logic.

New structure:

- `apps/worker/llm/`: LLM gateway and related types, replacing the single `apps/worker/llm_gateway.py` entry point with a compatibility shim.
- `apps/worker/modes/common/`: reusable retrieval, reading, prompt, graph, and formatting helpers.
- `apps/worker/modes/<mode>/`: mode-specific prompts, nodes, and graph wiring for atlas/frontier/divergent/review.

The first worker cleanup batch should move shared helpers and keep current imports working. Splitting every mode node in one commit is too risky; it should be staged by mode.

### Frontend

Frontend route pages should be thin route shells.

New structure:

- `apps/web/src/features/library/`: library components, constants, hooks, and API orchestration.
- `apps/web/src/features/settings/`: settings panel components and hooks.
- `apps/web/src/lib/api.ts`: keep low-level HTTP wrappers and add missing wrappers instead of raw `fetch` in pages.

The library re-analysis behavior should be kept only if it gets a typed API wrapper and tests/build coverage.

## Git And Cleanliness Rules

- Work on `main`, as previously approved by the user.
- Never use `git add .`.
- Preserve or deliberately replace useful uncommitted changes; do not silently lose behavior.
- Remove generated tracked files with `git rm --cached` where appropriate.
- Add ignore rules for generated build artifacts and local tool output.
- Keep `.codegraph/`, `.next/`, `node_modules/`, `.pytest_cache/`, `__pycache__/`, untracked temporary plans, and local runtime artifacts out of git.
- Run secret scans before commits. No real API keys or production-looking `sk-...` values may enter tracked files.

## Verification Strategy

Each batch must have focused tests plus final verification:

- Backend non-E2E suite: `PYTHONPATH=/root/research-os .venv/bin/python -m pytest tests/ -v --ignore=tests/test_e2e.py --ignore=tests/test_e2e_full_workflow.py`
- Frontend build: `cd apps/web && npm run build`
- Targeted tests for any moved API/database/worker behavior.
- Secret scan: strict `sk-[A-Za-z0-9]{20,}` scan excluding generated dependency/build directories.
- Legacy LLM scan: no production OpenAI/GPT/Claude LLM configuration strings outside allowed compatibility imports and negative tests.
- Final `git status --short` must be clean, except no exceptions: generated/untracked cleanup should be resolved before completion.

## Acceptance Criteria

- Repository status is clean at completion.
- Generated files are not tracked and do not reappear as untracked after tests/builds.
- Existing public API tests pass without route changes.
- Settings and DeepSeek credential behavior from the previous work remains intact.
- DashScope embedding/rerank tests remain unchanged and passing.
- Large files are reduced where practical in the first pass, and any remaining large business-logic files have a documented staged split plan.
- Useful library re-analysis changes are either integrated with tests or deliberately removed.
