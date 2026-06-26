from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest

from services.workspace_context import (
    DEFAULT_WORKSPACE_UUID,
    current_workspace_id,
    workspace_context,
)


def test_workspace_context_defaults_to_development_workspace() -> None:
    assert current_workspace_id() == DEFAULT_WORKSPACE_UUID


def test_workspace_context_restores_previous_value() -> None:
    first = UUID("11111111-1111-1111-1111-111111111111")
    second = UUID("22222222-2222-2222-2222-222222222222")

    with workspace_context(first):
        assert current_workspace_id() == first
        with workspace_context(second):
            assert current_workspace_id() == second
        assert current_workspace_id() == first

    assert current_workspace_id() == DEFAULT_WORKSPACE_UUID


@pytest.mark.asyncio
async def test_worker_executes_run_inside_workspace_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _assert_worker_executes_run_inside_workspace_context(monkeypatch)


@pytest.mark.asyncio
async def test_worker_run_executes_inside_loaded_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _assert_worker_executes_run_inside_workspace_context(monkeypatch)


async def _assert_worker_executes_run_inside_workspace_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.api import database
    from apps.worker import task_queue
    from apps.worker.runner import WorkerRunner

    run_id = UUID("33333333-3333-3333-3333-333333333333")
    workspace_id = UUID("44444444-4444-4444-4444-444444444444")
    seen_workspace_ids: list[UUID] = []

    async def fake_get_run(run_id_arg: UUID) -> dict[str, Any]:
        assert run_id_arg == run_id
        return {"workspace_id": workspace_id, "mode": "frontier"}

    async def fake_update_run(*args: Any, **kwargs: Any) -> None:
        return None

    async def fake_create_event(*args: Any, **kwargs: Any) -> None:
        return None

    async def fake_mark_active(*args: Any, **kwargs: Any) -> None:
        return None

    async def fake_mark_inactive(*args: Any, **kwargs: Any) -> None:
        return None

    async def fake_publish_event(*args: Any, **kwargs: Any) -> None:
        return None

    async def fake_execute_run_in_workspace(
        self: WorkerRunner,
        run_id_arg: UUID,
        job_arg: dict[str, Any],
        run_arg: dict[str, Any],
    ) -> None:
        seen_workspace_ids.append(current_workspace_id())
        assert run_id_arg == run_id
        assert job_arg == {"run_id": str(run_id)}
        assert run_arg["workspace_id"] == workspace_id

    monkeypatch.setattr(database, "get_run", fake_get_run)
    monkeypatch.setattr(database, "update_run", fake_update_run)
    monkeypatch.setattr(database, "create_event", fake_create_event)
    monkeypatch.setattr(task_queue, "mark_active", fake_mark_active)
    monkeypatch.setattr(task_queue, "mark_inactive", fake_mark_inactive)
    monkeypatch.setattr(task_queue, "publish_event", fake_publish_event)
    monkeypatch.setattr(
        WorkerRunner,
        "_execute_run_in_workspace",
        fake_execute_run_in_workspace,
        raising=False,
    )

    await WorkerRunner()._execute_run(run_id, {"run_id": str(run_id)})

    assert seen_workspace_ids == [workspace_id]
    assert current_workspace_id() == DEFAULT_WORKSPACE_UUID
