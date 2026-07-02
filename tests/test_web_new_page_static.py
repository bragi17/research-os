from __future__ import annotations

from pathlib import Path


NEW_PAGE = Path("apps/web/src/app/new/page.tsx")


def test_start_research_button_is_not_disabled_by_topic_state() -> None:
    source = NEW_PAGE.read_text()

    assert "disabled={loading || topic.trim().length < 10}" not in source
    assert "disabled={loading}" in source


def test_new_research_submit_reads_current_topic_input_value() -> None:
    source = NEW_PAGE.read_text()

    assert "textareaRef.current?.value" in source
    assert "currentTopic" in source
