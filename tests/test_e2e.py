"""
End-to-end integration tests for the Research OS API.

Tests the complete API flow: create run -> start -> check events -> export.
Uses FastAPI TestClient with mocked database layer.
"""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# In-memory mock state
# ---------------------------------------------------------------------------

_mock_runs: dict[str, dict[str, Any]] = {}
_mock_events: list[dict[str, Any]] = []
_mock_hypotheses: list[dict[str, Any]] = []


def _make_mock_run(run_data: dict[str, Any]) -> dict[str, Any]:
    """Create a mock run record with sensible defaults."""
    now = datetime.utcnow()
    base: dict[str, Any] = {
        "workspace_id": UUID("00000000-0000-0000-0000-000000000000"),
        "created_by": UUID("00000000-0000-0000-0000-000000000000"),
        "title": "Test Research Run",
        "topic": "Multi-agent coordination with shared memory",
        "status": "queued",
        "goal_type": "survey_plus_innovations",
        "autonomy_mode": "default_autonomous",
        "budget_json": {"max_new_papers": 50, "max_fulltext_reads": 10},
        "policy_json": {},
        "current_step": None,
        "progress_pct": Decimal("0"),
        "started_at": None,
        "completed_at": None,
        "created_at": now,
        "updated_at": now,
        "pause_reason": None,
    }
    base.update(run_data)
    # Ensure progress_pct is Decimal (RunResponse expects it)
    if not isinstance(base["progress_pct"], Decimal):
        base["progress_pct"] = Decimal(str(base["progress_pct"]))
    return base


# ---------------------------------------------------------------------------
# Mock database functions
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
    status: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[dict[str, Any]]:
    runs = list(_mock_runs.values())
    if status:
        runs = [r for r in runs if r["status"] == status]
    return runs[offset : offset + limit]


async def mock_update_run(
    run_id: UUID,
    updates: dict[str, Any],
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
    run_id: UUID,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    events = [e for e in _mock_events if str(e["run_id"]) == str(run_id)]
    events.sort(key=lambda e: e["created_at"], reverse=True)
    return events[offset : offset + limit]


async def mock_count_events(run_id: UUID) -> int:
    return len([e for e in _mock_events if str(e["run_id"]) == str(run_id)])


async def mock_count_runs(status: str | None = None) -> int:
    if status:
        return len([r for r in _mock_runs.values() if r["status"] == status])
    return len(_mock_runs)


async def mock_count_runs_by_status() -> dict[str, int]:
    from collections import Counter

    c = Counter(r["status"] for r in _mock_runs.values())
    return dict(c)


async def mock_list_hypotheses(run_id: UUID) -> list[dict[str, Any]]:
    return [h for h in _mock_hypotheses if str(h.get("run_id")) == str(run_id)]


async def mock_list_papers_by_run(
    run_id: UUID,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    return []


async def mock_count_papers_by_run(run_id: UUID) -> int:
    return 0


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_mock_state():
    """Reset mock data stores before each test."""
    _mock_runs.clear()
    _mock_events.clear()
    _mock_hypotheses.clear()


@pytest.fixture()
def client():
    """Create a FastAPI TestClient with all external dependencies mocked.

    The database module and Redis connections are replaced with in-memory
    implementations so no PostgreSQL or Redis process is required.
    """
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
        # The auth module also calls database.get_pool; stub it so imports
        # don't attempt a real connection.
        "apps.api.database.get_pool": AsyncMock(return_value=MagicMock()),
    }

    # Stack all database patches
    patches = [patch(target, new=mock_fn) for target, mock_fn in db_patches.items()]

    for p in patches:
        p.start()

    try:
        # Force reimport so the patched symbols are picked up
        import importlib
        import apps.api.main as main_mod

        importlib.reload(main_mod)
        app = main_mod.app

        # Disable Redis by setting the module-level _redis to None
        main_mod._redis = None

        with TestClient(app) as c:
            yield c
    finally:
        for p in reversed(patches):
            p.stop()


# ===================================================================
# Health & Status
# ===================================================================


class TestHealthEndpoints:
    """Verify health-check and system status endpoints."""

    def test_health_check(self, client: TestClient):
        r = client.get("/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "healthy"
        assert data["service"] == "research-os-api"

    def test_system_status(self, client: TestClient):
        r = client.get("/api/v1/status")
        assert r.status_code == 200
        data = r.json()
        assert "runs_total" in data
        assert "runs_by_status" in data
        assert data["runs_total"] == 0

    def test_system_status_reflects_runs(self, client: TestClient):
        """Status counts should update after creating runs."""
        client.post(
            "/api/v1/runs",
            json={
                "title": "Status Test",
                "topic": "Multi-agent coordination with shared memory",
            },
        )
        r = client.get("/api/v1/status")
        data = r.json()
        assert data["runs_total"] == 1
        assert data["runs_by_status"]["queued"] == 1


# ===================================================================
# Run CRUD
# ===================================================================


class TestRunLifecycle:
    """Test the complete run lifecycle: create -> start -> pause -> resume -> cancel."""

    def _create_run(self, client: TestClient, **overrides: Any) -> dict[str, Any]:
        """Helper: create a run and return the response body."""
        payload: dict[str, Any] = {
            "title": "Test Research",
            "topic": "Multi-agent coordination with shared memory mechanisms",
        }
        payload.update(overrides)
        r = client.post("/api/v1/runs", json=payload)
        assert r.status_code == 201
        return r.json()

    # -- Create --------------------------------------------------------

    def test_create_run(self, client: TestClient):
        data = self._create_run(client)
        assert data["status"] == "queued"
        assert data["title"] == "Test Research"
        assert "id" in data

    def test_create_run_with_custom_goal_type(self, client: TestClient):
        data = self._create_run(client, goal_type="survey")
        assert data["goal_type"] == "survey"

    def test_create_run_validation_short_title(self, client: TestClient):
        r = client.post(
            "/api/v1/runs",
            json={"title": "Ab", "topic": "Multi-agent coordination with shared memory"},
        )
        assert r.status_code == 422  # Pydantic validation error

    def test_create_run_validation_short_topic(self, client: TestClient):
        r = client.post("/api/v1/runs", json={"title": "Valid Title", "topic": "short"})
        assert r.status_code == 422

    # -- List ----------------------------------------------------------

    def test_list_runs_empty(self, client: TestClient):
        r = client.get("/api/v1/runs")
        assert r.status_code == 200
        assert r.json() == []

    def test_list_runs(self, client: TestClient):
        self._create_run(client)
        self._create_run(client, title="Second Run")
        r = client.get("/api/v1/runs")
        assert r.status_code == 200
        assert len(r.json()) == 2

    def test_list_runs_filter_by_status(self, client: TestClient):
        self._create_run(client)
        r = client.get("/api/v1/runs", params={"status": "running"})
        assert r.status_code == 200
        assert r.json() == []  # all are queued, none running

    # -- Get -----------------------------------------------------------

    def test_get_run(self, client: TestClient):
        created = self._create_run(client)
        run_id = created["id"]
        r = client.get(f"/api/v1/runs/{run_id}")
        assert r.status_code == 200
        assert r.json()["id"] == run_id

    def test_get_nonexistent_run(self, client: TestClient):
        fake_id = str(uuid4())
        r = client.get(f"/api/v1/runs/{fake_id}")
        assert r.status_code == 404

    # -- Start ---------------------------------------------------------

    def test_start_run(self, client: TestClient):
        created = self._create_run(client)
        run_id = created["id"]
        r = client.post(f"/api/v1/runs/{run_id}/start")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "started"
        assert body["run_id"] == run_id

    def test_start_nonexistent_run(self, client: TestClient):
        r = client.post(f"/api/v1/runs/{uuid4()}/start")
        assert r.status_code == 404

    def test_cannot_start_completed_run(self, client: TestClient):
        created = self._create_run(client)
        run_id = created["id"]
        _mock_runs[run_id]["status"] = "completed"
        r = client.post(f"/api/v1/runs/{run_id}/start")
        assert r.status_code == 400

    def test_cannot_start_cancelled_run(self, client: TestClient):
        created = self._create_run(client)
        run_id = created["id"]
        _mock_runs[run_id]["status"] = "cancelled"
        r = client.post(f"/api/v1/runs/{run_id}/start")
        assert r.status_code == 400

    def test_cannot_start_running_run(self, client: TestClient):
        created = self._create_run(client)
        run_id = created["id"]
        _mock_runs[run_id]["status"] = "running"
        r = client.post(f"/api/v1/runs/{run_id}/start")
        assert r.status_code == 400

    # -- Pause ---------------------------------------------------------

    def test_pause_running_run(self, client: TestClient):
        created = self._create_run(client)
        run_id = created["id"]
        client.post(f"/api/v1/runs/{run_id}/start")
        r = client.post(f"/api/v1/runs/{run_id}/pause", json={"mode": "soft"})
        assert r.status_code == 200
        assert r.json()["status"] == "paused"

    def test_pause_hard_mode(self, client: TestClient):
        created = self._create_run(client)
        run_id = created["id"]
        client.post(f"/api/v1/runs/{run_id}/start")
        r = client.post(f"/api/v1/runs/{run_id}/pause", json={"mode": "hard"})
        assert r.status_code == 200
        assert r.json()["mode"] == "hard"

    def test_cannot_pause_queued_run(self, client: TestClient):
        created = self._create_run(client)
        run_id = created["id"]
        r = client.post(f"/api/v1/runs/{run_id}/pause", json={"mode": "soft"})
        assert r.status_code == 400

    # -- Resume --------------------------------------------------------

    def test_resume_paused_run(self, client: TestClient):
        created = self._create_run(client)
        run_id = created["id"]
        client.post(f"/api/v1/runs/{run_id}/start")
        client.post(f"/api/v1/runs/{run_id}/pause", json={"mode": "soft"})
        r = client.post(f"/api/v1/runs/{run_id}/resume", json={})
        assert r.status_code == 200
        assert r.json()["status"] == "resumed"

    def test_resume_with_patch(self, client: TestClient):
        created = self._create_run(client)
        run_id = created["id"]
        client.post(f"/api/v1/runs/{run_id}/start")
        client.post(f"/api/v1/runs/{run_id}/pause", json={"mode": "soft"})
        r = client.post(
            f"/api/v1/runs/{run_id}/resume",
            json={"patch": {"max_papers": 200}},
        )
        assert r.status_code == 200
        assert r.json()["patch_applied"] == {"max_papers": 200}

    def test_cannot_resume_queued_run(self, client: TestClient):
        created = self._create_run(client)
        run_id = created["id"]
        r = client.post(f"/api/v1/runs/{run_id}/resume", json={})
        assert r.status_code == 400

    # -- Cancel --------------------------------------------------------

    def test_cancel_queued_run(self, client: TestClient):
        created = self._create_run(client)
        run_id = created["id"]
        r = client.post(f"/api/v1/runs/{run_id}/cancel")
        assert r.status_code == 200
        assert r.json()["status"] == "cancelled"

    def test_cancel_running_run(self, client: TestClient):
        created = self._create_run(client)
        run_id = created["id"]
        client.post(f"/api/v1/runs/{run_id}/start")
        r = client.post(f"/api/v1/runs/{run_id}/cancel")
        assert r.status_code == 200
        assert r.json()["status"] == "cancelled"

    def test_cannot_cancel_completed_run(self, client: TestClient):
        created = self._create_run(client)
        run_id = created["id"]
        _mock_runs[run_id]["status"] = "completed"
        r = client.post(f"/api/v1/runs/{run_id}/cancel")
        assert r.status_code == 400

    def test_cannot_cancel_already_cancelled_run(self, client: TestClient):
        created = self._create_run(client)
        run_id = created["id"]
        _mock_runs[run_id]["status"] = "cancelled"
        r = client.post(f"/api/v1/runs/{run_id}/cancel")
        assert r.status_code == 400


# ===================================================================
# Events
# ===================================================================


class TestEvents:
    """Verify event retrieval for a run."""

    def test_get_events_after_create(self, client: TestClient):
        r = client.post(
            "/api/v1/runs",
            json={
                "title": "Event Test",
                "topic": "Multi-agent coordination with shared memory",
            },
        )
        run_id = r.json()["id"]
        r = client.get(f"/api/v1/runs/{run_id}/events")
        assert r.status_code == 200
        data = r.json()
        assert data["run_id"] == run_id
        assert "events" in data
        assert "total" in data
        # The run.created event should be recorded
        assert data["total"] >= 1
        event_types = [e["event_type"] for e in data["events"]]
        assert "run.created" in event_types

    def test_events_accumulate(self, client: TestClient):
        r = client.post(
            "/api/v1/runs",
            json={
                "title": "Event Accumulate",
                "topic": "Multi-agent coordination with shared memory",
            },
        )
        run_id = r.json()["id"]
        client.post(f"/api/v1/runs/{run_id}/start")

        r = client.get(f"/api/v1/runs/{run_id}/events")
        data = r.json()
        assert data["total"] >= 2
        event_types = {e["event_type"] for e in data["events"]}
        assert "run.created" in event_types
        assert "run.started" in event_types

    def test_events_for_nonexistent_run(self, client: TestClient):
        r = client.get(f"/api/v1/runs/{uuid4()}/events")
        assert r.status_code == 404


# ===================================================================
# Hypotheses
# ===================================================================


class TestHypotheses:
    """Verify hypothesis endpoints."""

    def test_get_hypotheses_empty(self, client: TestClient):
        r = client.post(
            "/api/v1/runs",
            json={
                "title": "Hypo Test",
                "topic": "Multi-agent coordination with shared memory",
            },
        )
        run_id = r.json()["id"]
        r = client.get(f"/api/v1/runs/{run_id}/hypotheses")
        assert r.status_code == 200
        assert r.json() == []

    def test_hypotheses_for_nonexistent_run(self, client: TestClient):
        r = client.get(f"/api/v1/runs/{uuid4()}/hypotheses")
        assert r.status_code == 404


# ===================================================================
# Papers
# ===================================================================


class TestPapers:
    """Verify paper listing endpoints."""

    def test_get_papers_empty(self, client: TestClient):
        r = client.post(
            "/api/v1/runs",
            json={
                "title": "Paper Test",
                "topic": "Multi-agent coordination with shared memory",
            },
        )
        run_id = r.json()["id"]
        r = client.get(f"/api/v1/runs/{run_id}/papers")
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 0
        assert data["papers"] == []

    def test_papers_for_nonexistent_run(self, client: TestClient):
        r = client.get(f"/api/v1/runs/{uuid4()}/papers")
        assert r.status_code == 404


# ===================================================================
# Queue Status
# ===================================================================


class TestQueueStatus:
    """Verify queue status endpoint."""

    def test_queue_status(self, client: TestClient):
        r = client.get("/api/v1/queue/status")
        assert r.status_code == 200
        data = r.json()
        assert data["redis_available"] is False
        assert data["queue_length"] == 0
        assert "active_runs" in data
        assert "queued_runs" in data


# ===================================================================
# Export
# ===================================================================


class TestExport:
    """Verify export endpoint guards."""

    def test_cannot_export_non_completed_run(self, client: TestClient):
        r = client.post(
            "/api/v1/runs",
            json={
                "title": "Export Test",
                "topic": "Multi-agent coordination with shared memory",
            },
        )
        run_id = r.json()["id"]
        r = client.post(
            f"/api/v1/runs/{run_id}/export",
            json={"formats": ["markdown"]},
        )
        assert r.status_code == 400

    def test_export_completed_run(self, client: TestClient):
        r = client.post(
            "/api/v1/runs",
            json={
                "title": "Export Complete",
                "topic": "Multi-agent coordination with shared memory",
            },
        )
        run_id = r.json()["id"]
        _mock_runs[run_id]["status"] = "completed"

        r = client.post(
            f"/api/v1/runs/{run_id}/export",
            json={"formats": ["markdown", "json", "csv", "bibtex"]},
        )
        assert r.status_code == 200
        data = r.json()
        assert len(data["exports"]) == 4
        formats_returned = {e["format"] for e in data["exports"]}
        assert formats_returned == {"markdown", "json", "csv", "bibtex"}

    def test_export_nonexistent_run(self, client: TestClient):
        r = client.post(
            f"/api/v1/runs/{uuid4()}/export",
            json={"formats": ["markdown"]},
        )
        assert r.status_code == 404


# ===================================================================
# Full Workflow
# ===================================================================


class TestFullWorkflow:
    """Test a complete research workflow from creation to cancellation."""

    def test_full_lifecycle(self, client: TestClient):
        """Walk through: create -> verify queued -> start -> pause -> resume -> cancel."""

        # 1. Create a run
        r = client.post(
            "/api/v1/runs",
            json={
                "title": "Full Workflow Test",
                "topic": "Multi-agent systems with long-term memory for cooperative planning",
                "keywords": ["multi-agent", "memory", "planning"],
                "goal_type": "survey_plus_innovations",
            },
        )
        assert r.status_code == 201
        run_id = r.json()["id"]

        # 2. Verify it is queued
        r = client.get(f"/api/v1/runs/{run_id}")
        assert r.status_code == 200
        assert r.json()["status"] == "queued"

        # 3. Start the run
        r = client.post(f"/api/v1/runs/{run_id}/start")
        assert r.status_code == 200
        assert r.json()["status"] == "started"

        # 4. Verify events include created + started
        r = client.get(f"/api/v1/runs/{run_id}/events")
        assert r.status_code == 200
        assert r.json()["total"] >= 2
        event_types = {e["event_type"] for e in r.json()["events"]}
        assert "run.created" in event_types
        assert "run.started" in event_types

        # 5. Pause
        r = client.post(f"/api/v1/runs/{run_id}/pause", json={"mode": "soft"})
        assert r.status_code == 200
        assert r.json()["status"] == "paused"

        # 6. Resume
        r = client.post(f"/api/v1/runs/{run_id}/resume", json={})
        assert r.status_code == 200
        assert r.json()["status"] == "resumed"

        # 7. Cancel
        r = client.post(f"/api/v1/runs/{run_id}/cancel")
        assert r.status_code == 200
        assert r.json()["status"] == "cancelled"

        # 8. Verify final persisted state is cancelled
        r = client.get(f"/api/v1/runs/{run_id}")
        assert r.status_code == 200
        assert r.json()["status"] == "cancelled"

        # 9. Verify events include all lifecycle transitions
        r = client.get(f"/api/v1/runs/{run_id}/events")
        event_types = {e["event_type"] for e in r.json()["events"]}
        assert "run.paused" in event_types
        assert "run.resumed" in event_types
        assert "run.cancelled" in event_types

    def test_create_multiple_runs_independent(self, client: TestClient):
        """Multiple runs should be independent of each other."""
        r1 = client.post(
            "/api/v1/runs",
            json={
                "title": "Run Alpha",
                "topic": "Multi-agent coordination with shared memory",
            },
        )
        r2 = client.post(
            "/api/v1/runs",
            json={
                "title": "Run Beta",
                "topic": "Reinforcement learning for robotic manipulation",
            },
        )
        id1 = r1.json()["id"]
        id2 = r2.json()["id"]
        assert id1 != id2

        # Start only the first
        client.post(f"/api/v1/runs/{id1}/start")

        # Verify second is still queued
        r = client.get(f"/api/v1/runs/{id2}")
        assert r.json()["status"] == "queued"

        # Events for run 2 should not contain run.started
        r = client.get(f"/api/v1/runs/{id2}/events")
        event_types = {e["event_type"] for e in r.json()["events"]}
        assert "run.started" not in event_types
