"""
End-to-end tests for all Research OS modes.

Tests real API calls with realistic user scenarios.
Requires API server running on localhost:8000.

Usage:
    PYTHONPATH=/root/research-os .venv/bin/python -m pytest tests/test_e2e_modes.py -v -x
"""

import asyncio
import os
import time
from uuid import UUID

import httpx
import pytest

API_BASE = os.getenv("TEST_API_BASE", "http://localhost:8000")
TIMEOUT = 30


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=API_BASE, timeout=TIMEOUT) as c:
        yield c


def _assert_healthy(client: httpx.Client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "healthy"


def _create_run(client: httpx.Client, payload: dict) -> dict:
    r = client.post("/api/v1/runs/multimode", json=payload)
    assert r.status_code == 201, f"Create failed: {r.status_code} {r.text}"
    data = r.json()
    assert "id" in data
    UUID(data["id"])  # validates UUID format
    return data


def _start_run(client: httpx.Client, run_id: str) -> dict:
    r = client.post(f"/api/v1/runs/{run_id}/start")
    assert r.status_code == 200, f"Start failed: {r.status_code} {r.text}"
    return r.json()


def _get_run(client: httpx.Client, run_id: str) -> dict:
    r = client.get(f"/api/v1/runs/{run_id}")
    assert r.status_code == 200
    return r.json()


def _get_events(client: httpx.Client, run_id: str) -> dict:
    r = client.get(f"/api/v1/runs/{run_id}/events")
    assert r.status_code == 200
    return r.json()


# ---------------------------------------------------------------------------
# Scenario 1: Frontier — minimal input (user only fills topic + seed paper)
# This is the most common real-world scenario
# ---------------------------------------------------------------------------


class TestFrontierMinimalInput:
    """
    User scenario: researcher knows a recent paper (2505.24431), enters topic,
    leaves keywords/benchmark/venue_filter empty.
    System should auto-discover related papers and produce analysis.
    """

    def test_create_frontier_with_seed_only(self, client):
        _assert_healthy(client)

        data = _create_run(client, {
            "title": "3D AD Frontier Test",
            "topic": "3D anomaly detection for industrial point cloud inspection",
            "mode": "frontier",
            "keywords": [],
            "seed_papers": ["2505.24431"],
            "budget": {
                "max_new_papers": 20,
                "max_fulltext_reads": 3,
                "max_estimated_cost_usd": 2,
            },
        })
        assert data["mode"] == "frontier"
        assert data["status"] == "queued"
        assert "2505.24431" in data["policy_json"]["seed_papers"]

    def test_create_frontier_no_seed_no_keywords(self, client):
        """User only enters topic — no seed papers, no keywords at all."""
        data = _create_run(client, {
            "title": "3D AD Minimal",
            "topic": "3D anomaly detection in manufacturing quality control",
            "mode": "frontier",
            "keywords": [],
            "seed_papers": [],
            "budget": {},
        })
        assert data["mode"] == "frontier"
        assert data["status"] == "queued"

    def test_start_and_check_status(self, client):
        data = _create_run(client, {
            "title": "3D AD Start Test",
            "topic": "3D anomaly detection with point clouds and RGB-D images",
            "mode": "frontier",
            "seed_papers": ["2505.24431"],
            "budget": {"max_new_papers": 10},
        })
        run_id = data["id"]

        result = _start_run(client, run_id)
        assert result["status"] == "started"
        assert result["enqueued"] is True

        # Run should now be running or queued
        run = _get_run(client, run_id)
        assert run["status"] in ("queued", "running")

    def test_events_exist_after_creation(self, client):
        data = _create_run(client, {
            "title": "3D AD Events",
            "topic": "3D anomaly detection event tracking test case",
            "mode": "frontier",
            "seed_papers": [],
        })
        events = _get_events(client, data["id"])
        assert events["total"] >= 1
        types = [e["event_type"] for e in events["events"]]
        assert "run.created" in types


# ---------------------------------------------------------------------------
# Scenario 2: Atlas — user entering a new field, only fills topic
# ---------------------------------------------------------------------------


class TestAtlasOnboarding:
    """
    User scenario: student new to multi-agent systems, enters only the topic.
    System should produce taxonomy, timeline, reading path.
    """

    def test_create_atlas_topic_only(self, client):
        data = _create_run(client, {
            "title": "Multi-Agent Survey",
            "topic": "Multi-agent reinforcement learning and cooperative AI systems",
            "mode": "atlas",
            "keywords": [],
            "seed_papers": [],
        })
        assert data["mode"] == "atlas"
        assert data["status"] == "queued"

    def test_atlas_with_broad_topic(self, client):
        """Very broad topic — system should still handle it."""
        data = _create_run(client, {
            "title": "LLM Survey",
            "topic": "Large language models and their applications in scientific research",
            "mode": "atlas",
        })
        assert data["mode"] == "atlas"

    def test_atlas_start_and_events(self, client):
        data = _create_run(client, {
            "title": "Atlas Start Test",
            "topic": "Vision transformers for medical image analysis and diagnosis",
            "mode": "atlas",
        })
        run_id = data["id"]

        _start_run(client, run_id)
        events = _get_events(client, run_id)
        types = [e["event_type"] for e in events["events"]]
        assert "run.created" in types
        assert "run.started" in types


# ---------------------------------------------------------------------------
# Scenario 3: Divergent — user has pain points, wants innovation
# ---------------------------------------------------------------------------


class TestDivergentInnovation:
    """
    User scenario: experienced researcher knows the pain points,
    wants cross-domain idea generation.
    """

    def test_create_divergent_with_keywords(self, client):
        data = _create_run(client, {
            "title": "3D AD Innovation",
            "topic": "Finding cross-domain innovations for 3D anomaly detection generalization",
            "mode": "divergent",
            "keywords": ["3D anomaly detection", "generalization", "zero-shot"],
            "seed_papers": [],
        })
        assert data["mode"] == "divergent"
        assert "3D anomaly detection" in data["policy_json"]["keywords"]

    def test_create_divergent_minimal(self, client):
        """Only topic, no keywords or seeds."""
        data = _create_run(client, {
            "title": "Innovation Minimal",
            "topic": "Novel approaches to unsupervised anomaly detection without any training data",
            "mode": "divergent",
        })
        assert data["mode"] == "divergent"


# ---------------------------------------------------------------------------
# Scenario 4: Review — synthesis mode
# ---------------------------------------------------------------------------


class TestReviewSynthesis:
    def test_create_review(self, client):
        data = _create_run(client, {
            "title": "Research Summary",
            "topic": "Summarize 3D anomaly detection research progress and compile a report",
            "mode": "review",
        })
        assert data["mode"] == "review"

    def test_review_start(self, client):
        data = _create_run(client, {
            "title": "Export Test",
            "topic": "Export and compile a structured review of recent 3D AD methods",
            "mode": "review",
        })
        _start_run(client, data["id"])
        run = _get_run(client, data["id"])
        assert run["status"] in ("queued", "running")


# ---------------------------------------------------------------------------
# Scenario 5: Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_topic_too_short_rejected(self, client):
        """Topic must be >= 10 chars."""
        r = client.post("/api/v1/runs/multimode", json={
            "title": "Test",
            "topic": "short",
            "mode": "frontier",
        })
        assert r.status_code == 422

    def test_title_too_short_rejected(self, client):
        """Title must be >= 3 chars."""
        r = client.post("/api/v1/runs/multimode", json={
            "title": "AB",
            "topic": "This is a valid topic for testing",
            "mode": "atlas",
        })
        assert r.status_code == 422

    def test_invalid_mode_rejected(self, client):
        r = client.post("/api/v1/runs/multimode", json={
            "title": "Invalid Mode",
            "topic": "Testing invalid mode handling in the API",
            "mode": "nonexistent",
        })
        assert r.status_code == 422

    def test_empty_body_rejected(self, client):
        r = client.post("/api/v1/runs/multimode", json={})
        assert r.status_code == 422

    def test_missing_topic_rejected(self, client):
        r = client.post("/api/v1/runs/multimode", json={
            "title": "No Topic",
            "mode": "atlas",
        })
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# Scenario 6: Mode chaining (spawn)
# ---------------------------------------------------------------------------


class TestModeChaining:
    """Test spawning child runs from parent runs."""

    def test_spawn_frontier_from_atlas(self, client):
        """Create atlas run, then spawn frontier child."""
        parent = _create_run(client, {
            "title": "Parent Atlas",
            "topic": "Comprehensive survey of 3D anomaly detection research field",
            "mode": "atlas",
        })

        r = client.post(f"/api/v1/runs/{parent['id']}/spawn", json={
            "target_mode": "frontier",
            "selection": {"sub_direction": "point cloud methods"},
        })
        assert r.status_code == 201
        child = r.json()
        assert child["mode"] == "frontier"
        assert child["parent_run_id"] == parent["id"]

    def test_spawn_divergent_from_frontier(self, client):
        """Create frontier run, then spawn divergent child."""
        parent = _create_run(client, {
            "title": "Parent Frontier",
            "topic": "3D point cloud anomaly detection methods and benchmarks analysis",
            "mode": "frontier",
        })

        r = client.post(f"/api/v1/runs/{parent['id']}/spawn", json={
            "target_mode": "divergent",
            "selection": {"pain_point_ids": []},
        })
        assert r.status_code == 201
        child = r.json()
        assert child["mode"] == "divergent"


# ---------------------------------------------------------------------------
# Scenario 7: V2 sub-endpoints
# ---------------------------------------------------------------------------


class TestV2SubEndpoints:
    """Test that all v2 sub-endpoints return proper structure."""

    @pytest.fixture(autouse=True)
    def setup_run(self, client):
        self.run = _create_run(client, {
            "title": "Endpoint Test",
            "topic": "Testing all API sub-endpoints for Research OS v2 modes",
            "mode": "frontier",
        })
        self.run_id = self.run["id"]

    def test_pain_points_endpoint(self, client):
        r = client.get(f"/api/v1/runs/{self.run_id}/pain-points")
        assert r.status_code == 200
        data = r.json()
        assert "items" in data

    def test_idea_cards_endpoint(self, client):
        r = client.get(f"/api/v1/runs/{self.run_id}/idea-cards")
        assert r.status_code == 200
        data = r.json()
        assert "items" in data

    def test_timeline_endpoint(self, client):
        r = client.get(f"/api/v1/runs/{self.run_id}/timeline")
        assert r.status_code == 200

    def test_taxonomy_endpoint(self, client):
        r = client.get(f"/api/v1/runs/{self.run_id}/taxonomy")
        assert r.status_code == 200

    def test_mindmap_endpoint(self, client):
        r = client.get(f"/api/v1/runs/{self.run_id}/mindmap")
        assert r.status_code == 200

    def test_comparison_endpoint(self, client):
        r = client.get(f"/api/v1/runs/{self.run_id}/comparison")
        assert r.status_code == 200

    def test_figures_endpoint(self, client):
        r = client.get(f"/api/v1/runs/{self.run_id}/figures")
        assert r.status_code == 200

    def test_reading_path_endpoint(self, client):
        r = client.get(f"/api/v1/runs/{self.run_id}/reading-path")
        assert r.status_code == 200

    def test_nonexistent_run_404(self, client):
        r = client.get("/api/v1/runs/00000000-0000-0000-0000-000000000000/pain-points")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Scenario 8: User actions
# ---------------------------------------------------------------------------


class TestUserActions:
    """Test user action endpoint."""

    @pytest.fixture(autouse=True)
    def setup_run(self, client):
        self.run = _create_run(client, {
            "title": "Action Test",
            "topic": "Testing user action endpoints for interactive research control",
            "mode": "frontier",
        })
        self.run_id = self.run["id"]

    def test_valid_action(self, client):
        r = client.post(
            f"/api/v1/runs/{self.run_id}/actions/pin_paper",
            json={"payload": {"paper_id": "test-paper-123"}},
        )
        assert r.status_code == 200

    def test_invalid_action(self, client):
        r = client.post(
            f"/api/v1/runs/{self.run_id}/actions/invalid_action",
            json={"payload": {}},
        )
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# Scenario 9: List runs with mode filter
# ---------------------------------------------------------------------------


class TestListRuns:
    def test_list_returns_mode(self, client):
        """Verify list endpoint includes mode field."""
        r = client.get("/api/v1/runs")
        assert r.status_code == 200
        runs = r.json()
        if runs:
            # At least one run should have mode set
            modes = [r.get("mode") for r in runs if r.get("mode")]
            assert len(modes) > 0
