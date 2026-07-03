from __future__ import annotations

from pathlib import Path

API = Path("apps/web/src/lib/api.ts")
WORK_PAGE = Path("apps/web/src/app/works/[id]/page.tsx")
PHASE_STEPPER = Path("apps/web/src/components/work/PhaseStepper.tsx")
PHASE_RUN_PANEL = Path("apps/web/src/components/work/PhaseRunPanel.tsx")


def test_work_api_types_and_helpers_exist() -> None:
    source = API.read_text()

    expected_exports = [
        "export type ResearchPhase",
        "export interface Work",
        "export interface PhaseExecution",
        "export interface ArtifactCard",
        "export const listWorks",
        "export const getWork",
        "export const getWorkPhases",
        "export const listArtifactCards",
        "export const updateArtifactCard",
        "export const startPhaseExecution",
    ]

    for export in expected_exports:
        assert export in source


def test_artifact_card_patch_type_is_focused() -> None:
    source = API.read_text()

    assert "Partial<ArtifactCard>" not in source


def test_work_page_uses_phase_model_not_child_runs() -> None:
    source = WORK_PAGE.read_text()

    assert "useParams" in source
    assert "getWork(" in source
    assert "getWorkPhases(" in source
    assert "listArtifactCards(" in source
    assert "startPhaseExecution(" in source
    assert "PhaseStepper" in source
    assert "PhaseRunPanel" in source
    assert "child of" not in source
    assert "spawnRun" not in source
    assert "/children" not in source
    assert "start_divergent" not in source


def test_phase_stepper_lists_three_research_phases() -> None:
    source = PHASE_STEPPER.read_text()

    assert '"atlas"' in source
    assert '"frontier"' in source
    assert '"divergent"' in source


def test_phase_run_panel_has_independent_and_next_phase_actions() -> None:
    source = PHASE_RUN_PANEL.read_text()

    assert "Run this phase" in source
    assert "Start Frontier from selected Atlas cards" in source
    assert "Start Divergent from selected gaps" in source
    assert "Validate selected ideas with Frontier" in source


def test_phase_run_panel_disables_next_action_without_selection() -> None:
    source = PHASE_RUN_PANEL.read_text()

    assert "selectedCount === 0" in source
    assert "disabled={nextDisabled}" in source
    assert "title={nextActionTitle}" in source
    assert "aria-label={nextActionAriaLabel}" in source
    assert "const nextDisabled = running || selectedCount === 0" in source


def test_phase_run_panel_disables_current_phase_action_without_input() -> None:
    source = PHASE_RUN_PANEL.read_text()

    assert "canRunPhase" in source
    assert "const phaseDisabled = running || !canRunPhase" in source
    assert "disabled={phaseDisabled}" in source
    assert "title={phaseActionTitle}" in source
    assert "aria-label={phaseActionAriaLabel}" in source


def test_work_page_current_phase_action_requires_input_for_non_atlas() -> None:
    source = WORK_PAGE.read_text()
    guard_index = source.index('if (activePhase !== "atlas" && sourceCardIds.length === 0)')
    start_index = source.index("startPhaseExecution(workId, activePhase")

    assert guard_index < start_index
    assert 'setRunningAction("phase")' not in source[:guard_index]
    assert "const phaseRunData: StartPhaseExecutionData =" in source
    assert 'activePhase === "atlas"' in source
    assert "source_card_ids: sourceCardIds" in source
    assert 'canRunPhase={activePhase === "atlas" || selectedCards.length > 0}' in source


def test_work_page_next_phase_action_requires_selected_cards() -> None:
    source = WORK_PAGE.read_text()
    guard_index = source.index("if (sourceCardIds.length === 0)")
    start_index = source.index("startPhaseExecution(workId, target.phase")

    assert guard_index < start_index
    assert "setRunningAction(\"next\")" not in source[:guard_index]
    assert "source_card_ids: sourceCardIds" in source
    assert "source_card_ids: selectedCards.map" not in source
    assert "source_card_ids: []" not in source


def test_work_page_scopes_selected_cards_to_active_phase() -> None:
    source = WORK_PAGE.read_text()

    assert "card.phase === activePhase" in source
    assert "const selectedCards = phaseCards.filter" in source


def test_work_page_ignores_stale_card_responses() -> None:
    source = WORK_PAGE.read_text()

    assert "cardsRequestSeqRef" in source
    assert "requestedPhase" in source
    assert "if (requestId !== cardsRequestSeqRef.current)" in source
    assert "if (phaseRef.current !== requestedPhase)" in source
