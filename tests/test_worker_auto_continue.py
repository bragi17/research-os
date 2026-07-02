from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest

from apps.worker.modes.base import ModeGraphState


@pytest.mark.asyncio
async def test_completed_frontier_run_auto_spawns_divergent_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.api import database
    from apps.worker import runner as runner_module
    from apps.worker import task_queue
    from apps.worker.runner import WorkerRunner

    parent_id = UUID("11111111-1111-1111-1111-111111111111")
    workspace_id = UUID("22222222-2222-2222-2222-222222222222")
    project_id = UUID("33333333-3333-3333-3333-333333333333")
    created_runs: list[dict[str, Any]] = []
    updates: list[tuple[UUID, dict[str, Any]]] = []
    events: list[tuple[UUID, str, dict[str, Any]]] = []
    queued: list[tuple[UUID, dict[str, Any]]] = []
    published: list[tuple[UUID, dict[str, Any]]] = []

    async def fake_list_child_runs(
        parent_run_id: UUID,
        mode: str | None = None,
    ) -> list[dict[str, Any]]:
        assert parent_run_id == parent_id
        assert mode == "divergent"
        return []

    async def fake_create_run(run_data: dict[str, Any]) -> dict[str, Any]:
        created_runs.append(run_data)
        return dict(run_data)

    async def fake_update_run(run_id: UUID, fields: dict[str, Any]) -> None:
        updates.append((run_id, fields))

    async def fake_create_event(
        run_id: UUID,
        event_type: str,
        severity: str = "info",
        payload: dict[str, Any] | None = None,
    ) -> None:
        events.append((run_id, event_type, payload or {}))

    async def fake_enqueue_run(run_id: UUID, payload: dict[str, Any]) -> None:
        queued.append((run_id, payload))

    async def fake_publish_event(run_id: UUID, event: dict[str, Any]) -> None:
        published.append((run_id, event))

    monkeypatch.setattr(database, "list_child_runs", fake_list_child_runs, raising=False)
    monkeypatch.setattr(database, "create_run", fake_create_run)
    monkeypatch.setattr(database, "update_run", fake_update_run)
    monkeypatch.setattr(database, "create_event", fake_create_event)
    monkeypatch.setattr(task_queue, "enqueue_run", fake_enqueue_run)
    monkeypatch.setattr(task_queue, "publish_event", fake_publish_event)
    monkeypatch.setattr(
        runner_module,
        "uuid4",
        lambda: UUID("44444444-4444-4444-4444-444444444444"),
        raising=False,
    )

    state = ModeGraphState(
        run_id=parent_id,
        mode="frontier",
        topic="structured light 3D reconstruction telecentric camera",
        current_step="frontier_summary",
        should_stop=True,
        stop_reason="completed",
        papers_discovered=4,
        papers_read=3,
        gaps=[{"description": "Gap A", "gap_type": "method"}],
        context_bundle={
            "gaps": [{"description": "Gap A", "gap_type": "method"}],
            "paper_summaries": [{"title": "Paper A"}],
        },
    )
    parent_run = {
        "id": parent_id,
        "workspace_id": workspace_id,
        "created_by": UUID("55555555-5555-5555-5555-555555555555"),
        "project_id": project_id,
        "title": "Frontier Run",
        "topic": state.topic,
        "status": "running",
        "goal_type": "survey_plus_innovations",
        "autonomy_mode": "default_autonomous",
        "budget_json": {"max_fulltext_reads": 5},
        "policy_json": {"keywords": ["structured light"], "library_pool_ids": []},
        "context_bundle_id": None,
    }

    child = await WorkerRunner()._maybe_spawn_next_mode(
        parent_run_id=parent_id,
        parent_run=parent_run,
        mode="frontier",
        final_status="completed",
        result_state=state,
    )

    assert child is not None
    assert created_runs[0]["id"] == UUID("44444444-4444-4444-4444-444444444444")
    assert created_runs[0]["mode"] == "divergent"
    assert created_runs[0]["parent_run_id"] == parent_id
    assert created_runs[0]["workspace_id"] == workspace_id
    assert created_runs[0]["status"] == "queued"
    assert updates == []
    assert queued[0][0] == created_runs[0]["id"]
    assert queued[0][1]["mode"] == "divergent"
    assert queued[0][1]["context_bundle"]["gaps"][0]["description"] == "Gap A"
    assert queued[0][1]["context_bundle"]["source_run_id"] == str(parent_id)
    assert any(
        run_id == parent_id
        and event_type == "run.child_spawned"
        and payload["target_mode"] == "divergent"
        and payload["auto"] is True
        for run_id, event_type, payload in events
    )
    assert any(
        run_id == created_runs[0]["id"]
        and event_type == "run.enqueued"
        and payload["auto_spawned"] is True
        for run_id, event_type, payload in events
    )
    assert any(
        run_id == parent_id and event.get("event_type") == "run.child_spawned"
        for run_id, event in published
    )


@pytest.mark.asyncio
async def test_completed_frontier_run_does_not_duplicate_existing_divergent_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.api import database
    from apps.worker.runner import WorkerRunner

    parent_id = UUID("11111111-1111-1111-1111-111111111111")
    child_id = UUID("66666666-6666-6666-6666-666666666666")
    created_runs: list[dict[str, Any]] = []

    async def fake_list_child_runs(
        parent_run_id: UUID,
        mode: str | None = None,
    ) -> list[dict[str, Any]]:
        return [{"id": child_id, "parent_run_id": parent_run_id, "mode": mode}]

    async def fake_create_run(run_data: dict[str, Any]) -> dict[str, Any]:
        created_runs.append(run_data)
        return dict(run_data)

    monkeypatch.setattr(database, "list_child_runs", fake_list_child_runs, raising=False)
    monkeypatch.setattr(database, "create_run", fake_create_run)

    existing = await WorkerRunner()._maybe_spawn_next_mode(
        parent_run_id=parent_id,
        parent_run={
            "id": parent_id,
            "workspace_id": UUID("22222222-2222-2222-2222-222222222222"),
            "title": "Frontier Run",
            "topic": "structured light 3D reconstruction telecentric camera",
            "goal_type": "survey_plus_innovations",
            "policy_json": {},
            "budget_json": {},
        },
        mode="frontier",
        final_status="completed",
        result_state=ModeGraphState(run_id=parent_id, mode="frontier"),
    )

    assert existing == {"id": child_id, "parent_run_id": parent_id, "mode": "divergent"}
    assert created_runs == []


@pytest.mark.asyncio
async def test_execute_run_in_workspace_calls_auto_spawn_after_persistence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.api import database
    from apps.worker import task_queue
    from apps.worker import llm_gateway
    from apps.worker.runner import WorkerRunner

    run_id = UUID("11111111-1111-1111-1111-111111111111")
    calls: list[str] = []

    async def fake_update_run(*args: Any, **kwargs: Any) -> None:
        return None

    async def fake_create_event(*args: Any, **kwargs: Any) -> None:
        return None

    async def fake_publish_event(*args: Any, **kwargs: Any) -> None:
        return None

    async def fake_run_mode_graph(self: WorkerRunner, **kwargs: Any) -> ModeGraphState:
        return ModeGraphState(
            run_id=run_id,
            mode="frontier",
            topic="structured light 3D reconstruction telecentric camera",
            current_step="frontier_summary",
            should_stop=True,
            stop_reason="completed",
        )

    async def fake_persist_results(self: WorkerRunner, run_id_arg: UUID, state: Any) -> None:
        calls.append("persist")

    def fake_write_workspace_outputs(self: WorkerRunner, run_id_arg: UUID, run: dict[str, Any], state: Any) -> None:
        calls.append("write")

    async def fake_maybe_spawn_next_mode(self: WorkerRunner, **kwargs: Any) -> None:
        calls.append("auto_spawn")

    monkeypatch.setattr(database, "update_run", fake_update_run)
    monkeypatch.setattr(database, "create_event", fake_create_event)
    monkeypatch.setattr(task_queue, "publish_event", fake_publish_event)
    monkeypatch.setattr(llm_gateway, "get_gateway", lambda: SimpleNamespace(total_tokens=0, call_count=0))
    monkeypatch.setattr(WorkerRunner, "_run_mode_graph", fake_run_mode_graph)
    monkeypatch.setattr(WorkerRunner, "_persist_results", fake_persist_results)
    monkeypatch.setattr(WorkerRunner, "_write_workspace_outputs", fake_write_workspace_outputs)
    monkeypatch.setattr(WorkerRunner, "_maybe_spawn_next_mode", fake_maybe_spawn_next_mode, raising=False)

    await WorkerRunner()._execute_run_in_workspace(
        run_id,
        {"run_id": str(run_id), "mode": "frontier"},
        {
            "id": run_id,
            "workspace_id": UUID("22222222-2222-2222-2222-222222222222"),
            "topic": "structured light 3D reconstruction telecentric camera",
            "title": "Frontier Run",
            "mode": "frontier",
            "goal_type": "survey_plus_innovations",
            "budget_json": {},
            "policy_json": {},
        },
    )

    assert calls == ["persist", "write", "auto_spawn"]
