"""
Tests for the Research OS V2 mode-aware API endpoints.

Verifies:
- POST /api/v1/runs creates a run with mode field
- POST /api/v1/runs/{id}/spawn creates a child run
- GET endpoints return proper structure (mock DB)
- POST /api/v1/runs/{id}/actions/{action} records user actions

Uses the same mock pattern as tests/test_e2e.py.
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
_mock_pain_points: dict[str, list[dict[str, Any]]] = {}
_mock_idea_cards: dict[str, list[dict[str, Any]]] = {}
_mock_figures: dict[str, list[dict[str, Any]]] = {}
_mock_reading_paths: dict[str, dict[str, Any]] = {}
_mock_context_bundles: dict[str, dict[str, Any]] = {}


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
    return []


async def mock_list_papers_by_run(
    run_id: UUID,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    return []


async def mock_count_papers_by_run(run_id: UUID) -> int:
    return 0


# v2 mock functions

async def mock_list_pain_points(
    run_id: UUID,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    return _mock_pain_points.get(str(run_id), [])[offset : offset + limit]


async def mock_list_idea_cards(
    run_id: UUID,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    return _mock_idea_cards.get(str(run_id), [])[offset : offset + limit]


async def mock_list_figures_by_run(
    run_id: UUID,
    limit: int = 50,
) -> list[dict[str, Any]]:
    return _mock_figures.get(str(run_id), [])[:limit]


async def mock_get_reading_path(run_id: UUID) -> dict[str, Any] | None:
    return _mock_reading_paths.get(str(run_id))


async def mock_get_context_bundle(bundle_id: UUID) -> dict[str, Any] | None:
    return _mock_context_bundles.get(str(bundle_id))


async def mock_create_context_bundle(data: dict[str, Any]) -> dict[str, Any]:
    bundle_id = uuid4()
    bundle = {"id": bundle_id, **data}
    _mock_context_bundles[str(bundle_id)] = bundle
    return bundle


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_mock_state():
    """Reset mock data stores before each test."""
    _mock_runs.clear()
    _mock_events.clear()
    _mock_pain_points.clear()
    _mock_idea_cards.clear()
    _mock_figures.clear()
    _mock_reading_paths.clear()
    _mock_context_bundles.clear()


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

    patches = [patch(target, new=mock_fn) for target, mock_fn in db_patches.items()]
    for p in patches:
        p.start()

    try:
        import importlib
        import apps.api.routes_v2 as routes_v2_mod
        import apps.api.main as main_mod

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
# Create Run V2
# ===================================================================


class TestCreateRunV2:
    """Test POST /api/v1/runs creates a run with mode field."""

    def test_create_run_default_mode(self, client: TestClient):
        r = client.post(
            "/api/v1/runs/multimode",
            json={
                "title": "Atlas Research",
                "topic": "Multi-agent coordination with shared memory",
            },
        )
        assert r.status_code == 201
        data = r.json()
        assert data["mode"] == "intake"  # default mode
        assert data["status"] == "queued"
        assert data["title"] == "Atlas Research"
        assert "id" in data

    def test_create_run_with_explicit_mode(self, client: TestClient):
        r = client.post(
            "/api/v1/runs/multimode",
            json={
                "title": "Frontier Research",
                "topic": "Reinforcement learning for robotic manipulation",
                "mode": "frontier",
                "keywords": ["RL", "robotics"],
            },
        )
        assert r.status_code == 201
        data = r.json()
        assert data["mode"] == "frontier"

    def test_create_run_with_atlas_mode(self, client: TestClient):
        r = client.post(
            "/api/v1/runs/multimode",
            json={
                "title": "Atlas Survey",
                "topic": "Large language models for code generation and analysis",
                "mode": "atlas",
                "seed_papers": ["arxiv:2301.00001"],
            },
        )
        assert r.status_code == 201
        data = r.json()
        assert data["mode"] == "atlas"

    def test_create_run_with_parent(self, client: TestClient):
        parent_id = str(uuid4())
        r = client.post(
            "/api/v1/runs/multimode",
            json={
                "title": "Child Research",
                "topic": "Multi-agent coordination with shared memory",
                "mode": "divergent",
                "parent_run_id": parent_id,
            },
        )
        assert r.status_code == 201
        data = r.json()
        assert data["mode"] == "divergent"
        assert data["parent_run_id"] == parent_id

    def test_create_run_invalid_mode(self, client: TestClient):
        r = client.post(
            "/api/v1/runs/multimode",
            json={
                "title": "Bad Mode",
                "topic": "Multi-agent coordination with shared memory",
                "mode": "nonexistent_mode",
            },
        )
        assert r.status_code == 422

    def test_create_run_validation_short_title(self, client: TestClient):
        r = client.post(
            "/api/v1/runs/multimode",
            json={
                "title": "Ab",
                "topic": "Multi-agent coordination with shared memory",
            },
        )
        assert r.status_code == 422

    def test_create_run_validation_short_topic(self, client: TestClient):
        r = client.post(
            "/api/v1/runs/multimode",
            json={"title": "Valid Title", "topic": "short"},
        )
        assert r.status_code == 422

    def test_create_run_current_stage_is_init(self, client: TestClient):
        r = client.post(
            "/api/v1/runs/multimode",
            json={
                "title": "Stage Test",
                "topic": "Multi-agent coordination with shared memory",
            },
        )
        assert r.status_code == 201
        assert r.json()["current_stage"] == "init"


# ===================================================================
# Spawn Run
# ===================================================================


class TestSpawnRun:
    """Test POST /api/v1/runs/{id}/spawn creates a child run."""

    def _create_parent(self, client: TestClient) -> str:
        r = client.post(
            "/api/v1/runs/multimode",
            json={
                "title": "Parent Research",
                "topic": "Multi-agent coordination with shared memory",
                "mode": "intake",
            },
        )
        assert r.status_code == 201
        return r.json()["id"]

    def test_spawn_child_run(self, client: TestClient):
        parent_id = self._create_parent(client)
        bundle_id = str(uuid4())

        r = client.post(
            f"/api/v1/runs/{parent_id}/spawn",
            json={
                "target_mode": "atlas",
                "context_bundle_id": bundle_id,
            },
        )
        assert r.status_code == 201
        data = r.json()
        assert data["mode"] == "atlas"
        assert data["parent_run_id"] == parent_id
        assert data["status"] == "queued"

    def test_spawn_inherits_topic(self, client: TestClient):
        parent_id = self._create_parent(client)
        r = client.post(
            f"/api/v1/runs/{parent_id}/spawn",
            json={
                "target_mode": "frontier",
                "context_bundle_id": str(uuid4()),
            },
        )
        assert r.status_code == 201
        data = r.json()
        assert "Multi-agent coordination" in data["topic"]

    def test_spawn_nonexistent_parent(self, client: TestClient):
        r = client.post(
            f"/api/v1/runs/{uuid4()}/spawn",
            json={
                "target_mode": "atlas",
                "context_bundle_id": str(uuid4()),
            },
        )
        assert r.status_code == 404

    def test_spawn_creates_event_on_parent(self, client: TestClient):
        parent_id = self._create_parent(client)
        client.post(
            f"/api/v1/runs/{parent_id}/spawn",
            json={
                "target_mode": "divergent",
                "context_bundle_id": str(uuid4()),
            },
        )
        # Check events on parent (uses v1 event endpoint)
        found = [
            e for e in _mock_events
            if str(e["run_id"]) == parent_id and e["event_type"] == "run.child_spawned"
        ]
        assert len(found) == 1
        assert found[0]["payload"]["target_mode"] == "divergent"


# ===================================================================
# GET Endpoints — proper structure with empty data
# ===================================================================


class TestGetEndpoints:
    """Verify GET endpoints return proper structure."""

    def _create_run(self, client: TestClient) -> str:
        r = client.post(
            "/api/v1/runs/multimode",
            json={
                "title": "GET Test",
                "topic": "Multi-agent coordination with shared memory",
                "mode": "atlas",
            },
        )
        return r.json()["id"]

    def test_pain_points_empty(self, client: TestClient):
        run_id = self._create_run(client)
        r = client.get(f"/api/v1/runs/{run_id}/pain-points")
        assert r.status_code == 200
        data = r.json()
        assert data["run_id"] == run_id
        assert data["items"] == []

    def test_pain_points_with_data(self, client: TestClient):
        run_id = self._create_run(client)
        _mock_pain_points[run_id] = [
            {"id": str(uuid4()), "statement": "Lack of benchmarks", "severity_score": 0.8},
            {"id": str(uuid4()), "statement": "No reproducibility", "severity_score": 0.6},
        ]
        r = client.get(f"/api/v1/runs/{run_id}/pain-points")
        assert r.status_code == 200
        assert len(r.json()["items"]) == 2

    def test_pain_points_nonexistent_run(self, client: TestClient):
        r = client.get(f"/api/v1/runs/{uuid4()}/pain-points")
        assert r.status_code == 404

    def test_idea_cards_empty(self, client: TestClient):
        run_id = self._create_run(client)
        r = client.get(f"/api/v1/runs/{run_id}/idea-cards")
        assert r.status_code == 200
        data = r.json()
        assert data["run_id"] == run_id
        assert data["items"] == []

    def test_idea_cards_with_data(self, client: TestClient):
        run_id = self._create_run(client)
        _mock_idea_cards[run_id] = [
            {"id": str(uuid4()), "title": "Novel benchmark", "status": "candidate"},
        ]
        r = client.get(f"/api/v1/runs/{run_id}/idea-cards")
        assert r.status_code == 200
        assert len(r.json()["items"]) == 1

    def test_figures_empty(self, client: TestClient):
        run_id = self._create_run(client)
        r = client.get(f"/api/v1/runs/{run_id}/figures")
        assert r.status_code == 200
        data = r.json()
        assert data["run_id"] == run_id
        assert data["items"] == []

    def test_reading_path_empty(self, client: TestClient):
        run_id = self._create_run(client)
        r = client.get(f"/api/v1/runs/{run_id}/reading-path")
        assert r.status_code == 200
        data = r.json()
        assert data["run_id"] == run_id
        assert data["reading_path"] is None

    def test_reading_path_with_data(self, client: TestClient):
        run_id = self._create_run(client)
        _mock_reading_paths[run_id] = {
            "id": str(uuid4()),
            "run_id": run_id,
            "ordered_units": [{"paper_id": str(uuid4()), "order": 1}],
            "estimated_hours": 5.0,
        }
        r = client.get(f"/api/v1/runs/{run_id}/reading-path")
        assert r.status_code == 200
        data = r.json()
        assert data["reading_path"] is not None
        assert data["reading_path"]["estimated_hours"] == 5.0

    def test_context_bundle_empty(self, client: TestClient):
        run_id = self._create_run(client)
        r = client.get(f"/api/v1/runs/{run_id}/context-bundle")
        assert r.status_code == 200
        data = r.json()
        assert data["run_id"] == run_id
        assert data["context_bundle"] is None

    def test_timeline_empty(self, client: TestClient):
        run_id = self._create_run(client)
        r = client.get(f"/api/v1/runs/{run_id}/timeline")
        assert r.status_code == 200
        data = r.json()
        assert data["run_id"] == run_id
        assert data["timeline"] == {}

    def test_taxonomy_empty(self, client: TestClient):
        run_id = self._create_run(client)
        r = client.get(f"/api/v1/runs/{run_id}/taxonomy")
        assert r.status_code == 200
        assert r.json()["taxonomy"] == {}

    def test_comparison_empty(self, client: TestClient):
        run_id = self._create_run(client)
        r = client.get(f"/api/v1/runs/{run_id}/comparison")
        assert r.status_code == 200
        assert r.json()["comparison"] == {}

    def test_mindmap_empty(self, client: TestClient):
        run_id = self._create_run(client)
        r = client.get(f"/api/v1/runs/{run_id}/mindmap")
        assert r.status_code == 200
        assert r.json()["mindmap"] == {}


# ===================================================================
# User Actions
# ===================================================================


class TestUserActions:
    """Test POST /api/v1/runs/{id}/actions/{action} endpoint."""

    def _create_run(self, client: TestClient) -> str:
        r = client.post(
            "/api/v1/runs/multimode",
            json={
                "title": "Action Test",
                "topic": "Multi-agent coordination with shared memory",
            },
        )
        return r.json()["id"]

    def test_pin_paper_action(self, client: TestClient):
        run_id = self._create_run(client)
        paper_id = str(uuid4())
        r = client.post(
            f"/api/v1/runs/{run_id}/actions/pin_paper",
            json={"payload": {"paper_id": paper_id}},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["action"] == "pin_paper"
        assert data["status"] == "recorded"

    def test_exclude_paper_action(self, client: TestClient):
        run_id = self._create_run(client)
        r = client.post(
            f"/api/v1/runs/{run_id}/actions/exclude_paper",
            json={"payload": {"paper_id": str(uuid4())}},
        )
        assert r.status_code == 200

    def test_tighten_scope_action(self, client: TestClient):
        run_id = self._create_run(client)
        r = client.post(
            f"/api/v1/runs/{run_id}/actions/tighten_scope",
            json={"payload": {"venues": ["NeurIPS", "ICML"]}},
        )
        assert r.status_code == 200

    def test_expand_scope_action(self, client: TestClient):
        run_id = self._create_run(client)
        r = client.post(
            f"/api/v1/runs/{run_id}/actions/expand_scope",
            json={"payload": {}},
        )
        assert r.status_code == 200

    def test_switch_mode_action(self, client: TestClient):
        run_id = self._create_run(client)
        r = client.post(
            f"/api/v1/runs/{run_id}/actions/switch_mode",
            json={"payload": {"target_mode": "frontier"}},
        )
        assert r.status_code == 200
        # Verify mode was updated on the run
        assert _mock_runs[run_id]["mode"] == "frontier"

    def test_request_more_figures_action(self, client: TestClient):
        run_id = self._create_run(client)
        r = client.post(
            f"/api/v1/runs/{run_id}/actions/request_more_figures",
            json={"payload": {}},
        )
        assert r.status_code == 200

    def test_send_to_mode_c_action(self, client: TestClient):
        run_id = self._create_run(client)
        r = client.post(
            f"/api/v1/runs/{run_id}/actions/send_to_mode_c",
            json={"payload": {}},
        )
        assert r.status_code == 200

    def test_recheck_prior_art_action(self, client: TestClient):
        run_id = self._create_run(client)
        r = client.post(
            f"/api/v1/runs/{run_id}/actions/recheck_prior_art",
            json={"payload": {"idea_card_id": str(uuid4())}},
        )
        assert r.status_code == 200

    def test_invalid_action(self, client: TestClient):
        run_id = self._create_run(client)
        r = client.post(
            f"/api/v1/runs/{run_id}/actions/invalid_action",
            json={"payload": {}},
        )
        assert r.status_code == 400
        assert "Invalid action" in r.json()["detail"]

    def test_action_nonexistent_run(self, client: TestClient):
        r = client.post(
            f"/api/v1/runs/{uuid4()}/actions/pin_paper",
            json={"payload": {}},
        )
        assert r.status_code == 404

    def test_action_records_event(self, client: TestClient):
        run_id = self._create_run(client)
        client.post(
            f"/api/v1/runs/{run_id}/actions/pin_paper",
            json={"payload": {"paper_id": "abc"}},
        )
        action_events = [
            e for e in _mock_events
            if str(e["run_id"]) == run_id and e["event_type"] == "user.action.pin_paper"
        ]
        assert len(action_events) == 1
        assert action_events[0]["payload"]["paper_id"] == "abc"
