from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from apps.api.main import app


def test_works_router_is_registered() -> None:
    routes = {route.path for route in app.routes}
    assert "/api/v1/works" in routes


def test_create_work_returns_created_work(monkeypatch):
    created: dict[str, object] = {}

    async def fake_create_work(data):
        created.update(data)
        return {
            "id": uuid4(),
            "title": data["title"],
            "topic": data["topic"],
            "status": "active",
            "active_phase": None,
            "root_run_id": None,
            "project_id": None,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }

    monkeypatch.setattr("apps.api.database.create_work", fake_create_work)
    client = TestClient(app)

    response = client.post(
        "/api/v1/works",
        json={"title": "3D AD", "topic": "3D anomaly detection for point clouds"},
    )

    assert response.status_code == 201
    assert response.json()["title"] == "3D AD"
    assert created["topic"] == "3D anomaly detection for point clouds"


def test_list_works_returns_items_and_total(monkeypatch):
    work_id = uuid4()
    captured: dict[str, object] = {}

    async def fake_list_works(workspace_id, limit=100, offset=0):
        captured["workspace_id"] = workspace_id
        captured["limit"] = limit
        captured["offset"] = offset
        return [
            {
                "id": work_id,
                "title": "3D AD",
                "topic": "3D anomaly detection for point clouds",
                "status": "active",
                "active_phase": "frontier",
                "root_run_id": None,
                "project_id": None,
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
            }
        ]

    monkeypatch.setattr("apps.api.database.list_works", fake_list_works)
    client = TestClient(app)

    response = client.get("/api/v1/works?limit=10&offset=5")

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["id"] == str(work_id)
    assert captured["limit"] == 10
    assert captured["offset"] == 5


def test_get_work_returns_work(monkeypatch):
    work_id = uuid4()
    captured: dict[str, object] = {}

    async def fake_get_work(request_work_id, workspace_id):
        captured["work_id"] = request_work_id
        captured["workspace_id"] = workspace_id
        return {
            "id": request_work_id,
            "title": "3D AD",
            "topic": "3D anomaly detection for point clouds",
            "status": "active",
            "active_phase": None,
            "root_run_id": None,
            "project_id": None,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }

    monkeypatch.setattr("apps.api.database.get_work", fake_get_work)
    client = TestClient(app)

    response = client.get(f"/api/v1/works/{work_id}")

    assert response.status_code == 200
    assert response.json()["id"] == str(work_id)
    assert response.json()["title"] == "3D AD"
    assert captured["work_id"] == work_id


def test_get_work_phases_returns_executions(monkeypatch):
    work_id = uuid4()
    execution_id = uuid4()
    captured: dict[str, object] = {}

    async def fake_get_work(request_work_id, workspace_id):
        return {"id": request_work_id, "workspace_id": workspace_id, "status": "active"}

    async def fake_list_phase_executions(request_work_id):
        captured["work_id"] = request_work_id
        return [
            {
                "id": execution_id,
                "work_id": request_work_id,
                "phase": "frontier",
                "execution_kind": "standard",
                "status": "completed",
                "backing_run_id": None,
                "output_bundle_id": None,
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
            }
        ]

    monkeypatch.setattr("apps.api.database.get_work", fake_get_work)
    monkeypatch.setattr(
        "apps.api.database.list_phase_executions",
        fake_list_phase_executions,
    )
    client = TestClient(app)

    response = client.get(f"/api/v1/works/{work_id}/phases")

    assert response.status_code == 200
    assert response.json()["work_id"] == str(work_id)
    assert response.json()["executions"][0]["id"] == str(execution_id)
    assert captured["work_id"] == work_id


def test_get_artifact_cards_rejects_foreign_work(monkeypatch):
    async def fake_get_work(work_id, workspace_id):
        return None

    monkeypatch.setattr("apps.api.database.get_work", fake_get_work)
    client = TestClient(app)

    response = client.get(f"/api/v1/works/{uuid4()}/artifact-cards")

    assert response.status_code == 404
    assert response.json()["detail"] == "Work not found"


def test_get_artifact_cards_returns_items_and_total(monkeypatch):
    work_id = uuid4()
    card_id = uuid4()
    captured: dict[str, object] = {}

    async def fake_get_work(request_work_id, workspace_id):
        return {"id": request_work_id, "workspace_id": workspace_id, "status": "active"}

    async def fake_list_artifact_cards(request_work_id, phase=None):
        captured["work_id"] = request_work_id
        captured["phase"] = phase
        return [
            {
                "id": card_id,
                "work_id": request_work_id,
                "phase": "frontier",
                "artifact_type": "frontier_gap",
                "title": "Sparse labels",
                "body": None,
                "payload": {"significance": "high"},
                "status": "active",
                "selection_state": "unselected",
                "source_execution_id": None,
                "source_card_ids": [],
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
            }
        ]

    monkeypatch.setattr("apps.api.database.get_work", fake_get_work)
    monkeypatch.setattr("apps.api.database.list_artifact_cards", fake_list_artifact_cards)
    client = TestClient(app)

    response = client.get(f"/api/v1/works/{work_id}/artifact-cards?phase=frontier")

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["id"] == str(card_id)
    assert captured["work_id"] == work_id
    assert captured["phase"] == "frontier"


def test_create_artifact_card_records_user_edit_source(monkeypatch):
    work_id = uuid4()
    captured: dict[str, object] = {}

    async def fake_get_work(request_work_id, workspace_id):
        return {"id": request_work_id, "workspace_id": workspace_id, "status": "active"}

    async def fake_create_artifact_card(data):
        captured.update(data)
        return {
            "id": uuid4(),
            "work_id": data["work_id"],
            "phase": data["phase"],
            "artifact_type": data["artifact_type"],
            "title": data["title"],
            "body": data.get("body"),
            "payload": data.get("payload", {}),
            "status": "active",
            "selection_state": "unselected",
            "source_execution_id": None,
            "source_card_ids": [],
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }

    monkeypatch.setattr("apps.api.database.get_work", fake_get_work)
    monkeypatch.setattr(
        "apps.api.database.create_artifact_card",
        fake_create_artifact_card,
    )
    client = TestClient(app)

    response = client.post(
        f"/api/v1/works/{work_id}/artifact-cards",
        json={
            "phase": "frontier",
            "artifact_type": "frontier_gap",
            "title": "Sparse labels",
            "payload": {"significance": "high"},
        },
    )

    assert response.status_code == 201
    assert captured["edit_source"] == "user"
    assert captured["work_id"] == work_id


def test_create_artifact_card_rejects_foreign_work(monkeypatch):
    create_called = False

    async def fake_get_work(request_work_id, workspace_id):
        return None

    async def fake_create_artifact_card(data):
        nonlocal create_called
        create_called = True
        return data

    monkeypatch.setattr("apps.api.database.get_work", fake_get_work)
    monkeypatch.setattr(
        "apps.api.database.create_artifact_card",
        fake_create_artifact_card,
    )
    client = TestClient(app)

    response = client.post(
        f"/api/v1/works/{uuid4()}/artifact-cards",
        json={
            "phase": "frontier",
            "artifact_type": "frontier_gap",
            "title": "Sparse labels",
            "payload": {"significance": "high"},
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Work not found"
    assert create_called is False


def test_create_artifact_card_rejects_wrong_work_source_card_without_persisting(
    monkeypatch,
):
    work_id = uuid4()
    foreign_card_id = uuid4()
    create_called = False

    async def fake_get_work(request_work_id, workspace_id):
        return {"id": request_work_id, "workspace_id": workspace_id, "status": "active"}

    async def fake_list_artifact_cards(request_work_id, phase=None):
        return []

    async def fake_create_artifact_card(data):
        nonlocal create_called
        create_called = True
        return data

    monkeypatch.setattr("apps.api.database.get_work", fake_get_work)
    monkeypatch.setattr("apps.api.database.list_artifact_cards", fake_list_artifact_cards)
    monkeypatch.setattr(
        "apps.api.database.create_artifact_card",
        fake_create_artifact_card,
    )
    client = TestClient(app)

    response = client.post(
        f"/api/v1/works/{work_id}/artifact-cards",
        json={
            "phase": "frontier",
            "artifact_type": "frontier_gap",
            "title": "Derived gap",
            "source_card_ids": [str(foreign_card_id)],
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Artifact card not found"
    assert create_called is False


def test_create_artifact_card_rejects_wrong_work_source_execution_without_persisting(
    monkeypatch,
):
    work_id = uuid4()
    foreign_execution_id = uuid4()
    create_called = False

    async def fake_get_work(request_work_id, workspace_id):
        return {"id": request_work_id, "workspace_id": workspace_id, "status": "active"}

    async def fake_list_phase_executions(request_work_id):
        return []

    async def fake_create_artifact_card(data):
        nonlocal create_called
        create_called = True
        return data

    monkeypatch.setattr("apps.api.database.get_work", fake_get_work)
    monkeypatch.setattr(
        "apps.api.database.list_phase_executions",
        fake_list_phase_executions,
    )
    monkeypatch.setattr(
        "apps.api.database.create_artifact_card",
        fake_create_artifact_card,
    )
    client = TestClient(app)

    response = client.post(
        f"/api/v1/works/{work_id}/artifact-cards",
        json={
            "phase": "frontier",
            "artifact_type": "frontier_gap",
            "title": "Execution-derived gap",
            "source_execution_id": str(foreign_execution_id),
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Phase execution not found"
    assert create_called is False


def test_patch_artifact_card_returns_updated_card(monkeypatch):
    work_id = uuid4()
    card_id = uuid4()
    captured: dict[str, object] = {}

    async def fake_get_work(request_work_id, workspace_id):
        return {"id": request_work_id, "workspace_id": workspace_id, "status": "active"}

    async def fake_list_artifact_cards(request_work_id, phase=None):
        return [
            {
                "id": card_id,
                "work_id": request_work_id,
                "phase": "frontier",
                "artifact_type": "frontier_gap",
                "title": "Sparse labels",
                "body": None,
                "payload": {"significance": "high"},
                "status": "active",
                "selection_state": "unselected",
                "source_execution_id": None,
                "source_card_ids": [],
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
            }
        ]

    async def fake_update_artifact_card(request_card_id, updates):
        captured["card_id"] = request_card_id
        captured.update(updates)
        return {
            "id": request_card_id,
            "work_id": work_id,
            "phase": "frontier",
            "artifact_type": "frontier_gap",
            "title": updates["title"],
            "body": None,
            "payload": {"significance": "high"},
            "status": "active",
            "selection_state": "unselected",
            "source_execution_id": None,
            "source_card_ids": [],
            "created_at": datetime.now(timezone.utc),
            "updated_at": updates["updated_at"],
        }

    monkeypatch.setattr("apps.api.database.get_work", fake_get_work)
    monkeypatch.setattr("apps.api.database.list_artifact_cards", fake_list_artifact_cards)
    monkeypatch.setattr("apps.api.database.update_artifact_card", fake_update_artifact_card)
    client = TestClient(app)

    response = client.patch(
        f"/api/v1/works/{work_id}/artifact-cards/{card_id}",
        json={"title": "Updated gap"},
    )

    assert response.status_code == 200
    assert response.json()["id"] == str(card_id)
    assert response.json()["title"] == "Updated gap"
    assert captured["card_id"] == card_id
    assert captured["title"] == "Updated gap"
    assert captured["updated_by"] == UUID("00000000-0000-0000-0000-000000000000")
    assert isinstance(captured["updated_at"], datetime)


def test_patch_artifact_card_empty_body_returns_400(monkeypatch):
    work_id = uuid4()
    card_id = uuid4()
    update_called = False

    async def fake_get_work(request_work_id, workspace_id):
        return {"id": request_work_id, "workspace_id": workspace_id, "status": "active"}

    async def fake_update_artifact_card(request_card_id, updates):
        nonlocal update_called
        update_called = True
        return None

    monkeypatch.setattr("apps.api.database.get_work", fake_get_work)
    monkeypatch.setattr("apps.api.database.update_artifact_card", fake_update_artifact_card)
    client = TestClient(app)

    response = client.patch(
        f"/api/v1/works/{work_id}/artifact-cards/{card_id}",
        json={},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "No valid fields to update"
    assert update_called is False


def test_patch_artifact_card_rejects_wrong_work_card(monkeypatch):
    work_id = uuid4()
    other_work_id = uuid4()
    card_id = uuid4()
    stored_card = {
        "id": card_id,
        "work_id": other_work_id,
        "phase": "frontier",
        "artifact_type": "frontier_gap",
        "title": "Original gap",
        "body": None,
        "payload": {},
        "status": "active",
        "selection_state": "unselected",
        "source_execution_id": None,
        "source_card_ids": [],
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    update_called = False

    async def fake_get_work(request_work_id, workspace_id):
        return {"id": request_work_id, "workspace_id": workspace_id, "status": "active"}

    async def fake_list_artifact_cards(request_work_id, phase=None):
        return []

    async def fake_update_artifact_card(request_card_id, updates):
        nonlocal update_called
        update_called = True
        stored_card.update(updates)
        return stored_card

    monkeypatch.setattr("apps.api.database.get_work", fake_get_work)
    monkeypatch.setattr("apps.api.database.list_artifact_cards", fake_list_artifact_cards)
    monkeypatch.setattr("apps.api.database.update_artifact_card", fake_update_artifact_card)
    client = TestClient(app)

    response = client.patch(
        f"/api/v1/works/{work_id}/artifact-cards/{card_id}",
        json={"title": "Updated gap"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Artifact card not found"
    assert update_called is False
    assert stored_card["title"] == "Original gap"


def test_save_phase_inputs_invalid_phase_returns_400(monkeypatch):
    work_id = uuid4()
    upsert_called = False

    async def fake_get_work(request_work_id, workspace_id):
        return {"id": request_work_id, "workspace_id": workspace_id, "status": "active"}

    async def fake_upsert_phase_input_selection(**kwargs):
        nonlocal upsert_called
        upsert_called = True
        return kwargs

    monkeypatch.setattr("apps.api.database.get_work", fake_get_work)
    monkeypatch.setattr(
        "apps.api.database.upsert_phase_input_selection",
        fake_upsert_phase_input_selection,
    )
    client = TestClient(app)

    response = client.post(
        f"/api/v1/works/{work_id}/phase-inputs/invalid",
        json={"source_card_ids": [], "manual_input": {}},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid phase"
    assert upsert_called is False


def test_save_phase_inputs_rejects_wrong_work_source_card_without_persisting(
    monkeypatch,
):
    work_id = uuid4()
    foreign_card_id = uuid4()
    upsert_called = False

    async def fake_get_work(request_work_id, workspace_id):
        return {"id": request_work_id, "workspace_id": workspace_id, "status": "active"}

    async def fake_list_artifact_cards(request_work_id, phase=None):
        return []

    async def fake_upsert_phase_input_selection(**kwargs):
        nonlocal upsert_called
        upsert_called = True
        return kwargs

    monkeypatch.setattr("apps.api.database.get_work", fake_get_work)
    monkeypatch.setattr("apps.api.database.list_artifact_cards", fake_list_artifact_cards)
    monkeypatch.setattr(
        "apps.api.database.upsert_phase_input_selection",
        fake_upsert_phase_input_selection,
    )
    client = TestClient(app)

    response = client.post(
        f"/api/v1/works/{work_id}/phase-inputs/frontier",
        json={"source_card_ids": [str(foreign_card_id)], "manual_input": {}},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Artifact card not found"
    assert upsert_called is False


def test_save_phase_inputs_calls_upsert_with_expected_args(monkeypatch):
    work_id = uuid4()
    card_id = uuid4()
    captured: dict[str, object] = {}

    async def fake_get_work(request_work_id, workspace_id):
        return {"id": request_work_id, "workspace_id": workspace_id, "status": "active"}

    async def fake_list_artifact_cards(request_work_id, phase=None):
        return [{"id": card_id, "work_id": request_work_id, "status": "active"}]

    async def fake_upsert_phase_input_selection(**kwargs):
        captured.update(kwargs)
        return {
            "work_id": kwargs["work_id"],
            "target_phase": kwargs["target_phase"],
            "source_card_ids": kwargs["source_card_ids"],
            "manual_input_json": kwargs["manual_input_json"],
            "created_by": kwargs["created_by"],
        }

    monkeypatch.setattr("apps.api.database.get_work", fake_get_work)
    monkeypatch.setattr("apps.api.database.list_artifact_cards", fake_list_artifact_cards)
    monkeypatch.setattr(
        "apps.api.database.upsert_phase_input_selection",
        fake_upsert_phase_input_selection,
    )
    client = TestClient(app)

    response = client.post(
        f"/api/v1/works/{work_id}/phase-inputs/frontier",
        json={
            "source_card_ids": [str(card_id)],
            "manual_input": {"notes": "use these"},
        },
    )

    assert response.status_code == 200
    assert captured["work_id"] == work_id
    assert captured["target_phase"] == "frontier"
    assert captured["source_card_ids"] == [card_id]
    assert captured["manual_input_json"] == {"notes": "use these"}
    assert captured["created_by"] == UUID("00000000-0000-0000-0000-000000000000")


def test_start_frontier_phase_execution_enqueues_same_work_payload(monkeypatch):
    work_id = uuid4()
    source_card_id = uuid4()
    backing_run_id = uuid4()
    execution_id = uuid4()
    enqueued: list[tuple[UUID, dict[str, object]]] = []
    run_updates: list[tuple[UUID, dict[str, object]]] = []
    execution_updates: list[tuple[UUID, dict[str, object]]] = []

    async def fake_get_work(request_work_id, workspace_id):
        return {
            "id": request_work_id,
            "workspace_id": workspace_id,
            "created_by": uuid4(),
            "title": "3D AD",
            "topic": "3D anomaly detection for point clouds",
            "budget_json": {"max_new_papers": 50},
            "policy_json": {"keywords": ["3d anomaly"]},
            "project_id": None,
        }

    async def fake_list_artifact_cards(request_work_id, phase=None):
        return [
            {
                "id": source_card_id,
                "work_id": request_work_id,
                "phase": "atlas",
                "artifact_type": "atlas_direction",
                "title": "Point-cloud inspection",
                "payload": {"name": "Point-cloud inspection"},
            }
        ]

    async def fake_create_run(data):
        assert data["mode"] == "frontier"
        assert data["parent_run_id"] is None
        assert data["status"] == "failed"
        return {**data, "id": backing_run_id}

    async def fake_create_phase_execution(data):
        assert data["work_id"] == work_id
        assert data["phase"] == "frontier"
        assert data["backing_run_id"] == backing_run_id
        assert data["status"] == "failed"
        assert data["input_json"]["manual_input"] == {
            "scope": "industrial point clouds",
        }
        assert data["input_json"]["source_card_ids"] == [str(source_card_id)]
        return {
            "id": execution_id,
            **data,
            "status": "queued",
            "output_bundle_id": None,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }

    async def fake_enqueue_run(run_id, payload):
        enqueued.append((run_id, payload))
        return True

    async def fake_update_run(run_id, updates):
        run_updates.append((run_id, updates))
        return {**updates, "id": run_id}

    async def fake_update_phase_execution(phase_execution_id, updates):
        execution_updates.append((phase_execution_id, updates))
        return {
            "id": phase_execution_id,
            "work_id": work_id,
            "phase": "frontier",
            "execution_kind": "standard",
            "status": updates["status"],
            "backing_run_id": backing_run_id,
            "output_bundle_id": None,
            "created_at": datetime.now(timezone.utc),
            "updated_at": updates["updated_at"],
        }

    monkeypatch.setattr("apps.api.database.get_work", fake_get_work)
    monkeypatch.setattr("apps.api.database.list_artifact_cards", fake_list_artifact_cards)
    monkeypatch.setattr("apps.api.database.create_run", fake_create_run)
    monkeypatch.setattr(
        "apps.api.database.create_phase_execution",
        fake_create_phase_execution,
    )
    monkeypatch.setattr("apps.api.database.update_run", fake_update_run)
    monkeypatch.setattr(
        "apps.api.database.update_phase_execution",
        fake_update_phase_execution,
    )
    monkeypatch.setattr("apps.worker.task_queue.enqueue_run", fake_enqueue_run)
    client = TestClient(app)

    response = client.post(
        f"/api/v1/works/{work_id}/phases/frontier/executions",
        json={
            "phase": "frontier",
            "source_card_ids": [str(source_card_id)],
            "manual_input": {"scope": "industrial point clouds"},
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["phase"] == "frontier"
    assert body["status"] == "queued"
    assert enqueued[0][0] == backing_run_id
    payload = enqueued[0][1]
    assert payload["mode"] == "frontier"
    assert payload["work_id"] == str(work_id)
    assert payload["phase_execution_id"] == str(execution_id)
    assert payload["context_bundle"]["sub_directions"] == [
        {"name": "Point-cloud inspection"},
    ]
    assert run_updates[0][0] == backing_run_id
    assert run_updates[0][1]["status"] == "queued"
    assert run_updates[0][1]["completed_at"] is None
    assert isinstance(run_updates[0][1]["updated_at"], datetime)
    assert execution_updates[0][0] == execution_id
    assert execution_updates[0][1]["status"] == "queued"
    assert execution_updates[0][1]["error_message"] is None
    assert execution_updates[0][1]["completed_at"] is None
    assert isinstance(execution_updates[0][1]["updated_at"], datetime)


def test_start_phase_execution_returns_500_when_queued_promotion_fails(
    monkeypatch,
):
    work_id = uuid4()
    source_card_id = uuid4()
    backing_run_id = uuid4()
    execution_id = uuid4()
    enqueued: list[tuple[UUID, dict[str, object]]] = []
    run_updates: list[tuple[UUID, dict[str, object]]] = []

    async def fake_get_work(request_work_id, workspace_id):
        return {
            "id": request_work_id,
            "workspace_id": workspace_id,
            "title": "3D AD",
            "topic": "3D anomaly detection for point clouds",
            "budget_json": {},
            "policy_json": {},
            "project_id": None,
        }

    async def fake_list_artifact_cards(request_work_id, phase=None):
        return [
            {
                "id": source_card_id,
                "work_id": request_work_id,
                "phase": "atlas",
                "artifact_type": "atlas_direction",
                "title": "Point-cloud inspection",
                "payload": {"name": "Point-cloud inspection"},
            }
        ]

    async def fake_create_run(data):
        assert data["status"] == "failed"
        return {**data, "id": backing_run_id}

    async def fake_create_phase_execution(data):
        assert data["status"] == "failed"
        return {
            "id": execution_id,
            **data,
            "status": data["status"],
            "output_bundle_id": None,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }

    async def fake_enqueue_run(run_id, payload):
        enqueued.append((run_id, payload))
        return True

    async def fake_update_run(run_id, updates):
        run_updates.append((run_id, updates))
        return {**updates, "id": run_id}

    async def fake_update_phase_execution(phase_execution_id, updates):
        raise RuntimeError("phase promotion failed")

    monkeypatch.setattr("apps.api.database.get_work", fake_get_work)
    monkeypatch.setattr("apps.api.database.list_artifact_cards", fake_list_artifact_cards)
    monkeypatch.setattr("apps.api.database.create_run", fake_create_run)
    monkeypatch.setattr(
        "apps.api.database.create_phase_execution",
        fake_create_phase_execution,
    )
    monkeypatch.setattr("apps.api.database.update_run", fake_update_run)
    monkeypatch.setattr(
        "apps.api.database.update_phase_execution",
        fake_update_phase_execution,
    )
    monkeypatch.setattr("apps.worker.task_queue.enqueue_run", fake_enqueue_run)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(
        f"/api/v1/works/{work_id}/phases/frontier/executions",
        json={
            "phase": "frontier",
            "source_card_ids": [str(source_card_id)],
            "manual_input": {},
        },
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "Failed to mark phase execution queued"
    assert enqueued[0][0] == backing_run_id
    assert run_updates[0][1]["status"] == "queued"


def test_start_phase_execution_returns_500_when_run_promotion_returns_none(
    monkeypatch,
):
    work_id = uuid4()
    source_card_id = uuid4()
    backing_run_id = uuid4()
    execution_id = uuid4()
    enqueued: list[tuple[UUID, dict[str, object]]] = []
    phase_execution_promoted = False

    async def fake_get_work(request_work_id, workspace_id):
        return {
            "id": request_work_id,
            "workspace_id": workspace_id,
            "title": "3D AD",
            "topic": "3D anomaly detection for point clouds",
            "budget_json": {},
            "policy_json": {},
            "project_id": None,
        }

    async def fake_list_artifact_cards(request_work_id, phase=None):
        return [
            {
                "id": source_card_id,
                "work_id": request_work_id,
                "phase": "atlas",
                "artifact_type": "atlas_direction",
                "title": "Point-cloud inspection",
                "payload": {"name": "Point-cloud inspection"},
            }
        ]

    async def fake_create_run(data):
        return {**data, "id": backing_run_id}

    async def fake_create_phase_execution(data):
        return {
            "id": execution_id,
            **data,
            "status": data["status"],
            "output_bundle_id": None,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }

    async def fake_enqueue_run(run_id, payload):
        enqueued.append((run_id, payload))
        return True

    async def fake_update_run(run_id, updates):
        return None

    async def fake_update_phase_execution(phase_execution_id, updates):
        nonlocal phase_execution_promoted
        phase_execution_promoted = True
        return updates

    monkeypatch.setattr("apps.api.database.get_work", fake_get_work)
    monkeypatch.setattr("apps.api.database.list_artifact_cards", fake_list_artifact_cards)
    monkeypatch.setattr("apps.api.database.create_run", fake_create_run)
    monkeypatch.setattr(
        "apps.api.database.create_phase_execution",
        fake_create_phase_execution,
    )
    monkeypatch.setattr("apps.api.database.update_run", fake_update_run)
    monkeypatch.setattr(
        "apps.api.database.update_phase_execution",
        fake_update_phase_execution,
    )
    monkeypatch.setattr("apps.worker.task_queue.enqueue_run", fake_enqueue_run)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(
        f"/api/v1/works/{work_id}/phases/frontier/executions",
        json={
            "phase": "frontier",
            "source_card_ids": [str(source_card_id)],
            "manual_input": {},
        },
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "Failed to mark run queued"
    assert enqueued[0][0] == backing_run_id
    assert phase_execution_promoted is False


def test_start_phase_execution_clears_legacy_auto_spawn_policy(monkeypatch):
    work_id = uuid4()
    source_card_id = uuid4()
    backing_run_id = uuid4()
    execution_id = uuid4()
    captured_run: dict[str, object] = {}

    async def fake_get_work(request_work_id, workspace_id):
        return {
            "id": request_work_id,
            "workspace_id": workspace_id,
            "title": "3D AD",
            "topic": "3D anomaly detection for point clouds",
            "budget_json": {},
            "policy_json": {
                "auto_continue": True,
                "auto_spawn_next": True,
                "keywords": ["3d anomaly"],
                "seed_papers": ["paper-1"],
                "library_pool_ids": ["pool-1"],
            },
            "project_id": None,
        }

    async def fake_list_artifact_cards(request_work_id, phase=None):
        return [
            {
                "id": source_card_id,
                "work_id": request_work_id,
                "phase": "atlas",
                "artifact_type": "atlas_direction",
                "title": "Point-cloud inspection",
                "payload": {"name": "Point-cloud inspection"},
            }
        ]

    async def fake_create_run(data):
        captured_run.update(data)
        return {**data, "id": backing_run_id}

    async def fake_create_phase_execution(data):
        return {
            "id": execution_id,
            **data,
            "status": data["status"],
            "output_bundle_id": None,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }

    async def fake_enqueue_run(run_id, payload):
        return True

    async def fake_update_run(run_id, updates):
        return {**updates, "id": run_id}

    async def fake_update_phase_execution(phase_execution_id, updates):
        return {
            "id": phase_execution_id,
            "work_id": work_id,
            "phase": "frontier",
            "execution_kind": "standard",
            "status": updates["status"],
            "backing_run_id": backing_run_id,
            "output_bundle_id": None,
            "created_at": datetime.now(timezone.utc),
            "updated_at": updates["updated_at"],
        }

    monkeypatch.setattr("apps.api.database.get_work", fake_get_work)
    monkeypatch.setattr("apps.api.database.list_artifact_cards", fake_list_artifact_cards)
    monkeypatch.setattr("apps.api.database.create_run", fake_create_run)
    monkeypatch.setattr(
        "apps.api.database.create_phase_execution",
        fake_create_phase_execution,
    )
    monkeypatch.setattr("apps.api.database.update_run", fake_update_run)
    monkeypatch.setattr(
        "apps.api.database.update_phase_execution",
        fake_update_phase_execution,
    )
    monkeypatch.setattr("apps.worker.task_queue.enqueue_run", fake_enqueue_run)
    client = TestClient(app)

    response = client.post(
        f"/api/v1/works/{work_id}/phases/frontier/executions",
        json={"phase": "frontier", "source_card_ids": [str(source_card_id)]},
    )

    assert response.status_code == 201
    policy = captured_run["policy_json"]
    assert policy.get("auto_continue") is not True
    assert policy.get("auto_spawn_next") is not True
    assert policy["keywords"] == ["3d anomaly"]
    assert policy["seed_papers"] == ["paper-1"]
    assert policy["library_pool_ids"] == ["pool-1"]


def test_start_phase_execution_uses_all_work_cards_when_no_source_ids(
    monkeypatch,
):
    work_id = uuid4()
    backing_run_id = uuid4()
    execution_id = uuid4()
    atlas_card_id = uuid4()
    gap_card_id = uuid4()
    enqueued: list[tuple[UUID, dict[str, object]]] = []

    async def fake_get_work(request_work_id, workspace_id):
        return {
            "id": request_work_id,
            "workspace_id": workspace_id,
            "title": "3D AD",
            "topic": "3D anomaly detection for point clouds",
            "budget_json": {},
            "policy_json": {},
            "project_id": None,
        }

    async def fake_list_artifact_cards(request_work_id, phase=None):
        return [
            {
                "id": atlas_card_id,
                "work_id": request_work_id,
                "phase": "atlas",
                "artifact_type": "atlas_direction",
                "title": "Point-cloud inspection",
                "payload": {"name": "Point-cloud inspection"},
            },
            {
                "id": gap_card_id,
                "work_id": request_work_id,
                "phase": "frontier",
                "artifact_type": "frontier_gap",
                "title": "Sparse labels",
                "payload": {"name": "Sparse labels"},
            },
        ]

    async def fake_create_run(data):
        return {**data, "id": backing_run_id}

    async def fake_create_phase_execution(data):
        return {
            "id": execution_id,
            **data,
            "status": data["status"],
            "output_bundle_id": None,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }

    async def fake_enqueue_run(run_id, payload):
        enqueued.append((run_id, payload))
        return True

    async def fake_update_run(run_id, updates):
        return {**updates, "id": run_id}

    async def fake_update_phase_execution(phase_execution_id, updates):
        return {
            "id": phase_execution_id,
            "work_id": work_id,
            "phase": "frontier",
            "execution_kind": "standard",
            "status": updates["status"],
            "backing_run_id": backing_run_id,
            "output_bundle_id": None,
            "created_at": datetime.now(timezone.utc),
            "updated_at": updates["updated_at"],
        }

    monkeypatch.setattr("apps.api.database.get_work", fake_get_work)
    monkeypatch.setattr("apps.api.database.list_artifact_cards", fake_list_artifact_cards)
    monkeypatch.setattr("apps.api.database.create_run", fake_create_run)
    monkeypatch.setattr(
        "apps.api.database.create_phase_execution",
        fake_create_phase_execution,
    )
    monkeypatch.setattr("apps.api.database.update_run", fake_update_run)
    monkeypatch.setattr(
        "apps.api.database.update_phase_execution",
        fake_update_phase_execution,
    )
    monkeypatch.setattr("apps.worker.task_queue.enqueue_run", fake_enqueue_run)
    client = TestClient(app)

    response = client.post(
        f"/api/v1/works/{work_id}/phases/frontier/executions",
        json={"phase": "frontier", "manual_input": {}},
    )

    assert response.status_code == 201
    context_bundle = enqueued[0][1]["context_bundle"]
    assert context_bundle["sub_directions"] == [
        {"name": "Point-cloud inspection"},
    ]
    assert context_bundle["gaps"] == [{"name": "Sparse labels"}]
    assert context_bundle["artifact_cards"] == [
        {
            "id": str(atlas_card_id),
            "work_id": str(work_id),
            "phase": "atlas",
            "artifact_type": "atlas_direction",
            "title": "Point-cloud inspection",
            "payload": {"name": "Point-cloud inspection"},
        },
        {
            "id": str(gap_card_id),
            "work_id": str(work_id),
            "phase": "frontier",
            "artifact_type": "frontier_gap",
            "title": "Sparse labels",
            "payload": {"name": "Sparse labels"},
        },
    ]


def test_start_phase_execution_path_body_mismatch_returns_400():
    work_id = uuid4()
    client = TestClient(app)

    response = client.post(
        f"/api/v1/works/{work_id}/phases/frontier/executions",
        json={"phase": "atlas", "source_card_ids": [], "manual_input": {}},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Phase path and request body do not match"


def test_start_phase_execution_invalid_phase_returns_400():
    work_id = uuid4()
    client = TestClient(app)

    response = client.post(
        f"/api/v1/works/{work_id}/phases/invalid/executions",
        json={"phase": "frontier", "source_card_ids": [], "manual_input": {}},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid phase"


def test_start_non_atlas_phase_without_upstream_or_manual_input_returns_400(
    monkeypatch,
):
    work_id = uuid4()
    create_run_called = False
    enqueue_called = False

    async def fake_get_work(request_work_id, workspace_id):
        return {
            "id": request_work_id,
            "workspace_id": workspace_id,
            "title": "3D AD",
            "topic": "3D anomaly detection for point clouds",
            "budget_json": {},
            "policy_json": {},
            "project_id": None,
        }

    async def fake_list_artifact_cards(request_work_id, phase=None):
        return []

    async def fake_create_run(data):
        nonlocal create_run_called
        create_run_called = True
        return data

    async def fake_enqueue_run(run_id, payload):
        nonlocal enqueue_called
        enqueue_called = True

    monkeypatch.setattr("apps.api.database.get_work", fake_get_work)
    monkeypatch.setattr("apps.api.database.list_artifact_cards", fake_list_artifact_cards)
    monkeypatch.setattr("apps.api.database.create_run", fake_create_run)
    monkeypatch.setattr("apps.worker.task_queue.enqueue_run", fake_enqueue_run)
    client = TestClient(app)

    response = client.post(
        f"/api/v1/works/{work_id}/phases/frontier/executions",
        json={"phase": "frontier", "source_card_ids": [], "manual_input": {}},
    )

    assert response.status_code == 400
    assert (
        response.json()["detail"]
        == "Select upstream cards or provide manual input before starting this phase"
    )
    assert create_run_called is False
    assert enqueue_called is False


def test_start_phase_execution_rejects_wrong_work_source_card_before_create(
    monkeypatch,
):
    work_id = uuid4()
    foreign_card_id = uuid4()
    create_run_called = False
    create_execution_called = False
    enqueue_called = False

    async def fake_get_work(request_work_id, workspace_id):
        return {
            "id": request_work_id,
            "workspace_id": workspace_id,
            "title": "3D AD",
            "topic": "3D anomaly detection for point clouds",
            "budget_json": {},
            "policy_json": {},
            "project_id": None,
        }

    async def fake_list_artifact_cards(request_work_id, phase=None):
        return []

    async def fake_create_run(data):
        nonlocal create_run_called
        create_run_called = True
        return data

    async def fake_create_phase_execution(data):
        nonlocal create_execution_called
        create_execution_called = True
        return data

    async def fake_enqueue_run(run_id, payload):
        nonlocal enqueue_called
        enqueue_called = True

    monkeypatch.setattr("apps.api.database.get_work", fake_get_work)
    monkeypatch.setattr("apps.api.database.list_artifact_cards", fake_list_artifact_cards)
    monkeypatch.setattr("apps.api.database.create_run", fake_create_run)
    monkeypatch.setattr(
        "apps.api.database.create_phase_execution",
        fake_create_phase_execution,
    )
    monkeypatch.setattr("apps.worker.task_queue.enqueue_run", fake_enqueue_run)
    client = TestClient(app)

    response = client.post(
        f"/api/v1/works/{work_id}/phases/frontier/executions",
        json={
            "phase": "frontier",
            "source_card_ids": [str(foreign_card_id)],
            "manual_input": {"scope": "industrial point clouds"},
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Artifact card not found"
    assert create_run_called is False
    assert create_execution_called is False
    assert enqueue_called is False


def test_start_atlas_phase_allows_empty_upstream_and_manual_input(monkeypatch):
    work_id = uuid4()
    backing_run_id = uuid4()
    execution_id = uuid4()
    enqueued: list[tuple[UUID, dict[str, object]]] = []

    async def fake_get_work(request_work_id, workspace_id):
        return {
            "id": request_work_id,
            "workspace_id": workspace_id,
            "title": "3D AD",
            "topic": "3D anomaly detection for point clouds",
            "budget_json": {},
            "policy_json": {},
            "project_id": None,
        }

    async def fake_list_artifact_cards(request_work_id, phase=None):
        return []

    async def fake_create_run(data):
        assert data["mode"] == "atlas"
        assert data["parent_run_id"] is None
        return {**data, "id": backing_run_id}

    async def fake_create_phase_execution(data):
        return {
            "id": execution_id,
            **data,
            "status": data["status"],
            "output_bundle_id": None,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }

    async def fake_enqueue_run(run_id, payload):
        enqueued.append((run_id, payload))

    async def fake_update_run(run_id, updates):
        return {**updates, "id": run_id}

    async def fake_update_phase_execution(phase_execution_id, updates):
        return {
            "id": phase_execution_id,
            "work_id": work_id,
            "phase": "atlas",
            "execution_kind": "standard",
            "status": updates["status"],
            "backing_run_id": backing_run_id,
            "output_bundle_id": None,
            "created_at": datetime.now(timezone.utc),
            "updated_at": updates["updated_at"],
        }

    monkeypatch.setattr("apps.api.database.get_work", fake_get_work)
    monkeypatch.setattr("apps.api.database.list_artifact_cards", fake_list_artifact_cards)
    monkeypatch.setattr("apps.api.database.create_run", fake_create_run)
    monkeypatch.setattr(
        "apps.api.database.create_phase_execution",
        fake_create_phase_execution,
    )
    monkeypatch.setattr("apps.api.database.update_run", fake_update_run)
    monkeypatch.setattr(
        "apps.api.database.update_phase_execution",
        fake_update_phase_execution,
    )
    monkeypatch.setattr("apps.worker.task_queue.enqueue_run", fake_enqueue_run)
    client = TestClient(app)

    response = client.post(
        f"/api/v1/works/{work_id}/phases/atlas/executions",
        json={"phase": "atlas", "source_card_ids": [], "manual_input": {}},
    )

    assert response.status_code == 201
    assert response.json()["phase"] == "atlas"
    assert enqueued[0][0] == backing_run_id
    assert enqueued[0][1]["context_bundle"]["artifact_cards"] == []


def test_start_phase_execution_enqueue_failure_returns_503(monkeypatch):
    work_id = uuid4()
    source_card_id = uuid4()
    backing_run_id = uuid4()
    execution_id = uuid4()
    run_updates: list[tuple[UUID, dict[str, object]]] = []
    execution_updates: list[tuple[UUID, dict[str, object]]] = []

    async def fake_get_work(request_work_id, workspace_id):
        return {
            "id": request_work_id,
            "workspace_id": workspace_id,
            "title": "3D AD",
            "topic": "3D anomaly detection for point clouds",
            "budget_json": {},
            "policy_json": {},
            "project_id": None,
        }

    async def fake_list_artifact_cards(request_work_id, phase=None):
        return [
            {
                "id": source_card_id,
                "work_id": request_work_id,
                "phase": "atlas",
                "artifact_type": "atlas_direction",
                "title": "Point-cloud inspection",
                "payload": {"name": "Point-cloud inspection"},
            }
        ]

    async def fake_create_run(data):
        return {**data, "id": backing_run_id}

    async def fake_create_phase_execution(data):
        return {
            "id": execution_id,
            **data,
            "status": "queued",
            "output_bundle_id": None,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }

    async def fake_enqueue_run(run_id, payload):
        raise RuntimeError("queue unavailable")

    async def fake_update_run(run_id, updates):
        run_updates.append((run_id, updates))
        return updates

    async def fake_update_phase_execution(phase_execution_id, updates):
        execution_updates.append((phase_execution_id, updates))
        return updates

    monkeypatch.setattr("apps.api.database.get_work", fake_get_work)
    monkeypatch.setattr("apps.api.database.list_artifact_cards", fake_list_artifact_cards)
    monkeypatch.setattr("apps.api.database.create_run", fake_create_run)
    monkeypatch.setattr(
        "apps.api.database.create_phase_execution",
        fake_create_phase_execution,
    )
    monkeypatch.setattr("apps.api.database.update_run", fake_update_run)
    monkeypatch.setattr(
        "apps.api.database.update_phase_execution",
        fake_update_phase_execution,
    )
    monkeypatch.setattr("apps.worker.task_queue.enqueue_run", fake_enqueue_run)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(
        f"/api/v1/works/{work_id}/phases/frontier/executions",
        json={
            "phase": "frontier",
            "source_card_ids": [str(source_card_id)],
            "manual_input": {},
        },
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "Failed to enqueue run"
    assert run_updates[0][0] == backing_run_id
    assert run_updates[0][1]["status"] == "failed"
    assert isinstance(run_updates[0][1]["updated_at"], datetime)
    assert isinstance(run_updates[0][1]["completed_at"], datetime)
    assert execution_updates[0][0] == execution_id
    assert execution_updates[0][1]["status"] == "failed"
    assert execution_updates[0][1]["error_message"] == "Failed to enqueue run"
    assert isinstance(execution_updates[0][1]["updated_at"], datetime)
    assert isinstance(execution_updates[0][1]["completed_at"], datetime)


def test_start_phase_execution_marks_run_failed_when_execution_create_fails(
    monkeypatch,
):
    work_id = uuid4()
    source_card_id = uuid4()
    backing_run_id = uuid4()
    run_updates: list[tuple[UUID, dict[str, object]]] = []
    enqueue_called = False

    async def fake_get_work(request_work_id, workspace_id):
        return {
            "id": request_work_id,
            "workspace_id": workspace_id,
            "title": "3D AD",
            "topic": "3D anomaly detection for point clouds",
            "budget_json": {},
            "policy_json": {},
            "project_id": None,
        }

    async def fake_list_artifact_cards(request_work_id, phase=None):
        return [
            {
                "id": source_card_id,
                "work_id": request_work_id,
                "phase": "atlas",
                "artifact_type": "atlas_direction",
                "title": "Point-cloud inspection",
                "payload": {"name": "Point-cloud inspection"},
            }
        ]

    async def fake_create_run(data):
        return {**data, "id": backing_run_id}

    async def fake_create_phase_execution(data):
        raise RuntimeError("phase insert failed")

    async def fake_update_run(run_id, updates):
        run_updates.append((run_id, updates))
        return updates

    async def fake_enqueue_run(run_id, payload):
        nonlocal enqueue_called
        enqueue_called = True

    monkeypatch.setattr("apps.api.database.get_work", fake_get_work)
    monkeypatch.setattr("apps.api.database.list_artifact_cards", fake_list_artifact_cards)
    monkeypatch.setattr("apps.api.database.create_run", fake_create_run)
    monkeypatch.setattr(
        "apps.api.database.create_phase_execution",
        fake_create_phase_execution,
    )
    monkeypatch.setattr("apps.api.database.update_run", fake_update_run)
    monkeypatch.setattr("apps.worker.task_queue.enqueue_run", fake_enqueue_run)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(
        f"/api/v1/works/{work_id}/phases/frontier/executions",
        json={
            "phase": "frontier",
            "source_card_ids": [str(source_card_id)],
            "manual_input": {},
        },
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "Failed to create phase execution"
    assert run_updates[0][0] == backing_run_id
    assert run_updates[0][1]["status"] == "failed"
    assert isinstance(run_updates[0][1]["updated_at"], datetime)
    assert isinstance(run_updates[0][1]["completed_at"], datetime)
    assert enqueue_called is False


def test_start_phase_execution_enqueues_json_serializable_card_context(
    monkeypatch,
):
    work_id = uuid4()
    source_card_id = uuid4()
    backing_run_id = uuid4()
    execution_id = uuid4()
    source_execution_id = uuid4()
    upstream_card_id = uuid4()
    created_at = datetime.now(timezone.utc)
    pushed: list[str] = []

    class FakeRedis:
        async def rpush(self, _queue_key, job):
            pushed.append(job)

    async def fake_get_work(request_work_id, workspace_id):
        return {
            "id": request_work_id,
            "workspace_id": workspace_id,
            "title": "3D AD",
            "topic": "3D anomaly detection for point clouds",
            "budget_json": {"max_new_papers": 50},
            "policy_json": {"keywords": ["3d anomaly"]},
            "project_id": None,
        }

    async def fake_list_artifact_cards(request_work_id, phase=None):
        return [
            {
                "id": source_card_id,
                "work_id": request_work_id,
                "phase": "atlas",
                "artifact_type": "atlas_direction",
                "title": "Point-cloud inspection",
                "body": "Inspect sparse point clouds.",
                "payload": {
                    "name": "Point-cloud inspection",
                    "related_ids": [uuid4()],
                    "observed_at": created_at,
                },
                "status": "active",
                "selection_state": "selected",
                "source_execution_id": source_execution_id,
                "source_card_ids": [upstream_card_id],
                "created_at": created_at,
                "updated_at": created_at,
            }
        ]

    async def fake_create_run(data):
        return {**data, "id": backing_run_id}

    async def fake_create_phase_execution(data):
        return {
            "id": execution_id,
            **data,
            "status": data["status"],
            "output_bundle_id": None,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }

    async def fake_get_redis():
        return FakeRedis()

    async def fake_update_run(run_id, updates):
        return {**updates, "id": run_id}

    async def fake_update_phase_execution(phase_execution_id, updates):
        return {
            "id": phase_execution_id,
            "work_id": work_id,
            "phase": "frontier",
            "execution_kind": "standard",
            "status": updates["status"],
            "backing_run_id": backing_run_id,
            "output_bundle_id": None,
            "created_at": datetime.now(timezone.utc),
            "updated_at": updates["updated_at"],
        }

    monkeypatch.setattr("apps.api.database.get_work", fake_get_work)
    monkeypatch.setattr("apps.api.database.list_artifact_cards", fake_list_artifact_cards)
    monkeypatch.setattr("apps.api.database.create_run", fake_create_run)
    monkeypatch.setattr(
        "apps.api.database.create_phase_execution",
        fake_create_phase_execution,
    )
    monkeypatch.setattr("apps.api.database.update_run", fake_update_run)
    monkeypatch.setattr(
        "apps.api.database.update_phase_execution",
        fake_update_phase_execution,
    )
    monkeypatch.setattr("apps.worker.task_queue.get_redis", fake_get_redis)
    client = TestClient(app)

    response = client.post(
        f"/api/v1/works/{work_id}/phases/frontier/executions",
        json={
            "phase": "frontier",
            "source_card_ids": [str(source_card_id)],
            "manual_input": {"scope": "industrial point clouds"},
        },
    )

    assert response.status_code == 201
    queued = json.loads(pushed[0])
    context_bundle = queued["context_bundle"]
    assert context_bundle["sub_directions"][0]["name"] == "Point-cloud inspection"
    assert context_bundle["sub_directions"][0]["observed_at"] == created_at.isoformat()
    assert context_bundle["artifact_cards"][0] == {
        "id": str(source_card_id),
        "work_id": str(work_id),
        "phase": "atlas",
        "artifact_type": "atlas_direction",
        "title": "Point-cloud inspection",
        "body": "Inspect sparse point clouds.",
        "payload": context_bundle["sub_directions"][0],
        "status": "active",
        "selection_state": "selected",
        "source_execution_id": str(source_execution_id),
        "source_card_ids": [str(upstream_card_id)],
    }
