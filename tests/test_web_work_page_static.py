from __future__ import annotations

from pathlib import Path

API = Path("apps/web/src/lib/api.ts")


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
