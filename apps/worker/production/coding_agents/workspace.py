from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True)
class CodingWorkspace:
    root: Path
    workdir: Path
    context_dir: Path
    logs_dir: Path
    artifacts_dir: Path
    research_os_dir: Path


def prepare_coding_workspace(
    root: str | Path,
    project_id: str,
    coding_task_id: str,
    context_files: Mapping[str, Any],
) -> CodingWorkspace:
    """Create an isolated coding-task workspace and inject context files."""

    root_path = Path(root).resolve()
    project_segment = _safe_path_segment(project_id, "project_id")
    task_segment = _safe_path_segment(coding_task_id, "coding_task_id")

    task_root = (
        root_path
        / "projects"
        / project_segment
        / "code"
        / "tasks"
        / task_segment
    )
    workdir = task_root / "workdir"
    context_dir = task_root / "context"
    logs_dir = task_root / "logs"
    artifacts_dir = task_root / "artifacts"
    research_os_dir = task_root / ".research-os"

    workspace = CodingWorkspace(
        root=_ensure_inside(task_root, root_path),
        workdir=_ensure_inside(workdir, root_path),
        context_dir=_ensure_inside(context_dir, root_path),
        logs_dir=_ensure_inside(logs_dir, root_path),
        artifacts_dir=_ensure_inside(artifacts_dir, root_path),
        research_os_dir=_ensure_inside(research_os_dir, root_path),
    )

    context_entries = []
    for name, value in context_files.items():
        relative_path = _safe_context_path(name)
        target = _ensure_inside(workspace.context_dir / relative_path, workspace.context_dir)
        context_entries.append((target, _serialize_context_value(value)))

    for directory in (
        workspace.workdir,
        workspace.context_dir,
        workspace.logs_dir,
        workspace.artifacts_dir,
        workspace.research_os_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)

    for target, content in context_entries:
        target.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_text(target, content)

    return workspace


def _safe_path_segment(value: str, field_name: str) -> str:
    if not value or value.strip() != value:
        raise ValueError(f"{field_name} must be a non-empty path segment")
    path = Path(value)
    if path.is_absolute() or len(path.parts) != 1 or value in {".", ".."}:
        raise ValueError(f"{field_name} must be a safe path segment")
    return value


def _safe_context_path(name: str) -> Path:
    path = Path(name)
    if path.is_absolute() or not path.parts:
        raise ValueError(f"context file path is unsafe: {name}")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"context file path is unsafe: {name}")
    return path


def _ensure_inside(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"path escapes workspace root: {path}") from exc
    return resolved


def _serialize_context_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list)):
        return json.dumps(value, indent=2, sort_keys=True) + "\n"
    raise TypeError("context file values must be strings, dicts, or lists")


def _atomic_write_text(target: Path, content: str) -> None:
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_name = temp_file.name
            temp_file.write(content)
        os.replace(temp_name, target)
    finally:
        if temp_name is not None:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
