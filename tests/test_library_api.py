"""
Tests for the Paper Library API endpoints.

Verifies:
- POST /api/v1/library/papers returns 201
- GET /api/v1/library/papers returns {items, total}
- GET /api/v1/library/papers/{id} returns 404 for missing
- DELETE /api/v1/library/papers/{id} returns 404 for missing
- GET /api/v1/library/search/titles?q=test returns {items}
- GET /api/v1/library/stats returns {papers, chunks}

Uses the same mock pattern as tests/test_api_v2.py.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# In-memory mock state for database.py (shared app-level mocks)
# ---------------------------------------------------------------------------

_mock_runs: dict[str, dict[str, Any]] = {}
_mock_events: list[dict[str, Any]] = []

# Library-specific mock state
_mock_library_papers: dict[str, dict[str, Any]] = {}
_mock_library_chunks: dict[str, list[dict[str, Any]]] = {}


def _make_mock_run(run_data: dict[str, Any]) -> dict[str, Any]:
    now = datetime.utcnow()
    base: dict[str, Any] = {
        "workspace_id": UUID("00000000-0000-0000-0000-000000000000"),
        "created_by": UUID("00000000-0000-0000-0000-000000000000"),
        "title": "Test Research Run",
        "topic": "Multi-agent coordination with shared memory",
        "status": "queued",
        "goal_type": "survey_plus_innovations",
        "autonomy_mode": "default_autonomous",
        "budget_json": {},
        "policy_json": {},
        "current_step": None,
        "progress_pct": Decimal("0"),
        "started_at": None,
        "completed_at": None,
        "created_at": now,
        "updated_at": now,
        "pause_reason": None,
        "mode": "intake",
        "parent_run_id": None,
        "context_bundle_id": None,
        "output_bundle_id": None,
        "current_stage": "init",
    }
    base.update(run_data)
    return base


# ---------------------------------------------------------------------------
# Mock database functions (apps.api.database — needed for app startup)
# ---------------------------------------------------------------------------


async def mock_init_pool() -> None:
    pass


async def mock_close_pool() -> None:
    pass


async def mock_create_run(run_data: dict[str, Any]) -> dict[str, Any]:
    run = _make_mock_run(run_data)
    _mock_runs[str(run_data["id"])] = run
    return run


async def mock_get_run(run_id: UUID) -> dict[str, Any] | None:
    return _mock_runs.get(str(run_id))


async def mock_list_runs(
    status: str | None = None, limit: int = 20, offset: int = 0
) -> list[dict[str, Any]]:
    runs = list(_mock_runs.values())
    if status:
        runs = [r for r in runs if r["status"] == status]
    return runs[offset : offset + limit]


async def mock_update_run(
    run_id: UUID, updates: dict[str, Any]
) -> dict[str, Any] | None:
    key = str(run_id)
    if key in _mock_runs:
        _mock_runs[key] = {**_mock_runs[key], **updates}
        return _mock_runs[key]
    return None


async def mock_create_event(
    run_id: UUID,
    event_type: str,
    severity: str = "info",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    evt: dict[str, Any] = {
        "id": len(_mock_events) + 1,
        "run_id": run_id,
        "event_type": event_type,
        "severity": severity,
        "payload": payload or {},
        "created_at": datetime.utcnow(),
    }
    _mock_events.append(evt)
    return evt


async def mock_list_events(
    run_id: UUID, limit: int = 100, offset: int = 0
) -> list[dict[str, Any]]:
    return []


async def mock_count_events(run_id: UUID) -> int:
    return 0


async def mock_count_runs(status: str | None = None) -> int:
    return len(_mock_runs)


async def mock_count_runs_by_status() -> dict[str, int]:
    return {}


async def mock_list_hypotheses(run_id: UUID) -> list[dict[str, Any]]:
    return []


async def mock_list_papers_by_run(
    run_id: UUID, limit: int = 50, offset: int = 0
) -> list[dict[str, Any]]:
    return []


async def mock_count_papers_by_run(run_id: UUID) -> int:
    return 0


async def mock_list_pain_points(
    run_id: UUID, limit: int = 50, offset: int = 0
) -> list[dict[str, Any]]:
    return []


async def mock_list_idea_cards(
    run_id: UUID, limit: int = 50, offset: int = 0
) -> list[dict[str, Any]]:
    return []


async def mock_list_figures_by_run(
    run_id: UUID, limit: int = 50
) -> list[dict[str, Any]]:
    return []


async def mock_get_reading_path(run_id: UUID) -> dict[str, Any] | None:
    return None


async def mock_get_context_bundle(bundle_id: UUID) -> dict[str, Any] | None:
    return None


async def mock_create_context_bundle(data: dict[str, Any]) -> dict[str, Any]:
    return {"id": uuid4(), **data}


# ---------------------------------------------------------------------------
# Mock library tools_db functions
# ---------------------------------------------------------------------------


async def mock_insert_library_paper(data: dict[str, Any]) -> dict[str, Any]:
    paper_id = uuid4()
    now = datetime.utcnow()
    paper: dict[str, Any] = {
        "id": paper_id,
        "title": data["title"],
        "arxiv_id": data.get("arxiv_id"),
        "authors": data.get("authors", []),
        "year": data.get("year"),
        "field": data.get("field"),
        "sub_field": data.get("sub_field"),
        "status": data.get("status", "pending"),
        "keywords": data.get("keywords", []),
        "methods": data.get("methods", []),
        "datasets": data.get("datasets", []),
        "benchmarks": data.get("benchmarks", []),
        "innovation_points": data.get("innovation_points", []),
        "project_tags": data.get("project_tags", []),
        "created_at": now,
        "updated_at": now,
    }
    _mock_library_papers[str(paper_id)] = paper
    return paper


async def mock_get_library_paper(paper_id: UUID) -> dict[str, Any] | None:
    return _mock_library_papers.get(str(paper_id))


async def mock_list_library_papers(
    field: str | None = None,
    project_tag: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    papers = list(_mock_library_papers.values())
    if field:
        papers = [p for p in papers if p.get("field") == field]
    if project_tag:
        papers = [p for p in papers if project_tag in p.get("project_tags", [])]
    return papers[offset : offset + limit]


async def mock_delete_library_paper(paper_id: UUID) -> bool:
    key = str(paper_id)
    if key in _mock_library_papers:
        del _mock_library_papers[key]
        return True
    return False


async def mock_update_library_paper(
    paper_id: UUID, updates: dict[str, Any]
) -> dict[str, Any] | None:
    key = str(paper_id)
    if key in _mock_library_papers:
        _mock_library_papers[key] = {**_mock_library_papers[key], **updates}
        return _mock_library_papers[key]
    return None


async def mock_insert_library_chunks(
    library_paper_id: UUID, chunks: list[dict[str, Any]]
) -> int:
    key = str(library_paper_id)
    _mock_library_chunks.setdefault(key, []).extend(chunks)
    return len(chunks)


async def mock_search_library_vectors(
    query_embedding: list[float],
    limit: int = 30,
    field: str | None = None,
) -> list[dict[str, Any]]:
    return []


async def mock_search_library_text(
    query: str, limit: int = 20
) -> list[dict[str, Any]]:
    pattern = query.lower()
    results = [
        p
        for p in _mock_library_papers.values()
        if pattern in p.get("title", "").lower()
    ]
    return results[:limit]


async def mock_count_library_papers() -> int:
    return len(_mock_library_papers)


async def mock_count_library_chunks() -> int:
    total = 0
    for chunks in _mock_library_chunks.values():
        total += len(chunks)
    return total


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_mock_state():
    """Reset mock data stores before each test."""
    _mock_runs.clear()
    _mock_events.clear()
    _mock_library_papers.clear()
    _mock_library_chunks.clear()


@pytest.fixture()
def client():
    """Create a FastAPI TestClient with all external dependencies mocked."""
    db_patches = {
        "apps.api.database.init_pool": AsyncMock(side_effect=mock_init_pool),
        "apps.api.database.close_pool": AsyncMock(side_effect=mock_close_pool),
        "apps.api.database.create_run": AsyncMock(side_effect=mock_create_run),
        "apps.api.database.get_run": AsyncMock(side_effect=mock_get_run),
        "apps.api.database.list_runs": AsyncMock(side_effect=mock_list_runs),
        "apps.api.database.update_run": AsyncMock(side_effect=mock_update_run),
        "apps.api.database.create_event": AsyncMock(side_effect=mock_create_event),
        "apps.api.database.list_events": AsyncMock(side_effect=mock_list_events),
        "apps.api.database.count_events": AsyncMock(side_effect=mock_count_events),
        "apps.api.database.count_runs": AsyncMock(side_effect=mock_count_runs),
        "apps.api.database.count_runs_by_status": AsyncMock(
            side_effect=mock_count_runs_by_status
        ),
        "apps.api.database.list_hypotheses": AsyncMock(
            side_effect=mock_list_hypotheses
        ),
        "apps.api.database.list_papers_by_run": AsyncMock(
            side_effect=mock_list_papers_by_run
        ),
        "apps.api.database.count_papers_by_run": AsyncMock(
            side_effect=mock_count_papers_by_run
        ),
        "apps.api.database.get_pool": AsyncMock(return_value=MagicMock()),
        # v2 database mocks
        "apps.api.database.list_pain_points": AsyncMock(
            side_effect=mock_list_pain_points
        ),
        "apps.api.database.list_idea_cards": AsyncMock(
            side_effect=mock_list_idea_cards
        ),
        "apps.api.database.list_figures_by_run": AsyncMock(
            side_effect=mock_list_figures_by_run
        ),
        "apps.api.database.get_reading_path": AsyncMock(
            side_effect=mock_get_reading_path
        ),
        "apps.api.database.get_context_bundle": AsyncMock(
            side_effect=mock_get_context_bundle
        ),
        "apps.api.database.create_context_bundle": AsyncMock(
            side_effect=mock_create_context_bundle
        ),
    }

    library_patches = {
        "services.library.tools_db.insert_library_paper": AsyncMock(
            side_effect=mock_insert_library_paper
        ),
        "services.library.tools_db.get_library_paper": AsyncMock(
            side_effect=mock_get_library_paper
        ),
        "services.library.tools_db.list_library_papers": AsyncMock(
            side_effect=mock_list_library_papers
        ),
        "services.library.tools_db.delete_library_paper": AsyncMock(
            side_effect=mock_delete_library_paper
        ),
        "services.library.tools_db.update_library_paper": AsyncMock(
            side_effect=mock_update_library_paper
        ),
        "services.library.tools_db.insert_library_chunks": AsyncMock(
            side_effect=mock_insert_library_chunks
        ),
        "services.library.tools_db.search_library_vectors": AsyncMock(
            side_effect=mock_search_library_vectors
        ),
        "services.library.tools_db.search_library_text": AsyncMock(
            side_effect=mock_search_library_text
        ),
        "services.library.tools_db.count_library_papers": AsyncMock(
            side_effect=mock_count_library_papers
        ),
        "services.library.tools_db.count_library_chunks": AsyncMock(
            side_effect=mock_count_library_chunks
        ),
    }

    all_patches = {**db_patches, **library_patches}
    patches = [patch(target, new=mock_fn) for target, mock_fn in all_patches.items()]
    for p in patches:
        p.start()

    try:
        import importlib
        import apps.api.routes_library as routes_library_mod
        import apps.api.routes_v2 as routes_v2_mod
        import apps.api.main as main_mod

        importlib.reload(routes_library_mod)
        importlib.reload(routes_v2_mod)
        importlib.reload(main_mod)
        app = main_mod.app
        main_mod._redis = None

        with TestClient(app) as c:
            yield c
    finally:
        for p in reversed(patches):
            p.stop()


# ===================================================================
# POST /api/v1/library/papers
# ===================================================================


class TestAddPaper:
    """Test POST /api/v1/library/papers."""

    def test_add_paper_returns_201(self, client: TestClient):
        r = client.post(
            "/api/v1/library/papers",
            json={"title": "Attention Is All You Need", "year": 2017},
        )
        assert r.status_code == 201
        data = r.json()
        assert data["title"] == "Attention Is All You Need"
        assert "id" in data

    def test_add_paper_missing_title_returns_400(self, client: TestClient):
        r = client.post("/api/v1/library/papers", json={"year": 2023})
        assert r.status_code == 400
        assert "title is required" in r.json()["detail"]

    def test_add_paper_with_field(self, client: TestClient):
        r = client.post(
            "/api/v1/library/papers",
            json={
                "title": "BERT: Pre-training",
                "field": "NLP",
                "keywords": ["transformers", "pre-training"],
            },
        )
        assert r.status_code == 201
        data = r.json()
        assert data["field"] == "NLP"
        assert data["keywords"] == ["transformers", "pre-training"]


# ===================================================================
# GET /api/v1/library/papers
# ===================================================================


class TestListPapers:
    """Test GET /api/v1/library/papers."""

    def test_list_papers_returns_items_and_total(self, client: TestClient):
        # Add a paper first
        client.post(
            "/api/v1/library/papers",
            json={"title": "Test Paper 1"},
        )
        r = client.get("/api/v1/library/papers")
        assert r.status_code == 200
        data = r.json()
        assert "items" in data
        assert "total" in data
        assert data["total"] == 1
        assert len(data["items"]) == 1

    def test_list_papers_empty(self, client: TestClient):
        r = client.get("/api/v1/library/papers")
        assert r.status_code == 200
        data = r.json()
        assert data["items"] == []
        assert data["total"] == 0


# ===================================================================
# GET /api/v1/library/papers/{id}
# ===================================================================


class TestGetPaper:
    """Test GET /api/v1/library/papers/{id}."""

    def test_get_paper_returns_404_for_missing(self, client: TestClient):
        missing_id = str(uuid4())
        r = client.get(f"/api/v1/library/papers/{missing_id}")
        assert r.status_code == 404
        assert "Paper not found" in r.json()["detail"]

    def test_get_paper_returns_paper(self, client: TestClient):
        create_r = client.post(
            "/api/v1/library/papers",
            json={"title": "Retrievable Paper"},
        )
        paper_id = create_r.json()["id"]
        r = client.get(f"/api/v1/library/papers/{paper_id}")
        assert r.status_code == 200
        assert r.json()["title"] == "Retrievable Paper"


# ===================================================================
# DELETE /api/v1/library/papers/{id}
# ===================================================================


class TestDeletePaper:
    """Test DELETE /api/v1/library/papers/{id}."""

    def test_delete_paper_returns_404_for_missing(self, client: TestClient):
        missing_id = str(uuid4())
        r = client.delete(f"/api/v1/library/papers/{missing_id}")
        assert r.status_code == 404
        assert "Paper not found" in r.json()["detail"]

    def test_delete_paper_succeeds(self, client: TestClient):
        create_r = client.post(
            "/api/v1/library/papers",
            json={"title": "Deletable Paper"},
        )
        paper_id = create_r.json()["id"]
        r = client.delete(f"/api/v1/library/papers/{paper_id}")
        assert r.status_code == 200
        assert r.json()["status"] == "deleted"

        # Verify it's gone
        r2 = client.get(f"/api/v1/library/papers/{paper_id}")
        assert r2.status_code == 404


# ===================================================================
# PATCH /api/v1/library/papers/{id}
# ===================================================================


class TestPatchPaper:
    """Test PATCH /api/v1/library/papers/{id}."""

    def test_patch_paper_returns_404_for_missing(self, client: TestClient):
        missing_id = str(uuid4())
        r = client.patch(
            f"/api/v1/library/papers/{missing_id}",
            json={"status": "analyzed"},
        )
        assert r.status_code == 404

    def test_patch_paper_updates_fields(self, client: TestClient):
        create_r = client.post(
            "/api/v1/library/papers",
            json={"title": "Patchable Paper"},
        )
        paper_id = create_r.json()["id"]
        r = client.patch(
            f"/api/v1/library/papers/{paper_id}",
            json={"status": "analyzed", "field": "CV"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "analyzed"
        assert data["field"] == "CV"


# ===================================================================
# POST /api/v1/library/papers/{id}/analyze
# ===================================================================


class TestAnalyzePaper:
    """Test POST /api/v1/library/papers/{id}/analyze."""

    def test_analyze_returns_404_for_missing(self, client: TestClient):
        missing_id = str(uuid4())
        r = client.post(f"/api/v1/library/papers/{missing_id}/analyze")
        assert r.status_code == 404

    def test_analyze_returns_queued(self, client: TestClient):
        create_r = client.post(
            "/api/v1/library/papers",
            json={"title": "Analyzable Paper"},
        )
        paper_id = create_r.json()["id"]
        r = client.post(f"/api/v1/library/papers/{paper_id}/analyze")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "queued"
        assert data["paper_id"] == paper_id


# ===================================================================
# GET /api/v1/library/search/titles?q=
# ===================================================================


class TestSearchTitles:
    """Test GET /api/v1/library/search/titles."""

    def test_search_titles_returns_items(self, client: TestClient):
        client.post(
            "/api/v1/library/papers",
            json={"title": "Attention Is All You Need"},
        )
        client.post(
            "/api/v1/library/papers",
            json={"title": "BERT Pre-training"},
        )
        r = client.get("/api/v1/library/search/titles?q=attention")
        assert r.status_code == 200
        data = r.json()
        assert "items" in data
        assert len(data["items"]) == 1
        assert data["items"][0]["title"] == "Attention Is All You Need"

    def test_search_titles_empty_result(self, client: TestClient):
        r = client.get("/api/v1/library/search/titles?q=nonexistent")
        assert r.status_code == 200
        data = r.json()
        assert data["items"] == []
        assert data["total"] == 0


# ===================================================================
# GET /api/v1/library/stats
# ===================================================================


class TestStats:
    """Test GET /api/v1/library/stats."""

    def test_stats_returns_papers_and_chunks(self, client: TestClient):
        r = client.get("/api/v1/library/stats")
        assert r.status_code == 200
        data = r.json()
        assert "papers" in data
        assert "chunks" in data
        assert data["papers"] == 0
        assert data["chunks"] == 0

    def test_stats_counts_papers(self, client: TestClient):
        client.post(
            "/api/v1/library/papers",
            json={"title": "Paper A"},
        )
        client.post(
            "/api/v1/library/papers",
            json={"title": "Paper B"},
        )
        r = client.get("/api/v1/library/stats")
        assert r.status_code == 200
        data = r.json()
        assert data["papers"] == 2


# ===================================================================
# GET /api/v1/library/search (hybrid search — fallback to text)
# ===================================================================


class TestHybridSearch:
    """Test GET /api/v1/library/search (falls back to text search on error)."""

    def test_search_returns_items(self, client: TestClient):
        client.post(
            "/api/v1/library/papers",
            json={"title": "Transformer Networks for NLP"},
        )
        r = client.get("/api/v1/library/search?q=transformer")
        assert r.status_code == 200
        data = r.json()
        assert "items" in data
        assert "total" in data
