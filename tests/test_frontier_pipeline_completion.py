from __future__ import annotations

from uuid import UUID

from apps.worker.modes.base import ModeGraphState
from apps.worker.modes.frontier import create_frontier_graph


def test_frontier_deep_reading_always_enters_comparison_when_read_budget_exhausted() -> None:
    workflow = create_frontier_graph()
    state = ModeGraphState(
        run_id=UUID("11111111-1111-1111-1111-111111111111"),
        mode="frontier",
        topic="structured light 3D reconstruction telecentric camera",
        current_step="deep_reading",
        papers_read=3,
        max_fulltext_reads=3,
        selected_paper_ids=["paper-a", "paper-b", "paper-c"],
        read_paper_ids=["paper-a", "paper-b", "paper-c"],
    )

    assert state.papers_read == state.max_fulltext_reads
    assert ("deep_reading", "comparison_build") in workflow.edges
    assert "deep_reading" not in workflow.branches
