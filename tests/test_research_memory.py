from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest


PROJECT_ID = uuid4()
RUN_ID = uuid4()
ITEM_ID = uuid4()
TARGET_ID = uuid4()


class FakeRecord(dict):
    """Dict subclass that mimics asyncpg.Record enough for record_to_dict."""


@pytest.fixture()
def mock_pool():
    pool = AsyncMock()
    pool.fetchrow = AsyncMock()
    pool.fetch = AsyncMock()
    return pool


@pytest.fixture(autouse=True)
def _patch_get_pool(mock_pool):
    with patch("apps.api.db.pool.get_pool", return_value=mock_pool):
        yield


def _record(data):
    return FakeRecord(data)


@pytest.mark.asyncio
async def test_upsert_memory_item(mock_pool):
    mock_pool.fetchrow.return_value = _record(
        {
            "id": ITEM_ID,
            "project_id": PROJECT_ID,
            "source_run_id": RUN_ID,
            "item_type": "failed_idea",
            "stable_key": "weak-retrieval-idea",
            "title": "Weak Retrieval Idea",
            "status": "reject",
            "payload_json": {"quality_verdict": "reject"},
        }
    )

    from apps.api.database import upsert_research_memory_item

    result = await upsert_research_memory_item(
        {
            "project_id": PROJECT_ID,
            "source_run_id": RUN_ID,
            "item_type": "failed_idea",
            "stable_key": "weak-retrieval-idea",
            "title": "Weak Retrieval Idea",
            "status": "reject",
            "payload_json": {"quality_verdict": "reject"},
        }
    )

    sql = mock_pool.fetchrow.call_args.args[0]
    assert "INSERT INTO research_memory_item" in sql
    assert "ON CONFLICT (project_id, item_type, stable_key)" in sql
    assert result["item_type"] == "failed_idea"


@pytest.mark.asyncio
async def test_list_memory_items_filters_by_type(mock_pool):
    mock_pool.fetch.return_value = [
        _record({"stable_key": "weak-retrieval-idea", "item_type": "failed_idea"}),
    ]

    from apps.api.database import list_research_memory_items

    result = await list_research_memory_items(
        PROJECT_ID,
        item_type="failed_idea",
        limit=10,
    )

    sql = mock_pool.fetch.call_args.args[0]
    assert "FROM research_memory_item" in sql
    assert "item_type = $2" in sql
    assert result[0]["stable_key"] == "weak-retrieval-idea"


@pytest.mark.asyncio
async def test_create_memory_edge(mock_pool):
    mock_pool.fetchrow.return_value = _record(
        {
            "id": uuid4(),
            "project_id": PROJECT_ID,
            "source_item_id": ITEM_ID,
            "target_item_id": TARGET_ID,
            "edge_type": "derived_from",
        }
    )

    from apps.api.database import create_research_memory_edge

    result = await create_research_memory_edge(
        {
            "project_id": PROJECT_ID,
            "source_item_id": ITEM_ID,
            "target_item_id": TARGET_ID,
            "edge_type": "derived_from",
            "evidence": "Generated from the recorded pain point.",
        }
    )

    sql = mock_pool.fetchrow.call_args.args[0]
    assert "INSERT INTO research_memory_edge" in sql
    assert "ON CONFLICT (source_item_id, target_item_id, edge_type)" in sql
    assert result["edge_type"] == "derived_from"


def test_memory_items_from_state_emits_paper_and_failed_idea():
    from apps.worker.modes.base import ModeGraphState
    from services.research_memory import memory_items_from_state

    state = ModeGraphState(
        project_id=PROJECT_ID,
        run_id=RUN_ID,
        topic="research agents",
        mode="divergent",
        context_bundle={
            "paper_summaries": [
                {
                    "paper_id": "s2:123",
                    "title": "Agentic Retrieval",
                    "summary": "Retrieval systems for agents.",
                }
            ]
        },
        idea_cards=[
            {
                "title": "Reviewer-Guided Retrieval",
                "problem_statement": "Agents cite plausible papers.",
                "dedup_key": (
                    "reviewer-guided-retrieval-agents-cite-plausible-papers"
                ),
                "quality_verdict": "reject",
                "strongest_objection": "Covered by verified prior art.",
            }
        ],
    )

    items = memory_items_from_state(state)

    item_types = {item["item_type"] for item in items}
    assert "paper" in item_types
    assert "failed_idea" in item_types
    failed = next(item for item in items if item["item_type"] == "failed_idea")
    assert (
        failed["stable_key"]
        == "reviewer-guided-retrieval-agents-cite-plausible-papers"
    )
    assert (
        failed["payload_json"]["strongest_objection"]
        == "Covered by verified prior art."
    )
