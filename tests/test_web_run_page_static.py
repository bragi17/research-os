from __future__ import annotations

import re
from pathlib import Path

RUN_PAGE = Path("apps/web/src/app/runs/[id]/page.tsx")
DIVERGENT_PAGE = Path("apps/web/src/app/runs/[id]/divergent/page.tsx")
API_FILE = Path("apps/web/src/lib/api.ts")
LEGACY_CONTINUATION_COPY = (
    "child of",
    "Check prior art further",
    "Explore innovations for these gaps",
    "Phase continuation",
    "Continue in topic work",
)


def test_legacy_run_pages_do_not_show_old_phase_continuation_copy() -> None:
    for path in (RUN_PAGE, DIVERGENT_PAGE):
        source = path.read_text()

        for text in LEGACY_CONTINUATION_COPY:
            assert text not in source


def test_frontend_run_type_carries_work_id_for_legacy_work_links() -> None:
    source = API_FILE.read_text()

    assert "work_id?: string | null;" in source


def test_run_results_paper_list_is_collapsible_and_closed_by_default() -> None:
    source = RUN_PAGE.read_text()

    assert "showResultPapers" in source
    assert "useState(false)" in source
    assert "setShowResultPapers" in source
    assert "Show papers" in source
    assert "Hide papers" in source
    assert "showResultPapers &&" in source


def test_run_page_does_not_embed_auto_divergent_child_pipeline() -> None:
    source = RUN_PAGE.read_text()

    assert "getRunChildren" not in source
    assert "divergentContinuation" not in source
    assert "extraSteps={shouldShowDivergentStep" not in source
    assert "continuation={divergentContinuation}" not in source
    assert "parent_run_id" not in source


def test_run_page_always_shows_current_frontier_full_results_link() -> None:
    source = RUN_PAGE.read_text()

    assert "View full Frontier results" in source
    assert "View full {MODE_LABELS" in source
    assert '!(run.mode === "frontier" && divergentRun)' not in source
    assert "divergentRun" not in source


def test_run_page_exposes_same_run_divergent_phase_from_events() -> None:
    source = RUN_PAGE.read_text()

    assert "work_id" in source
    assert "hasDivergentPhase" in source
    assert 'event.event_type === "run.divergent_enqueued"' in source
    assert 'event.event_type === "user.action.start_divergent"' in source
    assert 'event.payload?.mode === "divergent"' in source
    assert "View full Divergent results" in source
    assert "Open topic work" in source


def test_divergent_full_results_include_papers_section() -> None:
    source = DIVERGENT_PAGE.read_text()

    assert "getRunPapers(runId)" in source
    assert "Papers Explored" in source
    assert "papers.map((paper)" in source
    assert "papers.slice(0, 20)" not in source


def test_divergent_page_retires_child_frontier_spawn_fallback() -> None:
    source = DIVERGENT_PAGE.read_text()

    assert "spawnRun" not in source
    assert "startRun" not in source
    assert "await startRun(newRun.id)" not in source
    assert "useRouter" not in source
    assert "spawning" not in source
    assert re.search(r"[{,]\s*mode:\s*\"frontier\"", source) is None
    assert "linear-gradient(135deg, var(--accent-purple)" not in source
    assert "?mode=frontier" in source
    assert "encodeURIComponent(run.topic)" in source


def test_divergent_papers_can_be_added_to_library_and_opened_after_add() -> None:
    source = DIVERGENT_PAGE.read_text()

    assert "addToLibrary" in source
    assert "handleAddPaperToLibrary" in source
    assert "Add to library" in source
    assert "Open in library" in source
    assert 'source_run_id: runId' in source
