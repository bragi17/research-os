from __future__ import annotations

import json
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


@pytest.mark.asyncio
async def test_run_mode_graph_passes_project_id_to_state(monkeypatch):
    from apps.worker.modes import divergent

    seen_state: dict = {}

    class FakeCompiledGraph:
        async def ainvoke(self, initial_state, config=None):
            seen_state.update(initial_state)
            return initial_state

    class FakeGraph:
        def compile(self, checkpointer=None):
            return FakeCompiledGraph()

    monkeypatch.setattr(divergent, "create_divergent_graph", lambda: FakeGraph())

    run_id = uuid4()
    project_id = uuid4()
    worker = WorkerRunner()

    result = await worker._run_mode_graph(
        mode="divergent",
        run_id=run_id,
        topic="research agents",
        keywords=[],
        seed_paper_ids=[],
        context_bundle={},
        budget={},
        run_record={
            "project_id": project_id,
            "goal_type": "survey_plus_innovations",
        },
    )

    assert seen_state["project_id"] == project_id
    assert result.project_id == project_id


def test_worker_writes_run_outputs_to_experiment_workspace(monkeypatch, tmp_path):
    from apps.worker.production.workspaces import run_workspace_record

    monkeypatch.setenv("RESEARCH_OS_WORKSPACE_ROOT", str(tmp_path))
    run_id = uuid4()
    workspace = run_workspace_record(
        run_id=run_id,
        title="Prime Gap Study",
    )
    state = ModeGraphState(
        run_id=run_id,
        topic="CPU-only prime gap verification",
        mode="frontier",
        report_markdown="# Prime Gap Study\n\nDone.\n",
        context_bundle={"paper_summaries": [{"title": "Prime gaps"}]},
        idea_cards=[{"title": "Residual envelope check"}],
        comparison_matrix=[{"method": "baseline"}],
    )

    WorkerRunner()._write_workspace_outputs(
        run_id,
        {"title": "Prime Gap Study", "policy_json": {"experiment_workspace": workspace}},
        state,
    )

    workspace_path = tmp_path / workspace["relative_path"]
    assert (workspace_path / "report.md").read_text() == "# Prime Gap Study\n\nDone.\n"
    assert json.loads((workspace_path / "context_bundle.json").read_text()) == {
        "paper_summaries": [{"title": "Prime gaps"}],
    }
    assert json.loads((workspace_path / "idea_cards.json").read_text()) == [
        {"title": "Residual envelope check"},
    ]
    assert json.loads((workspace_path / "paper_summaries.json").read_text()) == [
        {"title": "Prime gaps"},
    ]
    assert json.loads((workspace_path / "run_state.json").read_text())["run_id"] == str(run_id)
