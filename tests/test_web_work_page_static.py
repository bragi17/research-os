from __future__ import annotations

from pathlib import Path

API = Path("apps/web/src/lib/api.ts")
WORK_PAGE = Path("apps/web/src/app/works/[id]/page.tsx")
PHASE_STEPPER = Path("apps/web/src/components/work/PhaseStepper.tsx")
PHASE_RUN_PANEL = Path("apps/web/src/components/work/PhaseRunPanel.tsx")
ARTIFACT_DECK = Path("apps/web/src/components/work/ArtifactCardDeck.tsx")
SIDEBAR = Path("apps/web/src/components/Sidebar.tsx")
NEW_PAGE = Path("apps/web/src/app/new/page.tsx")


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
    assert "ArtifactCardDeck" in source
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


def test_artifact_deck_supports_edit_and_selection() -> None:
    source = ARTIFACT_DECK.read_text()

    assert "selection_state" in source
    assert "updateArtifactCard" in source
    assert "Edit" in source
    assert "Save" in source
    assert "Selected" in source


def test_work_page_renders_artifact_deck_with_active_phase_cards() -> None:
    source = WORK_PAGE.read_text()

    assert "import ArtifactCardDeck" in source
    assert "<ArtifactCardDeck" in source
    assert "cards={cards.filter((card) => card.phase === activePhase)}" in source
    assert "onCardsChanged={fetchCardsForActivePhase}" in source


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


def test_sidebar_lists_works_without_child_language() -> None:
    source = SIDEBAR.read_text()

    assert "listWorks" in source
    assert "child of" not in source


def test_sidebar_uses_work_links_on_primary_path() -> None:
    source = SIDEBAR.read_text()

    assert "phase ? `/works/${work.id}?phase=${phase}` : `/works/${work.id}`" in source
    if "listRuns" in source:
        assert source.index("listWorks") < source.index("listRuns")
    assert "spawnRun" not in source
    assert "/children" not in source


def test_sidebar_preserves_known_work_phase_for_links() -> None:
    source = SIDEBAR.read_text()

    assert "ros_work_phases" in source
    assert "workPhaseHints" in source
    assert "const phase = work.active_phase ?? workPhaseHints[work.id] ?? (work.isFallbackRun ? work.mode : undefined)" in source
    assert "const href = work.isFallbackRun" in source


def test_new_research_creates_work_before_initial_phase() -> None:
    source = NEW_PAGE.read_text()
    create_index = source.index("const work = await createWork")
    start_index = source.index("await startPhaseExecution(work.id")

    assert create_index < start_index
    assert "source_card_ids: []" in source
    assert "manual_input" in source


def test_new_research_routes_to_work_page() -> None:
    source = NEW_PAGE.read_text()

    assert "`/works/${work.id}?phase=${mode}`" in source
    assert "rememberWorkPhase(work.id, mode)" in source
    assert "createRunV2" not in source
    assert "startRun" not in source
    assert "`/runs/${" not in source
    assert "spawnRun" not in source
    assert "/children" not in source


def test_work_page_initializes_phase_from_query_param() -> None:
    source = WORK_PAGE.read_text()

    assert "useSearchParams" in source
    assert 'searchParams.get("phase")' in source
    assert "isResearchPhase" in source
    assert "rememberWorkPhase(workId, queryPhase)" in source
    assert "queryPhase" in source
    assert "queryPhase ?? workData.active_phase ?? rememberedPhase ?? \"atlas\"" in source


def test_work_page_uses_remembered_phase_for_direct_load() -> None:
    source = WORK_PAGE.read_text()

    assert "const [rememberedPhase, setRememberedPhase]" in source
    assert "localStorage.getItem(WORK_PHASE_HINTS_STORAGE_KEY)" in source
    assert "setRememberedPhase(isResearchPhase(phaseHint) ? phaseHint : null)" in source
    assert "queryPhase ?? workData.active_phase ?? rememberedPhase ?? \"atlas\"" in source


def test_work_page_persists_active_phase_changes() -> None:
    source = WORK_PAGE.read_text()

    assert "rememberWorkPhase(workId, activePhase)" in source
    assert "[activePhase, queryPhase, workId]" in source
    assert "onPhaseChange" in source
    assert "<PhaseStepper activePhase={activePhase} onChange={onPhaseChange}" in source
    assert "rememberWorkPhase(workId, target.phase)" in source


def test_work_page_fetch_work_only_applies_initial_phase_once() -> None:
    source = WORK_PAGE.read_text()
    fetch_source = source[
        source.index("const fetchWork = useCallback") : source.index("const fetchCards = useCallback")
    ]
    guard_index = fetch_source.index("if (!phaseInitializedRef.current) {")
    set_index = fetch_source.index("setActivePhase(initialPhase)")
    initialized_index = fetch_source.index("phaseInitializedRef.current = true")

    assert guard_index < set_index < initialized_index
    assert "|| queryPhase" not in fetch_source
    assert "|| (!workData.active_phase && rememberedPhase)" not in fetch_source
    assert "if (!rememberedPhaseLoaded) return" in source


def test_new_research_workspace_policy_uses_default_object_shape() -> None:
    source = NEW_PAGE.read_text()
    policy_index = source.index("const experimentWorkspacePolicy = {")
    edited_index = source.index("if (workspaceEdited")

    assert policy_index < edited_index
    assert "path: displayedExperimentWorkspace.trim()" in source
    assert "experiment_workspace: experimentWorkspacePolicy" in source
    assert "manualInput.experiment_workspace = experimentWorkspacePolicy" in source
    assert "policy.experiment_workspace = displayedExperimentWorkspace.trim()" not in source


def test_new_research_phase_start_failure_routes_to_created_work() -> None:
    source = NEW_PAGE.read_text()
    create_index = source.index("const work = await createWork")
    phase_try_index = source.index("try {\n        await startPhaseExecution(work.id")
    phase_catch_index = source.index("catch (phaseErr)")
    route_index = source.index(
        "router.push(`/works/${work.id}?phase=${mode}&phase_start=failed`)",
    )

    assert create_index < phase_try_index < phase_catch_index < route_index
    assert "Failed to create research" not in source[phase_catch_index:route_index]


def test_failed_initial_phase_recovery_routes_to_prefilled_new_research() -> None:
    work_source = WORK_PAGE.read_text()
    new_source = NEW_PAGE.read_text()

    assert "phaseStartRecoveryHref" in work_source
    assert "`/new?mode=${activePhase}&topic=${encodeURIComponent(work.topic)}`" in work_source
    assert 'href={phaseStartRecoveryHref}' in work_source
    assert "Retry setup" in work_source
    assert "You can run it from here" not in work_source
    assert 'searchParams.get("topic")' in new_source
    assert 'useState(topicParam ?? "")' in new_source
