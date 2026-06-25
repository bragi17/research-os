"""Tests for automated research production API routes."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.app import create_app
from libs.schemas.production import (
    ClaimLedgerCreate,
    CodeArtifactCreate,
    CodingEventCreate,
    CodingTaskCreate,
    ExperimentJobCreate,
    ExperimentManifestCreate,
    ManuscriptPackageCreate,
    ProjectCreate,
    RemoteHostCreate,
    SubmissionPackageCreate,
    TerminalSessionCreate,
)

TEST_USER_ID = UUID("00000000-0000-0000-0000-000000000001")
TEST_USER = {
    "id": TEST_USER_ID,
    "email": "tester@example.test",
    "username": "tester",
    "role": "admin",
    "workspace_id": UUID("00000000-0000-0000-0000-000000000002"),
}


class FakeWebSocket:
    def __init__(
        self,
        query_string: str = "",
        headers: dict[str, str] | None = None,
        incoming_texts: list[str] | None = None,
    ) -> None:
        self.scope = {
            "query_string": query_string.encode(),
            "headers": [(key.lower().encode(), value.encode()) for key, value in (headers or {}).items()],
        }
        self.accepted = False
        self.closed: tuple[int | None, str | None] | None = None
        self.sent: list[dict[str, object]] = []
        self.incoming_texts = list(incoming_texts or [])

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, payload: dict[str, object]) -> None:
        self.sent.append(payload)

    async def close(self, code: int | None = None, reason: str | None = None) -> None:
        self.closed = (code, reason)

    async def receive_text(self) -> str:
        if self.incoming_texts:
            return self.incoming_texts.pop(0)
        from starlette.websockets import WebSocketDisconnect

        raise WebSocketDisconnect()


@pytest.fixture
def authed_app() -> FastAPI:
    import apps.api.routes_production as routes_production

    app = FastAPI()
    app.include_router(routes_production.router)
    app.dependency_overrides[routes_production.require_production_user] = lambda: TEST_USER
    return app


def test_app_includes_production_router_paths() -> None:
    import apps.api.routes_production as routes_production

    app = create_app()
    paths = {route.path for route in app.routes}

    assert routes_production.router.dependencies == []
    assert "/api/v1/production/projects" in paths
    assert "/api/v1/production/projects/{project_id}" in paths
    assert "/api/v1/production/coding-tasks" in paths
    assert "/api/v1/production/coding-tasks/{task_id}/events" in paths
    assert "/api/v1/production/code-artifacts" in paths
    assert "/api/v1/production/manuscripts" in paths
    assert "/api/v1/production/submissions" in paths
    assert "/api/v1/production/agent-runtimes" in paths
    assert "/api/v1/production/agent-runtimes/detect" in paths
    assert "/api/v1/production/experiment-manifests/{manifest_id}/jobs/expand" in paths
    assert "/api/v1/production/experiment-jobs/{job_id}/run-local" in paths
    assert "/api/v1/production/experiment-jobs/{job_id}/logs/{stream_name}" in paths
    assert "/api/v1/production/experiment-jobs/{job_id}/artifacts" in paths
    assert "/api/v1/production/experiment-plans/{plan_id}/claims/generate" in paths
    assert "/api/v1/production/coding-tasks/{task_id}/run" in paths
    assert "/api/v1/production/workspaces/tree" in paths
    assert "/api/v1/production/workspaces/file" in paths
    assert "/api/v1/production/terminal/sessions" in paths
    assert "/api/v1/production/terminal/sessions/{session_id}" in paths
    assert "/api/v1/production/terminal/sessions/{session_id}/resize" in paths
    assert "/api/v1/production/terminal/sessions/{session_id}/close" in paths
    assert "/api/v1/production/terminal/sessions/{session_id}/ws" in paths
    assert "/api/v1/production/manuscripts/{manuscript_id}/start-drafting" in paths
    assert "/api/v1/production/submissions/{submission_id}/gate" in paths
    assert "/api/v1/production/submissions/{submission_id}/submit" in paths


@pytest.mark.asyncio
async def test_create_project_route_calls_db_helper(monkeypatch: pytest.MonkeyPatch) -> None:
    import apps.api.routes_production as routes_production

    now = datetime.now(timezone.utc)
    project_id = uuid4()
    create_project = AsyncMock(return_value={
        "id": project_id,
        "title": "Durable project",
        "description": None,
        "primary_topic": "automatic research",
        "status": "active",
        "owner_user_id": TEST_USER_ID,
        "default_library_pool_ids": [],
        "default_workspace_path": None,
        "metadata_json": {},
        "created_at": now,
        "updated_at": now,
    })
    monkeypatch.setattr(routes_production.db, "create_project", create_project)

    result = await routes_production.create_project(
        ProjectCreate(title="Durable project", primary_topic="automatic research"),
        user=TEST_USER,
    )

    create_project.assert_awaited_once()
    payload = create_project.call_args.args[0]
    assert payload["title"] == "Durable project"
    assert payload["status"] == "active"
    assert payload["owner_user_id"] == TEST_USER_ID
    assert payload["workspace_id"] == TEST_USER["workspace_id"]
    assert result["id"] == project_id


@pytest.mark.asyncio
async def test_list_projects_route_filters_by_workspace(monkeypatch: pytest.MonkeyPatch) -> None:
    import apps.api.routes_production as routes_production

    list_projects = AsyncMock(return_value=[])
    monkeypatch.setattr(routes_production.db, "list_projects", list_projects)

    result = await routes_production.list_projects(
        status="active",
        limit=10,
        offset=5,
        user=TEST_USER,
    )

    list_projects.assert_awaited_once_with(
        status="active",
        workspace_id=TEST_USER["workspace_id"],
        limit=10,
        offset=5,
    )
    assert result == []


@pytest.mark.asyncio
async def test_create_coding_task_route_calls_orchestrator(monkeypatch: pytest.MonkeyPatch) -> None:
    import apps.api.routes_production as routes_production

    now = datetime.now(timezone.utc)
    task_id = uuid4()
    project_id = uuid4()
    create_coding_task = AsyncMock(return_value={
        "id": task_id,
        "project_id": project_id,
        "run_id": None,
        "experiment_plan_id": None,
        "provider": "codex",
        "provider_session_id": None,
        "workspace_path": None,
        "thread_name": None,
        "system_prompt": None,
        "user_prompt": "Implement experiment",
        "model": "gpt-5-codex",
        "timeout_sec": None,
        "semantic_inactivity_timeout_sec": None,
        "env_json": {"CUDA_VISIBLE_DEVICES": "0"},
        "mcp_config_json": {"servers": {}},
        "thinking_level": None,
        "prompt_hash": None,
        "status": "queued",
        "failure_reason": None,
        "failure_detail": None,
        "started_at": None,
        "completed_at": None,
        "duration_ms": None,
        "token_usage_json": {},
        "extra_args": [],
        "custom_args": [],
        "metadata_json": {},
        "created_at": now,
        "updated_at": now,
    })
    fake_orchestrator = type(
        "FakeOrchestrator",
        (),
        {"create_coding_task": create_coding_task},
    )()
    monkeypatch.setattr(routes_production, "get_orchestrator", lambda: fake_orchestrator)
    monkeypatch.setattr(
        routes_production.db,
        "get_project",
        AsyncMock(return_value={"id": project_id, "owner_user_id": TEST_USER_ID}),
    )

    result = await routes_production.create_coding_task(
        CodingTaskCreate(
            project_id=project_id,
            user_prompt="Implement experiment",
            model="gpt-5-codex",
            env={"CUDA_VISIBLE_DEVICES": "0"},
            mcp_config={"servers": {}},
        ),
        user=TEST_USER,
    )

    create_coding_task.assert_awaited_once()
    payload = create_coding_task.call_args.args[0]
    assert payload["env_json"] == {"CUDA_VISIBLE_DEVICES": "0"}
    assert payload["mcp_config_json"] == {"servers": {}}
    assert "env" not in payload
    assert "mcp_config" not in payload
    assert result["id"] == task_id


@pytest.mark.asyncio
async def test_list_coding_events_route_returns_db_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import apps.api.routes_production as routes_production

    task_id = uuid4()
    now = datetime.now(timezone.utc)
    list_coding_events = AsyncMock(return_value=[
        {
            "id": 1,
            "coding_task_id": task_id,
            "run_id": None,
            "event_type": "text",
            "content": "working",
            "tool": None,
            "call_id": None,
            "input_json": None,
            "output_text": None,
            "status_text": None,
            "level": None,
            "provider_raw_json": {},
            "created_at": now,
        }
    ])
    monkeypatch.setattr(routes_production.db, "list_coding_events", list_coding_events)
    monkeypatch.setattr(
        routes_production.db,
        "get_coding_task",
        AsyncMock(return_value={"id": task_id, "project_id": uuid4()}),
    )
    monkeypatch.setattr(
        routes_production.db,
        "get_project",
        AsyncMock(return_value={"id": uuid4(), "owner_user_id": TEST_USER_ID}),
    )

    result = await routes_production.list_coding_events(task_id, user=TEST_USER)

    list_coding_events.assert_awaited_once_with(task_id, limit=100, offset=0)
    assert result[0]["content"] == "working"


@pytest.mark.asyncio
async def test_code_artifact_routes_create_and_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import apps.api.routes_production as routes_production

    now = datetime.now(timezone.utc)
    artifact_id = uuid4()
    project_id = uuid4()
    create_code_artifact = AsyncMock(return_value={
        "id": artifact_id,
        "coding_task_id": None,
        "project_id": project_id,
        "experiment_plan_id": None,
        "artifact_type": "manifest",
        "path": "manifest.json",
        "content_hash": None,
        "summary": None,
        "validation_status": "pending",
        "metadata_json": {},
        "created_at": now,
    })
    list_code_artifacts = AsyncMock(return_value=[create_code_artifact.return_value])
    monkeypatch.setattr(routes_production.db, "create_code_artifact", create_code_artifact)
    monkeypatch.setattr(routes_production.db, "list_code_artifacts", list_code_artifacts)
    monkeypatch.setattr(
        routes_production.db,
        "get_project",
        AsyncMock(return_value={"id": project_id, "owner_user_id": TEST_USER_ID}),
    )

    created = await routes_production.create_code_artifact(
        CodeArtifactCreate(
            project_id=project_id,
            artifact_type="manifest",
            path="manifest.json",
        ),
        user=TEST_USER,
    )
    listed = await routes_production.list_code_artifacts(project_id=project_id, user=TEST_USER)

    create_code_artifact.assert_awaited_once()
    list_code_artifacts.assert_awaited_once_with(
        project_id=project_id,
        coding_task_id=None,
        experiment_plan_id=None,
        artifact_type=None,
        limit=50,
        offset=0,
    )
    assert created["id"] == artifact_id
    assert listed[0]["path"] == "manifest.json"


@pytest.mark.asyncio
async def test_create_routes_reject_cross_project_secondary_references(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import apps.api.routes_production as routes_production

    project_id = uuid4()
    other_project_id = uuid4()
    plan_id = uuid4()
    task_id = uuid4()
    manifest_id = uuid4()
    job_id = uuid4()
    create_coding_task = AsyncMock()
    create_code_artifact = AsyncMock()
    create_experiment_manifest = AsyncMock()
    create_experiment_job = AsyncMock()
    create_claim = AsyncMock()
    create_terminal_session = AsyncMock()
    monkeypatch.setattr(
        routes_production.db,
        "get_project",
        AsyncMock(return_value={"id": project_id, "owner_user_id": TEST_USER_ID}),
    )
    monkeypatch.setattr(
        routes_production.db,
        "get_experiment_plan",
        AsyncMock(return_value={"id": plan_id, "project_id": other_project_id}),
    )
    monkeypatch.setattr(
        routes_production.db,
        "get_coding_task",
        AsyncMock(return_value={"id": task_id, "project_id": other_project_id}),
    )
    monkeypatch.setattr(
        routes_production.db,
        "get_experiment_manifest",
        AsyncMock(return_value={"id": manifest_id, "project_id": other_project_id}),
    )
    monkeypatch.setattr(
        routes_production.db,
        "get_experiment_job",
        AsyncMock(return_value={"id": job_id, "project_id": other_project_id}),
    )
    monkeypatch.setattr(routes_production.db, "create_code_artifact", create_code_artifact)
    monkeypatch.setattr(routes_production.db, "create_experiment_manifest", create_experiment_manifest)
    monkeypatch.setattr(routes_production.db, "create_experiment_job", create_experiment_job)
    monkeypatch.setattr(routes_production.db, "create_claim_ledger_entry", create_claim)
    monkeypatch.setattr(routes_production.db, "create_terminal_session", create_terminal_session)
    fake_orchestrator = type(
        "FakeOrchestrator",
        (),
        {"create_coding_task": create_coding_task},
    )()
    monkeypatch.setattr(routes_production, "get_orchestrator", lambda: fake_orchestrator)

    with pytest.raises(Exception, match="experiment_plan_id project_id mismatch"):
        await routes_production.create_coding_task(
            CodingTaskCreate(
                project_id=project_id,
                experiment_plan_id=plan_id,
                user_prompt="Implement experiment",
            ),
            user=TEST_USER,
        )
    with pytest.raises(Exception, match="coding_task_id project_id mismatch"):
        await routes_production.create_code_artifact(
            CodeArtifactCreate(
                coding_task_id=task_id,
                project_id=project_id,
                artifact_type="manifest",
                path="manifest.json",
            ),
            user=TEST_USER,
        )
    with pytest.raises(Exception, match="project_id mismatch"):
        await routes_production.create_experiment_manifest(
            ExperimentManifestCreate(
                experiment_plan_id=plan_id,
                project_id=project_id,
                generated_by_coding_task_id=task_id,
            ),
            user=TEST_USER,
        )
    with pytest.raises(Exception, match="manifest_id project_id mismatch"):
        await routes_production.create_experiment_job(
            ExperimentJobCreate(
                manifest_id=manifest_id,
                experiment_plan_id=plan_id,
                project_id=project_id,
                phase_name="sanity",
                job_name="smoke",
                cmd="python train.py",
            ),
            user=TEST_USER,
        )
    with pytest.raises(Exception, match="experiment_plan_id project_id mismatch"):
        await routes_production.create_claim(
            ClaimLedgerCreate(
                project_id=project_id,
                experiment_plan_id=plan_id,
                claim_text="Model improves accuracy.",
            ),
            user=TEST_USER,
        )
    with pytest.raises(Exception, match="experiment_job_id project_id mismatch"):
        await routes_production.create_terminal_session(
            TerminalSessionCreate(project_id=project_id, experiment_job_id=job_id),
            user=TEST_USER,
        )

    create_coding_task.assert_not_awaited()
    create_code_artifact.assert_not_awaited()
    create_experiment_manifest.assert_not_awaited()
    create_experiment_job.assert_not_awaited()
    create_claim.assert_not_awaited()
    create_terminal_session.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_coding_event_route_verifies_path_task_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import apps.api.routes_production as routes_production

    task_id = uuid4()
    now = datetime.now(timezone.utc)
    create_coding_event = AsyncMock(return_value={
        "id": 2,
        "coding_task_id": task_id,
        "run_id": None,
        "event_type": "status",
        "content": None,
        "tool": None,
        "call_id": None,
        "input_json": None,
        "output_text": None,
        "status_text": "queued",
        "level": None,
        "provider_raw_json": {},
        "created_at": now,
    })
    monkeypatch.setattr(routes_production.db, "create_coding_event", create_coding_event)
    monkeypatch.setattr(
        routes_production.db,
        "get_coding_task",
        AsyncMock(return_value={"id": task_id, "project_id": uuid4()}),
    )
    monkeypatch.setattr(
        routes_production.db,
        "get_project",
        AsyncMock(return_value={"id": uuid4(), "owner_user_id": TEST_USER_ID}),
    )

    result = await routes_production.create_coding_event(
        task_id,
        CodingEventCreate(
            coding_task_id=task_id,
            event_type="status",
            status_text="queued",
        ),
        user=TEST_USER,
    )

    create_coding_event.assert_awaited_once()
    assert create_coding_event.call_args.args[0]["coding_task_id"] == task_id
    assert result["status_text"] == "queued"

    with pytest.raises(Exception):
        await routes_production.create_coding_event(
            task_id,
            CodingEventCreate(coding_task_id=uuid4(), event_type="status"),
            user=TEST_USER,
        )


@pytest.mark.asyncio
async def test_patch_coding_task_route_uses_allowlisted_updates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import apps.api.routes_production as routes_production

    task_id = uuid4()
    project_id = uuid4()
    update_coding_task = AsyncMock(return_value={"id": task_id, "status": "running"})
    monkeypatch.setattr(routes_production.db, "update_coding_task", update_coding_task)
    monkeypatch.setattr(
        routes_production.db,
        "get_coding_task",
        AsyncMock(return_value={"id": task_id, "project_id": project_id}),
    )
    monkeypatch.setattr(
        routes_production.db,
        "get_project",
        AsyncMock(return_value={"id": project_id, "owner_user_id": TEST_USER_ID}),
    )

    result = await routes_production.patch_coding_task(
        task_id,
        {"status": "running", "project_id": str(uuid4())},
        user=TEST_USER,
    )

    update_coding_task.assert_awaited_once_with(task_id, {"status": "running"})
    assert result["status"] == "running"


def test_patch_routes_validate_known_enum_fields(authed_app: FastAPI) -> None:
    client = TestClient(authed_app)

    task_id = uuid4()
    job_id = uuid4()
    terminal_id = uuid4()

    assert client.patch(
        f"/api/v1/production/coding-tasks/{task_id}",
        json={"status": "not-a-status"},
    ).status_code == 422
    assert client.patch(
        f"/api/v1/production/experiment-jobs/{job_id}",
        json={"status": "not-a-status"},
    ).status_code == 422
    assert client.patch(
        f"/api/v1/production/terminal/sessions/{terminal_id}",
        json={"status": "not-a-status"},
    ).status_code == 422


@pytest.mark.asyncio
async def test_expand_manifest_jobs_route_calls_orchestrator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import apps.api.routes_production as routes_production

    now = datetime.now(timezone.utc)
    manifest_id = uuid4()
    job_id = uuid4()
    project_id = uuid4()
    plan_id = uuid4()
    create_manifest_jobs = AsyncMock(return_value=[
        {
            "id": job_id,
            "manifest_id": manifest_id,
            "experiment_plan_id": plan_id,
            "project_id": project_id,
            "phase_name": "sanity",
            "job_name": "smoke",
            "executor_type": "local",
            "remote_host_id": None,
            "cmd": "python train.py",
            "cwd": ".",
            "pid": None,
            "status": "pending",
            "attempt": 1,
            "max_attempts": 1,
            "expected_outputs_json": ["metrics.json"],
            "metrics_json": {},
            "stdout_log_path": None,
            "stderr_log_path": None,
            "artifact_dir": None,
            "started_at": None,
            "completed_at": None,
            "last_heartbeat_at": None,
            "failure_reason": None,
            "created_at": now,
            "updated_at": now,
        }
    ])
    fake_orchestrator = type(
        "FakeOrchestrator",
        (),
        {"create_manifest_jobs": create_manifest_jobs},
    )()
    monkeypatch.setattr(routes_production, "get_orchestrator", lambda: fake_orchestrator)
    monkeypatch.setattr(
        routes_production.db,
        "get_experiment_manifest",
        AsyncMock(return_value={"id": manifest_id, "project_id": project_id}),
    )
    monkeypatch.setattr(
        routes_production.db,
        "get_project",
        AsyncMock(return_value={"id": project_id, "owner_user_id": TEST_USER_ID}),
    )

    result = await routes_production.expand_experiment_manifest_jobs(manifest_id, user=TEST_USER)

    create_manifest_jobs.assert_awaited_once_with(manifest_id)
    assert result[0]["id"] == job_id
    assert result[0]["status"] == "pending"


@pytest.mark.asyncio
async def test_run_local_job_route_calls_orchestrator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import apps.api.routes_production as routes_production

    now = datetime.now(timezone.utc)
    job_id = uuid4()
    row = {
        "id": job_id,
        "status": "completed",
        "completed_at": now,
    }
    result = type(
        "FakeLocalJobRun",
        (),
        {
            "row": row,
            "result": type(
                "FakeLocalJobResult",
                (),
                {
                    "job_id": str(job_id),
                    "status": "completed",
                    "returncode": 0,
                    "stdout_log": "/tmp/stdout.log",
                    "stderr_log": "/tmp/stderr.log",
                    "expected_outputs_found": ["/tmp/metrics.json"],
                    "missing_expected_outputs": [],
                    "failure_reason": None,
                    "duration_ms": 10,
                },
            )(),
        },
    )()
    run_local_job = AsyncMock(return_value=result)
    project_id = uuid4()
    monkeypatch.setattr(
        routes_production.db,
        "get_experiment_job",
        AsyncMock(return_value={"id": job_id, "project_id": project_id}),
    )
    monkeypatch.setattr(
        routes_production.db,
        "get_project",
        AsyncMock(return_value={"id": project_id, "owner_user_id": TEST_USER_ID}),
    )
    claimed_job = {"id": job_id, "status": "running"}
    claim_experiment_job = AsyncMock(return_value=claimed_job)
    monkeypatch.setattr(routes_production.db, "claim_experiment_job", claim_experiment_job)
    fake_orchestrator = type(
        "FakeOrchestrator",
        (),
        {"run_local_job": run_local_job},
    )()
    monkeypatch.setattr(routes_production, "get_orchestrator", lambda: fake_orchestrator)

    response = await routes_production.run_local_experiment_job(
            job_id,
            {"workspace_root": "/tmp/workspace"},
            user=TEST_USER,
    )

    claim_experiment_job.assert_awaited_once()
    run_local_job.assert_awaited_once_with(job_id, preclaimed=True, claimed_job=claimed_job)
    assert response["job"] == row
    assert response["result"]["status"] == "completed"
    assert response["result"]["returncode"] == 0


@pytest.mark.asyncio
async def test_run_coding_task_route_calls_orchestrator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import apps.api.routes_production as routes_production

    now = datetime.now(timezone.utc)
    task_id = uuid4()
    project_id = uuid4()
    task = {
        "id": task_id,
        "project_id": project_id,
        "run_id": None,
        "experiment_plan_id": None,
        "provider": "codex",
        "provider_session_id": None,
        "workspace_path": "/tmp/work",
        "thread_name": None,
        "system_prompt": None,
        "user_prompt": "Implement",
        "model": None,
        "timeout_sec": None,
        "semantic_inactivity_timeout_sec": None,
        "env_json": {},
        "mcp_config_json": {},
        "thinking_level": None,
        "prompt_hash": None,
        "status": "completed",
        "failure_reason": None,
        "failure_detail": None,
        "started_at": now,
        "completed_at": now,
        "duration_ms": 1,
        "token_usage_json": {},
        "extra_args": [],
        "custom_args": [],
        "metadata_json": {},
        "created_at": now,
        "updated_at": now,
    }
    result = type(
        "FakeCodexTaskRun",
        (),
        {
            "task": task,
            "events": [],
            "output": "done",
            "status": "completed",
            "failure_reason": None,
            "failure_detail": None,
        },
    )()
    run_codex_task = AsyncMock(return_value=result)
    fake_orchestrator = type(
        "FakeOrchestrator",
        (),
        {"run_codex_task": run_codex_task},
    )()
    monkeypatch.setattr(routes_production, "get_orchestrator", lambda: fake_orchestrator)
    monkeypatch.setattr(
        routes_production.db,
        "get_coding_task",
        AsyncMock(return_value={"id": task_id, "project_id": project_id}),
    )
    monkeypatch.setattr(
        routes_production.db,
        "get_project",
        AsyncMock(return_value={"id": project_id, "owner_user_id": TEST_USER_ID}),
    )
    claimed_task = {"id": task_id, "status": "running"}
    claim_coding_task = AsyncMock(return_value=claimed_task)
    monkeypatch.setattr(routes_production.db, "claim_coding_task", claim_coding_task)

    response = await routes_production.run_coding_task(task_id, user=TEST_USER)

    claim_coding_task.assert_awaited_once()
    run_codex_task.assert_awaited_once_with(task_id, preclaimed=True, claimed_task=claimed_task)
    assert response["task"] == task
    assert response["status"] == "completed"
    assert response["output"] == "done"


@pytest.mark.asyncio
async def test_manual_run_routes_return_conflict_when_claim_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import apps.api.routes_production as routes_production

    task_id = uuid4()
    job_id = uuid4()
    project_id = uuid4()
    run_codex_task = AsyncMock()
    run_local_job = AsyncMock()
    fake_orchestrator = type(
        "FakeOrchestrator",
        (),
        {"run_codex_task": run_codex_task, "run_local_job": run_local_job},
    )()
    monkeypatch.setattr(routes_production, "get_orchestrator", lambda: fake_orchestrator)
    monkeypatch.setattr(
        routes_production.db,
        "get_project",
        AsyncMock(return_value={"id": project_id, "owner_user_id": TEST_USER_ID}),
    )
    monkeypatch.setattr(
        routes_production.db,
        "get_coding_task",
        AsyncMock(return_value={"id": task_id, "project_id": project_id}),
    )
    monkeypatch.setattr(
        routes_production.db,
        "get_experiment_job",
        AsyncMock(return_value={"id": job_id, "project_id": project_id}),
    )
    monkeypatch.setattr(routes_production.db, "claim_coding_task", AsyncMock(return_value=None))
    monkeypatch.setattr(routes_production.db, "claim_experiment_job", AsyncMock(return_value=None))

    with pytest.raises(Exception, match="already running"):
        await routes_production.run_coding_task(task_id, user=TEST_USER)
    with pytest.raises(Exception, match="already running"):
        await routes_production.run_local_experiment_job(job_id, {}, user=TEST_USER)

    run_codex_task.assert_not_awaited()
    run_local_job.assert_not_awaited()


@pytest.mark.asyncio
async def test_generate_claims_and_gate_routes_call_orchestrator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import apps.api.routes_production as routes_production

    plan_id = uuid4()
    project_id = uuid4()
    manuscript_id = uuid4()
    submission_id = uuid4()
    generated = type(
        "FakeClaimGeneration",
        (),
        {"claims": [{"id": str(uuid4())}], "evidence": [{"id": str(uuid4())}]},
    )()
    generate_claims = AsyncMock(return_value=generated)
    manuscript = {"id": manuscript_id, "status": "drafting"}
    submission = {"id": submission_id, "status": "ready", "claim_audit_report_json": {}}
    prepare_manuscript = AsyncMock(return_value=manuscript)
    gate_submission = AsyncMock(return_value=submission)
    submit_row = {**submission, "status": "submitted"}
    update_submission_package = AsyncMock(return_value=submit_row)
    fake_orchestrator = type(
        "FakeOrchestrator",
        (),
        {
            "generate_claims_from_results": generate_claims,
            "prepare_manuscript_drafting": prepare_manuscript,
            "gate_submission_package": gate_submission,
        },
    )()
    monkeypatch.setattr(routes_production, "get_orchestrator", lambda: fake_orchestrator)
    monkeypatch.setattr(
        routes_production.db,
        "get_experiment_plan",
        AsyncMock(return_value={"id": plan_id, "project_id": project_id}),
    )
    monkeypatch.setattr(
        routes_production.db,
        "get_manuscript_package",
        AsyncMock(return_value={"id": manuscript_id, "project_id": project_id}),
    )
    monkeypatch.setattr(
        routes_production.db,
        "get_submission_package",
        AsyncMock(return_value={"id": submission_id, "manuscript_package_id": manuscript_id}),
    )
    monkeypatch.setattr(routes_production.db, "update_submission_package", update_submission_package)
    monkeypatch.setattr(
        routes_production.db,
        "get_project",
        AsyncMock(return_value={"id": project_id, "owner_user_id": TEST_USER_ID}),
    )

    claims_response = await routes_production.generate_claims_from_results(
        plan_id,
        {"project_id": str(project_id)},
        user=TEST_USER,
    )
    manuscript_response = await routes_production.start_manuscript_drafting(manuscript_id, user=TEST_USER)
    submission_response = await routes_production.gate_submission_package(submission_id, user=TEST_USER)
    submitted_response = await routes_production.submit_submission_package(submission_id, user=TEST_USER)

    generate_claims.assert_awaited_once_with(plan_id, project_id=project_id)
    prepare_manuscript.assert_awaited_once_with(manuscript_id)
    gate_submission.assert_awaited_once_with(submission_id)
    update_submission_package.assert_awaited_once()
    assert claims_response["claims"] == generated.claims
    assert manuscript_response == manuscript
    assert submission_response == submission
    assert submitted_response == submit_row


@pytest.mark.asyncio
async def test_workspace_and_log_routes_call_service_helpers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import apps.api.routes_production as routes_production

    project_id = uuid4()
    job_id = uuid4()
    tree_workspace = AsyncMock(return_value={"root": "/tmp/work", "path": ".", "entries": []})
    read_workspace_file = AsyncMock(return_value={"path": "README.md", "content": "hello", "truncated": False})
    tail_job_log = AsyncMock(return_value={"path": "stdout.log", "content": "tail", "truncated": False})
    list_job_artifacts = AsyncMock(return_value={"root": "/tmp/work", "entries": []})
    monkeypatch.setattr(routes_production, "tree_workspace", tree_workspace)
    monkeypatch.setattr(routes_production, "read_workspace_file", read_workspace_file)
    monkeypatch.setattr(routes_production, "tail_job_log", tail_job_log)
    monkeypatch.setattr(routes_production, "list_job_artifacts", list_job_artifacts)
    monkeypatch.setattr(
        routes_production.db,
        "get_project",
        AsyncMock(return_value={"id": project_id, "owner_user_id": TEST_USER_ID}),
    )
    monkeypatch.setattr(
        routes_production.db,
        "get_experiment_job",
        AsyncMock(return_value={"id": job_id, "project_id": project_id}),
    )

    tree = await routes_production.get_workspace_tree(project_id=project_id, run_id=None, path=".", user=TEST_USER)
    file_response = await routes_production.get_workspace_file(
        project_id=project_id,
        run_id=None,
        path="README.md",
        user=TEST_USER,
    )
    log_response = await routes_production.get_experiment_job_log(job_id, "stdout", lines=50, user=TEST_USER)
    artifact_response = await routes_production.get_experiment_job_artifacts(job_id, user=TEST_USER)

    tree_workspace.assert_awaited_once_with(project_id=project_id, run_id=None, path=".")
    read_workspace_file.assert_awaited_once_with(project_id=project_id, run_id=None, path="README.md")
    tail_job_log.assert_awaited_once_with(job_id, "stdout", lines=50)
    list_job_artifacts.assert_awaited_once_with(job_id)
    assert tree["entries"] == []
    assert file_response["content"] == "hello"
    assert log_response["content"] == "tail"
    assert artifact_response["entries"] == []


@pytest.mark.asyncio
async def test_production_auth_rejects_missing_credentials_even_when_dev_auth_is_open() -> None:
    import apps.api.routes_production as routes_production

    with pytest.raises(Exception, match="Production authentication required"):
        await routes_production.require_production_user(credentials=None)


@pytest.mark.asyncio
async def test_production_auth_rejects_non_operator_roles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import apps.api.routes_production as routes_production
    from apps.api.auth import create_access_token

    user_id = uuid4()
    token = create_access_token(user_id, "user@example.test", "research_user")
    credentials = type("Credentials", (), {"credentials": token})()
    monkeypatch.setattr(
        routes_production,
        "get_user_by_id",
        AsyncMock(return_value={
            "id": user_id,
            "email": "user@example.test",
            "username": "user",
            "role": "research_user",
            "is_active": True,
        }),
    )

    with pytest.raises(Exception, match="Production operator role required"):
        await routes_production.require_production_user(credentials=credentials)


@pytest.mark.asyncio
async def test_remote_host_routes_are_owner_scoped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import apps.api.routes_production as routes_production

    remote_host_id = uuid4()
    create_remote_host = AsyncMock(return_value={
        "id": remote_host_id,
        "name": "gpu-box",
        "owner_user_id": TEST_USER_ID,
        "host": "gpu.example.test",
        "port": 22,
        "username": None,
        "auth_type": "agent",
        "key_ref": None,
        "default_workdir": None,
        "default_env_json": {},
        "capabilities_json": {},
        "status": "unknown",
        "last_checked_at": None,
    })
    list_remote_hosts = AsyncMock(return_value=[create_remote_host.return_value])
    monkeypatch.setattr(routes_production.db, "create_remote_host", create_remote_host)
    monkeypatch.setattr(routes_production.db, "list_remote_hosts", list_remote_hosts)

    created = await routes_production.create_remote_host(
        RemoteHostCreate(name="gpu-box", host="gpu.example.test"),
        user=TEST_USER,
    )
    listed = await routes_production.list_remote_hosts(status="unknown", user=TEST_USER)

    assert created["id"] == remote_host_id
    assert create_remote_host.call_args.args[0]["owner_user_id"] == TEST_USER_ID
    list_remote_hosts.assert_awaited_once_with(
        status="unknown",
        owner_user_id=TEST_USER_ID,
        limit=50,
        offset=0,
    )
    assert listed[0]["owner_user_id"] == TEST_USER_ID


def test_workspace_relative_payloads_reject_unsafe_paths() -> None:
    project_id = uuid4()
    manuscript_id = uuid4()

    with pytest.raises(ValueError, match="path must be a workspace-relative path"):
        CodeArtifactCreate(
            project_id=project_id,
            artifact_type="review_report",
            path="/etc/passwd",
        )

    with pytest.raises(ValueError, match="paper_dir must be a workspace-relative path"):
        ManuscriptPackageCreate(
            project_id=project_id,
            title="Paper",
            paper_dir="../outside",
        )

    with pytest.raises(ValueError, match="submission_dir must be a workspace-relative path"):
        SubmissionPackageCreate(
            manuscript_package_id=manuscript_id,
            venue="ICLR",
            submission_dir="/tmp/submission",
        )


@pytest.mark.asyncio
async def test_project_owner_scope_rejects_other_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import apps.api.routes_production as routes_production

    project_id = uuid4()
    user_id = uuid4()
    monkeypatch.setattr(
        routes_production.db,
        "get_project",
        AsyncMock(return_value={
            "id": project_id,
            "owner_user_id": uuid4(),
            "default_workspace_path": None,
        }),
    )

    with pytest.raises(Exception, match="Project access denied"):
        await routes_production.get_workspace_tree(
            project_id=project_id,
            run_id=None,
            path=".",
            user={"id": user_id},
        )


@pytest.mark.asyncio
async def test_project_owner_scope_rejects_null_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import apps.api.routes_production as routes_production

    project_id = uuid4()
    monkeypatch.setattr(
        routes_production.db,
        "get_project",
        AsyncMock(return_value={
            "id": project_id,
            "owner_user_id": None,
            "default_workspace_path": None,
        }),
    )

    with pytest.raises(Exception, match="Project access denied"):
        await routes_production.get_workspace_file(
            project_id=project_id,
            run_id=None,
            path="README.md",
            user=TEST_USER,
        )


@pytest.mark.asyncio
async def test_experiment_job_routes_reject_other_project_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import apps.api.routes_production as routes_production

    project_id = uuid4()
    job_id = uuid4()
    run_local_job = AsyncMock()
    tail_job_log = AsyncMock()
    list_job_artifacts = AsyncMock()
    fake_orchestrator = type(
        "FakeOrchestrator",
        (),
        {"run_local_job": run_local_job},
    )()
    monkeypatch.setattr(routes_production, "get_orchestrator", lambda: fake_orchestrator)
    monkeypatch.setattr(routes_production, "tail_job_log", tail_job_log)
    monkeypatch.setattr(routes_production, "list_job_artifacts", list_job_artifacts)
    monkeypatch.setattr(
        routes_production.db,
        "get_experiment_job",
        AsyncMock(return_value={"id": job_id, "project_id": project_id}),
    )
    monkeypatch.setattr(
        routes_production.db,
        "get_project",
        AsyncMock(return_value={"id": project_id, "owner_user_id": uuid4()}),
    )
    monkeypatch.setattr(routes_production, "get_user_by_id", AsyncMock(return_value={**TEST_USER, "is_active": True}))

    with pytest.raises(Exception, match="Project access denied"):
        await routes_production.run_local_experiment_job(job_id, user=TEST_USER)
    with pytest.raises(Exception, match="Project access denied"):
        await routes_production.get_experiment_job_log(job_id, "stdout", user=TEST_USER)
    with pytest.raises(Exception, match="Project access denied"):
        await routes_production.get_experiment_job_artifacts(job_id, user=TEST_USER)

    run_local_job.assert_not_awaited()
    tail_job_log.assert_not_awaited()
    list_job_artifacts.assert_not_awaited()


@pytest.mark.asyncio
async def test_terminal_mutation_rejects_other_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import apps.api.routes_production as routes_production

    session_id = uuid4()
    user_id = uuid4()
    monkeypatch.setattr(
        routes_production.db,
        "get_terminal_session",
        AsyncMock(return_value={"id": session_id, "created_by": uuid4(), "status": "open"}),
    )

    with pytest.raises(Exception, match="Terminal session access denied"):
        await routes_production.resize_terminal_session(
            session_id,
            routes_production.TerminalResizeRequest(rows=24, cols=80),
            user={"id": user_id},
        )


@pytest.mark.asyncio
async def test_terminal_routes_reject_other_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import apps.api.routes_production as routes_production

    session_id = uuid4()
    row = {"id": session_id, "created_by": uuid4(), "status": "open"}
    update_terminal_session = AsyncMock()
    monkeypatch.setattr(
        routes_production.db,
        "get_terminal_session",
        AsyncMock(return_value=row),
    )
    monkeypatch.setattr(
        routes_production.db,
        "update_terminal_session",
        update_terminal_session,
    )

    with pytest.raises(Exception, match="Terminal session access denied"):
        await routes_production.get_terminal_session(session_id, user=TEST_USER)
    with pytest.raises(Exception, match="Terminal session access denied"):
        await routes_production.patch_terminal_session(session_id, {"status": "closed"}, user=TEST_USER)
    with pytest.raises(Exception, match="Terminal session access denied"):
        await routes_production.close_terminal_session(session_id, user=TEST_USER)

    update_terminal_session.assert_not_awaited()


@pytest.mark.asyncio
async def test_terminal_routes_reject_other_project_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import apps.api.routes_production as routes_production

    session_id = uuid4()
    project_id = uuid4()
    update_terminal_session = AsyncMock()
    monkeypatch.setattr(
        routes_production.db,
        "get_terminal_session",
        AsyncMock(return_value={
            "id": session_id,
            "project_id": project_id,
            "created_by": TEST_USER_ID,
            "status": "open",
        }),
    )
    monkeypatch.setattr(
        routes_production.db,
        "get_project",
        AsyncMock(return_value={"id": project_id, "owner_user_id": uuid4()}),
    )
    monkeypatch.setattr(
        routes_production.db,
        "update_terminal_session",
        update_terminal_session,
    )

    with pytest.raises(Exception, match="Project access denied"):
        await routes_production.patch_terminal_session(session_id, {"status": "closed"}, user=TEST_USER)
    with pytest.raises(Exception, match="Project access denied"):
        await routes_production.close_terminal_session(session_id, user=TEST_USER)

    update_terminal_session.assert_not_awaited()


@pytest.mark.asyncio
async def test_terminal_patch_revalidates_cwd_shell_and_remote_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import apps.api.routes_production as routes_production

    session_id = uuid4()
    project_id = uuid4()
    remote_host_id = uuid4()
    update_terminal_session = AsyncMock()
    monkeypatch.setattr(
        routes_production.db,
        "get_terminal_session",
        AsyncMock(return_value={
            "id": session_id,
            "project_id": project_id,
            "created_by": TEST_USER_ID,
            "status": "open",
        }),
    )
    monkeypatch.setattr(
        routes_production.db,
        "get_project",
        AsyncMock(return_value={
            "id": project_id,
            "owner_user_id": TEST_USER_ID,
            "default_workspace_path": "projects/demo",
        }),
    )
    monkeypatch.setattr(
        routes_production.db,
        "get_remote_host",
        AsyncMock(return_value={
            "id": remote_host_id,
            "owner_user_id": uuid4(),
        }),
    )
    monkeypatch.setattr(routes_production.db, "update_terminal_session", update_terminal_session)

    with pytest.raises(Exception, match="cwd must be a workspace-relative path"):
        await routes_production.patch_terminal_session(
            session_id,
            {"cwd": "../outside"},
            user=TEST_USER,
        )
    with pytest.raises(Exception, match="unsafe shell"):
        await routes_production.patch_terminal_session(
            session_id,
            {"shell": "bash -lc whoami"},
            user=TEST_USER,
        )
    with pytest.raises(Exception, match="Remote host access denied"):
        await routes_production.patch_terminal_session(
            session_id,
            routes_production.TerminalSessionPatch(remote_host_id=remote_host_id),
            user=TEST_USER,
        )

    update_terminal_session.assert_not_awaited()


@pytest.mark.asyncio
async def test_terminal_websocket_rejects_missing_access_token_before_opening_pty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import apps.api.routes_production as routes_production

    session_id = uuid4()
    get_terminal_session = AsyncMock()
    monkeypatch.setattr(routes_production.db, "get_terminal_session", get_terminal_session)
    open_terminal = AsyncMock()
    monkeypatch.setattr(routes_production.terminal_manager, "open", open_terminal)
    websocket = FakeWebSocket()

    await routes_production.terminal_session_websocket(websocket, session_id)  # type: ignore[arg-type]

    assert websocket.accepted is True
    assert websocket.closed == (1008, "missing terminal token")
    get_terminal_session.assert_not_awaited()
    open_terminal.assert_not_called()


@pytest.mark.asyncio
async def test_terminal_websocket_rejects_project_owner_mismatch_before_opening_pty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import apps.api.routes_production as routes_production
    from apps.api.auth import create_access_token

    session_id = uuid4()
    project_id = uuid4()
    token = create_access_token(TEST_USER_ID, TEST_USER["email"], TEST_USER["role"])
    monkeypatch.setattr(
        routes_production.db,
        "get_terminal_session",
        AsyncMock(return_value={
            "id": session_id,
            "project_id": project_id,
            "created_by": TEST_USER_ID,
            "session_type": "local",
            "status": "open",
        }),
    )
    monkeypatch.setattr(
        routes_production.db,
        "get_project",
        AsyncMock(return_value={"id": project_id, "owner_user_id": uuid4()}),
    )
    monkeypatch.setattr(routes_production, "get_user_by_id", AsyncMock(return_value={**TEST_USER, "is_active": True}))
    open_terminal = AsyncMock()
    monkeypatch.setattr(routes_production.terminal_manager, "open", open_terminal)
    websocket = FakeWebSocket(incoming_texts=[json.dumps({"type": "auth", "token": token})])

    await routes_production.terminal_session_websocket(websocket, session_id)  # type: ignore[arg-type]

    assert websocket.accepted is True
    assert websocket.sent == [{"type": "error", "message": "Project access denied"}]
    assert websocket.closed == (1008, None)
    open_terminal.assert_not_called()


@pytest.mark.asyncio
async def test_terminal_websocket_rejects_owner_mismatch_before_opening_pty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import apps.api.routes_production as routes_production
    from apps.api.auth import create_access_token

    session_id = uuid4()
    token = create_access_token(TEST_USER_ID, TEST_USER["email"], TEST_USER["role"])
    monkeypatch.setattr(
        routes_production.db,
        "get_terminal_session",
        AsyncMock(return_value={
            "id": session_id,
            "created_by": uuid4(),
            "session_type": "local",
            "status": "open",
        }),
    )
    monkeypatch.setattr(routes_production, "get_user_by_id", AsyncMock(return_value={**TEST_USER, "is_active": True}))
    open_terminal = AsyncMock()
    monkeypatch.setattr(routes_production.terminal_manager, "open", open_terminal)
    websocket = FakeWebSocket(incoming_texts=[json.dumps({"type": "auth", "token": token})])

    await routes_production.terminal_session_websocket(websocket, session_id)  # type: ignore[arg-type]

    assert websocket.accepted is True
    assert websocket.sent == [{"type": "error", "message": "terminal session owner mismatch"}]
    assert websocket.closed == (1008, None)
    open_terminal.assert_not_called()


@pytest.mark.asyncio
async def test_terminal_websocket_rejects_disabled_user_before_opening_pty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import apps.api.routes_production as routes_production
    from apps.api.auth import create_access_token

    session_id = uuid4()
    token = create_access_token(TEST_USER_ID, TEST_USER["email"], TEST_USER["role"])
    monkeypatch.setattr(
        routes_production.db,
        "get_terminal_session",
        AsyncMock(return_value={
            "id": session_id,
            "created_by": TEST_USER_ID,
            "session_type": "local",
            "status": "open",
        }),
    )
    monkeypatch.setattr(routes_production, "get_user_by_id", AsyncMock(return_value={**TEST_USER, "is_active": False}))
    open_terminal = AsyncMock()
    monkeypatch.setattr(routes_production.terminal_manager, "open", open_terminal)
    websocket = FakeWebSocket(incoming_texts=[json.dumps({"type": "auth", "token": token})])

    await routes_production.terminal_session_websocket(websocket, session_id)  # type: ignore[arg-type]

    assert websocket.accepted is True
    assert websocket.sent == [{"type": "error", "message": "User not found or disabled"}]
    assert websocket.closed == (1008, None)
    open_terminal.assert_not_called()


@pytest.mark.asyncio
async def test_runtime_detect_endpoint_uses_monkeypatched_detector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import apps.api.routes_production as routes_production

    def fake_detect_runtime(provider: str):
        return {
            "provider": provider,
            "command": "/usr/local/bin/codex",
            "status": "available",
            "supports_json_events": True,
        }

    monkeypatch.setattr(routes_production, "detect_runtime", fake_detect_runtime)

    result = await routes_production.detect_agent_runtime({"provider": "codex"})

    assert result["provider"] == "codex"
    assert result["status"] == "available"
    assert result["supports_json_events"] is True


def test_list_endpoints_reject_invalid_pagination(authed_app: FastAPI) -> None:
    client = TestClient(authed_app)

    assert client.get("/api/v1/production/projects?limit=0").status_code == 422
    assert client.get("/api/v1/production/coding-tasks?limit=101").status_code == 422
    assert client.get("/api/v1/production/code-artifacts?offset=-1").status_code == 422
    assert client.get("/api/v1/production/terminal/sessions?limit=0").status_code == 422


def test_terminal_session_routes_create_list_and_update_with_testclient(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    authed_app: FastAPI,
) -> None:
    import apps.api.routes_production as routes_production

    client = TestClient(authed_app)

    now = datetime.now(timezone.utc)
    session_id = uuid4()
    project_id = uuid4()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("RESEARCH_OS_WORKSPACE_ROOT", str(tmp_path))
    row = {
        "id": session_id,
        "project_id": project_id,
        "run_id": None,
        "experiment_job_id": None,
        "session_type": "local",
        "remote_host_id": None,
        "cwd": "/tmp/work",
        "shell": "/bin/bash",
        "status": "open",
        "created_by": UUID("00000000-0000-0000-0000-000000000001"),
        "closed_at": None,
        "created_at": now,
    }
    create_terminal_session = AsyncMock(return_value=row)
    list_terminal_sessions = AsyncMock(return_value=[row])
    update_terminal_session = AsyncMock(return_value={**row, "status": "closed", "closed_at": now})
    get_project = AsyncMock(return_value={
        "id": project_id,
        "owner_user_id": TEST_USER_ID,
        "default_workspace_path": str(workspace),
        "created_at": now,
        "updated_at": now,
    })
    monkeypatch.setattr(routes_production.db, "get_project", get_project)
    monkeypatch.setattr(
        routes_production.db,
        "create_terminal_session",
        create_terminal_session,
    )
    monkeypatch.setattr(
        routes_production.db,
        "list_terminal_sessions",
        list_terminal_sessions,
    )
    monkeypatch.setattr(
        routes_production.db,
        "update_terminal_session",
        update_terminal_session,
    )
    monkeypatch.setattr(
        routes_production.db,
        "get_terminal_session",
        AsyncMock(return_value=row),
    )

    create_response = client.post(
        "/api/v1/production/terminal/sessions",
            json={
                "project_id": str(project_id),
                "session_type": "local",
                "cwd": str(workspace),
                "shell": "/bin/bash",
                "status": "open",
            },
    )
    list_response = client.get(
        f"/api/v1/production/terminal/sessions?project_id={project_id}&status=open"
    )
    get_response = client.get(f"/api/v1/production/terminal/sessions/{session_id}")
    patch_response = client.patch(
        f"/api/v1/production/terminal/sessions/{session_id}",
        json={"status": "closed", "project_id": str(uuid4())},
    )

    assert create_response.status_code == 201
    assert create_response.json()["id"] == str(session_id)
    create_terminal_session.assert_awaited_once()
    assert create_terminal_session.call_args.args[0]["project_id"] == project_id
    assert create_terminal_session.call_args.args[0]["created_by"] is not None

    assert list_response.status_code == 200
    assert list_response.json()[0]["id"] == str(session_id)
    list_terminal_sessions.assert_awaited_once_with(
        project_id=project_id,
        run_id=None,
        experiment_job_id=None,
        status="open",
        created_by=UUID("00000000-0000-0000-0000-000000000001"),
        limit=50,
        offset=0,
    )

    assert get_response.status_code == 200
    assert get_response.json()["id"] == str(session_id)

    assert patch_response.status_code == 200
    assert patch_response.json()["status"] == "closed"
    update_terminal_session.assert_awaited_once_with(session_id, {"status": "closed"})
