from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from libs.schemas.literature import LiteratureErrorKind, LiteratureSource
from services.literature_sources.base import normalize_title_key
from services.literature_sources.deepxiv import DeepXivSource
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


@pytest.mark.asyncio
async def test_obsidian_source_uses_relative_path_in_raw(tmp_path: Path) -> None:
    note = tmp_path / "nested" / "paper.md"
    note.parent.mkdir()
    note.write_text("# Relative Path Paper\nDOI: 10.1000/relative\n", encoding="utf-8")
    source = ObsidianSource({"path": str(tmp_path)})

    result = await source.search("relative path")

    assert result.candidates[0].raw["path"] == "nested/paper.md"


@pytest.mark.asyncio
async def test_deepxiv_source_times_out_and_kills_process(monkeypatch: pytest.MonkeyPatch) -> None:
    class SlowProcess:
        returncode = None

        def __init__(self) -> None:
            self.killed = False
            self.waited = False

        async def communicate(self) -> tuple[bytes, bytes]:
            await asyncio.sleep(60)
            return b"[]", b""

        def kill(self) -> None:
            self.killed = True

        async def wait(self) -> None:
            self.waited = True

    process = SlowProcess()

    async def fake_create_subprocess_exec(*args: object, **kwargs: object) -> SlowProcess:
        return process

    monkeypatch.setattr(
        "services.literature_sources.deepxiv.asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )
    source = DeepXivSource({"command": "deepxiv", "timeout_seconds": 0.01})

    result = await source.search("graph", limit=5)

    assert result.candidates == []
    assert result.errors[0].kind == LiteratureErrorKind.TRANSIENT_ERROR
    assert result.errors[0].query == "graph"
    assert "timed out" in result.errors[0].message
    assert process.killed is True
    assert process.waited is True
