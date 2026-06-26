from __future__ import annotations

from uuid import uuid4

import pytest

from apps.worker.modes.base import ModeGraphState
from apps.worker.run_persistence import (
    _listify_idea_value,
    _normalize_idea_card_payload,
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
