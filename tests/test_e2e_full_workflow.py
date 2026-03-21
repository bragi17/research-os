"""
Full end-to-end workflow test for Research OS.

Tests the complete lifecycle of a Frontier mode research run:
  Create → Start → Monitor → Verify results persistence → Check sidebar

Requires all services running:
  - API on localhost:8000
  - Worker process consuming Redis queue
  - PostgreSQL with research_os database

Usage:
    PYTHONPATH=/root/research-os .venv/bin/python -m pytest tests/test_e2e_full_workflow.py -v -x -s

Note: This test takes ~8-10 minutes as it runs a real research workflow.
"""

import time
from uuid import UUID

import httpx
import pytest

API = "http://localhost:8000"
TIMEOUT = 30
MAX_WAIT_SECONDS = 600  # 10 minutes


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=API, timeout=TIMEOUT) as c:
        yield c


class TestFullFrontierWorkflow:
    """
    E2E: Frontier run on '3D Anomaly Detection' with seed paper 2505.24431.
    Each step is numbered and has assertions with trace-friendly error messages.
    """

    run_id: str = ""

    # ── 1. Create ───────────────────────────────────────────

    def test_01_create_run(self, client):
        """[TRACE:create] Create Frontier run with topic + seed paper."""
        r = client.post("/api/v1/runs/multimode", json={
            "title": "E2E Full — 3D Anomaly Detection",
            "topic": "3D anomaly detection methods for industrial point cloud inspection",
            "mode": "frontier",
            "keywords": ["3D anomaly detection", "point cloud", "industrial inspection"],
            "seed_papers": ["2505.24431"],
            "budget": {"max_new_papers": 20, "max_fulltext_reads": 5},
        })
        assert r.status_code == 201, f"[TRACE:create] HTTP {r.status_code}: {r.text[:200]}"
        data = r.json()
        UUID(data["id"])
        assert data["status"] == "queued", f"[TRACE:create] Expected queued, got {data['status']}"
        assert data["mode"] == "frontier", f"[TRACE:create] Expected frontier, got {data['mode']}"
        assert "2505.24431" in data["policy_json"]["seed_papers"], "[TRACE:create] Seed paper missing"
        TestFullFrontierWorkflow.run_id = data["id"]
        print(f"\n  [TRACE:create] run_id={data['id']}")

    # ── 2. Start ────────────────────────────────────────────

    def test_02_start_run(self, client):
        """[TRACE:start] Enqueue run to Redis for worker."""
        r = client.post(f"/api/v1/runs/{self.run_id}/start")
        assert r.status_code == 200, f"[TRACE:start] HTTP {r.status_code}"
        assert r.json()["enqueued"] is True, "[TRACE:start] Not enqueued"
        print(f"  [TRACE:start] enqueued=True")

    # ── 3. Sidebar ──────────────────────────────────────────

    def test_03_appears_in_list(self, client):
        """[TRACE:sidebar] Run must appear in list (sidebar data source)."""
        r = client.get("/api/v1/runs")
        runs = r.json()
        # Handle both array and {items} format
        if isinstance(runs, dict):
            runs = runs.get("items", [])
        found = any(run["id"] == self.run_id for run in runs)
        assert found, f"[TRACE:sidebar] run_id={self.run_id} not in {len(runs)} runs"
        print(f"  [TRACE:sidebar] found in {len(runs)} runs")

    # ── 4. Initial events ───────────────────────────────────

    def test_04_initial_events(self, client):
        """[TRACE:events] run.created and run.started events must exist."""
        r = client.get(f"/api/v1/runs/{self.run_id}/events")
        types = [e["event_type"] for e in r.json()["events"]]
        assert "run.created" in types, f"[TRACE:events] Missing run.created. Got: {types}"
        assert "run.started" in types, f"[TRACE:events] Missing run.started. Got: {types}"
        print(f"  [TRACE:events] {len(types)} events, has created+started")

    # ── 5. Wait for completion ──────────────────────────────

    def test_05_wait_for_completion(self, client):
        """[TRACE:wait] Poll until completed or failed (max 10 min)."""
        start = time.time()
        last_stage = ""

        while time.time() - start < MAX_WAIT_SECONDS:
            data = client.get(f"/api/v1/runs/{self.run_id}").json()
            status = data["status"]
            elapsed = int(time.time() - start)

            # Get latest progress event for trace
            events = client.get(f"/api/v1/runs/{self.run_id}/events?limit=5").json()
            progress = [e for e in events["events"] if e["event_type"].startswith("progress.")]
            stage = progress[0]["payload"].get("stage", "?") if progress else "?"
            msg = progress[0]["payload"].get("message", "")[:50] if progress else ""
            if stage != last_stage:
                print(f"  [TRACE:wait] {elapsed}s status={status} stage={stage} | {msg}")
                last_stage = stage

            if status == "completed":
                assert float(data["progress_pct"]) == 100.0, \
                    f"[TRACE:wait] Completed but progress={data['progress_pct']}"
                print(f"  [TRACE:wait] COMPLETED in {elapsed}s")
                return

            if status == "failed":
                err_events = [e for e in events["events"] if e["severity"] == "error"]
                err_msg = err_events[0]["payload"].get("error", "?")[:200] if err_events else "unknown"
                pytest.fail(f"[TRACE:wait] FAILED after {elapsed}s: {err_msg}")

            if status == "cancelled":
                pytest.fail("[TRACE:wait] CANCELLED")

            time.sleep(30)

        pytest.fail(f"[TRACE:wait] TIMEOUT after {MAX_WAIT_SECONDS}s, last status={status}")

    # ── 6. Progress events cover all stages ─────────────────

    def test_06_all_stages_covered(self, client):
        """[TRACE:stages] All 7 frontier stages must have progress events."""
        r = client.get(f"/api/v1/runs/{self.run_id}/events?limit=100")
        progress = [e for e in r.json()["events"] if e["event_type"].startswith("progress.")]
        stages = {e["payload"].get("stage", "") for e in progress}

        expected = {
            "scope_definition", "candidate_retrieval", "scope_pruning",
            "deep_reading", "comparison_build", "pain_mining", "frontier_summary",
        }
        missing = expected - stages
        assert not missing, f"[TRACE:stages] Missing: {missing}. Got: {sorted(stages)}"
        print(f"  [TRACE:stages] {len(progress)} events, all 7 stages covered")

    # ── 7. Sub-endpoints accessible ─────────────────────────

    def test_07_sub_endpoints(self, client):
        """[TRACE:endpoints] All result sub-endpoints return 200."""
        endpoints = ["pain-points", "idea-cards", "timeline", "taxonomy", "mindmap", "comparison"]
        for ep in endpoints:
            r = client.get(f"/api/v1/runs/{self.run_id}/{ep}")
            assert r.status_code == 200, f"[TRACE:endpoints] /{ep} → {r.status_code}: {r.text[:100]}"
        print(f"  [TRACE:endpoints] all {len(endpoints)} endpoints return 200")

    # ── 8. Results persisted to DB ──────────────────────────

    def test_08_results_persisted(self, client):
        """[TRACE:persist] Context bundle must be saved in database."""
        # Check comparison endpoint has data from persisted context_bundle
        r = client.get(f"/api/v1/runs/{self.run_id}/comparison")
        data = r.json()
        comparison = data.get("comparison", {})

        # The comparison should have at least papers_discovered or gaps
        has_data = (
            comparison.get("papers_discovered", 0) > 0
            or comparison.get("papers_read", 0) > 0
            or len(comparison.get("comparison_matrix", [])) > 0
            or len(comparison.get("gaps", [])) > 0
        )
        assert has_data, (
            f"[TRACE:persist] No result data persisted. "
            f"comparison keys: {list(comparison.keys())}. "
            f"Values: papers_discovered={comparison.get('papers_discovered')}, "
            f"gaps={len(comparison.get('gaps', []))}"
        )
        print(f"  [TRACE:persist] comparison has data: "
              f"papers_discovered={comparison.get('papers_discovered', 0)}, "
              f"gaps={len(comparison.get('gaps', []))}")

    # ── 9. Final metadata ───────────────────────────────────

    def test_09_final_metadata(self, client):
        """[TRACE:metadata] Completed run has correct final state."""
        data = client.get(f"/api/v1/runs/{self.run_id}").json()
        assert data["status"] == "completed", f"[TRACE:metadata] status={data['status']}"
        assert data["mode"] == "frontier", f"[TRACE:metadata] mode={data['mode']}"
        assert float(data["progress_pct"]) == 100.0, f"[TRACE:metadata] progress={data['progress_pct']}"
        assert data["started_at"] is not None, "[TRACE:metadata] started_at is None"
        assert data["completed_at"] is not None, "[TRACE:metadata] completed_at is None"
        print(f"  [TRACE:metadata] status=completed mode=frontier progress=100%")

    # ── 10. Sidebar persistence ─────────────────────────────

    def test_10_sidebar_after_completion(self, client):
        """[TRACE:sidebar2] Run still appears in list after completion."""
        r = client.get("/api/v1/runs")
        runs = r.json() if isinstance(r.json(), list) else r.json().get("items", [])
        target = [run for run in runs if run["id"] == self.run_id]
        assert len(target) == 1, f"[TRACE:sidebar2] Not found in {len(runs)} runs"
        assert target[0]["status"] == "completed", f"[TRACE:sidebar2] status={target[0]['status']}"
        print(f"  [TRACE:sidebar2] found, status=completed")

    # ── 11. Spawn child ─────────────────────────────────────

    def test_11_spawn_divergent(self, client):
        """[TRACE:spawn] Can spawn Divergent child from completed run."""
        r = client.post(f"/api/v1/runs/{self.run_id}/spawn", json={
            "target_mode": "divergent",
            "selection": {"intent": "explore innovations"},
        })
        assert r.status_code == 201, f"[TRACE:spawn] HTTP {r.status_code}: {r.text[:200]}"
        child = r.json()
        assert child["mode"] == "divergent", f"[TRACE:spawn] child mode={child['mode']}"
        assert child["parent_run_id"] == self.run_id, "[TRACE:spawn] parent_run_id mismatch"
        print(f"  [TRACE:spawn] child={child['id'][:8]}... mode=divergent")
