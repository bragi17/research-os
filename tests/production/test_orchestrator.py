"""Tests for production research orchestration services."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from apps.worker.production.coding_agents.base import CodingAgentEvent
from apps.worker.production.coding_agents.codex_provider import CodexProvider
from apps.worker.production.experiments.local_executor import LocalJobResult
from libs.schemas.production import CodingTaskCreate


def _now_row() -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    return {"created_at": now, "updated_at": now}


@dataclass
class FakeProductionDb:
    projects: dict[UUID, dict[str, Any]] = field(default_factory=dict)
    coding_tasks: dict[UUID, dict[str, Any]] = field(default_factory=dict)
    coding_events: list[dict[str, Any]] = field(default_factory=list)
    coding_task_updates: list[tuple[UUID, dict[str, Any]]] = field(default_factory=list)
    manifests: dict[UUID, dict[str, Any]] = field(default_factory=dict)
    experiment_jobs: dict[UUID, dict[str, Any]] = field(default_factory=dict)
    experiment_job_updates: list[tuple[UUID, dict[str, Any]]] = field(default_factory=list)
    claim_entries: list[dict[str, Any]] = field(default_factory=list)
    claim_evidence: list[dict[str, Any]] = field(default_factory=list)
    code_artifacts: list[dict[str, Any]] = field(default_factory=list)
    manuscripts: dict[UUID, dict[str, Any]] = field(default_factory=dict)
    manuscript_updates: list[tuple[UUID, dict[str, Any]]] = field(default_factory=list)
    submissions: dict[UUID, dict[str, Any]] = field(default_factory=dict)
    submission_updates: list[tuple[UUID, dict[str, Any]]] = field(default_factory=list)
    created_coding_tasks: list[dict[str, Any]] = field(default_factory=list)
    created_experiment_jobs: list[dict[str, Any]] = field(default_factory=list)
    created_query_packs: list[dict[str, Any]] = field(default_factory=list)
    created_manifests: list[dict[str, Any]] = field(default_factory=list)
    created_code_artifacts: list[dict[str, Any]] = field(default_factory=list)

    async def get_project(self, project_id: UUID) -> dict[str, Any] | None:
        return self.projects.get(project_id)

    async def create_coding_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        row = {
            "id": uuid4(),
            "provider_session_id": None,
            "status": "queued",
            **payload,
            **_now_row(),
        }
        self.created_coding_tasks.append(payload)
        self.coding_tasks[row["id"]] = row
        return row

    async def create_project_query_pack(self, payload: dict[str, Any]) -> dict[str, Any]:
        row = {"id": uuid4(), **payload, **_now_row()}
        self.created_query_packs.append(row)
        return row

    async def get_coding_task(self, task_id: UUID) -> dict[str, Any] | None:
        return self.coding_tasks.get(task_id)

    async def list_coding_tasks(
        self,
        project_id: UUID | None = None,
        run_id: UUID | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        rows = list(self.coding_tasks.values())
        if project_id is not None:
            rows = [row for row in rows if row.get("project_id") == project_id]
        if run_id is not None:
            rows = [row for row in rows if row.get("run_id") == run_id]
        if status is not None:
            rows = [row for row in rows if row.get("status") == status]
        return rows[offset : offset + limit]

    async def update_coding_task(
        self,
        task_id: UUID,
        updates: dict[str, Any],
    ) -> dict[str, Any] | None:
        row = self.coding_tasks.get(task_id)
        if row is None:
            return None
        row = {**row, **updates, "updated_at": datetime.now(timezone.utc)}
        self.coding_tasks[task_id] = row
        self.coding_task_updates.append((task_id, updates))
        return row

    async def update_coding_task_if_lease(
        self,
        task_id: UUID,
        updates: dict[str, Any],
        *,
        worker_id: str,
        lease_id: str,
    ) -> dict[str, Any] | None:
        row = self.coding_tasks.get(task_id)
        if row is None:
            return None
        lease = (row.get("metadata_json") or {}).get("scheduler_lease", {})
        if (
            row.get("status") != "running"
            or lease.get("worker_id") != worker_id
            or lease.get("lease_id") != lease_id
        ):
            return None
        return await self.update_coding_task(task_id, updates)

    async def create_coding_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        row = {"id": len(self.coding_events) + 1, **payload, "created_at": datetime.now(timezone.utc)}
        self.coding_events.append(row)
        return row

    async def get_experiment_manifest(self, manifest_id: UUID) -> dict[str, Any] | None:
        return self.manifests.get(manifest_id)

    async def create_experiment_job(self, payload: dict[str, Any]) -> dict[str, Any]:
        row = {"id": uuid4(), **payload, **_now_row()}
        self.created_experiment_jobs.append(payload)
        self.experiment_jobs[row["id"]] = row
        return row

    async def create_experiment_manifest(self, payload: dict[str, Any]) -> dict[str, Any]:
        row = {"id": uuid4(), **payload, **_now_row()}
        self.created_manifests.append(payload)
        self.manifests[row["id"]] = row
        return row

    async def get_remote_host(self, remote_host_id: UUID) -> dict[str, Any] | None:
        return getattr(self, "remote_hosts", {}).get(remote_host_id)

    async def get_experiment_job(self, job_id: UUID) -> dict[str, Any] | None:
        return self.experiment_jobs.get(job_id)

    async def list_experiment_jobs(
        self,
        project_id: UUID | None = None,
        experiment_plan_id: UUID | None = None,
        manifest_id: UUID | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        rows = list(self.experiment_jobs.values())
        if project_id is not None:
            rows = [row for row in rows if row.get("project_id") == project_id]
        if experiment_plan_id is not None:
            rows = [row for row in rows if row.get("experiment_plan_id") == experiment_plan_id]
        if manifest_id is not None:
            rows = [row for row in rows if row.get("manifest_id") == manifest_id]
        if status is not None:
            rows = [row for row in rows if row.get("status") == status]
        return rows[offset : offset + limit]

    async def update_experiment_job(
        self,
        job_id: UUID,
        updates: dict[str, Any],
    ) -> dict[str, Any] | None:
        row = self.experiment_jobs.get(job_id)
        if row is None:
            return None
        row = {**row, **updates, "updated_at": datetime.now(timezone.utc)}
        self.experiment_jobs[job_id] = row
        self.experiment_job_updates.append((job_id, updates))
        return row

    async def update_experiment_job_if_lease(
        self,
        job_id: UUID,
        updates: dict[str, Any],
        *,
        worker_id: str,
        lease_id: str,
    ) -> dict[str, Any] | None:
        row = self.experiment_jobs.get(job_id)
        if row is None:
            return None
        lease = (row.get("metrics_json") or {}).get("scheduler_lease", {})
        if (
            row.get("status") != "running"
            or lease.get("worker_id") != worker_id
            or lease.get("lease_id") != lease_id
        ):
            return None
        return await self.update_experiment_job(job_id, updates)

    async def list_claim_ledger(
        self,
        project_id: UUID | None = None,
        experiment_plan_id: UUID | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        rows = list(self.claim_entries)
        if project_id is not None:
            rows = [row for row in rows if row.get("project_id") == project_id]
        if experiment_plan_id is not None:
            rows = [row for row in rows if row.get("experiment_plan_id") == experiment_plan_id]
        if status is not None:
            rows = [row for row in rows if row.get("status") == status]
        return rows[offset : offset + limit]

    async def create_claim_ledger_entry(self, payload: dict[str, Any]) -> dict[str, Any]:
        row = {"id": uuid4(), **payload, **_now_row()}
        self.claim_entries.append(row)
        return row

    async def create_claim_evidence(self, payload: dict[str, Any]) -> dict[str, Any]:
        row = {"id": uuid4(), **payload, "created_at": datetime.now(timezone.utc)}
        self.claim_evidence.append(row)
        return row

    async def list_code_artifacts(
        self,
        project_id: UUID | None = None,
        coding_task_id: UUID | None = None,
        experiment_plan_id: UUID | None = None,
        artifact_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        rows = list(self.code_artifacts)
        if project_id is not None:
            rows = [row for row in rows if row.get("project_id") == project_id]
        if coding_task_id is not None:
            rows = [row for row in rows if row.get("coding_task_id") == coding_task_id]
        if experiment_plan_id is not None:
            rows = [row for row in rows if row.get("experiment_plan_id") == experiment_plan_id]
        if artifact_type is not None:
            rows = [row for row in rows if row.get("artifact_type") == artifact_type]
        return rows[offset : offset + limit]

    async def create_code_artifact(self, payload: dict[str, Any]) -> dict[str, Any]:
        row = {"id": uuid4(), **payload, "created_at": datetime.now(timezone.utc)}
        self.created_code_artifacts.append(payload)
        self.code_artifacts.append(row)
        return row

    async def get_manuscript_package(self, manuscript_id: UUID) -> dict[str, Any] | None:
        return self.manuscripts.get(manuscript_id)

    async def update_manuscript_package(
        self,
        manuscript_id: UUID,
        updates: dict[str, Any],
    ) -> dict[str, Any] | None:
        row = self.manuscripts.get(manuscript_id)
        if row is None:
            return None
        row = {**row, **updates, "updated_at": datetime.now(timezone.utc)}
        self.manuscripts[manuscript_id] = row
        self.manuscript_updates.append((manuscript_id, updates))
        return row

    async def get_submission_package(self, submission_id: UUID) -> dict[str, Any] | None:
        return self.submissions.get(submission_id)

    async def update_submission_package(
        self,
        submission_id: UUID,
        updates: dict[str, Any],
    ) -> dict[str, Any] | None:
        row = self.submissions.get(submission_id)
        if row is None:
            return None
        row = {**row, **updates, "updated_at": datetime.now(timezone.utc)}
        self.submissions[submission_id] = row
        self.submission_updates.append((submission_id, updates))
        return row


class FakeProvider:
    def __init__(self, events: list[CodingAgentEvent]) -> None:
        self.events = events
        self.calls: list[tuple[str, Any]] = []

    async def execute(self, prompt: str, options: Any) -> AsyncIterator[CodingAgentEvent]:
        self.calls.append((prompt, options))
        for event in self.events:
            yield event


class ExplodingProvider:
    async def execute(self, prompt: str, options: Any) -> AsyncIterator[CodingAgentEvent]:
        raise RuntimeError("codex crashed")
        yield  # pragma: no cover


class FakeLocalExecutor:
    def __init__(self, result: LocalJobResult | None = None) -> None:
        self.result = result
        self.specs: list[Any] = []

    async def run(self, spec: Any) -> LocalJobResult:
        self.specs.append(spec)
        if self.result is not None:
            return self.result
        return LocalJobResult(
            job_id=spec.job_id,
            status="completed",
            returncode=0,
            stdout_log=spec.log_dir / "stdout.log",
            stderr_log=spec.log_dir / "stderr.log",
            expected_outputs_found=[spec.cwd / "metrics.json"],
            missing_expected_outputs=[spec.cwd / "plot.png"],
            failure_reason=None,
            duration_ms=12,
        )


class ExplodingLocalExecutor:
    async def run(self, spec: Any) -> LocalJobResult:
        raise RuntimeError("process launcher failed")


def test_submission_paper_claim_audit_report_reads_file(tmp_path: Path) -> None:
    from apps.worker.production.orchestrator import (
        _submission_paper_claim_audit_report,
    )

    paper_dir = tmp_path / "paper"
    paper_dir.mkdir()
    (paper_dir / "PAPER_CLAIM_AUDIT.json").write_text(
        '{"passed": true, "checked_claims": 3, "blockers": []}',
        encoding="utf-8",
    )

    report = _submission_paper_claim_audit_report(paper_dir)

    assert report["passed"] is True
    assert report["checked_claims"] == 3


def test_submission_adversarial_audit_report_missing_blocks(
    tmp_path: Path,
) -> None:
    from apps.worker.production.orchestrator import (
        _submission_adversarial_audit_report,
    )

    paper_dir = tmp_path / "paper"
    paper_dir.mkdir()

    report = _submission_adversarial_audit_report(paper_dir)

    assert report["passed"] is False
    assert report["missing"] is True
    assert report["required_file"] == "KILL_ARGUMENT.json"


def _set_workspace_base(monkeypatch: pytest.MonkeyPatch, path: Path) -> Path:
    base = path / "trusted-workspaces"
    base.mkdir()
    monkeypatch.setenv("RESEARCH_OS_WORKSPACE_ROOT", str(base))
    return base


@pytest.mark.asyncio
async def test_create_coding_task_normalizes_payload_and_adds_stable_prompt_hash(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from apps.worker.production import orchestrator

    fake_db = FakeProductionDb()
    monkeypatch.setattr(orchestrator, "db", fake_db)
    base = _set_workspace_base(monkeypatch, tmp_path)
    project_id = uuid4()
    fake_db.projects[project_id] = {
        "id": project_id,
        "default_workspace_path": "projects/demo",
        **_now_row(),
    }

    first = await orchestrator.create_coding_task(
        {
            "project_id": project_id,
            "user_prompt": "Implement the experiment",
            "system_prompt": "Be precise",
            "model": "gpt-5-codex",
            "env": {"CUDA_VISIBLE_DEVICES": "0"},
            "mcp_config": {"servers": {}},
        }
    )
    second = await orchestrator.create_coding_task(
        CodingTaskCreate(
            project_id=project_id,
            user_prompt="Implement the experiment",
            system_prompt="Be precise",
            model="gpt-5-codex",
            env={"CUDA_VISIBLE_DEVICES": "0"},
            mcp_config={"servers": {}},
        )
    )

    payload = fake_db.created_coding_tasks[0]
    assert payload["env_json"] == {"CUDA_VISIBLE_DEVICES": "0"}
    assert payload["mcp_config_json"] == {"servers": {}}
    assert "env" not in payload
    assert "mcp_config" not in payload
    assert payload["workspace_path"] == str((base / "projects" / "demo").resolve())
    assert len(first["prompt_hash"]) == 64
    assert first["prompt_hash"] == second["prompt_hash"]


@pytest.mark.asyncio
async def test_create_coding_task_rejects_workspace_outside_configured_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from apps.worker.production import orchestrator

    fake_db = FakeProductionDb()
    monkeypatch.setattr(orchestrator, "db", fake_db)
    _set_workspace_base(monkeypatch, tmp_path)
    project_id = uuid4()
    fake_db.projects[project_id] = {"id": project_id, "default_workspace_path": None, **_now_row()}

    with pytest.raises(ValueError, match="workspace_path escapes workspace root"):
        await orchestrator.create_coding_task(
            {
                "project_id": project_id,
                "workspace_path": str(tmp_path / "outside"),
                "user_prompt": "Implement the experiment",
            }
        )

    assert fake_db.created_coding_tasks == []


@pytest.mark.asyncio
async def test_run_codex_task_streams_events_and_persists_completed_status(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from apps.worker.production import orchestrator

    fake_db = FakeProductionDb()
    monkeypatch.setattr(orchestrator, "db", fake_db)
    base = _set_workspace_base(monkeypatch, tmp_path)
    workspace = base / "codex-task"
    workspace.mkdir()
    task_id = uuid4()
    fake_db.coding_tasks[task_id] = {
        "id": task_id,
        "project_id": uuid4(),
        "run_id": uuid4(),
        "provider_session_id": "resume-1",
        "workspace_path": str(workspace),
        "thread_name": "thread-a",
        "system_prompt": "System",
        "user_prompt": "Do the work",
        "model": "gpt-5-codex",
        "timeout_sec": 60,
        "semantic_inactivity_timeout_sec": 10,
        "env_json": {"CUDA_VISIBLE_DEVICES": "0"},
        "mcp_config_json": {"servers": {}},
        "thinking_level": "medium",
        "extra_args": ["--skip-git-repo-check"],
        "custom_args": [],
        "status": "queued",
        "token_usage_json": {},
        **_now_row(),
    }
    provider = FakeProvider(
        [
            CodingAgentEvent(type="status", status="started", session_id="session-2"),
            CodingAgentEvent(type="text", content="hello "),
            CodingAgentEvent(type="tool_use", tool="shell", call_id="c1", input={"cmd": "pytest"}),
            CodingAgentEvent(type="tool_result", call_id="c1", output="passed", status="ok"),
            CodingAgentEvent(type="status", status="completed", raw={"usage": {"total_tokens": 42}}),
        ]
    )

    result = await orchestrator.run_codex_task(task_id, provider=provider)

    prompt, options = provider.calls[0]
    assert prompt == "Do the work"
    assert options.cwd == str(workspace.resolve())
    assert options.resume_session_id == "resume-1"
    assert options.mcp_config is None
    CodexProvider(command="/bin/codex").build_command("Do the work", options)
    assert fake_db.coding_task_updates[0][1]["status"] == "running"
    assert fake_db.coding_task_updates[0][1]["started_at"].tzinfo is timezone.utc
    assert [event["event_type"] for event in fake_db.coding_events] == [
        "status",
        "text",
        "tool_use",
        "tool_result",
        "status",
    ]
    assert fake_db.coding_events[2]["input_json"] == {"cmd": "pytest"}
    final_update = fake_db.coding_task_updates[-1][1]
    assert final_update["status"] == "completed"
    assert final_update["completed_at"].tzinfo is timezone.utc
    assert final_update["duration_ms"] >= 0
    assert final_update["token_usage_json"] == {"total_tokens": 42}
    assert final_update["provider_session_id"] == "session-2"
    assert result.status == "completed"
    assert result.output == "hello "
    assert result.events == fake_db.coding_events


@pytest.mark.asyncio
async def test_run_codex_task_uses_configured_provider_factory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from apps.worker.production import orchestrator

    fake_db = FakeProductionDb()
    monkeypatch.setattr(orchestrator, "db", fake_db)
    base = _set_workspace_base(monkeypatch, tmp_path)
    workspace = base / "claude-task"
    workspace.mkdir()
    task_id = uuid4()
    fake_db.coding_tasks[task_id] = {
        "id": task_id,
        "project_id": uuid4(),
        "provider": "claude",
        "workspace_path": str(workspace),
        "user_prompt": "Use the configured agent",
        "mcp_config_json": {"servers": {}},
        "env_json": {},
        "status": "queued",
        **_now_row(),
    }
    provider = FakeProvider([CodingAgentEvent(type="status", status="completed")])
    selected: list[str] = []
    monkeypatch.setattr(
        orchestrator,
        "provider_for_name",
        lambda name: selected.append(name) or provider,
    )

    result = await orchestrator.run_codex_task(task_id)

    assert selected == ["claude"]
    assert result.status == "completed"
    assert provider.calls[0][0] == "Use the configured agent"


@pytest.mark.asyncio
async def test_run_codex_task_does_not_overwrite_after_lease_changes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from apps.worker.production import orchestrator

    fake_db = FakeProductionDb()
    monkeypatch.setattr(orchestrator, "db", fake_db)
    base = _set_workspace_base(monkeypatch, tmp_path)
    workspace = base / "leased-task"
    workspace.mkdir()
    task_id = uuid4()
    project_id = uuid4()
    claimed_task = {
        "id": task_id,
        "project_id": project_id,
        "provider": "codex",
        "workspace_path": str(workspace),
        "user_prompt": "Do old work",
        "mcp_config_json": {"servers": {}},
        "env_json": {},
        "status": "running",
        "metadata_json": {
            "scheduler_lease": {
                "worker_id": "worker-a",
                "lease_id": "old-lease",
            }
        },
        **_now_row(),
    }
    fake_db.coding_tasks[task_id] = {
        **claimed_task,
        "status": "running",
        "metadata_json": {
            "scheduler_lease": {
                "worker_id": "worker-a",
                "lease_id": "new-lease",
            }
        },
    }

    result = await orchestrator.run_codex_task(
        task_id,
        provider=FakeProvider([CodingAgentEvent(type="status", status="completed")]),
        preclaimed=True,
        claimed_task=claimed_task,
    )

    assert fake_db.coding_tasks[task_id]["status"] == "running"
    assert fake_db.coding_tasks[task_id]["metadata_json"]["scheduler_lease"]["lease_id"] == "new-lease"
    assert result.task["metadata_json"]["scheduler_lease"]["lease_id"] == "new-lease"


@pytest.mark.asyncio
async def test_run_codex_task_persists_provider_failure_without_reraising(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from apps.worker.production import orchestrator

    fake_db = FakeProductionDb()
    monkeypatch.setattr(orchestrator, "db", fake_db)
    base = _set_workspace_base(monkeypatch, tmp_path)
    workspace = base / "codex-task"
    workspace.mkdir()
    task_id = uuid4()
    fake_db.coding_tasks[task_id] = {
        "id": task_id,
        "project_id": uuid4(),
        "run_id": None,
        "provider_session_id": None,
        "workspace_path": str(workspace),
        "user_prompt": "Do the work",
        "status": "queued",
        "env_json": {},
        "mcp_config_json": {},
        "extra_args": [],
        "custom_args": [],
        **_now_row(),
    }

    result = await orchestrator.run_codex_task(task_id, provider=ExplodingProvider())

    final_update = fake_db.coding_task_updates[-1][1]
    assert final_update["status"] == "failed"
    assert final_update["failure_reason"] == "provider_error"
    assert "codex crashed" in final_update["failure_detail"]
    assert result.status == "failed"
    assert result.failure_reason == "provider_error"


@pytest.mark.asyncio
async def test_run_codex_task_requires_existing_task_and_workspace(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from apps.worker.production import orchestrator

    fake_db = FakeProductionDb()
    monkeypatch.setattr(orchestrator, "db", fake_db)
    _set_workspace_base(monkeypatch, tmp_path)
    missing_id = uuid4()

    with pytest.raises(ValueError, match=f"Coding task not found: {missing_id}"):
        await orchestrator.run_codex_task(missing_id, provider=FakeProvider([]))

    task_id = uuid4()
    fake_db.coding_tasks[task_id] = {
        "id": task_id,
        "project_id": uuid4(),
        "user_prompt": "Do the work",
        "workspace_path": None,
        **_now_row(),
    }
    result = await orchestrator.run_codex_task(task_id, provider=FakeProvider([]))

    final_update = fake_db.coding_task_updates[-1][1]
    assert final_update["status"] == "failed"
    assert final_update["failure_reason"] == "workspace_unavailable"
    assert result.status == "failed"


@pytest.mark.asyncio
async def test_run_codex_task_rejects_non_empty_mcp_config_before_provider_call(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from apps.worker.production import orchestrator

    fake_db = FakeProductionDb()
    monkeypatch.setattr(orchestrator, "db", fake_db)
    base = _set_workspace_base(monkeypatch, tmp_path)
    workspace = base / "codex-task"
    workspace.mkdir()
    task_id = uuid4()
    fake_db.coding_tasks[task_id] = {
        "id": task_id,
        "project_id": uuid4(),
        "workspace_path": str(workspace),
        "user_prompt": "Do the work",
        "env_json": {},
        "mcp_config_json": {"servers": {"filesystem": {"command": "node"}}},
        "extra_args": [],
        "custom_args": [],
        **_now_row(),
    }
    provider = FakeProvider([])

    result = await orchestrator.run_codex_task(task_id, provider=provider)

    assert provider.calls == []
    assert result.status == "failed"
    assert result.failure_reason == "unsupported_mcp_config"
    assert fake_db.coding_task_updates[-1][1]["status"] == "failed"


@pytest.mark.asyncio
async def test_run_codex_task_marks_workspace_escape_as_failed_before_provider_call(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from apps.worker.production import orchestrator

    fake_db = FakeProductionDb()
    monkeypatch.setattr(orchestrator, "db", fake_db)
    _set_workspace_base(monkeypatch, tmp_path)
    task_id = uuid4()
    fake_db.coding_tasks[task_id] = {
        "id": task_id,
        "project_id": uuid4(),
        "workspace_path": str(tmp_path / "outside"),
        "user_prompt": "Do the work",
        "env_json": {},
        "mcp_config_json": {},
        "extra_args": [],
        "custom_args": [],
        **_now_row(),
    }
    provider = FakeProvider([])

    result = await orchestrator.run_codex_task(task_id, provider=provider)

    assert provider.calls == []
    assert result.status == "failed"
    assert result.failure_reason == "workspace_path_escaped"
    assert "workspace_path escapes workspace root" in (result.failure_detail or "")


@pytest.mark.asyncio
async def test_create_manifest_jobs_expands_manifest_into_pending_local_jobs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.worker.production import orchestrator

    fake_db = FakeProductionDb()
    monkeypatch.setattr(orchestrator, "db", fake_db)
    manifest_id = uuid4()
    plan_id = uuid4()
    project_id = uuid4()
    fake_db.manifests[manifest_id] = {
        "id": manifest_id,
        "experiment_plan_id": plan_id,
        "project_id": project_id,
        "status": "accepted",
        "manifest_json": {
            "project": "demo",
            "workspace": "workspace",
            "phases": [
                {
                    "name": "sanity",
                    "jobs": [
                        {
                            "name": "smoke",
                            "cmd": "python train.py",
                            "cwd": "experiments/smoke",
                            "expected_outputs": ["metrics.json"],
                            "timeout_sec": 33,
                            "retry": {"max_attempts": 2},
                        }
                    ],
                }
            ],
        },
    }

    jobs = await orchestrator.create_manifest_jobs(manifest_id)

    assert len(jobs) == 1
    payload = fake_db.created_experiment_jobs[0]
    assert payload["manifest_id"] == manifest_id
    assert payload["experiment_plan_id"] == plan_id
    assert payload["project_id"] == project_id
    assert payload["phase_name"] == "sanity"
    assert payload["job_name"] == "smoke"
    assert payload["executor_type"] == "local"
    assert payload["status"] == "pending"
    assert payload["expected_outputs_json"] == ["metrics.json"]
    assert payload["max_attempts"] == 2
    assert payload["metrics_json"]["timeout_sec"] == 33
    assert payload["metrics_json"]["phase_dependencies"] == []


@pytest.mark.asyncio
async def test_create_manifest_jobs_rejects_unaccepted_manifest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.worker.production import orchestrator

    fake_db = FakeProductionDb()
    monkeypatch.setattr(orchestrator, "db", fake_db)
    manifest_id = uuid4()
    fake_db.manifests[manifest_id] = {
        "id": manifest_id,
        "experiment_plan_id": uuid4(),
        "project_id": uuid4(),
        "status": "draft",
        "manifest_json": {"phases": []},
    }

    with pytest.raises(ValueError, match="accepted manifest"):
        await orchestrator.create_manifest_jobs(manifest_id)

    assert fake_db.created_experiment_jobs == []


@pytest.mark.asyncio
async def test_create_manifest_jobs_can_expand_ssh_jobs_with_phase_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.worker.production import orchestrator

    fake_db = FakeProductionDb()
    monkeypatch.setattr(orchestrator, "db", fake_db)
    manifest_id = uuid4()
    plan_id = uuid4()
    project_id = uuid4()
    remote_host_id = uuid4()
    owner_user_id = uuid4()
    fake_db.projects[project_id] = {"id": project_id, "owner_user_id": owner_user_id}
    fake_db.remote_hosts = {
        remote_host_id: {
            "id": remote_host_id,
            "owner_user_id": owner_user_id,
            "host": "gpu.example.test",
            "port": 22,
            "auth_type": "agent",
        }
    }
    fake_db.manifests[manifest_id] = {
        "id": manifest_id,
        "experiment_plan_id": plan_id,
        "project_id": project_id,
        "status": "accepted",
        "manifest_json": {
            "project": "demo",
            "workspace": "workspace",
            "resources": {
                "local_first": False,
                "remote_host_id": str(remote_host_id),
                "max_parallel": 1,
            },
            "phases": [
                {
                    "name": "sanity",
                    "jobs": [{"name": "smoke", "cmd": "python smoke.py"}],
                },
                {
                    "name": "full",
                    "depends_on": ["sanity"],
                    "jobs": [
                        {
                            "name": "main",
                            "cmd": "python train.py",
                            "expected_outputs": ["metrics.json"],
                            "retry": {"max_attempts": 3, "oom_retry": True},
                        }
                    ],
                },
            ],
        },
    }

    await orchestrator.create_manifest_jobs(manifest_id)

    first, second = fake_db.created_experiment_jobs
    assert first["executor_type"] == "ssh"
    assert first["remote_host_id"] == remote_host_id
    assert first["metrics_json"]["phase_dependencies"] == []
    assert second["executor_type"] == "ssh"
    assert second["remote_host_id"] == remote_host_id
    assert second["max_attempts"] == 3
    assert second["metrics_json"]["oom_retry"] is True
    assert second["metrics_json"]["phase_dependencies"] == ["sanity"]


@pytest.mark.asyncio
async def test_create_manifest_jobs_rejects_ssh_remote_host_owned_by_another_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.worker.production import orchestrator

    fake_db = FakeProductionDb()
    monkeypatch.setattr(orchestrator, "db", fake_db)
    manifest_id = uuid4()
    plan_id = uuid4()
    project_id = uuid4()
    remote_host_id = uuid4()
    owner_id = uuid4()
    fake_db.projects[project_id] = {
        "id": project_id,
        "owner_user_id": owner_id,
        **_now_row(),
    }
    fake_db.remote_hosts = {
        remote_host_id: {
            "id": remote_host_id,
            "owner_user_id": uuid4(),
        }
    }
    fake_db.manifests[manifest_id] = {
        "id": manifest_id,
        "experiment_plan_id": plan_id,
        "project_id": project_id,
        "status": "accepted",
        "manifest_json": {
            "project": "demo",
            "workspace": "workspace",
            "resources": {
                "local_first": False,
                "remote_host_id": str(remote_host_id),
            },
            "phases": [
                {"name": "sanity", "jobs": [{"name": "smoke", "cmd": "python smoke.py"}]},
            ],
        },
    }

    with pytest.raises(ValueError, match="Remote host access denied"):
        await orchestrator.create_manifest_jobs(manifest_id)

    assert fake_db.created_experiment_jobs == []


@pytest.mark.asyncio
async def test_create_manifest_jobs_requires_existing_manifest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.worker.production import orchestrator

    fake_db = FakeProductionDb()
    monkeypatch.setattr(orchestrator, "db", fake_db)
    manifest_id = uuid4()

    with pytest.raises(ValueError, match=f"Experiment manifest not found: {manifest_id}"):
        await orchestrator.create_manifest_jobs(manifest_id)


@pytest.mark.asyncio
async def test_run_local_job_resolves_paths_and_persists_result_metrics(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from apps.worker.production import orchestrator

    fake_db = FakeProductionDb()
    monkeypatch.setattr(orchestrator, "db", fake_db)
    base = _set_workspace_base(monkeypatch, tmp_path)
    workspace = base / "workspace"
    job_cwd = workspace / "experiments" / "smoke"
    job_cwd.mkdir(parents=True)
    job_id = uuid4()
    project_id = uuid4()
    fake_db.projects[project_id] = {
        "id": project_id,
        "default_workspace_path": str(workspace),
        **_now_row(),
    }
    fake_db.experiment_jobs[job_id] = {
        "id": job_id,
        "manifest_id": uuid4(),
        "experiment_plan_id": uuid4(),
        "project_id": project_id,
        "phase_name": "sanity",
        "job_name": "smoke",
        "cmd": "python train.py",
        "cwd": "experiments/smoke",
        "expected_outputs_json": ["metrics.json", "plot.png"],
        "metrics_json": {"timeout_sec": 44},
        "status": "pending",
        **_now_row(),
    }
    executor = FakeLocalExecutor()

    result = await orchestrator.run_local_job(job_id, executor=executor)

    spec = executor.specs[0]
    assert spec.job_id == str(job_id)
    assert spec.cwd == job_cwd.resolve()
    assert spec.command == "python train.py"
    assert spec.log_dir == (workspace / ".research-os" / "jobs" / str(job_id) / "logs").resolve()
    assert spec.expected_outputs == [Path("metrics.json"), Path("plot.png")]
    assert spec.timeout_sec == 44
    assert fake_db.experiment_job_updates[0][1]["status"] == "running"
    assert fake_db.experiment_job_updates[0][1]["started_at"].tzinfo is timezone.utc
    final_update = fake_db.experiment_job_updates[-1][1]
    assert final_update["status"] == "completed"
    assert final_update["stdout_log_path"].endswith("stdout.log")
    assert final_update["stderr_log_path"].endswith("stderr.log")
    assert final_update["artifact_dir"] == str(job_cwd.resolve())
    assert final_update["metrics_json"]["returncode"] == 0
    assert final_update["metrics_json"]["expected_outputs_found"] == [str(job_cwd / "metrics.json")]
    assert final_update["metrics_json"]["missing_expected_outputs"] == [str(job_cwd / "plot.png")]
    assert result.row["status"] == "completed"
    assert result.result.status == "completed"


@pytest.mark.asyncio
async def test_run_local_job_skips_research_side_effects_after_lease_changes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from apps.worker.production import orchestrator

    fake_db = FakeProductionDb()
    monkeypatch.setattr(orchestrator, "db", fake_db)
    base = _set_workspace_base(monkeypatch, tmp_path)
    workspace = base / "workspace"
    job_cwd = workspace / "experiments" / "smoke"
    job_cwd.mkdir(parents=True)
    job_id = uuid4()
    project_id = uuid4()
    plan_id = uuid4()
    fake_db.projects[project_id] = {
        "id": project_id,
        "default_workspace_path": str(workspace),
        **_now_row(),
    }
    claimed_job = {
        "id": job_id,
        "manifest_id": uuid4(),
        "experiment_plan_id": plan_id,
        "project_id": project_id,
        "phase_name": "sanity",
        "job_name": "smoke",
        "cmd": "python train.py",
        "cwd": "experiments/smoke",
        "expected_outputs_json": ["metrics.json"],
        "metrics_json": {
            "scheduler_lease": {
                "worker_id": "worker-a",
                "lease_id": "old-lease",
            }
        },
        "status": "running",
        **_now_row(),
    }
    fake_db.experiment_jobs[job_id] = {
        **claimed_job,
        "metrics_json": {
            "scheduler_lease": {
                "worker_id": "worker-a",
                "lease_id": "new-lease",
            }
        },
    }
    result = LocalJobResult(
        job_id=str(job_id),
        status="failed",
        returncode=1,
        stdout_log=job_cwd / "stdout.log",
        stderr_log=job_cwd / "stderr.log",
        expected_outputs_found=[],
        missing_expected_outputs=[Path("metrics.json")],
        failure_reason="failed",
        duration_ms=5,
    )

    run = await orchestrator.run_local_job(
        job_id,
        executor=FakeLocalExecutor(result),
        preclaimed=True,
        claimed_job=claimed_job,
    )

    assert run.row["metrics_json"]["scheduler_lease"]["lease_id"] == "new-lease"
    assert fake_db.created_query_packs == []
    assert fake_db.created_coding_tasks == []
    assert fake_db.created_manifests == []
    assert fake_db.created_code_artifacts == []


@pytest.mark.asyncio
async def test_run_local_job_rejects_cwd_that_escapes_workspace(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from apps.worker.production import orchestrator

    fake_db = FakeProductionDb()
    monkeypatch.setattr(orchestrator, "db", fake_db)
    base = _set_workspace_base(monkeypatch, tmp_path)
    project_id = uuid4()
    fake_db.projects[project_id] = {
        "id": project_id,
        "default_workspace_path": str(base / "workspace"),
        **_now_row(),
    }
    job_id = uuid4()
    fake_db.experiment_jobs[job_id] = {
        "id": job_id,
        "project_id": project_id,
        "cmd": "python train.py",
        "cwd": "../outside",
        "expected_outputs_json": [],
        "metrics_json": {},
        **_now_row(),
    }

    with pytest.raises(ValueError, match="cwd escapes workspace_root"):
        await orchestrator.run_local_job(job_id, executor=FakeLocalExecutor())


@pytest.mark.asyncio
async def test_run_local_job_rejects_default_log_dir_symlink_escape(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from apps.worker.production import orchestrator

    fake_db = FakeProductionDb()
    monkeypatch.setattr(orchestrator, "db", fake_db)
    base = _set_workspace_base(monkeypatch, tmp_path)
    workspace = base / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    (workspace / ".research-os").symlink_to(outside, target_is_directory=True)
    job_id = uuid4()
    project_id = uuid4()
    fake_db.projects[project_id] = {
        "id": project_id,
        "default_workspace_path": str(workspace),
        **_now_row(),
    }
    fake_db.experiment_jobs[job_id] = {
        "id": job_id,
        "project_id": project_id,
        "cmd": "python train.py",
        "cwd": ".",
        "expected_outputs_json": [],
        "metrics_json": {},
        **_now_row(),
    }

    with pytest.raises(ValueError, match="log_dir escapes workspace_root"):
        await orchestrator.run_local_job(job_id, executor=FakeLocalExecutor())


@pytest.mark.asyncio
async def test_run_local_job_persists_executor_error_without_reraising(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from apps.worker.production import orchestrator

    fake_db = FakeProductionDb()
    monkeypatch.setattr(orchestrator, "db", fake_db)
    monkeypatch.setattr(
        orchestrator,
        "_search_library_for_experiment_failure",
        AsyncMock(return_value=[
            {
                "id": str(uuid4()),
                "title": "OOM-aware training stabilization",
                "methods": ["gradient accumulation"],
            }
        ]),
        raising=False,
    )
    base = _set_workspace_base(monkeypatch, tmp_path)
    workspace = base / "workspace"
    workspace.mkdir()
    job_id = uuid4()
    project_id = uuid4()
    fake_db.projects[project_id] = {
        "id": project_id,
        "default_workspace_path": str(workspace),
        **_now_row(),
    }
    fake_db.experiment_jobs[job_id] = {
        "id": job_id,
        "project_id": project_id,
        "manifest_id": uuid4(),
        "experiment_plan_id": uuid4(),
        "phase_name": "full",
        "job_name": "main",
        "cmd": "python train.py",
        "cwd": ".",
        "expected_outputs_json": [],
        "metrics_json": {},
        "status": "pending",
        **_now_row(),
    }

    result = await orchestrator.run_local_job(job_id, executor=ExplodingLocalExecutor())

    final_update = fake_db.experiment_job_updates[-1][1]
    assert final_update["status"] == "failed"
    assert final_update["failure_reason"] == "executor_error"
    assert final_update["metrics_json"]["returncode"] is None
    assert "process launcher failed" in final_update["metrics_json"]["error"]
    assert result.row["status"] == "failed"
    assert fake_db.created_query_packs[0]["query_pack_json"]["stage"] == "experiment_research"
    assert fake_db.created_query_packs[0]["query_pack_json"]["failure_reason"] == "executor_error"
    assert fake_db.created_query_packs[0]["query_pack_json"]["library_results"][0]["title"] == "OOM-aware training stabilization"
    assert fake_db.created_manifests[0]["manifest_version"].startswith("repair-")
    assert fake_db.created_manifests[0]["status"] == "accepted"
    assert fake_db.created_manifests[0]["manifest_json"]["phases"][0]["name"].startswith("repair-")
    assert fake_db.created_code_artifacts[0]["artifact_type"] == "review_report"
    assert not Path(fake_db.created_code_artifacts[0]["path"]).is_absolute()
    assert (workspace / fake_db.created_code_artifacts[0]["path"]).is_file()
    assert fake_db.created_coding_tasks[0]["thread_name"] == f"experiment-research-{job_id}"
    assert fake_db.created_coding_tasks[0]["metadata_json"]["stage"] == "experiment_research"
    assert "process launcher failed" in fake_db.created_coding_tasks[0]["user_prompt"]


@pytest.mark.asyncio
async def test_generate_claims_from_results_parses_metrics_logs_and_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from apps.worker.production import orchestrator

    fake_db = FakeProductionDb()
    monkeypatch.setattr(orchestrator, "db", fake_db)
    base = _set_workspace_base(monkeypatch, tmp_path)
    project_id = uuid4()
    plan_id = uuid4()
    completed_job_id = uuid4()
    failed_job_id = uuid4()
    workspace = base / "project"
    workspace.mkdir()
    metrics_path = workspace / "metrics.json"
    metrics_path.write_text(
        json.dumps({
            "accuracy": 0.91,
            "baseline_accuracy": 0.82,
            "f1": 0.88,
            "loss": 0.2,
        }),
        encoding="utf-8",
    )
    outside_metrics_path = tmp_path / "outside-metrics.json"
    outside_metrics_path.write_text(json.dumps({"secret_accuracy": 999}), encoding="utf-8")
    stdout_path = workspace / ".research-os" / "jobs" / str(completed_job_id) / "logs" / "stdout.log"
    stdout_path.parent.mkdir(parents=True)
    stdout_path.write_text("accuracy=0.91 baseline_accuracy=0.82 saved metrics.json\n", encoding="utf-8")
    artifact_path = workspace / "plots" / "curve.png"
    artifact_path.parent.mkdir()
    artifact_path.write_bytes(b"png")
    fake_db.projects[project_id] = {
        "id": project_id,
        "default_workspace_path": str(workspace),
        **_now_row(),
    }
    fake_db.code_artifacts.append({
        "id": uuid4(),
        "project_id": project_id,
        "experiment_plan_id": plan_id,
        "artifact_type": "test_output",
        "path": "plots/curve.png",
        "validation_status": "passed",
        "summary": "learning curve",
        **_now_row(),
    })
    fake_db.experiment_jobs[completed_job_id] = {
        "id": completed_job_id,
        "project_id": project_id,
        "experiment_plan_id": plan_id,
        "phase_name": "sanity",
        "job_name": "smoke",
        "status": "completed",
        "metrics_json": {
            "returncode": 0,
            "expected_outputs_found": ["metrics.json", str(outside_metrics_path)],
            "missing_expected_outputs": [],
        },
        "stdout_log_path": str(stdout_path),
        "artifact_dir": str(workspace),
        **_now_row(),
    }
    fake_db.experiment_jobs[failed_job_id] = {
        "id": failed_job_id,
        "project_id": project_id,
        "experiment_plan_id": plan_id,
        "phase_name": "full",
        "job_name": "ablation",
        "status": "failed",
        "failure_reason": "timeout",
        "metrics_json": {"returncode": 124},
        **_now_row(),
    }

    result = await orchestrator.generate_claims_from_results(plan_id, project_id=project_id)

    assert len(result.claims) >= 3
    assert fake_db.claim_entries[0]["status"] == "supported"
    assert fake_db.claim_entries[0]["support_level"] == 1.0
    assert any("accuracy" in claim["claim_text"] and "0.91" in claim["claim_text"] for claim in fake_db.claim_entries)
    assert not any("secret_accuracy" in claim["claim_text"] for claim in fake_db.claim_entries)
    assert any("learning curve" in (claim["evidence_summary"] or "") for claim in fake_db.claim_entries)
    assert any(claim["status"] == "unsupported" for claim in fake_db.claim_entries)
    assert fake_db.claim_evidence[0]["source_type"] == "experiment_job"
    assert fake_db.claim_evidence[0]["source_id"] == completed_job_id


@pytest.mark.asyncio
async def test_prepare_manuscript_and_gate_submission_write_files_and_full_audits(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from apps.worker.production import orchestrator

    fake_db = FakeProductionDb()
    monkeypatch.setattr(orchestrator, "db", fake_db)
    base = _set_workspace_base(monkeypatch, tmp_path)
    project_id = uuid4()
    manuscript_id = uuid4()
    submission_id = uuid4()
    workspace = base / "project"
    workspace.mkdir()
    artifact = workspace / "plots" / "main.pdf"
    artifact.parent.mkdir()
    artifact.write_bytes(b"%PDF-1.4")
    fake_db.projects[project_id] = {
        "id": project_id,
        "default_workspace_path": str(workspace),
        **_now_row(),
    }
    fake_db.claim_entries.extend([
        {
            "id": uuid4(),
            "project_id": project_id,
            "experiment_plan_id": uuid4(),
            "claim_text": "Main metric improves",
            "status": "supported",
            "support_level": 0.91,
            **_now_row(),
        },
    ])
    fake_db.code_artifacts.append({
        "id": uuid4(),
        "project_id": project_id,
        "experiment_plan_id": None,
        "artifact_type": "test_output",
        "path": "plots/main.pdf",
        "validation_status": "passed",
        "summary": "main result figure",
        **_now_row(),
    })
    fake_db.manuscripts[manuscript_id] = {
        "id": manuscript_id,
        "project_id": project_id,
        "title": "Paper",
        "status": "outline",
        **_now_row(),
    }
    fake_db.submissions[submission_id] = {
        "id": submission_id,
        "manuscript_package_id": manuscript_id,
        "venue": "ICLR",
        "status": "preparing",
        "checklist_json": {"required_files": ["paper.md", "claims_snapshot.json", "artifact_snapshot.json"]},
        "anonymity_report_json": {"passed": True, "issues": []},
        "compile_report_json": {"passed": True, "outputs": ["paper.md"]},
        "claim_audit_report_json": {},
        "citation_audit_report_json": {"passed": True, "missing_citations": []},
        **_now_row(),
    }

    manuscript = await orchestrator.prepare_manuscript_drafting(manuscript_id)
    submission = await orchestrator.gate_submission_package(submission_id)

    paper_dir = Path(fake_db.manuscript_updates[-1][1]["paper_dir"])
    assert not paper_dir.is_absolute()
    paper_dir = workspace / paper_dir
    assert manuscript["status"] == "drafting"
    assert (paper_dir / "paper.md").read_text(encoding="utf-8").startswith("# Paper")
    assert (paper_dir / "claims_snapshot.json").exists()
    assert (paper_dir / "artifact_snapshot.json").exists()
    assert (paper_dir / "bib_snapshot.json").exists()
    assert fake_db.manuscript_updates[-1][1]["claim_ledger_snapshot_id"] == fake_db.claim_entries[0]["id"]
    assert fake_db.manuscript_updates[-1][1]["artifact_snapshot_id"] == fake_db.code_artifacts[0]["id"]
    assert fake_db.manuscript_updates[-1][1]["bib_snapshot_id"] is not None
    assert submission["status"] == "ready"
    update = fake_db.submission_updates[-1][1]
    assert update["claim_audit_report_json"]["unsupported_claims"] == 0
    assert update["compile_report_json"]["passed"] is True
    assert update["anonymity_report_json"]["passed"] is True
    assert update["citation_audit_report_json"]["passed"] is True
    assert update["checklist_json"]["missing_required_files"] == []
    assert fake_db.created_coding_tasks[-1]["thread_name"] == f"manuscript-writing-{manuscript_id}"
    assert fake_db.created_coding_tasks[-1]["metadata_json"]["stage"] == "manuscript_writing"


@pytest.mark.asyncio
async def test_prepare_manuscript_skips_duplicate_active_writer_task(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from apps.worker.production import orchestrator

    fake_db = FakeProductionDb()
    monkeypatch.setattr(orchestrator, "db", fake_db)
    base = _set_workspace_base(monkeypatch, tmp_path)
    project_id = uuid4()
    manuscript_id = uuid4()
    workspace = base / "project"
    workspace.mkdir()
    fake_db.projects[project_id] = {"id": project_id, "default_workspace_path": str(workspace), **_now_row()}
    fake_db.manuscripts[manuscript_id] = {
        "id": manuscript_id,
        "project_id": project_id,
        "title": "Paper",
        "status": "outline",
        **_now_row(),
    }
    fake_db.coding_tasks[uuid4()] = {
        "id": uuid4(),
        "project_id": project_id,
        "status": "queued",
        "metadata_json": {
            "stage": "manuscript_writing",
            "manuscript_id": str(manuscript_id),
        },
        **_now_row(),
    }

    await orchestrator.prepare_manuscript_drafting(manuscript_id)

    assert fake_db.created_coding_tasks == []


@pytest.mark.asyncio
async def test_submission_gate_runs_automatic_audits_without_external_reports(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from apps.worker.production import orchestrator

    fake_db = FakeProductionDb()
    monkeypatch.setattr(orchestrator, "db", fake_db)
    base = _set_workspace_base(monkeypatch, tmp_path)
    project_id = uuid4()
    manuscript_id = uuid4()
    submission_id = uuid4()
    workspace = base / "project"
    paper_dir = workspace / "manuscripts" / str(manuscript_id)
    paper_dir.mkdir(parents=True)
    (paper_dir / "paper.md").write_text("# Paper\nCited claim [1].\n", encoding="utf-8")
    (paper_dir / "claims_snapshot.json").write_text("[]", encoding="utf-8")
    (paper_dir / "artifact_snapshot.json").write_text("[]", encoding="utf-8")
    fake_db.projects[project_id] = {
        "id": project_id,
        "default_workspace_path": str(workspace),
        **_now_row(),
    }
    fake_db.claim_entries.append({
        "id": uuid4(),
        "project_id": project_id,
        "experiment_plan_id": uuid4(),
        "claim_text": "Main metric improves",
        "status": "supported",
        "support_level": 0.91,
        **_now_row(),
    })
    fake_db.manuscripts[manuscript_id] = {
        "id": manuscript_id,
        "project_id": project_id,
        "title": "Paper",
        "paper_dir": str(paper_dir),
        "status": "drafting",
        **_now_row(),
    }
    fake_db.submissions[submission_id] = {
        "id": submission_id,
        "manuscript_package_id": manuscript_id,
        "venue": "ICLR",
        "status": "preparing",
        "checklist_json": {"required_files": ["paper.md", "claims_snapshot.json", "artifact_snapshot.json"]},
        "anonymity_report_json": {},
        "compile_report_json": {},
        "claim_audit_report_json": {},
        "citation_audit_report_json": {},
        "artifact_provenance_report_json": {},
        **_now_row(),
    }

    submission = await orchestrator.gate_submission_package(submission_id)

    assert submission["status"] == "ready"
    update = fake_db.submission_updates[-1][1]
    assert update["compile_report_json"]["passed"] is True
    assert update["compile_report_json"]["auto_checked"] is True
    assert update["compile_report_json"]["missing_external_report"] is False
    assert update["anonymity_report_json"]["passed"] is True
    assert update["anonymity_report_json"]["auto_checked"] is True
    assert update["citation_audit_report_json"]["passed"] is True
    assert update["citation_audit_report_json"]["auto_checked"] is True
    assert fake_db.created_coding_tasks == []
    gate_report = json.loads((paper_dir / "SUBMISSION_GATE_REPORT.json").read_text(encoding="utf-8"))
    assert gate_report["status"] == "ready"
    assert gate_report["reports"]["compile_report_json"]["passed"] is True


@pytest.mark.asyncio
async def test_submission_gate_skips_duplicate_active_revision_task(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from apps.worker.production import orchestrator

    fake_db = FakeProductionDb()
    monkeypatch.setattr(orchestrator, "db", fake_db)
    base = _set_workspace_base(monkeypatch, tmp_path)
    project_id = uuid4()
    manuscript_id = uuid4()
    submission_id = uuid4()
    workspace = base / "project"
    paper_dir = workspace / "manuscripts" / str(manuscript_id)
    paper_dir.mkdir(parents=True)
    (paper_dir / "paper.md").write_text("# Paper\n", encoding="utf-8")
    fake_db.projects[project_id] = {"id": project_id, "default_workspace_path": str(workspace), **_now_row()}
    fake_db.manuscripts[manuscript_id] = {
        "id": manuscript_id,
        "project_id": project_id,
        "title": "Paper",
        "paper_dir": str(paper_dir),
        "status": "reviewing",
        **_now_row(),
    }
    fake_db.submissions[submission_id] = {
        "id": submission_id,
        "manuscript_package_id": manuscript_id,
        "venue": "ICLR",
        "status": "preparing",
        "checklist_json": {"required_files": ["paper.md", "claims_snapshot.json"]},
        "anonymity_report_json": {},
        "compile_report_json": {},
        "claim_audit_report_json": {},
        "citation_audit_report_json": {},
        "artifact_provenance_report_json": {},
        **_now_row(),
    }
    fake_db.coding_tasks[uuid4()] = {
        "id": uuid4(),
        "project_id": project_id,
        "status": "running",
        "metadata_json": {
            "stage": "submission_revision",
            "submission_id": str(submission_id),
        },
        **_now_row(),
    }

    submission = await orchestrator.gate_submission_package(submission_id)

    assert submission["status"] == "gated"
    assert fake_db.created_coding_tasks == []


@pytest.mark.asyncio
async def test_submission_revision_task_reruns_submission_gate_after_completion(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from apps.worker.production import orchestrator

    fake_db = FakeProductionDb()
    monkeypatch.setattr(orchestrator, "db", fake_db)
    base = _set_workspace_base(monkeypatch, tmp_path)
    project_id = uuid4()
    manuscript_id = uuid4()
    submission_id = uuid4()
    task_id = uuid4()
    workspace = base / "project"
    paper_dir = workspace / "manuscripts" / str(manuscript_id)
    paper_dir.mkdir(parents=True)
    (paper_dir / "paper.md").write_text("# Paper\nCited claim [1].\n", encoding="utf-8")
    (paper_dir / "claims_snapshot.json").write_text("[]", encoding="utf-8")
    (paper_dir / "artifact_snapshot.json").write_text("[]", encoding="utf-8")
    fake_db.projects[project_id] = {
        "id": project_id,
        "default_workspace_path": str(workspace),
        **_now_row(),
    }
    fake_db.claim_entries.append({
        "id": uuid4(),
        "project_id": project_id,
        "experiment_plan_id": uuid4(),
        "claim_text": "Main metric improves",
        "status": "supported",
        "support_level": 0.91,
        **_now_row(),
    })
    fake_db.manuscripts[manuscript_id] = {
        "id": manuscript_id,
        "project_id": project_id,
        "title": "Paper",
        "paper_dir": str(paper_dir),
        "status": "drafting",
        **_now_row(),
    }
    fake_db.submissions[submission_id] = {
        "id": submission_id,
        "manuscript_package_id": manuscript_id,
        "venue": "ICLR",
        "status": "gated",
        "checklist_json": {
            "required_files": ["paper.md", "claims_snapshot.json", "artifact_snapshot.json"],
        },
        "anonymity_report_json": {},
        "compile_report_json": {},
        "claim_audit_report_json": {},
        "citation_audit_report_json": {},
        "artifact_provenance_report_json": {},
        **_now_row(),
    }
    fake_db.coding_tasks[task_id] = {
        "id": task_id,
        "project_id": project_id,
        "run_id": None,
        "provider_session_id": None,
        "workspace_path": str(paper_dir),
        "user_prompt": "Revise submission",
        "status": "queued",
        "env_json": {},
        "mcp_config_json": {},
        "extra_args": [],
        "custom_args": [],
        "metadata_json": {
            "stage": "submission_revision",
            "submission_id": str(submission_id),
        },
        **_now_row(),
    }

    result = await orchestrator.run_codex_task(
        task_id,
        provider=FakeProvider([CodingAgentEvent(type="status", status="completed")]),
    )

    assert result.status == "completed"
    assert fake_db.submission_updates[-1][1]["status"] == "ready"
    gate_report = json.loads((paper_dir / "SUBMISSION_GATE_REPORT.json").read_text(encoding="utf-8"))
    assert gate_report["status"] == "ready"
