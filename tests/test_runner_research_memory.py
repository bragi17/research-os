from __future__ import annotations

from uuid import uuid4

import pytest

from apps.worker.modes.base import ModeGraphState
from apps.worker import runner as runner_module
from apps.worker.runner import WorkerRunner


@pytest.mark.asyncio
async def test_worker_persists_research_memory_after_outputs(monkeypatch):
    persisted = []

    async def fake_persist_run_memory(state):
        persisted.append(state.run_id)
        return []

    monkeypatch.setattr(
        runner_module,
        "persist_run_memory",
        fake_persist_run_memory,
        raising=False,
    )

    run_id = uuid4()
    worker = WorkerRunner()
    state = ModeGraphState(
        project_id=uuid4(),
        run_id=run_id,
        topic="research agents",
        mode="divergent",
    )

    await worker._persist_results(run_id, state)

    assert persisted == [run_id]


@pytest.mark.asyncio
async def test_worker_logs_memory_error_without_failing_run(monkeypatch):
    warnings = []

    async def fake_persist_run_memory(state):
        raise RuntimeError("ledger unavailable")

    def fake_warning(event, **kwargs):
        warnings.append((event, kwargs))

    monkeypatch.setattr(
        runner_module,
        "persist_run_memory",
        fake_persist_run_memory,
        raising=False,
    )
    monkeypatch.setattr(runner_module.logger, "warning", fake_warning)

    run_id = uuid4()
    worker = WorkerRunner()
    state = ModeGraphState(
        project_id=uuid4(),
        run_id=run_id,
        topic="research agents",
        mode="divergent",
    )

    await worker._persist_results(run_id, state)

    assert warnings == [
        (
            "research_memory.persist_failed",
            {"run_id": str(run_id), "error": "ledger unavailable"},
        )
    ]
