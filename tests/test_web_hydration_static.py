from __future__ import annotations

from pathlib import Path


SIDEBAR = Path("apps/web/src/components/Sidebar.tsx")
NEW_PAGE = Path("apps/web/src/app/new/page.tsx")


def test_sidebar_does_not_read_local_storage_during_initial_render() -> None:
    source = SIDEBAR.read_text()

    assert "useState<Set<string>>(() => {\n    if (typeof window" not in source
    assert "useState<Project[]>(() => {\n    if (typeof window" not in source
    assert "storageReady" in source


def test_new_page_does_not_generate_draft_run_id_during_initial_render() -> None:
    source = NEW_PAGE.read_text()

    assert "useState(createDraftRunId)" not in source
    assert "setDraftRunId(createDraftRunId())" in source
    assert 'draftRunId || "draft"' in source
