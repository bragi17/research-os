from __future__ import annotations

from pathlib import Path

import pytest

from libs.schemas.literature import LiteratureSource
from services.literature_sources.base import normalize_title_key
from services.literature_sources.obsidian import ObsidianSource
from services.literature_sources.zotero import ZoteroSource


def test_normalize_title_key_collapses_case_and_spacing() -> None:
    assert normalize_title_key("  A  New   Method ") == "a new method"


@pytest.mark.asyncio
async def test_zotero_source_reads_json_export(tmp_path: Path) -> None:
    export = tmp_path / "zotero.json"
    export.write_text(
        '[{"title":"Graph Matching Paper","DOI":"10.1000/graph","date":"2024","creators":[{"lastName":"Ada"}]}]',
        encoding="utf-8",
    )
    source = ZoteroSource({"path": str(export)})

    result = await source.search("graph matching")

    assert result.candidates[0].title == "Graph Matching Paper"
    assert result.candidates[0].doi == "10.1000/graph"
    assert result.candidates[0].source == LiteratureSource.ZOTERO


@pytest.mark.asyncio
async def test_obsidian_source_extracts_doi_from_markdown(tmp_path: Path) -> None:
    note = tmp_path / "paper.md"
    note.write_text(
        "---\ntitle: Obsidian Graph Paper\nyear: 2025\n---\nDOI: 10.1000/obsidian\n",
        encoding="utf-8",
    )
    source = ObsidianSource({"path": str(tmp_path)})

    result = await source.search("obsidian graph")

    assert result.candidates[0].title == "Obsidian Graph Paper"
    assert result.candidates[0].doi == "10.1000/obsidian"
    assert result.candidates[0].source == LiteratureSource.OBSIDIAN
