from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest

from apps.worker.modes.base import ModeGraphState
from apps.worker.run_persistence import persist_results


class _FakeLog:
    def __init__(self) -> None:
        self.infos: list[tuple[str, dict[str, Any]]] = []
        self.warnings: list[tuple[str, dict[str, Any]]] = []
        self.errors: list[tuple[str, dict[str, Any]]] = []
        self.debugs: list[tuple[str, dict[str, Any]]] = []

    def info(self, event: str, **kwargs: Any) -> None:
        self.infos.append((event, kwargs))

    def warning(self, event: str, **kwargs: Any) -> None:
        self.warnings.append((event, kwargs))

    def error(self, event: str, **kwargs: Any) -> None:
        self.errors.append((event, kwargs))

    def debug(self, event: str, **kwargs: Any) -> None:
        self.debugs.append((event, kwargs))


async def _noop_memory_persister(state: Any) -> list[dict[str, Any]]:
    return []


def test_frontier_bundle_extracts_gap_and_pain_point_cards() -> None:
    from apps.worker.run_persistence import _artifact_cards_from_state

    long_description = "Sparse-label failure " * 40
    gap = {
        "description": long_description,
        "gap_type": "data",
        "significance": "high",
        "potential_impact": "Fewer false negatives on rare defects",
    }
    pain_point = {
        "statement": "Models overfit small defect sets",
        "pain_type": "generalization",
    }

    cards = _artifact_cards_from_state(
        work_id="00000000-0000-0000-0000-000000000001",
        phase="frontier",
        source_execution_id="00000000-0000-0000-0000-000000000002",
        state={
            "gaps": [gap],
            "pain_points": [pain_point],
        },
    )

    assert [card["artifact_type"] for card in cards] == [
        "frontier_gap",
        "frontier_pain_point",
    ]
    assert cards[0]["title"] == long_description[:500]
    assert cards[0]["body"] == "Fewer false negatives on rare defects"
    assert cards[0]["payload"] == gap
    assert cards[0]["source_execution_id"] == "00000000-0000-0000-0000-000000000002"
    assert cards[0]["edit_source"] == "ai"
    assert cards[1]["title"] == "Models overfit small defect sets"
    assert cards[1]["body"] == "generalization"


def test_divergent_bundle_extracts_idea_cards() -> None:
    from apps.worker.run_persistence import _artifact_cards_from_state

    idea = {
        "title": "Residual envelope checking",
        "problem_statement": "Detect rare defects",
    }

    cards = _artifact_cards_from_state(
        work_id="00000000-0000-0000-0000-000000000001",
        phase="divergent",
        source_execution_id="00000000-0000-0000-0000-000000000002",
        state={"idea_cards": [idea]},
    )

    assert len(cards) == 1
    assert cards[0]["artifact_type"] == "divergent_idea"
    assert cards[0]["title"] == "Residual envelope checking"
    assert cards[0]["body"] == "Detect rare defects"
    assert cards[0]["payload"] == idea


def test_atlas_bundle_extracts_direction_cards_from_object_state() -> None:
    from apps.worker.run_persistence import _artifact_cards_from_state

    direction = {
        "name": "Neural measurement taxonomies",
        "description": "Map sensor and reconstruction method families",
    }

    cards = _artifact_cards_from_state(
        work_id="00000000-0000-0000-0000-000000000001",
        phase="atlas",
        source_execution_id="00000000-0000-0000-0000-000000000002",
        state=SimpleNamespace(sub_directions=[direction]),
    )

    assert cards == [
        {
            "work_id": "00000000-0000-0000-0000-000000000001",
            "phase": "atlas",
            "artifact_type": "atlas_direction",
            "title": "Neural measurement taxonomies",
            "body": "Map sensor and reconstruction method families",
            "payload": direction,
            "source_execution_id": "00000000-0000-0000-0000-000000000002",
            "edit_source": "ai",
        }
    ]


def test_atlas_bundle_extracts_direction_cards_from_context_bundle() -> None:
    from apps.worker.run_persistence import _artifact_cards_from_state

    direction = {
        "title": "Adaptive inspection domains",
        "description": "Separate defect families by inspection setting",
    }

    cards = _artifact_cards_from_state(
        work_id="00000000-0000-0000-0000-000000000001",
        phase="atlas",
        source_execution_id="00000000-0000-0000-0000-000000000002",
        state={"context_bundle": {"sub_directions": [direction]}},
    )

    assert len(cards) == 1
    assert cards[0]["artifact_type"] == "atlas_direction"
    assert cards[0]["title"] == "Adaptive inspection domains"
    assert cards[0]["payload"] == direction


@pytest.mark.asyncio
async def test_persist_results_creates_work_cards_and_completes_phase_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import apps.api.database as database

    run_id = UUID("11111111-1111-1111-1111-111111111111")
    work_id = UUID("22222222-2222-2222-2222-222222222222")
    execution_id = UUID("33333333-3333-3333-3333-333333333333")
    output_bundle_id = UUID("44444444-4444-4444-4444-444444444444")
    created_cards: list[dict[str, Any]] = []
    phase_updates: list[tuple[Any, dict[str, Any]]] = []

    async def fake_create_pain_point(
        create_run_id: UUID,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return {"run_id": create_run_id, **payload}

    async def fake_create_idea_card(
        create_run_id: UUID,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return {"run_id": create_run_id, **payload}

    async def fake_create_context_bundle(payload: dict[str, Any]) -> dict[str, Any]:
        return {"id": output_bundle_id, **payload}

    async def fake_update_run(
        update_run_id: UUID,
        updates: dict[str, Any],
    ) -> dict[str, Any]:
        return {"id": update_run_id, **updates}

    async def fake_create_artifact_card(data: dict[str, Any]) -> dict[str, Any]:
        created_cards.append(dict(data))
        return {"id": uuid4(), **data}

    async def fake_update_phase_execution(
        update_execution_id: UUID,
        updates: dict[str, Any],
    ) -> dict[str, Any]:
        phase_updates.append((update_execution_id, dict(updates)))
        return {"id": update_execution_id, **updates}

    monkeypatch.setattr(database, "create_pain_point", fake_create_pain_point)
    monkeypatch.setattr(database, "create_idea_card", fake_create_idea_card)
    monkeypatch.setattr(database, "create_context_bundle", fake_create_context_bundle)
    monkeypatch.setattr(database, "update_run", fake_update_run)
    monkeypatch.setattr(database, "create_artifact_card", fake_create_artifact_card)
    monkeypatch.setattr(database, "update_phase_execution", fake_update_phase_execution)

    state = ModeGraphState(
        run_id=run_id,
        mode="frontier",
        context_bundle={"summary_text": "Frontier output"},
        gaps=[
            {
                "description": "Sparse-label failure",
                "gap_type": "data",
                "potential_impact": "Improves rare defect detection",
            }
        ],
        pain_points=[
            {
                "statement": "Models overfit small defect sets",
                "pain_type": "generalization",
            }
        ],
    )

    await persist_results(
        run_id,
        state,
        work_id=str(work_id),
        phase_execution_id=str(execution_id),
        memory_persister=_noop_memory_persister,
        log=_FakeLog(),
    )

    assert [card["artifact_type"] for card in created_cards] == [
        "frontier_gap",
        "frontier_pain_point",
    ]
    assert {card["work_id"] for card in created_cards} == {work_id}
    assert {card["source_execution_id"] for card in created_cards} == {execution_id}
    assert phase_updates[-1][0] == execution_id
    assert phase_updates[-1][1]["status"] == "completed"
    assert phase_updates[-1][1]["error_message"] is None
    assert phase_updates[-1][1]["output_bundle_id"] == output_bundle_id
    assert phase_updates[-1][1]["completed_at"] is not None
    assert phase_updates[-1][1]["updated_at"] is not None


@pytest.mark.asyncio
async def test_persist_results_accepts_dict_state_with_work_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import apps.api.database as database

    run_id = UUID("11111111-1111-1111-1111-111111111111")
    work_id = "22222222-2222-2222-2222-222222222222"
    execution_id = "33333333-3333-3333-3333-333333333333"
    created_cards: list[dict[str, Any]] = []
    phase_updates: list[tuple[Any, dict[str, Any]]] = []

    async def fake_create_pain_point(
        create_run_id: UUID,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return {"run_id": create_run_id, **payload}

    async def fake_create_idea_card(
        create_run_id: UUID,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return {"run_id": create_run_id, **payload}

    async def fake_create_artifact_card(data: dict[str, Any]) -> dict[str, Any]:
        created_cards.append(dict(data))
        return {"id": uuid4(), **data}

    async def fake_update_phase_execution(
        update_execution_id: UUID,
        updates: dict[str, Any],
    ) -> dict[str, Any]:
        phase_updates.append((update_execution_id, dict(updates)))
        return {"id": update_execution_id, **updates}

    monkeypatch.setattr(database, "create_pain_point", fake_create_pain_point)
    monkeypatch.setattr(database, "create_idea_card", fake_create_idea_card)
    monkeypatch.setattr(database, "create_artifact_card", fake_create_artifact_card)
    monkeypatch.setattr(database, "update_phase_execution", fake_update_phase_execution)

    log = _FakeLog()

    await persist_results(
        run_id,
        {
            "mode": "divergent",
            "idea_cards": [
                {
                    "title": "Residual envelope checking",
                    "problem_statement": "Detect rare defects",
                }
            ],
        },
        work_id=work_id,
        phase_execution_id=execution_id,
        memory_persister=_noop_memory_persister,
        log=log,
    )

    assert created_cards[0]["work_id"] == UUID(work_id)
    assert created_cards[0]["source_execution_id"] == UUID(execution_id)
    assert phase_updates[-1][0] == UUID(execution_id)
    assert phase_updates[-1][1]["status"] == "completed"
    assert log.errors == []


@pytest.mark.asyncio
async def test_persist_results_partial_object_state_does_not_fail_after_cards(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import apps.api.database as database

    run_id = UUID("11111111-1111-1111-1111-111111111111")
    work_id = UUID("22222222-2222-2222-2222-222222222222")
    execution_id = UUID("33333333-3333-3333-3333-333333333333")
    created_cards: list[dict[str, Any]] = []
    phase_updates: list[tuple[Any, dict[str, Any]]] = []

    async def fake_create_pain_point(
        create_run_id: UUID,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return {"run_id": create_run_id, **payload}

    async def fake_create_idea_card(
        create_run_id: UUID,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return {"run_id": create_run_id, **payload}

    async def fake_create_artifact_card(data: dict[str, Any]) -> dict[str, Any]:
        created_cards.append(dict(data))
        return {"id": uuid4(), **data}

    async def fake_update_phase_execution(
        update_execution_id: UUID,
        updates: dict[str, Any],
    ) -> dict[str, Any]:
        phase_updates.append((update_execution_id, dict(updates)))
        return {"id": update_execution_id, **updates}

    monkeypatch.setattr(database, "create_pain_point", fake_create_pain_point)
    monkeypatch.setattr(database, "create_idea_card", fake_create_idea_card)
    monkeypatch.setattr(database, "create_artifact_card", fake_create_artifact_card)
    monkeypatch.setattr(database, "update_phase_execution", fake_update_phase_execution)

    log = _FakeLog()

    await persist_results(
        run_id,
        SimpleNamespace(
            mode="divergent",
            idea_cards=[
                {
                    "title": "Residual envelope checking",
                    "problem_statement": "Detect rare defects",
                }
            ],
        ),
        work_id=work_id,
        phase_execution_id=execution_id,
        memory_persister=_noop_memory_persister,
        log=log,
    )

    assert len(created_cards) == 1
    assert phase_updates[-1][1]["status"] == "completed"
    assert all(update[1]["status"] != "failed" for update in phase_updates)
    assert log.errors == []


@pytest.mark.asyncio
async def test_persist_results_without_work_metadata_skips_artifact_cards(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import apps.api.database as database

    run_id = UUID("11111111-1111-1111-1111-111111111111")

    async def fake_create_pain_point(
        create_run_id: UUID,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return {"run_id": create_run_id, **payload}

    async def fake_create_idea_card(
        create_run_id: UUID,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return {"run_id": create_run_id, **payload}

    async def fail_create_artifact_card(data: dict[str, Any]) -> dict[str, Any]:
        raise AssertionError("artifact cards should not be created")

    async def fail_update_phase_execution(
        execution_id: UUID,
        updates: dict[str, Any],
    ) -> dict[str, Any]:
        raise AssertionError("phase execution should not be updated")

    monkeypatch.setattr(database, "create_pain_point", fake_create_pain_point)
    monkeypatch.setattr(database, "create_idea_card", fake_create_idea_card)
    monkeypatch.setattr(database, "create_artifact_card", fail_create_artifact_card)
    monkeypatch.setattr(database, "update_phase_execution", fail_update_phase_execution)

    state = ModeGraphState(
        run_id=run_id,
        mode="divergent",
        idea_cards=[
            {
                "title": "Residual envelope checking",
                "problem_statement": "Detect rare defects",
            }
        ],
    )

    await persist_results(
        run_id,
        state,
        memory_persister=_noop_memory_persister,
        log=_FakeLog(),
    )


@pytest.mark.asyncio
async def test_persist_results_marks_phase_failed_when_card_creation_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import apps.api.database as database

    run_id = UUID("11111111-1111-1111-1111-111111111111")
    work_id = UUID("22222222-2222-2222-2222-222222222222")
    execution_id = UUID("33333333-3333-3333-3333-333333333333")
    output_bundle_id = UUID("44444444-4444-4444-4444-444444444444")
    phase_updates: list[tuple[UUID, dict[str, Any]]] = []

    async def fake_create_pain_point(
        create_run_id: UUID,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return {"run_id": create_run_id, **payload}

    async def fake_create_idea_card(
        create_run_id: UUID,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return {"run_id": create_run_id, **payload}

    async def fail_create_artifact_card(data: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("card table unavailable")

    async def fake_create_context_bundle(payload: dict[str, Any]) -> dict[str, Any]:
        return {"id": output_bundle_id, **payload}

    async def fake_update_run(
        update_run_id: UUID,
        updates: dict[str, Any],
    ) -> dict[str, Any]:
        return {"id": update_run_id, **updates}

    async def fake_update_phase_execution(
        update_execution_id: UUID,
        updates: dict[str, Any],
    ) -> dict[str, Any]:
        phase_updates.append((update_execution_id, dict(updates)))
        return {"id": update_execution_id, **updates}

    monkeypatch.setattr(database, "create_pain_point", fake_create_pain_point)
    monkeypatch.setattr(database, "create_idea_card", fake_create_idea_card)
    monkeypatch.setattr(database, "create_context_bundle", fake_create_context_bundle)
    monkeypatch.setattr(database, "update_run", fake_update_run)
    monkeypatch.setattr(database, "create_artifact_card", fail_create_artifact_card)
    monkeypatch.setattr(database, "update_phase_execution", fake_update_phase_execution)

    state = ModeGraphState(
        run_id=run_id,
        mode="divergent",
        context_bundle={"summary_text": "Raw divergent output"},
        idea_cards=[
            {
                "title": "Residual envelope checking",
                "problem_statement": "Detect rare defects",
            }
        ],
    )
    log = _FakeLog()

    await persist_results(
        run_id,
        state,
        work_id=work_id,
        phase_execution_id=execution_id,
        memory_persister=_noop_memory_persister,
        log=log,
    )

    assert phase_updates[-1][0] == execution_id
    assert phase_updates[-1][1]["status"] == "failed"
    assert "card table unavailable" in phase_updates[-1][1]["error_message"]
    assert phase_updates[-1][1]["output_bundle_id"] == output_bundle_id
    assert phase_updates[-1][1]["completed_at"] is not None
    assert phase_updates[-1][1]["updated_at"] is not None
    assert log.warnings[-1][0] == "worker.artifact_card_extraction_failed"
