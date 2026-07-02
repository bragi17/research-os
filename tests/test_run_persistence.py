from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from apps.worker.modes.base import ModeGraphState
from apps.worker.run_persistence import (
    _listify_idea_value,
    _normalize_idea_card_payload,
    _persist_context_bundle,
    _persist_paper_summaries,
    persist_results,
)


def test_normalize_idea_card_payload_preserves_existing_plural_fields() -> None:
    payload = _normalize_idea_card_payload(
        {
            "title": "Verifier-Guided Retrieval",
            "borrowed_method": "structured audit",
            "borrowed_methods": ["existing audit"],
            "source_domain": ("software verification", "retrieval"),
        }
    )

    assert payload == {
        "title": "Verifier-Guided Retrieval",
        "borrowed_method": "structured audit",
        "borrowed_methods": ["existing audit"],
        "source_domain": ("software verification", "retrieval"),
        "source_domains": ["software verification", "retrieval"],
    }


def test_listify_idea_value_drops_empty_values() -> None:
    assert _listify_idea_value(None) == []
    assert _listify_idea_value("structured audit") == ["structured audit"]
    assert _listify_idea_value(["structured audit", None, ""]) == ["structured audit"]


@pytest.mark.asyncio
async def test_persist_results_logs_memory_error_without_failing() -> None:
    warnings = []

    async def failing_memory_persister(state):
        raise RuntimeError("ledger unavailable")

    class FakeLogger:
        def warning(self, event, **kwargs):
            warnings.append((event, kwargs))

        def info(self, *args, **kwargs):
            return None

        def debug(self, *args, **kwargs):
            return None

        def error(self, *args, **kwargs):
            return None

    run_id = uuid4()
    state = ModeGraphState(
        project_id=uuid4(),
        run_id=run_id,
        topic="research agents",
        mode="divergent",
    )

    await persist_results(
        run_id,
        state,
        memory_persister=failing_memory_persister,
        log=FakeLogger(),
    )

    assert warnings == [
        (
            "research_memory.persist_failed",
            {"run_id": str(run_id), "error": "ledger unavailable"},
        )
    ]


class _FakeLog:
    def __init__(self) -> None:
        self.infos: list[tuple[str, dict]] = []
        self.warnings: list[tuple[str, dict]] = []

    def info(self, event: str, **kwargs) -> None:
        self.infos.append((event, kwargs))

    def warning(self, event: str, **kwargs) -> None:
        self.warnings.append((event, kwargs))

    def debug(self, event: str, **kwargs) -> None:
        self.warnings.append((event, kwargs))


class _FakePool:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple]] = []

    async def execute(self, query: str, *params) -> str:
        self.calls.append((query, params))
        assert isinstance(params[-1], dict)
        return "INSERT 0 1"


@pytest.mark.asyncio
async def test_persist_paper_summaries_writes_valid_json_and_arxiv(monkeypatch) -> None:
    import apps.api.database as database

    run_id = uuid4()
    pool = _FakePool()

    async def fake_get_pool():
        return pool

    monkeypatch.setattr(database, "get_pool", fake_get_pool)

    long_summary = "x" * 6000
    state = SimpleNamespace(
        context_bundle={
            "paper_summaries": [
                {
                    "title": "Structured light with a million light planes per second",
                    "paper_id": "arxiv:2411.18597",
                    "doi": "10.1234/example",
                    "summary": long_summary,
                    "year": 2024,
                    "venue": "arXiv",
                }
            ]
        }
    )
    log = _FakeLog()

    await _persist_paper_summaries(run_id, state, log=log)

    assert len(pool.calls) == 1
    _, params = pool.calls[0]
    assert isinstance(params[0], UUID)
    assert params[3] == "10.1234/example"
    assert params[4] == "2411.18597"
    metadata = params[-1]
    assert metadata["source_run_id"] == str(run_id)
    assert metadata["summary"] == long_summary
    assert state.context_bundle["selected_paper_ids"] == [str(params[0])]
    assert log.infos[-1] == ("worker.papers_persisted", {"count": 1, "failed": 0})
    assert log.warnings == []


@pytest.mark.asyncio
async def test_persist_context_bundle_keeps_rich_frontier_fields(monkeypatch) -> None:
    import apps.api.database as database

    run_id = uuid4()
    created_payloads: list[dict] = []
    updates: list[tuple[UUID, dict]] = []
    paper_summaries = [
        {
            "paper_id": "arxiv:2411.18597",
            "title": "Single-shot structured light",
            "problem": "Motion artifacts in 3D reconstruction",
            "method": "Telecentric coded projection",
            "limitations": "Requires calibration",
        }
    ]

    async def fake_create_context_bundle(payload: dict) -> dict:
        created_payloads.append(payload)
        return {"id": uuid4(), **payload}

    async def fake_update_run(update_run_id: UUID, updates_payload: dict) -> dict:
        updates.append((update_run_id, updates_payload))
        return updates_payload

    monkeypatch.setattr(database, "update_run", fake_update_run)

    state = SimpleNamespace(
        context_bundle={
            "summary_text": "Frontier review summary",
            "selected_paper_ids": ["paper-1"],
            "key_findings": ["Calibration dominates error budgets"],
            "method_landscape": [{"family": "coded projection"}],
            "benchmark_status": {"status": "fragmented"},
            "entry_points": [{"title": "Start with telecentric optics"}],
            "mode_c_suggestions": [{"title": "Adaptive code selection"}],
            "future_work": ["Benchmark under vibration"],
            "pain_point_package": {"top_pain_points": ["No common benchmark"]},
            "paper_summaries": paper_summaries,
        },
        mode="frontier",
        report_markdown="",
        comparison_matrix=[{"axis": "hardware"}],
        gaps=[{"description": "No shared benchmark"}],
        pain_points=[{"statement": "Manual calibration"}],
        papers_read=4,
        papers_discovered=9,
    )

    await _persist_context_bundle(
        run_id,
        state,
        create_context_bundle=fake_create_context_bundle,
        log=_FakeLog(),
    )

    assert len(created_payloads) == 1
    payload = created_payloads[0]
    assert payload["summary_text"] == "Frontier review summary"
    assert payload["selected_paper_ids"] == ["paper-1"]
    benchmark_data = payload["benchmark_data"]
    assert benchmark_data["summary_text"] == "Frontier review summary"
    assert benchmark_data["key_findings"] == ["Calibration dominates error budgets"]
    assert benchmark_data["method_landscape"] == [{"family": "coded projection"}]
    assert benchmark_data["benchmark_status"] == {"status": "fragmented"}
    assert benchmark_data["entry_points"] == [{"title": "Start with telecentric optics"}]
    assert benchmark_data["mode_c_suggestions"] == [{"title": "Adaptive code selection"}]
    assert benchmark_data["future_work"] == ["Benchmark under vibration"]
    assert benchmark_data["pain_point_package"] == {
        "top_pain_points": ["No common benchmark"]
    }
    assert benchmark_data["paper_summaries"] == paper_summaries
    assert benchmark_data["comparison_matrix"] == [{"axis": "hardware"}]
    assert benchmark_data["gaps"] == [{"description": "No shared benchmark"}]
    assert benchmark_data["pain_points_count"] == 1
    assert benchmark_data["papers_read"] == 4
    assert benchmark_data["papers_discovered"] == 9
    assert updates[0][0] == run_id
