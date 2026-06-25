"""Tests for production database facade helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest


class FakeRecord(dict):
    """Dict subclass that mimics asyncpg.Record enough for record_to_dict."""


@pytest.fixture()
def mock_pool() -> AsyncMock:
    pool = AsyncMock()
    pool.fetchrow = AsyncMock()
    pool.fetch = AsyncMock()
    pool.execute = AsyncMock()
    return pool


@pytest.fixture(autouse=True)
def _patch_get_pool(mock_pool: AsyncMock):
    with patch("apps.api.db.pool.get_pool", return_value=mock_pool):
        yield


@pytest.mark.asyncio
async def test_create_project_inserts_core_project_fields(mock_pool: AsyncMock) -> None:
    project_id = uuid4()
    owner_user_id = uuid4()
    workspace_id = uuid4()
    mock_pool.fetchrow.return_value = FakeRecord({
        "id": project_id,
        "title": "Durable project",
        "primary_topic": "automatic research",
        "owner_user_id": owner_user_id,
        "workspace_id": workspace_id,
    })

    from apps.api.database import create_project

    result = await create_project({
        "title": "Durable project",
        "description": "Production workspace",
        "primary_topic": "automatic research",
        "owner_user_id": owner_user_id,
        "workspace_id": workspace_id,
        "metadata_json": {"priority": "high"},
    })

    mock_pool.fetchrow.assert_awaited_once()
    sql = mock_pool.fetchrow.call_args.args[0]
    assert "INSERT INTO research_project" in sql
    assert "title" in sql
    assert "description" in sql
    assert "primary_topic" in sql
    assert "owner_user_id" in sql
    assert "workspace_id" in sql
    assert "metadata_json" in sql
    assert result["id"] == project_id


@pytest.mark.asyncio
async def test_create_project_requires_owner_user_id(mock_pool: AsyncMock) -> None:
    from apps.api.database import create_project

    with pytest.raises(ValueError, match="owner_user_id is required"):
        await create_project({
            "title": "Durable project",
            "primary_topic": "automatic research",
        })

    mock_pool.fetchrow.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_project_requires_workspace_id(mock_pool: AsyncMock) -> None:
    from apps.api.database import create_project

    with pytest.raises(ValueError, match="workspace_id is required for production projects"):
        await create_project({
            "title": "Durable project",
            "primary_topic": "automatic research",
            "owner_user_id": uuid4(),
        })

    mock_pool.fetchrow.assert_not_awaited()


@pytest.mark.asyncio
async def test_list_projects_filters_by_workspace(mock_pool: AsyncMock) -> None:
    workspace_id = uuid4()
    project_id = uuid4()
    mock_pool.fetch.return_value = [
        FakeRecord({
            "id": project_id,
            "workspace_id": workspace_id,
            "title": "Durable project",
        })
    ]

    from apps.api.database import list_projects

    result = await list_projects(status="active", workspace_id=workspace_id, limit=10, offset=5)

    sql = mock_pool.fetch.call_args.args[0]
    args = mock_pool.fetch.call_args.args[1:]
    assert "FROM research_project" in sql
    assert "status = $1" in sql
    assert "workspace_id = $2" in sql
    assert "LIMIT $3 OFFSET $4" in sql
    assert args == ("active", workspace_id, 10, 5)
    assert result[0]["id"] == project_id


@pytest.mark.asyncio
async def test_remote_host_helpers_are_owner_scoped(mock_pool: AsyncMock) -> None:
    remote_host_id = uuid4()
    owner_user_id = uuid4()
    mock_pool.fetchrow.return_value = FakeRecord({
        "id": remote_host_id,
        "name": "gpu-box",
        "owner_user_id": owner_user_id,
    })
    mock_pool.fetch.return_value = [
        FakeRecord({
            "id": remote_host_id,
            "name": "gpu-box",
            "owner_user_id": owner_user_id,
        })
    ]

    from apps.api.database import create_remote_host, get_remote_host, list_remote_hosts

    created = await create_remote_host({
        "name": "gpu-box",
        "owner_user_id": owner_user_id,
        "host": "gpu.example.test",
    })
    assert created["id"] == remote_host_id
    insert_sql = mock_pool.fetchrow.call_args.args[0]
    assert "INSERT INTO remote_host" in insert_sql
    assert "owner_user_id" in insert_sql

    await get_remote_host(remote_host_id)
    get_sql = mock_pool.fetchrow.call_args.args[0]
    assert "SELECT id, name, owner_user_id" in get_sql

    listed = await list_remote_hosts(owner_user_id=owner_user_id, status="reachable", limit=10, offset=5)
    list_sql = mock_pool.fetch.call_args.args[0]
    args = mock_pool.fetch.call_args.args[1:]
    assert "FROM remote_host" in list_sql
    assert "status = $1" in list_sql
    assert "owner_user_id = $2" in list_sql
    assert args == ("reachable", owner_user_id, 10, 5)
    assert listed[0]["id"] == remote_host_id


@pytest.mark.asyncio
async def test_create_remote_host_requires_owner_user_id(mock_pool: AsyncMock) -> None:
    from apps.api.database import create_remote_host

    with pytest.raises(ValueError, match="owner_user_id is required"):
        await create_remote_host({"name": "gpu-box", "host": "gpu.example.test"})

    mock_pool.fetchrow.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_coding_task_inserts_runtime_configuration_fields(
    mock_pool: AsyncMock,
) -> None:
    task_id = uuid4()
    project_id = uuid4()
    mock_pool.fetchrow.return_value = FakeRecord({
        "id": task_id,
        "project_id": project_id,
        "user_prompt": "Implement experiment",
        "model": "gpt-5-codex",
        "env_json": {"CUDA_VISIBLE_DEVICES": "0"},
        "mcp_config_json": {"servers": {}},
    })

    from apps.api.database import create_coding_task

    result = await create_coding_task({
        "project_id": project_id,
        "user_prompt": "Implement experiment",
        "model": "gpt-5-codex",
        "timeout_sec": 3600,
        "env_json": {"CUDA_VISIBLE_DEVICES": "0"},
        "mcp_config_json": {"servers": {}},
    })

    mock_pool.fetchrow.assert_awaited_once()
    sql = mock_pool.fetchrow.call_args.args[0]
    assert "INSERT INTO coding_task" in sql
    assert "model" in sql
    assert "timeout_sec" in sql
    assert "env_json" in sql
    assert "mcp_config_json" in sql
    assert result["model"] == "gpt-5-codex"
    assert result["env_json"] == {"CUDA_VISIBLE_DEVICES": "0"}
    assert result["mcp_config_json"] == {"servers": {}}


@pytest.mark.asyncio
async def test_create_coding_task_coerces_none_runtime_dicts(
    mock_pool: AsyncMock,
) -> None:
    project_id = uuid4()
    mock_pool.fetchrow.return_value = FakeRecord({
        "id": uuid4(),
        "project_id": project_id,
        "user_prompt": "Implement experiment",
        "env_json": {},
        "mcp_config_json": {},
    })

    from apps.api.db import production as production_db

    await production_db.create_coding_task({
        "project_id": project_id,
        "user_prompt": "Implement experiment",
        "env": None,
        "mcp_config": None,
    })

    values = mock_pool.fetchrow.call_args.args[1:]
    assert values[production_db.CODING_TASK_COLUMNS.index("env_json")] == {}
    assert values[production_db.CODING_TASK_COLUMNS.index("mcp_config_json")] == {}


@pytest.mark.asyncio
async def test_list_coding_tasks_filters_by_run_id(mock_pool: AsyncMock) -> None:
    project_id = uuid4()
    run_id = uuid4()
    task_id = uuid4()
    mock_pool.fetch.return_value = [
        FakeRecord({
            "id": task_id,
            "project_id": project_id,
            "run_id": run_id,
            "status": "queued",
        })
    ]

    from apps.api.database import list_coding_tasks

    result = await list_coding_tasks(
        project_id=project_id,
        run_id=run_id,
        status="queued",
        limit=10,
        offset=5,
    )

    sql = mock_pool.fetch.call_args.args[0]
    args = mock_pool.fetch.call_args.args[1:]
    assert "SELECT *" not in sql
    assert "SELECT id, project_id, run_id" in sql
    assert "FROM coding_task" in sql
    assert "project_id = $1" in sql
    assert "run_id = $2" in sql
    assert "status = $3" in sql
    assert "LIMIT $4 OFFSET $5" in sql
    assert args == (project_id, run_id, "queued", 10, 5)
    assert result[0]["id"] == task_id


@pytest.mark.asyncio
async def test_create_code_artifact_inserts_artifact_fields(mock_pool: AsyncMock) -> None:
    artifact_id = uuid4()
    project_id = uuid4()
    mock_pool.fetchrow.return_value = FakeRecord({
        "id": artifact_id,
        "project_id": project_id,
        "artifact_type": "manifest",
        "path": "manifest.json",
    })

    from apps.api.database import create_code_artifact

    result = await create_code_artifact({
        "project_id": project_id,
        "artifact_type": "manifest",
        "path": "manifest.json",
        "metadata_json": {"source": "test"},
    })

    sql = mock_pool.fetchrow.call_args.args[0]
    assert "INSERT INTO code_artifact" in sql
    assert "artifact_type" in sql
    assert "path" in sql
    assert "metadata_json" in sql
    assert result["id"] == artifact_id


@pytest.mark.asyncio
async def test_create_manuscript_package_inserts_writing_fields(
    mock_pool: AsyncMock,
) -> None:
    manuscript_id = uuid4()
    project_id = uuid4()
    mock_pool.fetchrow.return_value = FakeRecord({
        "id": manuscript_id,
        "project_id": project_id,
        "title": "Research OS paper",
        "status": "outline",
    })

    from apps.api.database import create_manuscript_package

    result = await create_manuscript_package({
        "project_id": project_id,
        "title": "Research OS paper",
        "venue_target": "NeurIPS",
    })

    sql = mock_pool.fetchrow.call_args.args[0]
    assert "INSERT INTO manuscript_package" in sql
    assert "venue_target" in sql
    assert "paper_dir" in sql
    assert result["title"] == "Research OS paper"


@pytest.mark.asyncio
async def test_create_submission_package_inserts_submission_fields(
    mock_pool: AsyncMock,
) -> None:
    submission_id = uuid4()
    manuscript_id = uuid4()
    mock_pool.fetchrow.return_value = FakeRecord({
        "id": submission_id,
        "manuscript_package_id": manuscript_id,
        "venue": "NeurIPS",
        "status": "preparing",
    })

    from apps.api.database import create_submission_package

    result = await create_submission_package({
        "manuscript_package_id": manuscript_id,
        "venue": "NeurIPS",
        "checklist_json": {"format": "ok"},
    })

    sql = mock_pool.fetchrow.call_args.args[0]
    assert "INSERT INTO submission_package" in sql
    assert "checklist_json" in sql
    assert "claim_audit_report_json" in sql
    assert result["venue"] == "NeurIPS"


@pytest.mark.asyncio
async def test_update_coding_task_rejects_non_allowlisted_fields(
    mock_pool: AsyncMock,
) -> None:
    from apps.api.database import update_coding_task

    with pytest.raises(ValueError, match="Invalid column names"):
        await update_coding_task(uuid4(), {"project_id": uuid4()})

    mock_pool.fetchrow.assert_not_awaited()


@pytest.mark.asyncio
async def test_list_terminal_sessions_filters_and_paginates(mock_pool: AsyncMock) -> None:
    project_id = uuid4()
    session_id = uuid4()
    mock_pool.fetch.return_value = [
        FakeRecord({
            "id": session_id,
            "project_id": project_id,
            "status": "open",
            "session_type": "local",
        })
    ]

    from apps.api.database import list_terminal_sessions

    result = await list_terminal_sessions(
        project_id=project_id,
        status="open",
        limit=25,
        offset=10,
    )

    sql = mock_pool.fetch.call_args.args[0]
    args = mock_pool.fetch.call_args.args[1:]
    assert "SELECT *" not in sql
    assert "SELECT id, project_id, run_id, experiment_job_id" in sql
    assert "FROM terminal_session" in sql
    assert "project_id = $1" in sql
    assert "status = $2" in sql
    assert "LIMIT $3 OFFSET $4" in sql
    assert args == (project_id, "open", 25, 10)
    assert result[0]["id"] == session_id


@pytest.mark.asyncio
async def test_update_experiment_job_success_uses_allowlisted_columns(
    mock_pool: AsyncMock,
) -> None:
    job_id = uuid4()
    mock_pool.fetchrow.return_value = FakeRecord({
        "id": job_id,
        "status": "completed",
        "failure_reason": None,
    })

    from apps.api.database import update_experiment_job

    result = await update_experiment_job(
        job_id,
        {
            "status": "completed",
            "failure_reason": None,
            "metrics_json": {"accuracy": 0.9},
        },
    )

    sql = mock_pool.fetchrow.call_args.args[0]
    args = mock_pool.fetchrow.call_args.args[1:]
    assert "UPDATE experiment_job" in sql
    assert "RETURNING id, manifest_id, experiment_plan_id, project_id" in sql
    assert "status = $1" in sql
    assert "failure_reason = $2" in sql
    assert "metrics_json = $3" in sql
    assert "WHERE id = $4" in sql
    assert args == ("completed", None, {"accuracy": 0.9}, job_id)
    assert result["status"] == "completed"


@pytest.mark.asyncio
async def test_scheduler_claim_helpers_use_row_locks_and_state_transitions(
    mock_pool: AsyncMock,
) -> None:
    task_id = uuid4()
    job_id = uuid4()
    mock_pool.fetch.side_effect = [
        [FakeRecord({"id": task_id, "status": "running"})],
        [FakeRecord({"id": job_id, "status": "running"})],
    ]

    from apps.api.database import claim_experiment_jobs, claim_queued_coding_tasks

    tasks = await claim_queued_coding_tasks(
        limit=2,
        worker_id="scheduler-a",
        lease_seconds=120,
    )
    jobs = await claim_experiment_jobs(
        [job_id],
        limit=1,
        worker_id="scheduler-a",
        lease_seconds=120,
    )

    task_sql = mock_pool.fetch.call_args_list[0].args[0]
    task_args = mock_pool.fetch.call_args_list[0].args[1:]
    job_sql = mock_pool.fetch.call_args_list[1].args[0]
    job_args = mock_pool.fetch.call_args_list[1].args[1:]
    assert "FOR UPDATE SKIP LOCKED" in task_sql
    assert "UPDATE coding_task" in task_sql
    assert "status = 'running'" in task_sql
    assert "scheduler_lease" in task_sql
    assert "- 'scheduler_heartbeat'" in task_sql
    assert "$3::int::text || ' seconds'" in task_sql
    assert "'lease_seconds', $3::int" in task_sql
    assert task_args == (2, "scheduler-a", 120)
    assert "FOR UPDATE SKIP LOCKED" in job_sql
    assert "UPDATE experiment_job" in job_sql
    assert "status = 'running'" in job_sql
    assert "scheduler_lease" in job_sql
    assert "- 'scheduler_heartbeat'" in job_sql
    assert "$4::int::text || ' seconds'" in job_sql
    assert "'lease_seconds', $4::int" in job_sql
    assert job_args == ([job_id], 1, "scheduler-a", 120)
    assert tasks[0]["id"] == task_id
    assert jobs[0]["id"] == job_id


@pytest.mark.asyncio
async def test_manual_claim_helpers_claim_single_rows_by_id(
    mock_pool: AsyncMock,
) -> None:
    task_id = uuid4()
    job_id = uuid4()
    mock_pool.fetchrow.side_effect = [
        FakeRecord({"id": task_id, "status": "running"}),
        FakeRecord({"id": job_id, "status": "running"}),
    ]

    from apps.api.database import claim_coding_task, claim_experiment_job

    task = await claim_coding_task(
        task_id,
        worker_id="manual-user",
        lease_seconds=60,
    )
    job = await claim_experiment_job(
        job_id,
        worker_id="manual-user",
        lease_seconds=60,
    )

    task_sql = mock_pool.fetchrow.call_args_list[0].args[0]
    task_args = mock_pool.fetchrow.call_args_list[0].args[1:]
    job_sql = mock_pool.fetchrow.call_args_list[1].args[0]
    job_args = mock_pool.fetchrow.call_args_list[1].args[1:]
    assert "WHERE id = $1" in task_sql
    assert "AND status = 'queued'" in task_sql
    assert "scheduler_lease" in task_sql
    assert "- 'scheduler_heartbeat'" in task_sql
    assert "$3::int::text || ' seconds'" in task_sql
    assert "'lease_seconds', $3::int" in task_sql
    assert task_args == (task_id, "manual-user", 60)
    assert "WHERE id = $1" in job_sql
    assert "AND status = 'pending'" in job_sql
    assert "scheduler_lease" in job_sql
    assert "- 'scheduler_heartbeat'" in job_sql
    assert "$3::int::text || ' seconds'" in job_sql
    assert "'lease_seconds', $3::int" in job_sql
    assert job_args == (job_id, "manual-user", 60)
    assert task["id"] == task_id
    assert job["id"] == job_id


@pytest.mark.asyncio
async def test_scheduler_recovery_helpers_mark_stale_running_rows(
    mock_pool: AsyncMock,
) -> None:
    task_id = uuid4()
    job_id = uuid4()
    stale_before = datetime.now(timezone.utc)
    mock_pool.fetch.side_effect = [
        [FakeRecord({"id": task_id, "status": "queued"})],
        [FakeRecord({"id": job_id, "status": "stuck"})],
    ]

    from apps.api.database import recover_stale_coding_tasks, recover_stale_experiment_jobs

    tasks = await recover_stale_coding_tasks(stale_before)
    jobs = await recover_stale_experiment_jobs(stale_before)

    task_sql = mock_pool.fetch.call_args_list[0].args[0]
    job_sql = mock_pool.fetch.call_args_list[1].args[0]
    assert "UPDATE coding_task" in task_sql
    assert "status = 'queued'" in task_sql
    assert "scheduler_heartbeat,claimed_until" in task_sql
    assert "scheduler_lease,claimed_until" in task_sql
    assert "UPDATE experiment_job" in job_sql
    assert "status = 'stuck'" in job_sql
    assert "scheduler_heartbeat,claimed_until" in job_sql
    assert "scheduler_lease,claimed_until" in job_sql
    assert tasks[0]["id"] == task_id
    assert jobs[0]["id"] == job_id


@pytest.mark.asyncio
async def test_lease_guarded_update_helpers_require_current_worker(
    mock_pool: AsyncMock,
) -> None:
    task_id = uuid4()
    job_id = uuid4()
    mock_pool.fetchrow.side_effect = [
        FakeRecord({"id": task_id, "status": "completed"}),
        FakeRecord({"id": job_id, "status": "completed"}),
    ]

    from apps.api.database import update_coding_task_if_lease, update_experiment_job_if_lease

    task = await update_coding_task_if_lease(
        task_id,
        {"status": "completed"},
        worker_id="worker-a",
        lease_id="lease-a",
    )
    job = await update_experiment_job_if_lease(
        job_id,
        {"status": "completed"},
        worker_id="worker-a",
        lease_id="lease-a",
    )

    task_sql = mock_pool.fetchrow.call_args_list[0].args[0]
    task_args = mock_pool.fetchrow.call_args_list[0].args[1:]
    job_sql = mock_pool.fetchrow.call_args_list[1].args[0]
    job_args = mock_pool.fetchrow.call_args_list[1].args[1:]
    assert "status = 'running'" in task_sql
    assert "metadata_json #>> '{scheduler_lease,worker_id}'" in task_sql
    assert "metadata_json #>> '{scheduler_lease,lease_id}'" in task_sql
    assert task_args == ("completed", task_id, "worker-a", "lease-a")
    assert "status = 'running'" in job_sql
    assert "metrics_json #>> '{scheduler_lease,worker_id}'" in job_sql
    assert "metrics_json #>> '{scheduler_lease,lease_id}'" in job_sql
    assert job_args == ("completed", job_id, "worker-a", "lease-a")
    assert task["id"] == task_id
    assert job["id"] == job_id


@pytest.mark.asyncio
async def test_create_submission_package_includes_independent_audit_fields(
    monkeypatch,
) -> None:
    from apps.api.db import production

    captured: dict[str, object] = {}

    class Pool:
        async def fetchrow(self, sql, *values):
            captured["sql"] = sql
            captured["values"] = values
            return {
                "id": "00000000-0000-0000-0000-000000000010",
                "paper_claim_audit_report_json": {"passed": True},
                "adversarial_audit_report_json": {"passed": False},
            }

    async def fake_pool():
        return Pool()

    monkeypatch.setattr(production.db_pool, "get_pool", fake_pool)
    monkeypatch.setattr(production.db_pool, "record_to_dict", dict)

    await production.create_submission_package(
        {
            "manuscript_package_id": "00000000-0000-0000-0000-000000000001",
            "venue": "ICLR",
            "paper_claim_audit_report_json": {"passed": True},
            "adversarial_audit_report_json": {"passed": False},
        }
    )

    assert "paper_claim_audit_report_json" in str(captured["sql"])
    assert "adversarial_audit_report_json" in str(captured["sql"])
