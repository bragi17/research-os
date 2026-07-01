from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

WORKSPACE_A = UUID("11111111-1111-1111-1111-111111111111")
WORKSPACE_B = UUID("22222222-2222-2222-2222-222222222222")
USER_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


def _run(
    run_id: UUID,
    workspace_id: UUID,
    title: str,
    status: str = "queued",
) -> dict[str, Any]:
    now = datetime.utcnow()
    return {
        "id": run_id,
        "workspace_id": workspace_id,
        "created_by": USER_A,
        "title": title,
        "topic": "Workspace scoped research run visibility",
        "status": status,
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
        "mode": "atlas",
        "parent_run_id": None,
        "context_bundle_id": None,
        "output_bundle_id": None,
        "current_stage": "init",
        "project_id": None,
    }


async def fake_get_current_user() -> dict[str, Any]:
    return {
        "id": USER_A,
        "workspace_id": WORKSPACE_A,
        "role": "research_user",
    }


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    import apps.api.auth as auth
    import apps.api.database as database
    import apps.api.redis_queue as redis_queue
    from apps.api.app import create_app

    original_get_current_user = auth.get_current_user
    monkeypatch.setattr(auth, "get_current_user", fake_get_current_user)
    monkeypatch.setattr(database, "init_pool", AsyncMock())
    monkeypatch.setattr(database, "close_pool", AsyncMock())
    monkeypatch.setattr(redis_queue, "init_redis", AsyncMock())
    monkeypatch.setattr(redis_queue, "close_redis", AsyncMock())

    app = create_app()
    app.dependency_overrides[original_get_current_user] = fake_get_current_user
    return TestClient(app)


def test_list_runs_passes_workspace_id_and_returns_visible_run(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import apps.api.database as database

    visible_run_id = uuid4()
    hidden_run_id = uuid4()
    calls: list[dict[str, Any]] = []

    async def fake_list_runs(
        *,
        status: str | None = None,
        limit: int = 20,
        offset: int = 0,
        workspace_id: UUID,
    ) -> list[dict[str, Any]]:
        calls.append({
            "status": status,
            "limit": limit,
            "offset": offset,
            "workspace_id": workspace_id,
        })
        assert hidden_run_id != visible_run_id
        return [_run(visible_run_id, WORKSPACE_A, "Visible run")]

    monkeypatch.setattr(database, "list_runs", fake_list_runs)

    response = client.get("/api/v1/runs")

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [str(visible_run_id)]
    assert calls == [{
        "status": None,
        "limit": 20,
        "offset": 0,
        "workspace_id": WORKSPACE_A,
    }]


def test_get_run_passes_workspace_id_and_returns_404_when_missing(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import apps.api.database as database

    run_id = uuid4()
    calls: list[tuple[UUID, UUID]] = []

    async def fake_get_run(run_id_arg: UUID, *, workspace_id: UUID) -> None:
        calls.append((run_id_arg, workspace_id))
        return None

    monkeypatch.setattr(database, "get_run", fake_get_run)

    response = client.get(f"/api/v1/runs/{run_id}")

    assert response.status_code == 404
    assert response.json()["detail"] == "Run not found"
    assert calls == [(run_id, WORKSPACE_A)]


def test_patch_run_scopes_get_before_update(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import apps.api.database as database

    run_id = uuid4()
    calls: list[str] = []

    async def fake_get_run(run_id_arg: UUID, *, workspace_id: UUID) -> dict[str, Any]:
        assert run_id_arg == run_id
        assert workspace_id == WORKSPACE_A
        calls.append("get")
        return _run(run_id, WORKSPACE_A, "Original title")

    async def fake_update_run(
        run_id_arg: UUID,
        updates: dict[str, Any],
    ) -> dict[str, Any]:
        assert calls == ["get"]
        calls.append("update")
        updated = _run(run_id_arg, WORKSPACE_A, updates["title"])
        updated.update(updates)
        return updated

    monkeypatch.setattr(database, "get_run", fake_get_run)
    monkeypatch.setattr(database, "update_run", fake_update_run)

    response = client.patch(f"/api/v1/runs/{run_id}", json={"title": "New title"})

    assert response.status_code == 200
    assert calls == ["get", "update"]
    assert response.json()["title"] == "New title"


def test_patch_run_returns_404_without_update_when_scoped_get_missing(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import apps.api.database as database

    run_id = uuid4()
    get_calls: list[tuple[UUID, UUID]] = []
    update_calls: list[tuple[UUID, dict[str, Any]]] = []

    async def fake_get_run(run_id_arg: UUID, *, workspace_id: UUID) -> None:
        get_calls.append((run_id_arg, workspace_id))
        return None

    async def fake_update_run(run_id_arg: UUID, updates: dict[str, Any]) -> None:
        update_calls.append((run_id_arg, updates))
        return None

    monkeypatch.setattr(database, "get_run", fake_get_run)
    monkeypatch.setattr(database, "update_run", fake_update_run)

    response = client.patch(f"/api/v1/runs/{run_id}", json={"title": "New title"})

    assert response.status_code == 404
    assert response.json()["detail"] == "Run not found"
    assert get_calls == [(run_id, WORKSPACE_A)]
    assert update_calls == []


def test_delete_run_returns_404_without_unscoped_delete_when_scoped_get_missing(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import apps.api.database as database

    run_id = uuid4()
    get_calls: list[tuple[UUID, UUID]] = []
    execute_calls: list[str] = []
    fetchrow_calls: list[str] = []

    async def fake_get_run(run_id_arg: UUID, *, workspace_id: UUID) -> None:
        get_calls.append((run_id_arg, workspace_id))
        return None

    class FakePool:
        async def fetchrow(self, sql: str, *_args: Any) -> None:
            fetchrow_calls.append(sql)
            return None

        async def execute(self, sql: str, *_args: Any) -> str:
            execute_calls.append(sql)
            return "DELETE 1"

    monkeypatch.setattr(database, "get_run", fake_get_run)
    monkeypatch.setattr(database, "get_pool", AsyncMock(return_value=FakePool()))

    response = client.delete(f"/api/v1/runs/{run_id}")

    assert response.status_code == 404
    assert response.json()["detail"] == "Run not found"
    assert get_calls == [(run_id, WORKSPACE_A)]
    assert fetchrow_calls == []
    assert execute_calls == []


def test_delete_run_scopes_get_before_child_and_run_deletes(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import apps.api.database as database

    run_id = uuid4()
    calls: list[tuple[str, Any, Any]] = []

    async def fake_get_run(
        run_id_arg: UUID,
        *,
        workspace_id: UUID,
    ) -> dict[str, Any]:
        calls.append(("get", run_id_arg, workspace_id))
        return _run(run_id, WORKSPACE_A, "Deletable run")

    class FakePool:
        async def fetchrow(self, sql: str, *_args: Any) -> None:
            calls.append(("fetchrow", sql, _args))
            return None

        async def execute(self, sql: str, *args: Any) -> str:
            calls.append(("execute", sql, args))
            return "DELETE 1"

    monkeypatch.setattr(database, "get_run", fake_get_run)
    monkeypatch.setattr(database, "get_pool", AsyncMock(return_value=FakePool()))

    response = client.delete(f"/api/v1/runs/{run_id}")

    assert response.status_code == 200
    assert response.json() == {"status": "deleted", "run_id": str(run_id)}
    assert calls[0] == ("get", run_id, WORKSPACE_A)
    assert not any(call[0] == "fetchrow" for call in calls)
    assert [call[1] for call in calls[1:]] == [
        "DELETE FROM run_event WHERE run_id = $1",
        "DELETE FROM pain_point WHERE run_id = $1",
        "DELETE FROM reading_path WHERE run_id = $1",
        "DELETE FROM idea_card WHERE run_id = $1",
        "DELETE FROM research_run WHERE id = $1",
    ]
    assert all(call[2] == (run_id,) for call in calls[1:])


@pytest.mark.parametrize(
    ("path_suffix", "method_body", "existing_status", "expected_status"),
    [
        ("start", None, "queued", "started"),
        ("pause", {"mode": "soft"}, "running", "paused"),
        ("resume", {}, "paused", "resumed"),
        ("cancel", None, "running", "cancelled"),
    ],
)
def test_run_actions_scope_get_before_update(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    path_suffix: str,
    method_body: dict[str, Any] | None,
    existing_status: str,
    expected_status: str,
) -> None:
    import apps.api.database as database
    import apps.api.routes_runs as routes_runs

    run_id = uuid4()
    calls: list[str] = []

    async def fake_get_run(run_id_arg: UUID, *, workspace_id: UUID) -> dict[str, Any]:
        assert run_id_arg == run_id
        assert workspace_id == WORKSPACE_A
        calls.append("get")
        return _run(run_id, WORKSPACE_A, "Action run", status=existing_status)

    async def fake_update_run(
        run_id_arg: UUID,
        updates: dict[str, Any],
    ) -> dict[str, Any]:
        assert calls == ["get"]
        calls.append("update")
        updated = _run(
            run_id_arg,
            WORKSPACE_A,
            "Action run",
            status=updates.get("status", existing_status),
        )
        updated.update(updates)
        return updated

    async def fake_create_event(**_kwargs: Any) -> dict[str, Any]:
        return {}

    async def fake_enqueue_run(_run_id: UUID, _run: dict[str, Any]) -> bool:
        return True

    async def fake_publish_event(_run_id: UUID, _event: dict[str, Any]) -> None:
        return None

    monkeypatch.setattr(database, "get_run", fake_get_run)
    monkeypatch.setattr(database, "update_run", fake_update_run)
    monkeypatch.setattr(database, "create_event", fake_create_event)
    monkeypatch.setattr(routes_runs, "enqueue_run", fake_enqueue_run)
    monkeypatch.setattr(routes_runs, "publish_event", fake_publish_event)

    response = client.post(
        f"/api/v1/runs/{run_id}/{path_suffix}",
        json=method_body,
    )

    assert response.status_code == 200
    assert response.json()["status"] == expected_status
    assert calls == ["get", "update"]


def test_start_run_uses_timezone_aware_utc_timestamps(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import apps.api.database as database
    import apps.api.routes_runs as routes_runs

    run_id = uuid4()
    update_calls: list[dict[str, Any]] = []

    async def fake_get_run(run_id_arg: UUID, *, workspace_id: UUID) -> dict[str, Any]:
        assert run_id_arg == run_id
        assert workspace_id == WORKSPACE_A
        return _run(run_id, WORKSPACE_A, "Timezone-safe run")

    async def fake_update_run(
        run_id_arg: UUID,
        updates: dict[str, Any],
    ) -> dict[str, Any]:
        assert run_id_arg == run_id
        update_calls.append(updates)
        updated = _run(run_id, WORKSPACE_A, "Timezone-safe run", status=updates["status"])
        updated.update(updates)
        return updated

    async def fake_create_event(**_kwargs: Any) -> dict[str, Any]:
        return {}

    async def fake_enqueue_run(_run_id: UUID, _run: dict[str, Any]) -> bool:
        return True

    async def fake_publish_event(_run_id: UUID, _event: dict[str, Any]) -> None:
        return None

    monkeypatch.setattr(database, "get_run", fake_get_run)
    monkeypatch.setattr(database, "update_run", fake_update_run)
    monkeypatch.setattr(database, "create_event", fake_create_event)
    monkeypatch.setattr(routes_runs, "enqueue_run", fake_enqueue_run)
    monkeypatch.setattr(routes_runs, "publish_event", fake_publish_event)

    response = client.post(f"/api/v1/runs/{run_id}/start")

    assert response.status_code == 200
    assert len(update_calls) == 1
    assert update_calls[0]["started_at"].tzinfo is timezone.utc
    assert update_calls[0]["updated_at"].tzinfo is timezone.utc


def test_start_run_returns_503_without_marking_running_when_enqueue_fails(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import apps.api.database as database
    import apps.api.routes_runs as routes_runs

    run_id = uuid4()
    update_calls: list[dict[str, Any]] = []

    async def fake_get_run(run_id_arg: UUID, *, workspace_id: UUID) -> dict[str, Any]:
        assert run_id_arg == run_id
        assert workspace_id == WORKSPACE_A
        return _run(run_id, WORKSPACE_A, "Queue failure run")

    async def fake_update_run(
        run_id_arg: UUID,
        updates: dict[str, Any],
    ) -> dict[str, Any]:
        assert run_id_arg == run_id
        update_calls.append(updates)
        updated = _run(run_id, WORKSPACE_A, "Queue failure run", status=updates["status"])
        updated.update(updates)
        return updated

    async def fake_create_event(**_kwargs: Any) -> dict[str, Any]:
        return {}

    async def fake_enqueue_run(_run_id: UUID, _run: dict[str, Any]) -> bool:
        return False

    async def fake_publish_event(_run_id: UUID, _event: dict[str, Any]) -> None:
        return None

    monkeypatch.setattr(database, "get_run", fake_get_run)
    monkeypatch.setattr(database, "update_run", fake_update_run)
    monkeypatch.setattr(database, "create_event", fake_create_event)
    monkeypatch.setattr(routes_runs, "enqueue_run", fake_enqueue_run)
    monkeypatch.setattr(routes_runs, "publish_event", fake_publish_event)

    response = client.post(f"/api/v1/runs/{run_id}/start")

    assert response.status_code == 503
    assert response.json()["detail"] == "Failed to enqueue run"
    assert update_calls == []


@pytest.mark.parametrize(
    ("path_suffix", "method_body"),
    [
        ("start", None),
        ("pause", {"mode": "soft"}),
        ("resume", {}),
        ("cancel", None),
    ],
)
def test_run_actions_return_404_without_mutation_when_scoped_get_missing(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    path_suffix: str,
    method_body: dict[str, Any] | None,
) -> None:
    import apps.api.database as database
    import apps.api.routes_runs as routes_runs

    run_id = uuid4()
    get_calls: list[tuple[UUID, UUID]] = []
    update_calls: list[tuple[UUID, dict[str, Any]]] = []
    event_calls: list[dict[str, Any]] = []
    queue_calls: list[UUID] = []
    publish_calls: list[UUID] = []

    async def fake_get_run(run_id_arg: UUID, *, workspace_id: UUID) -> None:
        get_calls.append((run_id_arg, workspace_id))
        return None

    async def fake_update_run(run_id_arg: UUID, updates: dict[str, Any]) -> None:
        update_calls.append((run_id_arg, updates))
        return None

    async def fake_create_event(**kwargs: Any) -> dict[str, Any]:
        event_calls.append(kwargs)
        return {}

    async def fake_enqueue_run(run_id_arg: UUID, _run: dict[str, Any]) -> bool:
        queue_calls.append(run_id_arg)
        return True

    async def fake_publish_event(run_id_arg: UUID, _event: dict[str, Any]) -> None:
        publish_calls.append(run_id_arg)

    monkeypatch.setattr(database, "get_run", fake_get_run)
    monkeypatch.setattr(database, "update_run", fake_update_run)
    monkeypatch.setattr(database, "create_event", fake_create_event)
    monkeypatch.setattr(routes_runs, "enqueue_run", fake_enqueue_run)
    monkeypatch.setattr(routes_runs, "publish_event", fake_publish_event)

    response = client.post(
        f"/api/v1/runs/{run_id}/{path_suffix}",
        json=method_body,
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Run not found"
    assert get_calls == [(run_id, WORKSPACE_A)]
    assert update_calls == []
    assert event_calls == []
    assert queue_calls == []
    assert publish_calls == []


def test_status_passes_workspace_id_to_counts(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import apps.api.database as database

    calls: list[tuple[str, UUID]] = []

    async def fake_count_runs(
        status: str | None = None,
        *,
        workspace_id: UUID,
    ) -> int:
        assert status is None
        calls.append(("count_runs", workspace_id))
        return 1

    async def fake_count_runs_by_status(*, workspace_id: UUID) -> dict[str, int]:
        calls.append(("count_runs_by_status", workspace_id))
        return {"queued": 1}

    monkeypatch.setattr(database, "count_runs", fake_count_runs)
    monkeypatch.setattr(database, "count_runs_by_status", fake_count_runs_by_status)

    response = client.get("/api/v1/status")

    assert response.status_code == 200
    assert response.json()["runs_total"] == 1
    assert response.json()["runs_by_status"]["queued"] == 1
    assert calls == [
        ("count_runs", WORKSPACE_A),
        ("count_runs_by_status", WORKSPACE_A),
    ]


def test_queue_status_requires_auth_and_passes_workspace_id(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import apps.api.database as database
    import apps.api.routes_queue as routes_queue

    calls: list[UUID] = []

    async def fake_count_runs_by_status(*, workspace_id: UUID) -> dict[str, int]:
        calls.append(workspace_id)
        return {"queued": 2, "running": 1, "paused": 0}

    async def fake_queue_length() -> int:
        return 9

    monkeypatch.setattr(database, "count_runs_by_status", fake_count_runs_by_status)
    monkeypatch.setattr(routes_queue, "get_queue_length", fake_queue_length)
    monkeypatch.setattr(routes_queue, "get_redis", lambda: object())

    response = client.get("/api/v1/queue/status")

    assert response.status_code == 200
    assert response.json() == {
        "redis_available": True,
        "queue_length": 9,
        "active_runs": 1,
        "queued_runs": 2,
        "paused_runs": 0,
    }
    assert calls == [WORKSPACE_A]


def test_get_events_returns_404_without_event_queries_when_scoped_get_missing(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import apps.api.database as database

    run_id = uuid4()
    get_calls: list[tuple[UUID, UUID]] = []
    event_calls: list[str] = []

    async def fake_get_run(run_id_arg: UUID, *, workspace_id: UUID) -> None:
        get_calls.append((run_id_arg, workspace_id))
        return None

    async def fake_count_events(_run_id: UUID) -> int:
        event_calls.append("count")
        return 0

    async def fake_list_events(
        _run_id: UUID,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        event_calls.append(f"list:{limit}:{offset}")
        return []

    monkeypatch.setattr(database, "get_run", fake_get_run)
    monkeypatch.setattr(database, "count_events", fake_count_events)
    monkeypatch.setattr(database, "list_events", fake_list_events)

    response = client.get(f"/api/v1/runs/{run_id}/events")

    assert response.status_code == 404
    assert response.json()["detail"] == "Run not found"
    assert get_calls == [(run_id, WORKSPACE_A)]
    assert event_calls == []


def test_stream_events_returns_404_when_scoped_get_missing(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import apps.api.database as database

    run_id = uuid4()
    get_calls: list[tuple[UUID, UUID]] = []
    event_calls: list[str] = []

    async def fake_get_run(run_id_arg: UUID, *, workspace_id: UUID) -> None:
        get_calls.append((run_id_arg, workspace_id))
        return None

    async def fake_count_events(_run_id: UUID) -> int:
        event_calls.append("count")
        return 0

    monkeypatch.setattr(database, "get_run", fake_get_run)
    monkeypatch.setattr(database, "count_events", fake_count_events)

    response = client.get(f"/api/v1/runs/{run_id}/events/stream")

    assert response.status_code == 404
    assert response.json()["detail"] == "Run not found"
    assert get_calls == [(run_id, WORKSPACE_A)]
    assert event_calls == []


def test_get_hypotheses_returns_404_without_query_when_scoped_get_missing(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import apps.api.database as database

    run_id = uuid4()
    get_calls: list[tuple[UUID, UUID]] = []
    hypothesis_calls: list[UUID] = []

    async def fake_get_run(run_id_arg: UUID, *, workspace_id: UUID) -> None:
        get_calls.append((run_id_arg, workspace_id))
        return None

    async def fake_list_hypotheses(run_id_arg: UUID) -> list[dict[str, Any]]:
        hypothesis_calls.append(run_id_arg)
        return []

    monkeypatch.setattr(database, "get_run", fake_get_run)
    monkeypatch.setattr(database, "list_hypotheses", fake_list_hypotheses)

    response = client.get(f"/api/v1/runs/{run_id}/hypotheses")

    assert response.status_code == 404
    assert response.json()["detail"] == "Run not found"
    assert get_calls == [(run_id, WORKSPACE_A)]
    assert hypothesis_calls == []


def test_export_returns_404_when_scoped_get_missing(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import apps.api.database as database

    run_id = uuid4()
    get_calls: list[tuple[UUID, UUID]] = []

    async def fake_get_run(run_id_arg: UUID, *, workspace_id: UUID) -> None:
        get_calls.append((run_id_arg, workspace_id))
        return None

    monkeypatch.setattr(database, "get_run", fake_get_run)

    response = client.post(f"/api/v1/runs/{run_id}/export", json={"formats": ["json"]})

    assert response.status_code == 404
    assert response.json()["detail"] == "Run not found"
    assert get_calls == [(run_id, WORKSPACE_A)]


def test_get_papers_returns_404_without_paper_queries_when_scoped_get_missing(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import apps.api.database as database

    run_id = uuid4()
    get_calls: list[tuple[UUID, UUID]] = []
    paper_calls: list[str] = []

    async def fake_get_run(run_id_arg: UUID, *, workspace_id: UUID) -> None:
        get_calls.append((run_id_arg, workspace_id))
        return None

    async def fake_count_papers_by_run(run_id_arg: UUID) -> int:
        paper_calls.append(f"count:{run_id_arg}")
        return 0

    async def fake_list_papers_by_run(
        run_id_arg: UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        paper_calls.append(f"list:{run_id_arg}:{limit}:{offset}")
        return []

    monkeypatch.setattr(database, "get_run", fake_get_run)
    monkeypatch.setattr(database, "count_papers_by_run", fake_count_papers_by_run)
    monkeypatch.setattr(database, "list_papers_by_run", fake_list_papers_by_run)

    response = client.get(f"/api/v1/runs/{run_id}/papers")

    assert response.status_code == 404
    assert response.json()["detail"] == "Run not found"
    assert get_calls == [(run_id, WORKSPACE_A)]
    assert paper_calls == []


def test_download_json_returns_404_without_export_queries_when_scoped_get_missing(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import apps.api.database as database

    run_id = uuid4()
    get_calls: list[tuple[UUID, UUID]] = []
    export_calls: list[str] = []

    async def fake_get_run(run_id_arg: UUID, *, workspace_id: UUID) -> None:
        get_calls.append((run_id_arg, workspace_id))
        return None

    async def fake_list_papers_by_run(
        _run_id: UUID,
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        export_calls.append(f"papers:{limit}:{offset}")
        return []

    async def fake_list_hypotheses(_run_id: UUID) -> list[dict[str, Any]]:
        export_calls.append("hypotheses")
        return []

    async def fake_list_events(
        _run_id: UUID,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        export_calls.append(f"events:{limit}:{offset}")
        return []

    monkeypatch.setattr(database, "get_run", fake_get_run)
    monkeypatch.setattr(database, "list_papers_by_run", fake_list_papers_by_run)
    monkeypatch.setattr(database, "list_hypotheses", fake_list_hypotheses)
    monkeypatch.setattr(database, "list_events", fake_list_events)

    response = client.get(f"/api/v1/runs/{run_id}/downloads/json")

    assert response.status_code == 404
    assert response.json()["detail"] == "Run not found"
    assert get_calls == [(run_id, WORKSPACE_A)]
    assert export_calls == []
