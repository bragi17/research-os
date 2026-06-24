"""Trusted workspace resolution and file access for production workflows."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from uuid import UUID

import apps.api.database as db

DEFAULT_TREE_LIMIT = 300
DEFAULT_FILE_MAX_BYTES = 262_144
DEFAULT_LOG_MAX_BYTES = 262_144


def _is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
    except ValueError:
        return False
    return True


def workspace_base() -> Path:
    """Return the configured base directory for all local production workspaces."""

    configured = os.getenv("RESEARCH_OS_WORKSPACE_ROOT")
    raw = Path(configured).expanduser() if configured else Path.cwd() / ".research-os" / "workspaces"
    base = raw.resolve()
    base.mkdir(parents=True, exist_ok=True)
    return base


def _safe_relative_path(raw: str | Path | None, *, field_name: str = "path") -> Path:
    text = "." if raw is None or str(raw).strip() == "" else str(raw).strip()
    path = Path(text)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{field_name} must be a workspace-relative path")
    return path


def resolve_under_workspace(
    root: str | Path,
    raw: str | Path | None = ".",
    *,
    field_name: str = "path",
) -> Path:
    """Resolve a workspace-relative path and reject traversal or symlink escapes."""

    root_path = Path(root).expanduser().resolve()
    relative = _safe_relative_path(raw, field_name=field_name)
    candidate = (root_path / relative).resolve()
    if not _is_relative_to(candidate, root_path):
        raise ValueError(f"{field_name} escapes workspace_root")
    return candidate


def resolve_path_reference(
    root: str | Path,
    raw: str | Path | None,
    *,
    field_name: str = "path",
) -> Path:
    """Resolve either an absolute stored path under root or a workspace-relative path."""

    if raw is None or str(raw).strip() == "":
        return resolve_under_workspace(root, ".", field_name=field_name)
    root_path = Path(root).expanduser().resolve()
    path = Path(str(raw)).expanduser()
    candidate = path.resolve() if path.is_absolute() else (root_path / _safe_relative_path(path, field_name=field_name)).resolve()
    if not _is_relative_to(candidate, root_path):
        raise ValueError(f"{field_name} escapes workspace_root")
    return candidate


def _default_workspace_path(project_id: UUID, run_id: UUID | None = None) -> Path:
    path = workspace_base() / "projects" / str(project_id)
    if run_id is not None:
        path = path / "runs" / str(run_id)
    return path


def resolve_project_workspace_path(
    project: dict[str, Any],
    *,
    run_id: UUID | None = None,
) -> Path:
    """Resolve a project's trusted local workspace path under the configured base."""

    base = workspace_base()
    configured = project.get("default_workspace_path")
    if configured:
        raw = Path(str(configured)).expanduser()
        candidate = raw.resolve() if raw.is_absolute() else (base / _safe_relative_path(raw, field_name="default_workspace_path")).resolve()
    else:
        candidate = _default_workspace_path(project["id"], run_id=run_id).resolve()
    if not _is_relative_to(candidate, base):
        raise ValueError("default_workspace_path escapes workspace root")
    candidate.mkdir(parents=True, exist_ok=True)
    return candidate


def resolve_coding_workspace_path(
    task_or_payload: dict[str, Any],
    project: dict[str, Any],
) -> Path:
    """Resolve and validate a coding task workspace under the configured base."""

    configured = task_or_payload.get("workspace_path")
    if configured:
        base = workspace_base()
        raw = Path(str(configured)).expanduser()
        candidate = raw.resolve() if raw.is_absolute() else (base / _safe_relative_path(raw, field_name="workspace_path")).resolve()
        if not _is_relative_to(candidate, base):
            raise ValueError("workspace_path escapes workspace root")
        candidate.mkdir(parents=True, exist_ok=True)
        return candidate
    return resolve_project_workspace_path(project, run_id=task_or_payload.get("run_id"))


async def resolve_project_workspace(
    project_id: UUID,
    *,
    run_id: UUID | None = None,
) -> Path:
    project = await db.get_project(project_id)
    if project is None:
        raise ValueError(f"Project not found: {project_id}")
    return resolve_project_workspace_path(project, run_id=run_id)


async def resolve_job_workspace(job: dict[str, Any]) -> Path:
    project_id = job.get("project_id")
    if project_id is None:
        raise ValueError("project_id is required to resolve job workspace")
    return await resolve_project_workspace(project_id)


def _relative_display(path: Path, root: Path) -> str:
    relative = path.relative_to(root)
    return "." if str(relative) == "." else relative.as_posix()


def _tree_entry(path: Path, root: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "name": path.name,
        "path": _relative_display(path, root),
        "kind": "directory" if path.is_dir() else "file",
        "size": stat.st_size if path.is_file() else None,
        "modified_at": stat.st_mtime,
    }


def list_workspace_tree_sync(
    root: str | Path,
    path: str | Path | None = ".",
    *,
    limit: int = DEFAULT_TREE_LIMIT,
) -> dict[str, Any]:
    root_path = Path(root).expanduser().resolve()
    target = resolve_under_workspace(root_path, path, field_name="path")
    if not target.exists():
        raise ValueError(f"Workspace path not found: {path or '.'}")
    entries = [target] if target.is_file() else sorted(target.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower()))
    visible = entries[:limit]
    return {
        "root": str(root_path),
        "path": _relative_display(target, root_path),
        "entries": [_tree_entry(entry, root_path) for entry in visible],
        "truncated": len(entries) > len(visible),
    }


def read_workspace_file_sync(
    root: str | Path,
    path: str | Path,
    *,
    max_bytes: int = DEFAULT_FILE_MAX_BYTES,
) -> dict[str, Any]:
    root_path = Path(root).expanduser().resolve()
    target = resolve_under_workspace(root_path, path, field_name="path")
    if not target.is_file():
        raise ValueError(f"Workspace file not found: {path}")
    raw = target.read_bytes()
    truncated = len(raw) > max_bytes
    content = raw[:max_bytes].decode("utf-8", errors="replace")
    return {
        "root": str(root_path),
        "path": _relative_display(target, root_path),
        "content": content,
        "size": len(raw),
        "truncated": truncated,
    }


def tail_file_sync(
    root: str | Path,
    path: str | Path,
    *,
    lines: int = 200,
    max_bytes: int = DEFAULT_LOG_MAX_BYTES,
) -> dict[str, Any]:
    root_path = Path(root).expanduser().resolve()
    target = resolve_path_reference(root_path, path, field_name="log_path")
    if not target.is_file():
        raise ValueError(f"Log file not found: {path}")
    size = target.stat().st_size
    with target.open("rb") as handle:
        if size > max_bytes:
            handle.seek(size - max_bytes)
        raw = handle.read(max_bytes)
    decoded = raw.decode("utf-8", errors="replace")
    tail = "\n".join(decoded.splitlines()[-lines:])
    return {
        "root": str(root_path),
        "path": _relative_display(target, root_path),
        "content": tail,
        "size": size,
        "truncated": size > max_bytes,
    }


async def tree_workspace(
    *,
    project_id: UUID,
    run_id: UUID | None,
    path: str = ".",
) -> dict[str, Any]:
    root = await resolve_project_workspace(project_id, run_id=run_id)
    return list_workspace_tree_sync(root, path)


async def read_workspace_file(
    *,
    project_id: UUID,
    run_id: UUID | None,
    path: str,
) -> dict[str, Any]:
    root = await resolve_project_workspace(project_id, run_id=run_id)
    return read_workspace_file_sync(root, path)


async def tail_job_log(job_id: UUID, stream_name: str, *, lines: int = 200) -> dict[str, Any]:
    job = await db.get_experiment_job(job_id)
    if job is None:
        raise ValueError(f"Experiment job not found: {job_id}")
    if stream_name not in {"stdout", "stderr"}:
        raise ValueError("stream_name must be stdout or stderr")
    root = await resolve_job_workspace(job)
    stored = job.get("stdout_log_path") if stream_name == "stdout" else job.get("stderr_log_path")
    default = f".research-os/jobs/{job_id}/logs/{stream_name}.log"
    return tail_file_sync(root, stored or default, lines=lines)


async def list_job_artifacts(job_id: UUID) -> dict[str, Any]:
    job = await db.get_experiment_job(job_id)
    if job is None:
        raise ValueError(f"Experiment job not found: {job_id}")
    root = await resolve_job_workspace(job)
    artifact_dir = job.get("artifact_dir") or job.get("cwd") or "."
    artifact_path = resolve_path_reference(root, artifact_dir, field_name="artifact_dir")
    return list_workspace_tree_sync(root, artifact_path.relative_to(root))
