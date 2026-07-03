from __future__ import annotations

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
