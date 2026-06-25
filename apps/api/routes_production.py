"""Automated research production API routes."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
from datetime import datetime, timezone
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.security import HTTPAuthorizationCredentials

from apps.api.auth import decode_token, get_user_by_id, security
import apps.api.database as db
from apps.worker.production.terminal import terminal_manager
from apps.worker.production.workspaces import (
    list_job_artifacts,
    read_workspace_file,
    resolve_path_reference,
    resolve_project_workspace_path,
    tail_job_log,
    tree_workspace,
    workspace_base,
)
from libs.schemas.production import (
    ClaimLedgerCreate,
    ClaimLedgerResponse,
    CodeArtifactCreate,
    CodeArtifactResponse,
    CodingEventCreate,
    CodingEventResponse,
    CodingTaskPatch,
    CodingTaskCreate,
    CodingTaskResponse,
    ExperimentJobCreate,
    ExperimentJobPatch,
    ExperimentJobResponse,
    ExperimentManifestCreate,
    ExperimentManifestResponse,
    ExperimentPlanStatusPatch,
    ExperimentPlanCreate,
    ExperimentPlanResponse,
    ManuscriptPackageCreate,
    ManuscriptPackageResponse,
    ProjectCreate,
    ProjectQueryPackCreate,
    ProjectQueryPackResponse,
    ProjectResponse,
    RemoteHostCreate,
    RemoteHostResponse,
    SubmissionPackageCreate,
    SubmissionPackageResponse,
    TerminalSessionCreate,
    TerminalResizeRequest,
    TerminalSessionPatch,
    TerminalSessionResponse,
)

try:
    from apps.worker.production.coding_agents.runtime_detection import detect_runtime
except Exception:  # pragma: no cover - only used if worker runtime code is unavailable.
    def detect_runtime(provider: str) -> dict[str, Any]:
        return {
            "provider": provider,
            "status": "unsupported",
            "failure_reason": "runtime_detection_unavailable",
        }

PRODUCTION_OPERATOR_ROLES = {"admin", "production_operator", "operator"}


async def require_production_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> dict[str, Any]:
    """Strict auth dependency for shell/file/execution production endpoints."""

    if credentials is None:
        raise HTTPException(status_code=401, detail="Production authentication required")
    payload = decode_token(credentials.credentials)
    user = await get_user_by_id(UUID(payload["sub"]))
    if user is None or not user.get("is_active", False):
        raise HTTPException(status_code=401, detail="User not found or disabled")
    if user.get("role") not in PRODUCTION_OPERATOR_ROLES:
        raise HTTPException(status_code=403, detail="Production operator role required")
    return user


router = APIRouter(
    prefix="/api/v1/production",
    tags=["production"],
)

Limit50 = Annotated[int, Query(ge=1, le=100)]
Limit100 = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]

RUNTIME_PROVIDERS = ("codex", "claude", "copilot", "cursor", "opencode")

EXPERIMENT_PLAN_PATCH_FIELDS = frozenset({"status"})
CODING_TASK_PATCH_FIELDS = frozenset({
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
EXPERIMENT_JOB_PATCH_FIELDS = frozenset({
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
TERMINAL_SESSION_PATCH_FIELDS = frozenset({
    "remote_host_id",
    "cwd",
    "shell",
    "status",
    "closed_at",
})


def _payload(model: Any) -> dict[str, Any]:
    return model.model_dump()


def _coding_task_payload(request: CodingTaskCreate) -> dict[str, Any]:
    payload = request.model_dump()
    payload["env_json"] = payload.pop("env")
    payload["mcp_config_json"] = payload.pop("mcp_config") or {}
    return payload


def _allowlisted(body: dict[str, Any], allowed: frozenset[str]) -> dict[str, Any]:
    return {key: value for key, value in body.items() if key in allowed}


def _patch_payload(model: Any) -> dict[str, Any]:
    if isinstance(model, dict):
        return model
    return model.model_dump(exclude_unset=True)


def _runtime_payload(runtime: Any) -> dict[str, Any]:
    if hasattr(runtime, "model_dump"):
        return runtime.model_dump()
    if isinstance(runtime, dict):
        return runtime
    return dict(runtime)


def _enum_value(value: Any) -> Any:
    return getattr(value, "value", value)


def get_orchestrator() -> Any:
    from apps.worker.production import orchestrator

    return orchestrator


def _orchestrator_error(exc: ValueError) -> HTTPException:
    detail = str(exc)
    status_code = 404 if "not found" in detail.lower() else 400
    return HTTPException(status_code=status_code, detail=detail)


def _same_id(left: Any, right: Any) -> bool:
    return str(left) == str(right)


async def _project_for_access(project_id: UUID, user: dict[str, Any]) -> dict[str, Any]:
    project = await db.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    workspace_id = project.get("workspace_id")
    if workspace_id is not None:
        if _same_id(workspace_id, user["workspace_id"]):
            return project
        raise HTTPException(status_code=403, detail="Project access denied")
    owner_user_id = project.get("owner_user_id")
    if owner_user_id is None or not _same_id(owner_user_id, user["id"]):
        raise HTTPException(status_code=403, detail="Project access denied")
    return project


async def _task_for_access(task_id: UUID, user: dict[str, Any]) -> dict[str, Any]:
    task = await db.get_coding_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Coding task not found")
    await _project_for_access(task["project_id"], user)
    return task


async def _plan_for_access(plan_id: UUID, user: dict[str, Any]) -> dict[str, Any]:
    plan = await db.get_experiment_plan(plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Experiment plan not found")
    await _project_for_access(plan["project_id"], user)
    return plan


async def _manifest_for_access(manifest_id: UUID, user: dict[str, Any]) -> dict[str, Any]:
    manifest = await db.get_experiment_manifest(manifest_id)
    if manifest is None:
        raise HTTPException(status_code=404, detail="Experiment manifest not found")
    await _project_for_access(manifest["project_id"], user)
    return manifest


async def _job_for_access(job_id: UUID, user: dict[str, Any]) -> dict[str, Any]:
    job = await db.get_experiment_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Experiment job not found")
    await _project_for_access(job["project_id"], user)
    return job


async def _manuscript_for_access(manuscript_id: UUID, user: dict[str, Any]) -> dict[str, Any]:
    manuscript = await db.get_manuscript_package(manuscript_id)
    if manuscript is None:
        raise HTTPException(status_code=404, detail="Manuscript package not found")
    await _project_for_access(manuscript["project_id"], user)
    return manuscript


async def _submission_for_access(submission_id: UUID, user: dict[str, Any]) -> dict[str, Any]:
    submission = await db.get_submission_package(submission_id)
    if submission is None:
        raise HTTPException(status_code=404, detail="Submission package not found")
    await _manuscript_for_access(submission["manuscript_package_id"], user)
    return submission


async def _remote_host_for_access(remote_host_id: UUID, user: dict[str, Any]) -> dict[str, Any]:
    remote_host = await db.get_remote_host(remote_host_id)
    if remote_host is None:
        raise HTTPException(status_code=404, detail="Remote host not found")
    owner_user_id = remote_host.get("owner_user_id")
    if owner_user_id is None or not _same_id(owner_user_id, user["id"]):
        raise HTTPException(status_code=403, detail="Remote host access denied")
    return remote_host


def _assert_same_project(row: dict[str, Any], project_id: UUID, label: str) -> None:
    row_project_id = row.get("project_id")
    if row_project_id is not None and not _same_id(row_project_id, project_id):
        raise HTTPException(status_code=400, detail=f"{label} project_id mismatch")


async def _validate_plan_reference(plan_id: UUID | None, project_id: UUID, user: dict[str, Any]) -> None:
    if plan_id is None:
        return
    plan = await _plan_for_access(plan_id, user)
    _assert_same_project(plan, project_id, "experiment_plan_id")


async def _validate_task_reference(task_id: UUID | None, project_id: UUID, user: dict[str, Any]) -> None:
    if task_id is None:
        return
    task = await _task_for_access(task_id, user)
    _assert_same_project(task, project_id, "coding_task_id")


async def _validate_manifest_reference(manifest_id: UUID | None, project_id: UUID, user: dict[str, Any]) -> None:
    if manifest_id is None:
        return
    manifest = await _manifest_for_access(manifest_id, user)
    _assert_same_project(manifest, project_id, "manifest_id")


async def _validate_job_reference(job_id: UUID | None, project_id: UUID | None, user: dict[str, Any]) -> dict[str, Any] | None:
    if job_id is None:
        return None
    job = await _job_for_access(job_id, user)
    if project_id is not None:
        _assert_same_project(job, project_id, "experiment_job_id")
    return job


async def _filter_owned_rows(rows: list[dict[str, Any]], user: dict[str, Any]) -> list[dict[str, Any]]:
    owned: list[dict[str, Any]] = []
    for row in rows:
        try:
            await _project_for_access(row["project_id"], user)
        except HTTPException:
            continue
        owned.append(row)
    return owned


def _assert_terminal_access(row: dict[str, Any], user: dict[str, Any]) -> None:
    created_by = row.get("created_by")
    if created_by is None or not _same_id(created_by, user["id"]):
        raise HTTPException(status_code=403, detail="Terminal session access denied")


async def _terminal_session_for_access(session_id: UUID, user: dict[str, Any]) -> dict[str, Any]:
    row = await db.get_terminal_session(session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Terminal session not found")
    _assert_terminal_access(row, user)
    if row.get("project_id") is not None:
        await _project_for_access(row["project_id"], user)
    return row


def _local_job_result_payload(result: Any) -> dict[str, Any]:
    return {
        "job_id": result.job_id,
        "status": result.status,
        "returncode": result.returncode,
        "stdout_log": str(result.stdout_log),
        "stderr_log": str(result.stderr_log),
        "expected_outputs_found": [str(path) for path in result.expected_outputs_found],
        "missing_expected_outputs": [str(path) for path in result.missing_expected_outputs],
        "failure_reason": result.failure_reason,
        "duration_ms": result.duration_ms,
    }


def _codex_task_run_payload(result: Any) -> dict[str, Any]:
    return {
        "task": result.task,
        "events": result.events,
        "output": result.output,
        "status": result.status,
        "failure_reason": result.failure_reason,
        "failure_detail": result.failure_detail,
    }


async def _terminal_cwd(request: TerminalSessionCreate, project_id: UUID | None = None) -> str | None:
    if request.session_type != "local":
        return request.cwd
    resolved_project_id = project_id or request.project_id
    if resolved_project_id is not None:
        project = await db.get_project(resolved_project_id)
        if project is None:
            raise ValueError(f"Project not found: {resolved_project_id}")
        root = resolve_project_workspace_path(project, run_id=request.run_id)
    else:
        root = workspace_base()
    if request.cwd:
        return str(resolve_path_reference(root, request.cwd, field_name="cwd"))
    return str(root)


async def _terminal_patch_updates(
    existing: dict[str, Any],
    body: TerminalSessionPatch | dict[str, Any],
    user: dict[str, Any],
) -> dict[str, Any]:
    patch = body if isinstance(body, TerminalSessionPatch) else TerminalSessionPatch.model_validate(body)
    updates = _allowlisted(_patch_payload(patch), TERMINAL_SESSION_PATCH_FIELDS)
    if not updates:
        raise HTTPException(status_code=400, detail="No valid fields to update")
    if updates.get("remote_host_id") is not None:
        await _remote_host_for_access(updates["remote_host_id"], user)
    if "cwd" in updates:
        request = TerminalSessionCreate(
            project_id=existing.get("project_id"),
            run_id=existing.get("run_id"),
            experiment_job_id=existing.get("experiment_job_id"),
            session_type=existing.get("session_type") or "local",
            remote_host_id=updates.get("remote_host_id", existing.get("remote_host_id")),
            cwd=updates["cwd"],
            shell=updates.get("shell", existing.get("shell")),
            status=existing.get("status") or "opening",
            created_by=existing.get("created_by"),
            closed_at=existing.get("closed_at"),
        )
        updates["cwd"] = await _terminal_cwd(request, project_id=existing.get("project_id"))
    return updates


def _websocket_bearer_token(websocket: WebSocket) -> str | None:
    headers = {
        key.decode("latin1").lower(): value.decode("latin1")
        for key, value in websocket.scope.get("headers", [])
    }
    auth_header = headers.get("authorization")
    if auth_header and auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    return None


async def _receive_terminal_auth_token(websocket: WebSocket) -> str | None:
    try:
        message = await asyncio.wait_for(websocket.receive_text(), timeout=5)
    except (asyncio.TimeoutError, WebSocketDisconnect):
        return None
    try:
        payload = json.loads(message)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict) or payload.get("type") != "auth":
        return None
    token = payload.get("token")
    return token if isinstance(token, str) and token else None


async def _authorize_terminal_token(token: str | None, row: dict[str, Any]) -> dict[str, Any]:
    if not token:
        raise HTTPException(status_code=401, detail="missing terminal token")
    payload = decode_token(token)
    user = await get_user_by_id(UUID(payload["sub"]))
    if user is None or not user.get("is_active", False):
        raise HTTPException(status_code=401, detail="User not found or disabled")
    if user.get("role") not in PRODUCTION_OPERATOR_ROLES:
        raise HTTPException(status_code=403, detail="Production operator role required")
    created_by = row.get("created_by")
    if created_by is None:
        raise HTTPException(status_code=403, detail="terminal session owner missing")
    if str(created_by) != str(payload.get("sub")):
        raise HTTPException(status_code=403, detail="terminal session owner mismatch")
    return user


@router.get("/agent-runtimes")
async def list_agent_runtimes(
    providers: str | None = None,
    user: dict[str, Any] = Depends(require_production_user),
) -> list[dict[str, Any]]:
    requested = (
        tuple(provider.strip() for provider in providers.split(",") if provider.strip())
        if providers
        else RUNTIME_PROVIDERS
    )
    return [_runtime_payload(detect_runtime(provider)) for provider in requested]


@router.post("/agent-runtimes/detect")
async def detect_agent_runtime(
    request: dict[str, Any],
    user: dict[str, Any] = Depends(require_production_user),
) -> dict[str, Any]:
    provider = str(request.get("provider", "codex"))
    return _runtime_payload(detect_runtime(provider))


@router.post("/projects", response_model=ProjectResponse, status_code=201)
async def create_project(
    request: ProjectCreate,
    user: dict[str, Any] = Depends(require_production_user),
) -> dict[str, Any]:
    payload = _payload(request)
    payload["owner_user_id"] = user["id"]
    payload["workspace_id"] = user["workspace_id"]
    return await db.create_project(payload)


@router.get("/projects", response_model=list[ProjectResponse])
async def list_projects(
    status: str | None = None,
    limit: Limit50 = 50,
    offset: Offset = 0,
    user: dict[str, Any] = Depends(require_production_user),
) -> list[dict[str, Any]]:
    return await db.list_projects(
        status=status,
        workspace_id=user["workspace_id"],
        limit=limit,
        offset=offset,
    )


@router.get("/projects/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: UUID,
    user: dict[str, Any] = Depends(require_production_user),
) -> dict[str, Any]:
    return await _project_for_access(project_id, user)


@router.post(
    "/projects/{project_id}/query-packs",
    response_model=ProjectQueryPackResponse,
    status_code=201,
)
async def create_project_query_pack(
    project_id: UUID,
    request: ProjectQueryPackCreate,
    user: dict[str, Any] = Depends(require_production_user),
) -> dict[str, Any]:
    await _project_for_access(project_id, user)
    payload = _payload(request)
    if payload["project_id"] != project_id:
        raise HTTPException(status_code=400, detail="project_id mismatch")
    return await db.create_project_query_pack(payload)


@router.get(
    "/projects/{project_id}/query-packs",
    response_model=list[ProjectQueryPackResponse],
)
async def list_project_query_packs(
    project_id: UUID,
    limit: Limit50 = 50,
    offset: Offset = 0,
    user: dict[str, Any] = Depends(require_production_user),
) -> list[dict[str, Any]]:
    await _project_for_access(project_id, user)
    return await db.list_project_query_packs(project_id, limit=limit, offset=offset)


@router.post(
    "/experiment-plans",
    response_model=ExperimentPlanResponse,
    status_code=201,
)
async def create_experiment_plan(
    request: ExperimentPlanCreate,
    user: dict[str, Any] = Depends(require_production_user),
) -> dict[str, Any]:
    await _project_for_access(request.project_id, user)
    return await db.create_experiment_plan(_payload(request))


@router.get("/experiment-plans", response_model=list[ExperimentPlanResponse])
async def list_experiment_plans(
    project_id: UUID | None = None,
    status: str | None = None,
    limit: Limit50 = 50,
    offset: Offset = 0,
    user: dict[str, Any] = Depends(require_production_user),
) -> list[dict[str, Any]]:
    if project_id is not None:
        await _project_for_access(project_id, user)
    rows = await db.list_experiment_plans(
        project_id=project_id,
        status=status,
        limit=limit,
        offset=offset,
    )
    return rows if project_id is not None else await _filter_owned_rows(rows, user)


@router.get("/experiment-plans/{plan_id}", response_model=ExperimentPlanResponse)
async def get_experiment_plan(
    plan_id: UUID,
    user: dict[str, Any] = Depends(require_production_user),
) -> dict[str, Any]:
    return await _plan_for_access(plan_id, user)


@router.patch("/experiment-plans/{plan_id}/status", response_model=ExperimentPlanResponse)
async def patch_experiment_plan_status(
    plan_id: UUID,
    body: ExperimentPlanStatusPatch,
    user: dict[str, Any] = Depends(require_production_user),
) -> dict[str, Any]:
    await _plan_for_access(plan_id, user)
    updates = _allowlisted(_patch_payload(body), EXPERIMENT_PLAN_PATCH_FIELDS)
    if "status" not in updates:
        raise HTTPException(status_code=400, detail="No valid fields to update")
    row = await db.update_experiment_plan_status(plan_id, updates["status"])
    if row is None:
        raise HTTPException(status_code=404, detail="Experiment plan not found")
    return row


@router.post("/coding-tasks", response_model=CodingTaskResponse, status_code=201)
async def create_coding_task(
    request: CodingTaskCreate,
    user: dict[str, Any] = Depends(require_production_user),
) -> dict[str, Any]:
    await _project_for_access(request.project_id, user)
    await _validate_plan_reference(request.experiment_plan_id, request.project_id, user)
    try:
        return await get_orchestrator().create_coding_task(_coding_task_payload(request))
    except ValueError as exc:
        raise _orchestrator_error(exc) from exc


@router.get("/coding-tasks", response_model=list[CodingTaskResponse])
async def list_coding_tasks(
    project_id: UUID | None = None,
    run_id: UUID | None = None,
    status: str | None = None,
    limit: Limit50 = 50,
    offset: Offset = 0,
    user: dict[str, Any] = Depends(require_production_user),
) -> list[dict[str, Any]]:
    if project_id is not None:
        await _project_for_access(project_id, user)
    rows = await db.list_coding_tasks(
        project_id=project_id,
        run_id=run_id,
        status=status,
        limit=limit,
        offset=offset,
    )
    return rows if project_id is not None else await _filter_owned_rows(rows, user)


@router.get("/coding-tasks/{task_id}", response_model=CodingTaskResponse)
async def get_coding_task(
    task_id: UUID,
    user: dict[str, Any] = Depends(require_production_user),
) -> dict[str, Any]:
    return await _task_for_access(task_id, user)


@router.patch("/coding-tasks/{task_id}")
async def patch_coding_task(
    task_id: UUID,
    body: CodingTaskPatch,
    user: dict[str, Any] = Depends(require_production_user),
) -> dict[str, Any]:
    await _task_for_access(task_id, user)
    updates = _allowlisted(_patch_payload(body), CODING_TASK_PATCH_FIELDS)
    if not updates:
        raise HTTPException(status_code=400, detail="No valid fields to update")
    row = await db.update_coding_task(task_id, updates)
    if row is None:
        raise HTTPException(status_code=404, detail="Coding task not found")
    return row


@router.post("/coding-tasks/{task_id}/run")
async def run_coding_task(
    task_id: UUID,
    user: dict[str, Any] = Depends(require_production_user),
) -> dict[str, Any]:
    await _task_for_access(task_id, user)
    claimed = await db.claim_coding_task(
        task_id,
        worker_id=f"manual-{user['id']}",
        lease_seconds=3600,
    )
    if claimed is None:
        raise HTTPException(status_code=409, detail="Coding task is already running or not queued")
    try:
        run = await get_orchestrator().run_codex_task(
            task_id,
            preclaimed=True,
            claimed_task=claimed,
        )
    except ValueError as exc:
        raise _orchestrator_error(exc) from exc
    return _codex_task_run_payload(run)


@router.post(
    "/coding-tasks/{task_id}/events",
    response_model=CodingEventResponse,
    status_code=201,
)
async def create_coding_event(
    task_id: UUID,
    request: CodingEventCreate,
    user: dict[str, Any] = Depends(require_production_user),
) -> dict[str, Any]:
    await _task_for_access(task_id, user)
    payload = _payload(request)
    if payload["coding_task_id"] != task_id:
        raise HTTPException(status_code=400, detail="coding_task_id mismatch")
    return await db.create_coding_event(payload)


@router.get("/coding-tasks/{task_id}/events", response_model=list[CodingEventResponse])
async def list_coding_events(
    task_id: UUID,
    limit: Limit100 = 100,
    offset: Offset = 0,
    user: dict[str, Any] = Depends(require_production_user),
) -> list[dict[str, Any]]:
    await _task_for_access(task_id, user)
    return await db.list_coding_events(task_id, limit=limit, offset=offset)


@router.post("/code-artifacts", response_model=CodeArtifactResponse, status_code=201)
async def create_code_artifact(
    request: CodeArtifactCreate,
    user: dict[str, Any] = Depends(require_production_user),
) -> dict[str, Any]:
    await _project_for_access(request.project_id, user)
    await _validate_task_reference(request.coding_task_id, request.project_id, user)
    await _validate_plan_reference(request.experiment_plan_id, request.project_id, user)
    return await db.create_code_artifact(_payload(request))


@router.get("/code-artifacts", response_model=list[CodeArtifactResponse])
async def list_code_artifacts(
    project_id: UUID | None = None,
    coding_task_id: UUID | None = None,
    experiment_plan_id: UUID | None = None,
    artifact_type: str | None = None,
    limit: Limit50 = 50,
    offset: Offset = 0,
    user: dict[str, Any] = Depends(require_production_user),
) -> list[dict[str, Any]]:
    if project_id is not None:
        await _project_for_access(project_id, user)
    rows = await db.list_code_artifacts(
        project_id=project_id,
        coding_task_id=coding_task_id,
        experiment_plan_id=experiment_plan_id,
        artifact_type=artifact_type,
        limit=limit,
        offset=offset,
    )
    return rows if project_id is not None else await _filter_owned_rows(rows, user)


@router.post(
    "/experiment-manifests",
    response_model=ExperimentManifestResponse,
    status_code=201,
)
async def create_experiment_manifest(
    request: ExperimentManifestCreate,
    user: dict[str, Any] = Depends(require_production_user),
) -> dict[str, Any]:
    await _project_for_access(request.project_id, user)
    await _validate_plan_reference(request.experiment_plan_id, request.project_id, user)
    await _validate_task_reference(request.generated_by_coding_task_id, request.project_id, user)
    return await db.create_experiment_manifest(_payload(request))


@router.get(
    "/experiment-manifests",
    response_model=list[ExperimentManifestResponse],
)
async def list_experiment_manifests(
    project_id: UUID | None = None,
    experiment_plan_id: UUID | None = None,
    limit: Limit50 = 50,
    offset: Offset = 0,
    user: dict[str, Any] = Depends(require_production_user),
) -> list[dict[str, Any]]:
    if project_id is not None:
        await _project_for_access(project_id, user)
    rows = await db.list_experiment_manifests(
        project_id=project_id,
        experiment_plan_id=experiment_plan_id,
        limit=limit,
        offset=offset,
    )
    return rows if project_id is not None else await _filter_owned_rows(rows, user)


@router.post(
    "/experiment-manifests/{manifest_id}/jobs/expand",
    response_model=list[ExperimentJobResponse],
    status_code=201,
)
async def expand_experiment_manifest_jobs(
    manifest_id: UUID,
    user: dict[str, Any] = Depends(require_production_user),
) -> list[dict[str, Any]]:
    await _manifest_for_access(manifest_id, user)
    try:
        return await get_orchestrator().create_manifest_jobs(manifest_id)
    except ValueError as exc:
        raise _orchestrator_error(exc) from exc


@router.post("/experiment-jobs", response_model=ExperimentJobResponse, status_code=201)
async def create_experiment_job(
    request: ExperimentJobCreate,
    user: dict[str, Any] = Depends(require_production_user),
) -> dict[str, Any]:
    await _project_for_access(request.project_id, user)
    await _validate_manifest_reference(request.manifest_id, request.project_id, user)
    await _validate_plan_reference(request.experiment_plan_id, request.project_id, user)
    if request.remote_host_id is not None:
        await _remote_host_for_access(request.remote_host_id, user)
    if _enum_value(request.executor_type) == "ssh" and request.remote_host_id is None:
        raise HTTPException(status_code=400, detail="remote_host_id is required for ssh jobs")
    return await db.create_experiment_job(_payload(request))


@router.get("/experiment-jobs", response_model=list[ExperimentJobResponse])
async def list_experiment_jobs(
    project_id: UUID | None = None,
    experiment_plan_id: UUID | None = None,
    manifest_id: UUID | None = None,
    status: str | None = None,
    limit: Limit50 = 50,
    offset: Offset = 0,
    user: dict[str, Any] = Depends(require_production_user),
) -> list[dict[str, Any]]:
    if project_id is not None:
        await _project_for_access(project_id, user)
    rows = await db.list_experiment_jobs(
        project_id=project_id,
        experiment_plan_id=experiment_plan_id,
        manifest_id=manifest_id,
        status=status,
        limit=limit,
        offset=offset,
    )
    return rows if project_id is not None else await _filter_owned_rows(rows, user)


@router.get("/experiment-jobs/{job_id}", response_model=ExperimentJobResponse)
async def get_experiment_job(
    job_id: UUID,
    user: dict[str, Any] = Depends(require_production_user),
) -> dict[str, Any]:
    return await _job_for_access(job_id, user)


@router.post("/experiment-jobs/{job_id}/run-local")
async def run_local_experiment_job(
    job_id: UUID,
    body: dict[str, Any] | None = None,
    user: dict[str, Any] = Depends(require_production_user),
) -> dict[str, Any]:
    await _job_for_access(job_id, user)
    claimed = await db.claim_experiment_job(
        job_id,
        worker_id=f"manual-{user['id']}",
        lease_seconds=3600,
    )
    if claimed is None:
        raise HTTPException(status_code=409, detail="Experiment job is already running or not pending")
    try:
        run = await get_orchestrator().run_local_job(
            job_id,
            preclaimed=True,
            claimed_job=claimed,
        )
    except ValueError as exc:
        raise _orchestrator_error(exc) from exc
    return {"job": run.row, "result": _local_job_result_payload(run.result)}


@router.patch("/experiment-jobs/{job_id}")
async def patch_experiment_job(
    job_id: UUID,
    body: ExperimentJobPatch,
    user: dict[str, Any] = Depends(require_production_user),
) -> dict[str, Any]:
    existing = await _job_for_access(job_id, user)
    updates = _allowlisted(_patch_payload(body), EXPERIMENT_JOB_PATCH_FIELDS)
    if not updates:
        raise HTTPException(status_code=400, detail="No valid fields to update")
    if updates.get("remote_host_id") is not None:
        await _remote_host_for_access(updates["remote_host_id"], user)
    executor_type = _enum_value(updates.get("executor_type") or existing.get("executor_type") or "local")
    remote_host_id = updates.get("remote_host_id", existing.get("remote_host_id"))
    if executor_type == "ssh" and remote_host_id is None:
        raise HTTPException(status_code=400, detail="remote_host_id is required for ssh jobs")
    row = await db.update_experiment_job(job_id, updates)
    if row is None:
        raise HTTPException(status_code=404, detail="Experiment job not found")
    return row


@router.get("/experiment-jobs/{job_id}/logs/{stream_name}")
async def get_experiment_job_log(
    job_id: UUID,
    stream_name: str,
    lines: Annotated[int, Query(ge=1, le=2000)] = 200,
    user: dict[str, Any] = Depends(require_production_user),
) -> dict[str, Any]:
    await _job_for_access(job_id, user)
    try:
        return await tail_job_log(job_id, stream_name, lines=lines)
    except ValueError as exc:
        raise _orchestrator_error(exc) from exc


@router.get("/experiment-jobs/{job_id}/artifacts")
async def get_experiment_job_artifacts(
    job_id: UUID,
    user: dict[str, Any] = Depends(require_production_user),
) -> dict[str, Any]:
    await _job_for_access(job_id, user)
    try:
        return await list_job_artifacts(job_id)
    except ValueError as exc:
        raise _orchestrator_error(exc) from exc


@router.post("/claims", response_model=ClaimLedgerResponse, status_code=201)
async def create_claim(
    request: ClaimLedgerCreate,
    user: dict[str, Any] = Depends(require_production_user),
) -> dict[str, Any]:
    await _project_for_access(request.project_id, user)
    await _validate_plan_reference(request.experiment_plan_id, request.project_id, user)
    return await db.create_claim_ledger_entry(_payload(request))


@router.get("/claims", response_model=list[ClaimLedgerResponse])
async def list_claims(
    project_id: UUID | None = None,
    experiment_plan_id: UUID | None = None,
    status: str | None = None,
    limit: Limit50 = 50,
    offset: Offset = 0,
    user: dict[str, Any] = Depends(require_production_user),
) -> list[dict[str, Any]]:
    if project_id is not None:
        await _project_for_access(project_id, user)
    rows = await db.list_claim_ledger(
        project_id=project_id,
        experiment_plan_id=experiment_plan_id,
        status=status,
        limit=limit,
        offset=offset,
    )
    return rows if project_id is not None else await _filter_owned_rows(rows, user)


@router.post("/experiment-plans/{plan_id}/claims/generate")
async def generate_claims_from_results(
    plan_id: UUID,
    body: dict[str, Any] | None = None,
    user: dict[str, Any] = Depends(require_production_user),
) -> dict[str, Any]:
    plan = await _plan_for_access(plan_id, user)
    project_id_value = (body or {}).get("project_id")
    project_id = UUID(str(project_id_value)) if project_id_value else None
    if project_id is not None and project_id != plan["project_id"]:
        raise HTTPException(status_code=400, detail="project_id mismatch")
    try:
        run = await get_orchestrator().generate_claims_from_results(
            plan_id,
            project_id=project_id,
        )
    except ValueError as exc:
        raise _orchestrator_error(exc) from exc
    return {"claims": run.claims, "evidence": run.evidence}


@router.post("/remote-hosts", response_model=RemoteHostResponse, status_code=201)
async def create_remote_host(
    request: RemoteHostCreate,
    user: dict[str, Any] = Depends(require_production_user),
) -> dict[str, Any]:
    payload = _payload(request)
    payload["owner_user_id"] = user["id"]
    return await db.create_remote_host(payload)


@router.get("/remote-hosts", response_model=list[RemoteHostResponse])
async def list_remote_hosts(
    status: str | None = None,
    limit: Limit50 = 50,
    offset: Offset = 0,
    user: dict[str, Any] = Depends(require_production_user),
) -> list[dict[str, Any]]:
    return await db.list_remote_hosts(
        status=status,
        owner_user_id=user["id"],
        limit=limit,
        offset=offset,
    )


@router.post("/manuscripts", response_model=ManuscriptPackageResponse, status_code=201)
async def create_manuscript_package(
    request: ManuscriptPackageCreate,
    user: dict[str, Any] = Depends(require_production_user),
) -> dict[str, Any]:
    await _project_for_access(request.project_id, user)
    return await db.create_manuscript_package(_payload(request))


@router.get("/manuscripts", response_model=list[ManuscriptPackageResponse])
async def list_manuscript_packages(
    project_id: UUID | None = None,
    status: str | None = None,
    limit: Limit50 = 50,
    offset: Offset = 0,
    user: dict[str, Any] = Depends(require_production_user),
) -> list[dict[str, Any]]:
    if project_id is not None:
        await _project_for_access(project_id, user)
    rows = await db.list_manuscript_packages(
        project_id=project_id,
        status=status,
        limit=limit,
        offset=offset,
    )
    return rows if project_id is not None else await _filter_owned_rows(rows, user)


@router.post("/manuscripts/{manuscript_id}/start-drafting")
async def start_manuscript_drafting(
    manuscript_id: UUID,
    user: dict[str, Any] = Depends(require_production_user),
) -> dict[str, Any]:
    await _manuscript_for_access(manuscript_id, user)
    try:
        return await get_orchestrator().prepare_manuscript_drafting(manuscript_id)
    except ValueError as exc:
        raise _orchestrator_error(exc) from exc


@router.post("/submissions", response_model=SubmissionPackageResponse, status_code=201)
async def create_submission_package(
    request: SubmissionPackageCreate,
    user: dict[str, Any] = Depends(require_production_user),
) -> dict[str, Any]:
    await _manuscript_for_access(request.manuscript_package_id, user)
    return await db.create_submission_package(_payload(request))


@router.get("/submissions", response_model=list[SubmissionPackageResponse])
async def list_submission_packages(
    manuscript_package_id: UUID | None = None,
    status: str | None = None,
    limit: Limit50 = 50,
    offset: Offset = 0,
    user: dict[str, Any] = Depends(require_production_user),
) -> list[dict[str, Any]]:
    if manuscript_package_id is not None:
        await _manuscript_for_access(manuscript_package_id, user)
    rows = await db.list_submission_packages(
        manuscript_package_id=manuscript_package_id,
        status=status,
        limit=limit,
        offset=offset,
    )
    if manuscript_package_id is not None:
        return rows
    owned: list[dict[str, Any]] = []
    for row in rows:
        try:
            await _submission_for_access(row["id"], user)
        except HTTPException:
            continue
        owned.append(row)
    return owned


@router.post("/submissions/{submission_id}/gate")
async def gate_submission_package(
    submission_id: UUID,
    user: dict[str, Any] = Depends(require_production_user),
) -> dict[str, Any]:
    await _submission_for_access(submission_id, user)
    try:
        return await get_orchestrator().gate_submission_package(submission_id)
    except ValueError as exc:
        raise _orchestrator_error(exc) from exc


@router.post("/submissions/{submission_id}/submit", response_model=SubmissionPackageResponse)
async def submit_submission_package(
    submission_id: UUID,
    user: dict[str, Any] = Depends(require_production_user),
) -> dict[str, Any]:
    submission = await _submission_for_access(submission_id, user)
    status = _enum_value(submission.get("status"))
    if status not in {None, "ready", "submitted"}:
        raise HTTPException(status_code=409, detail="Submission package is not ready")
    row = await db.update_submission_package(submission_id, {"status": "submitted"})
    if row is None:
        raise HTTPException(status_code=404, detail="Submission package not found")
    return row


@router.get("/workspaces/tree")
async def get_workspace_tree(
    project_id: UUID,
    run_id: UUID | None = None,
    path: str = ".",
    user: dict[str, Any] = Depends(require_production_user),
) -> dict[str, Any]:
    try:
        await _project_for_access(project_id, user)
        return await tree_workspace(project_id=project_id, run_id=run_id, path=path)
    except ValueError as exc:
        raise _orchestrator_error(exc) from exc


@router.get("/workspaces/file")
async def get_workspace_file(
    project_id: UUID,
    run_id: UUID | None = None,
    path: str = ".",
    user: dict[str, Any] = Depends(require_production_user),
) -> dict[str, Any]:
    try:
        await _project_for_access(project_id, user)
        return await read_workspace_file(project_id=project_id, run_id=run_id, path=path)
    except ValueError as exc:
        raise _orchestrator_error(exc) from exc


@router.post(
    "/terminal/sessions",
    response_model=TerminalSessionResponse,
    status_code=201,
)
async def create_terminal_session(
    request: TerminalSessionCreate,
    user: dict[str, Any] = Depends(require_production_user),
) -> dict[str, Any]:
    try:
        job = await _validate_job_reference(request.experiment_job_id, request.project_id, user)
        project_id = request.project_id or (job["project_id"] if job is not None else None)
        if request.project_id is not None:
            await _project_for_access(request.project_id, user)
        if request.remote_host_id is not None:
            await _remote_host_for_access(request.remote_host_id, user)
        payload = _payload(request)
        if project_id is not None:
            payload["project_id"] = project_id
        payload["created_by"] = user["id"]
        payload["cwd"] = await _terminal_cwd(request, project_id=project_id)
        return await db.create_terminal_session(payload)
    except ValueError as exc:
        raise _orchestrator_error(exc) from exc


@router.get(
    "/terminal/sessions",
    response_model=list[TerminalSessionResponse],
)
async def list_terminal_sessions(
    project_id: UUID | None = None,
    run_id: UUID | None = None,
    experiment_job_id: UUID | None = None,
    status: str | None = None,
    limit: Limit50 = 50,
    offset: Offset = 0,
    user: dict[str, Any] = Depends(require_production_user),
) -> list[dict[str, Any]]:
    if project_id is not None:
        await _project_for_access(project_id, user)
    return await db.list_terminal_sessions(
        project_id=project_id,
        run_id=run_id,
        experiment_job_id=experiment_job_id,
        status=status,
        created_by=user["id"],
        limit=limit,
        offset=offset,
    )


@router.get(
    "/terminal/sessions/{session_id}",
    response_model=TerminalSessionResponse,
)
async def get_terminal_session(
    session_id: UUID,
    user: dict[str, Any] = Depends(require_production_user),
) -> dict[str, Any]:
    return await _terminal_session_for_access(session_id, user)


@router.patch("/terminal/sessions/{session_id}")
async def patch_terminal_session(
    session_id: UUID,
    body: TerminalSessionPatch,
    user: dict[str, Any] = Depends(require_production_user),
) -> dict[str, Any]:
    existing = await _terminal_session_for_access(session_id, user)
    try:
        updates = await _terminal_patch_updates(existing, body, user)
    except ValueError as exc:
        raise _orchestrator_error(exc) from exc
    row = await db.update_terminal_session(session_id, updates)
    if row is None:
        raise HTTPException(status_code=404, detail="Terminal session not found")
    return row


@router.post("/terminal/sessions/{session_id}/resize")
async def resize_terminal_session(
    session_id: UUID,
    request: TerminalResizeRequest,
    user: dict[str, Any] = Depends(require_production_user),
) -> dict[str, Any]:
    await _terminal_session_for_access(session_id, user)
    resized = terminal_manager.resize(session_id, rows=request.rows, cols=request.cols)
    return {"session_id": session_id, "resized": resized, "rows": request.rows, "cols": request.cols}


@router.post("/terminal/sessions/{session_id}/close", response_model=TerminalSessionResponse)
async def close_terminal_session(
    session_id: UUID,
    user: dict[str, Any] = Depends(require_production_user),
) -> dict[str, Any]:
    await _terminal_session_for_access(session_id, user)
    terminal_manager.close(session_id)
    row = await db.update_terminal_session(
        session_id,
        {
            "status": "closed",
            "closed_at": datetime.now(timezone.utc),
        },
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Terminal session not found")
    return row


@router.websocket("/terminal/sessions/{session_id}/ws")
async def terminal_session_websocket(websocket: WebSocket, session_id: UUID) -> None:
    await websocket.accept()
    token = _websocket_bearer_token(websocket)
    if not token:
        token = await _receive_terminal_auth_token(websocket)
    if not token:
        await websocket.close(code=1008, reason="missing terminal token")
        return
    row = await db.get_terminal_session(session_id)
    if row is None:
        await websocket.send_json({"type": "error", "message": "Terminal session not found"})
        await websocket.close(code=1008)
        return
    try:
        token_user = await _authorize_terminal_token(token, row)
    except HTTPException as exc:
        await websocket.send_json({"type": "error", "message": str(exc.detail)})
        await websocket.close(code=1008)
        return
    project: dict[str, Any] | None = None
    if row.get("project_id") is not None:
        try:
            project = await _project_for_access(row["project_id"], token_user)
        except HTTPException as exc:
            await websocket.send_json({"type": "error", "message": str(exc.detail)})
            await websocket.close(code=1008)
            return
    if row.get("session_type") != "local":
        await websocket.send_json({"type": "error", "message": "Only local terminal sessions are supported"})
        await websocket.close(code=1008)
        return

    try:
        if row.get("project_id"):
            if project is None:
                raise ValueError(f"Project not found: {row['project_id']}")
            root = resolve_project_workspace_path(project, run_id=row.get("run_id"))
        else:
            root = workspace_base()
        cwd = resolve_path_reference(root, row.get("cwd") or ".", field_name="cwd")
        shell = row.get("shell") or os.getenv("SHELL") or "/bin/bash"
        session = terminal_manager.open(session_id=session_id, cwd=cwd, shell=shell)
        await db.update_terminal_session(session_id, {"status": "open", "cwd": str(cwd), "shell": shell})
    except Exception as exc:
        await db.update_terminal_session(session_id, {"status": "failed"})
        await websocket.send_json({"type": "error", "message": str(exc)})
        await websocket.close(code=1011)
        return

    async def pump_output() -> None:
        while True:
            chunk = await session.read()
            if chunk is None:
                await websocket.send_json({"type": "status", "status": "closed"})
                return
            if chunk:
                await websocket.send_json({"type": "output", "data": chunk})

    output_task = asyncio.create_task(pump_output())
    try:
        await websocket.send_json({"type": "status", "status": "open"})
        while True:
            message = await websocket.receive_text()
            try:
                payload = json.loads(message)
            except json.JSONDecodeError:
                payload = {"type": "input", "data": message}
            message_type = payload.get("type")
            if message_type == "input":
                session.write(str(payload.get("data", "")))
            elif message_type == "resize":
                rows = int(payload.get("rows", 24))
                cols = int(payload.get("cols", 80))
                session.resize(rows=rows, cols=cols)
            elif message_type == "close":
                break
    except WebSocketDisconnect:
        pass
    finally:
        output_task.cancel()
        terminal_manager.close(session_id)
        await db.update_terminal_session(
            session_id,
            {
                "status": "closed",
                "closed_at": datetime.now(timezone.utc),
            },
        )
        with contextlib.suppress(asyncio.CancelledError):
            await output_task
