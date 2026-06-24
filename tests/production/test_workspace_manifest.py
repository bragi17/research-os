from __future__ import annotations

import json
from pathlib import Path

import pytest
from unittest.mock import AsyncMock
from uuid import uuid4

from apps.worker.production.coding_agents.workspace import prepare_coding_workspace
from apps.worker.production.experiments.manifest import (
    ManifestValidationError,
    expand_manifest_jobs,
)
from libs.schemas.production import ExperimentManifestPayload


def test_prepare_coding_workspace_creates_task_dirs_and_writes_context(tmp_path: Path) -> None:
    workspace = prepare_coding_workspace(
        tmp_path,
        "project-1",
        "task-1",
        {
            "constraints.md": "Use only public datasets.\n",
            "experiment_plan.json": {"title": "smoke", "epochs": 1},
            "nested/query_pack.json": [{"query": "contrastive learning"}],
        },
    )

    expected_root = tmp_path / "projects" / "project-1" / "code" / "tasks" / "task-1"
    assert workspace.root == expected_root
    assert workspace.workdir == expected_root / "workdir"
    assert workspace.context_dir == expected_root / "context"
    assert workspace.logs_dir == expected_root / "logs"
    assert workspace.artifacts_dir == expected_root / "artifacts"
    assert workspace.research_os_dir == expected_root / ".research-os"

    for path in (
        workspace.root,
        workspace.workdir,
        workspace.context_dir,
        workspace.logs_dir,
        workspace.artifacts_dir,
        workspace.research_os_dir,
    ):
        assert path.is_dir()
        assert path.resolve().is_relative_to(tmp_path.resolve())

    assert (workspace.context_dir / "constraints.md").read_text() == "Use only public datasets.\n"
    assert json.loads((workspace.context_dir / "experiment_plan.json").read_text()) == {
        "title": "smoke",
        "epochs": 1,
    }
    assert json.loads((workspace.context_dir / "nested/query_pack.json").read_text()) == [
        {"query": "contrastive learning"}
    ]
    assert (workspace.context_dir / "experiment_plan.json").read_text().endswith("\n")


@pytest.mark.parametrize("bad_name", ["/absolute.json", "../escape.json", "nested/../../escape.json"])
def test_prepare_coding_workspace_rejects_unsafe_context_names(
    tmp_path: Path, bad_name: str
) -> None:
    with pytest.raises(ValueError, match="context file"):
        prepare_coding_workspace(tmp_path, "project-1", "task-1", {bad_name: "nope"})


def test_prepare_coding_workspace_serializes_all_context_before_writing(
    tmp_path: Path,
) -> None:
    with pytest.raises(TypeError, match="JSON serializable"):
        prepare_coding_workspace(
            tmp_path,
            "project-1",
            "task-1",
            {
                "ok.txt": "should not be written",
                "bad.json": {"not_json": object()},
            },
        )

    task_root = tmp_path / "projects" / "project-1" / "code" / "tasks" / "task-1"
    assert not task_root.exists()


def test_expand_manifest_jobs_preserves_phase_and_job_order() -> None:
    manifest = {
        "project": "demo",
        "workspace": ".",
        "phases": [
            {
                "name": "sanity",
                "jobs": [
                    {
                        "name": "smoke",
                        "cmd": "python train.py --debug",
                        "cwd": "experiments",
                        "expected_outputs": ["outputs/sanity/metrics.json"],
                        "timeout_sec": 60,
                        "retry": {"max_attempts": 2, "oom_retry": True},
                    }
                ],
            },
            {
                "name": "full",
                "depends_on": ["sanity"],
                "jobs": [
                    {
                        "name": "main",
                        "cmd": "python train.py",
                        "expected_outputs": ["outputs/full/metrics.json", "outputs/full/model.pt"],
                    }
                ],
            },
        ],
    }

    jobs = expand_manifest_jobs(manifest)

    assert [(job.phase_name, job.job_name, job.phase_index, job.job_index) for job in jobs] == [
        ("sanity", "smoke", 0, 0),
        ("full", "main", 1, 0),
    ]
    assert jobs[0].cmd == "python train.py --debug"
    assert jobs[0].cwd == "experiments"
    assert jobs[0].expected_outputs == ["outputs/sanity/metrics.json"]
    assert jobs[0].timeout_sec == 60
    assert jobs[0].max_attempts == 2
    assert jobs[0].oom_retry is True
    assert jobs[1].cwd == "."
    assert jobs[1].timeout_sec == 1800
    assert jobs[1].max_attempts == 1
    assert jobs[1].oom_retry is False
    assert jobs[0].phase_dependencies == []
    assert jobs[1].phase_dependencies == ["sanity"]


def test_expand_manifest_jobs_accepts_schema_payload() -> None:
    payload = ExperimentManifestPayload(
        project="demo",
        workspace=".",
        phases=[
            {
                "name": "sanity",
                "jobs": [{"name": "smoke", "cmd": "python smoke.py"}],
            }
        ],
    )

    jobs = expand_manifest_jobs(payload)

    assert len(jobs) == 1
    assert jobs[0].phase_name == "sanity"
    assert jobs[0].job_name == "smoke"


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda m: m.update({"project": ""}), "project"),
        (lambda m: m.update({"workspace": ""}), "workspace"),
        (lambda m: m.update({"phases": []}), "phase"),
        (lambda m: m["phases"].append({"name": "sanity", "jobs": [{"name": "again", "cmd": "echo ok"}]}), "duplicate phase"),
        (lambda m: m["phases"][0]["jobs"].append({"name": "smoke", "cmd": "echo again"}), "duplicate job"),
        (lambda m: m["phases"][0].update({"depends_on": ["missing"]}), "unknown dependency"),
        (lambda m: m["phases"][0].update({"depends_on": ["sanity"]}), "self-dependency"),
        (lambda m: m["phases"][0].update({"depends_on": ["full"]}), "later phase"),
        (lambda m: m["phases"][0].update({"jobs": []}), "empty"),
        (lambda m: m["phases"][0]["jobs"][0].update({"cmd": "   "}), "cmd"),
    ],
)
def test_expand_manifest_jobs_rejects_invalid_manifests(mutation, message: str) -> None:
    manifest = {
        "project": "demo",
        "workspace": ".",
        "phases": [
            {"name": "sanity", "jobs": [{"name": "smoke", "cmd": "echo ok"}]},
            {"name": "full", "depends_on": ["sanity"], "jobs": [{"name": "main", "cmd": "echo full"}]},
        ],
    }
    mutation(manifest)

    with pytest.raises(ManifestValidationError, match=message):
        expand_manifest_jobs(manifest)


@pytest.mark.parametrize(
    ("job_update", "message"),
    [
        ({"cwd": "/tmp"}, "cwd"),
        ({"cwd": "../outside"}, "cwd"),
        ({"expected_outputs": ["/etc/passwd"]}, "expected_outputs"),
        ({"expected_outputs": ["../outside"]}, "expected_outputs"),
    ],
)
def test_expand_manifest_jobs_rejects_paths_outside_workspace(
    job_update: dict[str, object], message: str
) -> None:
    manifest = {
        "project": "demo",
        "workspace": ".",
        "phases": [
            {
                "name": "sanity",
                "jobs": [
                    {
                        "name": "smoke",
                        "cmd": "echo ok",
                        **job_update,
                    }
                ],
            },
        ],
    }

    with pytest.raises(ManifestValidationError, match=message):
        expand_manifest_jobs(manifest)


@pytest.mark.asyncio
async def test_list_job_artifacts_accepts_absolute_artifact_dir_under_workspace(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from apps.worker.production import workspaces

    project_id = uuid4()
    job_id = uuid4()
    workspace = tmp_path / "projects" / str(project_id)
    artifact_dir = workspace / "experiments" / "outputs"
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "metrics.json").write_text('{"accuracy": 0.9}\n', encoding="utf-8")
    monkeypatch.setenv("RESEARCH_OS_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setattr(
        workspaces.db,
        "get_experiment_job",
        AsyncMock(return_value={
            "id": job_id,
            "project_id": project_id,
            "cwd": "experiments",
            "artifact_dir": str(artifact_dir),
        }),
    )
    monkeypatch.setattr(
        workspaces.db,
        "get_project",
        AsyncMock(return_value={
            "id": project_id,
            "default_workspace_path": str(workspace),
        }),
    )

    result = await workspaces.list_job_artifacts(job_id)

    assert result["path"] == "experiments/outputs"
    assert result["entries"][0]["path"] == "experiments/outputs/metrics.json"
