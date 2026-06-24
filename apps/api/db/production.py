"""Production research database operations."""

from __future__ import annotations

import json
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from apps.api.db import pool as db_pool


def _db_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    return value


def _normalize(data: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(data)
    if "env" in normalized and "env_json" not in normalized:
        normalized["env_json"] = normalized.pop("env") or {}
    if "mcp_config" in normalized and "mcp_config_json" not in normalized:
        normalized["mcp_config_json"] = normalized.pop("mcp_config") or {}
    return normalized


def _select_columns(table: str) -> str:
    return ", ".join(TABLE_RESPONSE_COLUMNS[table])


async def _insert(
    table: str,
    columns: tuple[str, ...],
    data: dict[str, Any],
) -> dict[str, Any]:
    values = [_db_value(data.get(column)) for column in columns]
    column_sql = ", ".join(columns)
    placeholder_sql = ", ".join(f"${idx}" for idx in range(1, len(columns) + 1))
    pool = await db_pool.get_pool()
    row = await pool.fetchrow(
        f"""
        INSERT INTO {table} ({column_sql})
        VALUES ({placeholder_sql})
        RETURNING {_select_columns(table)}
        """,
        *values,
    )
    return db_pool.record_to_dict(row)


async def _get_by_id(table: str, row_id: UUID) -> dict[str, Any] | None:
    pool = await db_pool.get_pool()
    row = await pool.fetchrow(
        f"SELECT {_select_columns(table)} FROM {table} WHERE id = $1",
        row_id,
    )
    return db_pool.record_to_dict(row) if row is not None else None


async def _list(
    table: str,
    *,
    filters: dict[str, Any] | None = None,
    order_by: str = "created_at DESC",
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    filters = filters or {}
    values = [_db_value(value) for value in filters.values()]
    where_sql = ""
    if filters:
        predicates = [
            f"{column} = ${idx}"
            for idx, column in enumerate(filters.keys(), start=1)
        ]
        where_sql = f"WHERE {' AND '.join(predicates)}"

    values.extend([limit, offset])
    limit_idx = len(values) - 1
    offset_idx = len(values)
    pool = await db_pool.get_pool()
    rows = await pool.fetch(
        f"""
        SELECT {_select_columns(table)} FROM {table}
        {where_sql}
        ORDER BY {order_by}
        LIMIT ${limit_idx} OFFSET ${offset_idx}
        """,
        *values,
    )
    return [db_pool.record_to_dict(row) for row in rows]


async def _update(
    table: str,
    row_id: UUID,
    updates: dict[str, Any],
    allowed_columns: frozenset[str],
) -> dict[str, Any] | None:
    if not updates:
        return await _get_by_id(table, row_id)

    invalid = set(updates) - allowed_columns
    if invalid:
        raise ValueError(f"Invalid column names: {invalid}")

    set_parts: list[str] = []
    values: list[Any] = []
    for idx, (column, value) in enumerate(updates.items(), start=1):
        set_parts.append(f"{column} = ${idx}")
        values.append(_db_value(value))

    values.append(row_id)
    id_idx = len(values)
    pool = await db_pool.get_pool()
    row = await pool.fetchrow(
        f"""
        UPDATE {table}
        SET {', '.join(set_parts)}
        WHERE id = ${id_idx}
        RETURNING {_select_columns(table)}
        """,
        *values,
    )
    return db_pool.record_to_dict(row) if row is not None else None


PROJECT_COLUMNS = (
    "title",
    "description",
    "primary_topic",
    "status",
    "owner_user_id",
    "default_library_pool_ids",
    "default_workspace_path",
    "metadata_json",
)


async def create_project(project_data: dict[str, Any]) -> dict[str, Any]:
    data = {
        "description": None,
        "status": "active",
        "default_library_pool_ids": [],
        "default_workspace_path": None,
        "metadata_json": {},
        **project_data,
    }
    if data.get("owner_user_id") is None:
        raise ValueError("owner_user_id is required for production projects")
    return await _insert("research_project", PROJECT_COLUMNS, data)


async def get_project(project_id: UUID) -> dict[str, Any] | None:
    return await _get_by_id("research_project", project_id)


async def list_projects(
    status: str | None = None,
    owner_user_id: UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    filters = {}
    if status is not None:
        filters["status"] = status
    if owner_user_id is not None:
        filters["owner_user_id"] = owner_user_id
    return await _list("research_project", filters=filters, limit=limit, offset=offset)


QUERY_PACK_COLUMNS = (
    "project_id",
    "source_run_id",
    "topic",
    "query_pack_json",
)


async def create_project_query_pack(data: dict[str, Any]) -> dict[str, Any]:
    payload = {"source_run_id": None, "topic": None, "query_pack_json": {}, **data}
    return await _insert("project_query_pack", QUERY_PACK_COLUMNS, payload)


async def list_project_query_packs(
    project_id: UUID,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    return await _list(
        "project_query_pack",
        filters={"project_id": project_id},
        limit=limit,
        offset=offset,
    )


ACCEPTANCE_CRITERIA_DEFAULT = {
    "sanity_checks": [],
    "minimum_artifacts": [],
    "metric_thresholds": [],
    "negative_controls": [],
    "reproducibility_requirements": [],
    "claim_support_requirements": [],
}

EXPERIMENT_PLAN_COLUMNS = (
    "project_id",
    "idea_id",
    "source_run_id",
    "title",
    "hypothesis",
    "method_plan_markdown",
    "implementation_plan_markdown",
    "datasets_json",
    "baselines_json",
    "metrics_json",
    "ablation_plan_json",
    "resource_plan_json",
    "expected_outputs_json",
    "acceptance_criteria_json",
    "risk_register_json",
    "status",
)


async def create_experiment_plan(data: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "idea_id": None,
        "source_run_id": None,
        "method_plan_markdown": "",
        "implementation_plan_markdown": "",
        "datasets_json": {},
        "baselines_json": {},
        "metrics_json": {},
        "ablation_plan_json": {},
        "resource_plan_json": {},
        "expected_outputs_json": {},
        "acceptance_criteria_json": ACCEPTANCE_CRITERIA_DEFAULT,
        "risk_register_json": {},
        "status": "draft",
        **data,
    }
    return await _insert("experiment_plan", EXPERIMENT_PLAN_COLUMNS, payload)


async def get_experiment_plan(plan_id: UUID) -> dict[str, Any] | None:
    return await _get_by_id("experiment_plan", plan_id)


async def list_experiment_plans(
    project_id: UUID | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    filters = {}
    if project_id is not None:
        filters["project_id"] = project_id
    if status is not None:
        filters["status"] = status
    return await _list(
        "experiment_plan",
        filters=filters,
        limit=limit,
        offset=offset,
    )


async def update_experiment_plan_status(
    plan_id: UUID,
    status: str,
) -> dict[str, Any] | None:
    return await _update(
        "experiment_plan",
        plan_id,
        {"status": status},
        frozenset({"status"}),
    )


CODING_TASK_COLUMNS = (
    "project_id",
    "run_id",
    "experiment_plan_id",
    "provider",
    "provider_session_id",
    "workspace_path",
    "thread_name",
    "system_prompt",
    "user_prompt",
    "model",
    "timeout_sec",
    "semantic_inactivity_timeout_sec",
    "env_json",
    "mcp_config_json",
    "thinking_level",
    "prompt_hash",
    "status",
    "failure_reason",
    "failure_detail",
    "started_at",
    "completed_at",
    "duration_ms",
    "token_usage_json",
    "extra_args",
    "custom_args",
    "metadata_json",
)


async def create_coding_task(data: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "run_id": None,
        "experiment_plan_id": None,
        "provider": "codex",
        "provider_session_id": None,
        "workspace_path": None,
        "thread_name": None,
        "system_prompt": None,
        "model": None,
        "timeout_sec": None,
        "semantic_inactivity_timeout_sec": None,
        "env_json": {},
        "mcp_config_json": {},
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
        **_normalize(data),
    }
    return await _insert("coding_task", CODING_TASK_COLUMNS, payload)


async def get_coding_task(task_id: UUID) -> dict[str, Any] | None:
    return await _get_by_id("coding_task", task_id)


async def list_coding_tasks(
    project_id: UUID | None = None,
    run_id: UUID | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    filters = {}
    if project_id is not None:
        filters["project_id"] = project_id
    if run_id is not None:
        filters["run_id"] = run_id
    if status is not None:
        filters["status"] = status
    return await _list("coding_task", filters=filters, limit=limit, offset=offset)


async def claim_queued_coding_tasks(
    limit: int = 1,
    worker_id: str | None = None,
    lease_seconds: int = 3600,
) -> list[dict[str, Any]]:
    """Atomically claim queued coding tasks for a scheduler worker."""

    worker = worker_id or "scheduler"
    pool = await db_pool.get_pool()
    rows = await pool.fetch(
        f"""
        WITH picked AS (
            SELECT id
            FROM coding_task
            WHERE status = 'queued'
            ORDER BY created_at ASC
            FOR UPDATE SKIP LOCKED
            LIMIT $1
        )
        UPDATE coding_task
        SET
            status = 'running',
            started_at = COALESCE(started_at, NOW()),
            completed_at = NULL,
            failure_reason = NULL,
            failure_detail = NULL,
            metadata_json = (COALESCE(metadata_json, '{{}}'::jsonb) - 'scheduler_heartbeat')
                || jsonb_build_object(
                    'scheduler_lease',
                    jsonb_build_object(
                        'lease_id', gen_random_uuid()::text,
                        'worker_id', $2::text,
                        'claimed_at', NOW(),
                        'claimed_until', NOW() + ($3::text || ' seconds')::interval,
                        'lease_seconds', $3
                    )
                )
        WHERE id IN (SELECT id FROM picked)
        RETURNING {_select_columns("coding_task")}
        """,
        limit,
        worker,
        lease_seconds,
    )
    return [db_pool.record_to_dict(row) for row in rows]


async def claim_coding_task(
    task_id: UUID,
    *,
    worker_id: str | None = None,
    lease_seconds: int = 3600,
) -> dict[str, Any] | None:
    """Atomically claim one queued coding task for a manual or scheduler worker."""

    worker = worker_id or "manual"
    pool = await db_pool.get_pool()
    row = await pool.fetchrow(
        f"""
        UPDATE coding_task
        SET
            status = 'running',
            started_at = COALESCE(started_at, NOW()),
            completed_at = NULL,
            failure_reason = NULL,
            failure_detail = NULL,
            metadata_json = (COALESCE(metadata_json, '{{}}'::jsonb) - 'scheduler_heartbeat')
                || jsonb_build_object(
                    'scheduler_lease',
                    jsonb_build_object(
                        'lease_id', gen_random_uuid()::text,
                        'worker_id', $2::text,
                        'claimed_at', NOW(),
                        'claimed_until', NOW() + ($3::text || ' seconds')::interval,
                        'lease_seconds', $3
                    )
                )
        WHERE id = $1
          AND status = 'queued'
        RETURNING {_select_columns("coding_task")}
        """,
        task_id,
        worker,
        lease_seconds,
    )
    return db_pool.record_to_dict(row) if row is not None else None


async def recover_stale_coding_tasks(stale_before: datetime) -> list[dict[str, Any]]:
    """Requeue coding tasks left running by a dead scheduler/agent process."""

    pool = await db_pool.get_pool()
    rows = await pool.fetch(
        f"""
        UPDATE coding_task
        SET
            status = 'queued',
            started_at = NULL,
            completed_at = NULL,
            failure_reason = 'scheduler_recovered_stale_running',
            failure_detail = NULL
        WHERE status = 'running'
          AND COALESCE(
              NULLIF(metadata_json #>> '{{scheduler_heartbeat,claimed_until}}', '')::timestamptz,
              NULLIF(metadata_json #>> '{{scheduler_lease,claimed_until}}', '')::timestamptz,
              updated_at,
              started_at,
              created_at
          ) < $1
        RETURNING {_select_columns("coding_task")}
        """,
        stale_before,
    )
    return [db_pool.record_to_dict(row) for row in rows]


async def update_coding_task_if_lease(
    task_id: UUID,
    updates: dict[str, Any],
    *,
    worker_id: str,
    lease_id: str,
) -> dict[str, Any] | None:
    """Update a running task only while the caller still owns its scheduler lease."""

    if not worker_id or not lease_id:
        return None
    invalid = set(updates) - _CODING_TASK_UPDATABLE_COLUMNS
    if invalid:
        raise ValueError(f"Invalid column names: {invalid}")
    set_parts: list[str] = []
    values: list[Any] = []
    for idx, (column, value) in enumerate(updates.items(), start=1):
        set_parts.append(f"{column} = ${idx}")
        values.append(_db_value(value))
    values.extend([task_id, worker_id])
    values.append(lease_id)
    id_idx = len(values) - 2
    worker_idx = len(values) - 1
    lease_idx = len(values)
    pool = await db_pool.get_pool()
    row = await pool.fetchrow(
        f"""
        UPDATE coding_task
        SET {', '.join(set_parts)}
        WHERE id = ${id_idx}
          AND status = 'running'
          AND metadata_json #>> '{{scheduler_lease,worker_id}}' = ${worker_idx}
          AND metadata_json #>> '{{scheduler_lease,lease_id}}' = ${lease_idx}
        RETURNING {_select_columns("coding_task")}
        """,
        *values,
    )
    return db_pool.record_to_dict(row) if row is not None else None


async def heartbeat_coding_task_if_lease(
    task_id: UUID,
    *,
    worker_id: str,
    lease_id: str,
    heartbeat: dict[str, Any],
) -> dict[str, Any] | None:
    if not worker_id or not lease_id:
        return None
    pool = await db_pool.get_pool()
    row = await pool.fetchrow(
        f"""
        UPDATE coding_task
        SET metadata_json = jsonb_set(
            COALESCE(metadata_json, '{{}}'::jsonb),
            '{{scheduler_heartbeat}}',
            $4::jsonb,
            true
        )
        WHERE id = $1
          AND status = 'running'
          AND metadata_json #>> '{{scheduler_lease,worker_id}}' = $2
          AND metadata_json #>> '{{scheduler_lease,lease_id}}' = $3
        RETURNING {_select_columns("coding_task")}
        """,
        task_id,
        worker_id,
        lease_id,
        json.dumps(heartbeat),
    )
    return db_pool.record_to_dict(row) if row is not None else None


_CODING_TASK_UPDATABLE_COLUMNS = frozenset({
    "provider_session_id",
    "workspace_path",
    "thread_name",
    "system_prompt",
    "user_prompt",
    "model",
    "timeout_sec",
    "semantic_inactivity_timeout_sec",
    "env_json",
    "mcp_config_json",
    "thinking_level",
    "prompt_hash",
    "status",
    "failure_reason",
    "failure_detail",
    "started_at",
    "completed_at",
    "duration_ms",
    "token_usage_json",
    "extra_args",
    "custom_args",
    "metadata_json",
})


async def update_coding_task(
    task_id: UUID,
    updates: dict[str, Any],
) -> dict[str, Any] | None:
    return await _update(
        "coding_task",
        task_id,
        updates,
        _CODING_TASK_UPDATABLE_COLUMNS,
    )


CODING_EVENT_COLUMNS = (
    "coding_task_id",
    "run_id",
    "event_type",
    "content",
    "tool",
    "call_id",
    "input_json",
    "output_text",
    "status_text",
    "level",
    "provider_raw_json",
)


async def create_coding_event(data: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "run_id": None,
        "content": None,
        "tool": None,
        "call_id": None,
        "input_json": None,
        "output_text": None,
        "status_text": None,
        "level": None,
        "provider_raw_json": {},
        **data,
    }
    return await _insert("coding_event", CODING_EVENT_COLUMNS, payload)


async def list_coding_events(
    task_id: UUID,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    return await _list(
        "coding_event",
        filters={"coding_task_id": task_id},
        order_by="created_at ASC",
        limit=limit,
        offset=offset,
    )


CODE_ARTIFACT_COLUMNS = (
    "coding_task_id",
    "project_id",
    "experiment_plan_id",
    "artifact_type",
    "path",
    "content_hash",
    "summary",
    "validation_status",
    "metadata_json",
)


async def create_code_artifact(data: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "coding_task_id": None,
        "experiment_plan_id": None,
        "content_hash": None,
        "summary": None,
        "validation_status": "pending",
        "metadata_json": {},
        **data,
    }
    return await _insert("code_artifact", CODE_ARTIFACT_COLUMNS, payload)


async def list_code_artifacts(
    project_id: UUID | None = None,
    coding_task_id: UUID | None = None,
    experiment_plan_id: UUID | None = None,
    artifact_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    filters = {}
    if project_id is not None:
        filters["project_id"] = project_id
    if coding_task_id is not None:
        filters["coding_task_id"] = coding_task_id
    if experiment_plan_id is not None:
        filters["experiment_plan_id"] = experiment_plan_id
    if artifact_type is not None:
        filters["artifact_type"] = artifact_type
    return await _list("code_artifact", filters=filters, limit=limit, offset=offset)


EXPERIMENT_MANIFEST_COLUMNS = (
    "experiment_plan_id",
    "project_id",
    "manifest_json",
    "manifest_version",
    "generated_by_coding_task_id",
    "status",
)


async def create_experiment_manifest(data: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "manifest_json": {},
        "manifest_version": "1",
        "generated_by_coding_task_id": None,
        "status": "draft",
        **data,
    }
    return await _insert("experiment_manifest", EXPERIMENT_MANIFEST_COLUMNS, payload)


async def get_experiment_manifest(manifest_id: UUID) -> dict[str, Any] | None:
    return await _get_by_id("experiment_manifest", manifest_id)


async def list_experiment_manifests(
    project_id: UUID | None = None,
    experiment_plan_id: UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    filters = {}
    if project_id is not None:
        filters["project_id"] = project_id
    if experiment_plan_id is not None:
        filters["experiment_plan_id"] = experiment_plan_id
    return await _list(
        "experiment_manifest",
        filters=filters,
        limit=limit,
        offset=offset,
    )


EXPERIMENT_JOB_COLUMNS = (
    "manifest_id",
    "experiment_plan_id",
    "project_id",
    "phase_name",
    "job_name",
    "executor_type",
    "remote_host_id",
    "cmd",
    "cwd",
    "pid",
    "status",
    "attempt",
    "max_attempts",
    "expected_outputs_json",
    "metrics_json",
    "stdout_log_path",
    "stderr_log_path",
    "artifact_dir",
    "started_at",
    "completed_at",
    "last_heartbeat_at",
    "failure_reason",
)


async def create_experiment_job(data: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "executor_type": "local",
        "remote_host_id": None,
        "cwd": ".",
        "pid": None,
        "status": "pending",
        "attempt": 1,
        "max_attempts": 1,
        "expected_outputs_json": [],
        "metrics_json": {},
        "stdout_log_path": None,
        "stderr_log_path": None,
        "artifact_dir": None,
        "started_at": None,
        "completed_at": None,
        "last_heartbeat_at": None,
        "failure_reason": None,
        **data,
    }
    return await _insert("experiment_job", EXPERIMENT_JOB_COLUMNS, payload)


async def get_experiment_job(job_id: UUID) -> dict[str, Any] | None:
    return await _get_by_id("experiment_job", job_id)


async def list_experiment_jobs(
    project_id: UUID | None = None,
    experiment_plan_id: UUID | None = None,
    manifest_id: UUID | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    filters = {}
    if project_id is not None:
        filters["project_id"] = project_id
    if experiment_plan_id is not None:
        filters["experiment_plan_id"] = experiment_plan_id
    if manifest_id is not None:
        filters["manifest_id"] = manifest_id
    if status is not None:
        filters["status"] = status
    return await _list("experiment_job", filters=filters, limit=limit, offset=offset)


async def claim_experiment_jobs(
    job_ids: list[UUID],
    limit: int = 1,
    worker_id: str | None = None,
    lease_seconds: int = 3600,
) -> list[dict[str, Any]]:
    """Atomically claim specific pending experiment jobs in scheduler order."""

    if not job_ids:
        return []
    worker = worker_id or "scheduler"
    pool = await db_pool.get_pool()
    rows = await pool.fetch(
        f"""
        WITH requested(id, ord) AS (
            SELECT id, ord
            FROM unnest($1::uuid[]) WITH ORDINALITY AS t(id, ord)
        ),
        picked AS (
            SELECT experiment_job.id
            FROM experiment_job
            JOIN requested ON requested.id = experiment_job.id
            WHERE experiment_job.status = 'pending'
            ORDER BY requested.ord
            FOR UPDATE SKIP LOCKED
            LIMIT $2
        )
        UPDATE experiment_job
        SET
            status = 'running',
            started_at = COALESCE(started_at, NOW()),
            completed_at = NULL,
            last_heartbeat_at = NOW(),
            failure_reason = NULL,
            metrics_json = (COALESCE(metrics_json, '{{}}'::jsonb) - 'scheduler_heartbeat')
                || jsonb_build_object(
                    'scheduler_lease',
                    jsonb_build_object(
                        'lease_id', gen_random_uuid()::text,
                        'worker_id', $3::text,
                        'claimed_at', NOW(),
                        'claimed_until', NOW() + ($4::text || ' seconds')::interval,
                        'lease_seconds', $4
                    )
                )
        WHERE id IN (SELECT id FROM picked)
        RETURNING {_select_columns("experiment_job")}
        """,
        job_ids,
        limit,
        worker,
        lease_seconds,
    )
    return [db_pool.record_to_dict(row) for row in rows]


async def claim_experiment_job(
    job_id: UUID,
    *,
    worker_id: str | None = None,
    lease_seconds: int = 3600,
) -> dict[str, Any] | None:
    """Atomically claim one pending experiment job for a manual or scheduler worker."""

    worker = worker_id or "manual"
    pool = await db_pool.get_pool()
    row = await pool.fetchrow(
        f"""
        UPDATE experiment_job
        SET
            status = 'running',
            started_at = COALESCE(started_at, NOW()),
            completed_at = NULL,
            last_heartbeat_at = NOW(),
            failure_reason = NULL,
            metrics_json = (COALESCE(metrics_json, '{{}}'::jsonb) - 'scheduler_heartbeat')
                || jsonb_build_object(
                    'scheduler_lease',
                    jsonb_build_object(
                        'lease_id', gen_random_uuid()::text,
                        'worker_id', $2::text,
                        'claimed_at', NOW(),
                        'claimed_until', NOW() + ($3::text || ' seconds')::interval,
                        'lease_seconds', $3
                    )
                )
        WHERE id = $1
          AND status = 'pending'
        RETURNING {_select_columns("experiment_job")}
        """,
        job_id,
        worker,
        lease_seconds,
    )
    return db_pool.record_to_dict(row) if row is not None else None


async def recover_stale_experiment_jobs(stale_before: datetime) -> list[dict[str, Any]]:
    """Mark running experiment jobs stuck when their heartbeat lease expires."""

    pool = await db_pool.get_pool()
    rows = await pool.fetch(
        f"""
        UPDATE experiment_job
        SET
            status = 'stuck',
            failure_reason = 'scheduler_stale_heartbeat',
            last_heartbeat_at = NOW()
        WHERE status = 'running'
          AND COALESCE(
              NULLIF(metrics_json #>> '{{scheduler_heartbeat,claimed_until}}', '')::timestamptz,
              NULLIF(metrics_json #>> '{{scheduler_lease,claimed_until}}', '')::timestamptz,
              last_heartbeat_at,
              updated_at,
              started_at,
              created_at
          ) < $1
        RETURNING {_select_columns("experiment_job")}
        """,
        stale_before,
    )
    return [db_pool.record_to_dict(row) for row in rows]


_EXPERIMENT_JOB_UPDATABLE_COLUMNS = frozenset({
    "phase_name",
    "job_name",
    "executor_type",
    "remote_host_id",
    "cmd",
    "cwd",
    "pid",
    "status",
    "attempt",
    "max_attempts",
    "expected_outputs_json",
    "started_at",
    "completed_at",
    "last_heartbeat_at",
    "failure_reason",
    "metrics_json",
    "stdout_log_path",
    "stderr_log_path",
    "artifact_dir",
})


async def update_experiment_job(
    job_id: UUID,
    updates: dict[str, Any],
) -> dict[str, Any] | None:
    return await _update(
        "experiment_job",
        job_id,
        updates,
        _EXPERIMENT_JOB_UPDATABLE_COLUMNS,
    )


async def update_experiment_job_if_lease(
    job_id: UUID,
    updates: dict[str, Any],
    *,
    worker_id: str,
    lease_id: str,
) -> dict[str, Any] | None:
    """Update a running experiment job only while the caller owns its lease."""

    if not worker_id or not lease_id:
        return None
    invalid = set(updates) - _EXPERIMENT_JOB_UPDATABLE_COLUMNS
    if invalid:
        raise ValueError(f"Invalid column names: {invalid}")
    set_parts: list[str] = []
    values: list[Any] = []
    for idx, (column, value) in enumerate(updates.items(), start=1):
        set_parts.append(f"{column} = ${idx}")
        values.append(_db_value(value))
    values.extend([job_id, worker_id])
    values.append(lease_id)
    id_idx = len(values) - 2
    worker_idx = len(values) - 1
    lease_idx = len(values)
    pool = await db_pool.get_pool()
    row = await pool.fetchrow(
        f"""
        UPDATE experiment_job
        SET {', '.join(set_parts)}
        WHERE id = ${id_idx}
          AND status = 'running'
          AND metrics_json #>> '{{scheduler_lease,worker_id}}' = ${worker_idx}
          AND metrics_json #>> '{{scheduler_lease,lease_id}}' = ${lease_idx}
        RETURNING {_select_columns("experiment_job")}
        """,
        *values,
    )
    return db_pool.record_to_dict(row) if row is not None else None


async def heartbeat_experiment_job_if_lease(
    job_id: UUID,
    *,
    worker_id: str,
    lease_id: str,
    heartbeat: dict[str, Any],
    last_heartbeat_at: datetime,
) -> dict[str, Any] | None:
    if not worker_id or not lease_id:
        return None
    pool = await db_pool.get_pool()
    row = await pool.fetchrow(
        f"""
        UPDATE experiment_job
        SET
            last_heartbeat_at = $5,
            metrics_json = jsonb_set(
                COALESCE(metrics_json, '{{}}'::jsonb),
                '{{scheduler_heartbeat}}',
                $4::jsonb,
                true
            )
        WHERE id = $1
          AND status = 'running'
          AND metrics_json #>> '{{scheduler_lease,worker_id}}' = $2
          AND metrics_json #>> '{{scheduler_lease,lease_id}}' = $3
        RETURNING {_select_columns("experiment_job")}
        """,
        job_id,
        worker_id,
        lease_id,
        json.dumps(heartbeat),
        last_heartbeat_at,
    )
    return db_pool.record_to_dict(row) if row is not None else None


CLAIM_LEDGER_COLUMNS = (
    "project_id",
    "experiment_plan_id",
    "claim_text",
    "claim_type",
    "status",
    "support_level",
    "evidence_summary",
    "reviewer_model",
    "human_decision",
)


async def create_claim_ledger_entry(data: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "experiment_plan_id": None,
        "claim_type": "main",
        "status": "proposed",
        "support_level": None,
        "evidence_summary": None,
        "reviewer_model": None,
        "human_decision": None,
        **data,
    }
    return await _insert("claim_ledger", CLAIM_LEDGER_COLUMNS, payload)


async def list_claim_ledger(
    project_id: UUID | None = None,
    experiment_plan_id: UUID | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    filters = {}
    if project_id is not None:
        filters["project_id"] = project_id
    if experiment_plan_id is not None:
        filters["experiment_plan_id"] = experiment_plan_id
    if status is not None:
        filters["status"] = status
    return await _list("claim_ledger", filters=filters, limit=limit, offset=offset)


CLAIM_EVIDENCE_COLUMNS = (
    "claim_id",
    "source_type",
    "source_id",
    "quote_or_metric",
    "artifact_path",
    "support_relation",
)


async def create_claim_evidence(data: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "source_id": None,
        "quote_or_metric": None,
        "artifact_path": None,
        **data,
    }
    return await _insert("claim_evidence", CLAIM_EVIDENCE_COLUMNS, payload)


REMOTE_HOST_COLUMNS = (
    "name",
    "owner_user_id",
    "host",
    "port",
    "username",
    "auth_type",
    "key_ref",
    "default_workdir",
    "default_env_json",
    "capabilities_json",
    "status",
    "last_checked_at",
)


async def create_remote_host(data: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "port": 22,
        "username": None,
        "auth_type": "agent",
        "key_ref": None,
        "default_workdir": None,
        "default_env_json": {},
        "capabilities_json": {},
        "status": "unknown",
        "last_checked_at": None,
        **data,
    }
    if payload.get("owner_user_id") is None:
        raise ValueError("owner_user_id is required for remote hosts")
    return await _insert("remote_host", REMOTE_HOST_COLUMNS, payload)


async def get_remote_host(remote_host_id: UUID) -> dict[str, Any] | None:
    return await _get_by_id("remote_host", remote_host_id)


async def list_remote_hosts(
    status: str | None = None,
    owner_user_id: UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    filters = {}
    if status is not None:
        filters["status"] = status
    if owner_user_id is not None:
        filters["owner_user_id"] = owner_user_id
    return await _list("remote_host", filters=filters, limit=limit, offset=offset)


MANUSCRIPT_PACKAGE_COLUMNS = (
    "project_id",
    "title",
    "venue_target",
    "paper_dir",
    "status",
    "claim_ledger_snapshot_id",
    "bib_snapshot_id",
    "artifact_snapshot_id",
)


async def create_manuscript_package(data: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "venue_target": None,
        "paper_dir": None,
        "status": "outline",
        "claim_ledger_snapshot_id": None,
        "bib_snapshot_id": None,
        "artifact_snapshot_id": None,
        **data,
    }
    return await _insert("manuscript_package", MANUSCRIPT_PACKAGE_COLUMNS, payload)


async def get_manuscript_package(manuscript_id: UUID) -> dict[str, Any] | None:
    return await _get_by_id("manuscript_package", manuscript_id)


async def list_manuscript_packages(
    project_id: UUID | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    filters = {}
    if project_id is not None:
        filters["project_id"] = project_id
    if status is not None:
        filters["status"] = status
    return await _list(
        "manuscript_package",
        filters=filters,
        limit=limit,
        offset=offset,
    )


async def update_manuscript_package(
    manuscript_id: UUID,
    updates: dict[str, Any],
) -> dict[str, Any] | None:
    return await _update(
        "manuscript_package",
        manuscript_id,
        updates,
        frozenset({
            "title",
            "venue_target",
            "paper_dir",
            "status",
            "claim_ledger_snapshot_id",
            "bib_snapshot_id",
            "artifact_snapshot_id",
        }),
    )


SUBMISSION_PACKAGE_COLUMNS = (
    "manuscript_package_id",
    "venue",
    "deadline",
    "submission_dir",
    "checklist_json",
    "anonymity_report_json",
    "compile_report_json",
    "claim_audit_report_json",
    "citation_audit_report_json",
    "artifact_provenance_report_json",
    "paper_claim_audit_report_json",
    "adversarial_audit_report_json",
    "status",
)


async def create_submission_package(data: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "deadline": None,
        "submission_dir": None,
        "checklist_json": {},
        "anonymity_report_json": {},
        "compile_report_json": {},
        "claim_audit_report_json": {},
        "citation_audit_report_json": {},
        "artifact_provenance_report_json": {},
        "paper_claim_audit_report_json": {},
        "adversarial_audit_report_json": {},
        "status": "preparing",
        **data,
    }
    return await _insert("submission_package", SUBMISSION_PACKAGE_COLUMNS, payload)


async def get_submission_package(submission_id: UUID) -> dict[str, Any] | None:
    return await _get_by_id("submission_package", submission_id)


async def list_submission_packages(
    manuscript_package_id: UUID | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    filters = {}
    if manuscript_package_id is not None:
        filters["manuscript_package_id"] = manuscript_package_id
    if status is not None:
        filters["status"] = status
    return await _list(
        "submission_package",
        filters=filters,
        limit=limit,
        offset=offset,
    )


async def update_submission_package(
    submission_id: UUID,
    updates: dict[str, Any],
) -> dict[str, Any] | None:
    return await _update(
        "submission_package",
        submission_id,
        updates,
        frozenset({
            "venue",
            "deadline",
            "submission_dir",
            "checklist_json",
            "anonymity_report_json",
            "compile_report_json",
            "claim_audit_report_json",
            "citation_audit_report_json",
            "artifact_provenance_report_json",
            "paper_claim_audit_report_json",
            "adversarial_audit_report_json",
            "status",
        }),
    )


TERMINAL_SESSION_COLUMNS = (
    "project_id",
    "run_id",
    "experiment_job_id",
    "session_type",
    "remote_host_id",
    "cwd",
    "shell",
    "status",
    "created_by",
    "closed_at",
)


async def create_terminal_session(data: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "project_id": None,
        "run_id": None,
        "experiment_job_id": None,
        "session_type": "local",
        "remote_host_id": None,
        "cwd": None,
        "shell": None,
        "status": "opening",
        "created_by": None,
        "closed_at": None,
        **data,
    }
    return await _insert("terminal_session", TERMINAL_SESSION_COLUMNS, payload)


async def get_terminal_session(session_id: UUID) -> dict[str, Any] | None:
    return await _get_by_id("terminal_session", session_id)


async def list_terminal_sessions(
    project_id: UUID | None = None,
    run_id: UUID | None = None,
    experiment_job_id: UUID | None = None,
    status: str | None = None,
    created_by: UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    filters = {}
    if project_id is not None:
        filters["project_id"] = project_id
    if run_id is not None:
        filters["run_id"] = run_id
    if experiment_job_id is not None:
        filters["experiment_job_id"] = experiment_job_id
    if status is not None:
        filters["status"] = status
    if created_by is not None:
        filters["created_by"] = created_by
    return await _list("terminal_session", filters=filters, limit=limit, offset=offset)


async def update_terminal_session(
    session_id: UUID,
    updates: dict[str, Any],
) -> dict[str, Any] | None:
    return await _update(
        "terminal_session",
        session_id,
        updates,
        frozenset({"remote_host_id", "cwd", "shell", "status", "closed_at"}),
    )


TABLE_RESPONSE_COLUMNS: dict[str, tuple[str, ...]] = {
    "research_project": ("id", *PROJECT_COLUMNS, "created_at", "updated_at"),
    "project_query_pack": ("id", *QUERY_PACK_COLUMNS, "created_at", "updated_at"),
    "experiment_plan": ("id", *EXPERIMENT_PLAN_COLUMNS, "created_at", "updated_at"),
    "coding_task": ("id", *CODING_TASK_COLUMNS, "created_at", "updated_at"),
    "coding_event": ("id", *CODING_EVENT_COLUMNS, "created_at"),
    "code_artifact": ("id", *CODE_ARTIFACT_COLUMNS, "created_at"),
    "experiment_manifest": ("id", *EXPERIMENT_MANIFEST_COLUMNS, "created_at", "updated_at"),
    "experiment_job": ("id", *EXPERIMENT_JOB_COLUMNS, "created_at", "updated_at"),
    "claim_ledger": ("id", *CLAIM_LEDGER_COLUMNS, "created_at", "updated_at"),
    "claim_evidence": ("id", *CLAIM_EVIDENCE_COLUMNS, "created_at"),
    "remote_host": ("id", *REMOTE_HOST_COLUMNS, "created_at", "updated_at"),
    "manuscript_package": ("id", *MANUSCRIPT_PACKAGE_COLUMNS, "created_at", "updated_at"),
    "submission_package": ("id", *SUBMISSION_PACKAGE_COLUMNS, "created_at", "updated_at"),
    "terminal_session": ("id", *TERMINAL_SESSION_COLUMNS, "created_at"),
}
