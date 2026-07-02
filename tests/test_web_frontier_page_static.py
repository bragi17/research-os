from __future__ import annotations

from pathlib import Path


FRONTIER_PAGE = Path("apps/web/src/app/runs/[id]/frontier/page.tsx")


def test_frontier_page_fetches_context_bundle_for_full_results() -> None:
    source = FRONTIER_PAGE.read_text()

    assert "getRunContextBundle" in source
    assert "getRunContextBundle(runId, { preferContext: true })" in source
    assert "summary_text" in source
    assert "benchmark_data" in source
    assert "paper_summaries" in source


def test_frontier_page_renders_rich_paper_review_fields() -> None:
    source = FRONTIER_PAGE.read_text()

    assert "problem" in source
    assert "method" in source
    assert "experimental_setup" in source
    assert "datasets" in source
    assert "limitations" in source
    assert "main_results" in source
    assert "reusable_components" in source
    assert "paper_tags" in source
    assert "innovation_points" in source


def test_frontier_page_renders_report_landscape_and_entry_points() -> None:
    source = FRONTIER_PAGE.read_text()

    assert "Frontier Overview" in source
    assert "Key Findings" in source
    assert "Method Landscape" in source
    assert "Entry Points" in source
    assert "Paper Reviews" in source


def test_frontier_divergent_cta_stays_in_same_run_context() -> None:
    source = FRONTIER_PAGE.read_text()

    assert 'runAction(runId, "start_divergent"' in source
    assert 'intent: "explore innovations"' in source
    assert "spawnRun" not in source
    assert "router.push" not in source
