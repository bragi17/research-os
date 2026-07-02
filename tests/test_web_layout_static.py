from __future__ import annotations

from pathlib import Path


LAYOUT = Path("apps/web/src/app/layout.tsx")


def test_root_html_suppresses_extension_injected_hydration_attributes() -> None:
    source = LAYOUT.read_text()

    assert "suppressHydrationWarning" in source
