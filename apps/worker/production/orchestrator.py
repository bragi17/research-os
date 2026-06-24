"""Orchestrator services for production research workflows."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

import apps.api.database as db
from apps.worker.production.coding_agents.base import (
    CodingAgentEvent,
    CodingExecOptions,
)
from apps.worker.production.coding_agents.provider_factory import provider_for_name
from apps.worker.production.experiments.local_executor import (
    LocalExperimentExecutor,
    LocalJobResult,
    LocalJobSpec,
)
from apps.worker.production.experiments.manifest import expand_manifest_jobs
from apps.worker.production.experiments.ssh_executor import (
    SSHExperimentExecutor,
    SSHJobSpec,
    SSHRemoteHost,
    resolve_remote_cwd,
)
from apps.worker.production.result_to_claim import (
    audit_claims,
    claim_evidence_payload,
    claim_payloads_from_job_audit,
)
from apps.worker.production.workspaces import (
    resolve_coding_workspace_path,
    resolve_path_reference,
    resolve_project_workspace_path,
    resolve_under_workspace,
)
from libs.schemas.production import CodingTaskCreate


DEFAULT_LOCAL_JOB_TIMEOUT_SEC = 1800


@dataclass(frozen=True)
class CodexTaskRun:
    task: dict[str, Any]
    events: list[dict[str, Any]]
    output: str
    status: str
    failure_reason: str | None = None
    failure_detail: str | None = None


@dataclass(frozen=True)
class LocalJobRun:
    result: LocalJobResult
    row: dict[str, Any]


@dataclass(frozen=True)
class ClaimGenerationRun:
    claims: list[dict[str, Any]]
    evidence: list[dict[str, Any]]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _model_dump(payload: CodingTaskCreate | dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload, CodingTaskCreate):
        return payload.model_dump()
    return dict(payload)


def _prompt_hash(payload: dict[str, Any]) -> str:
    hasher = hashlib.sha256()
    for key in ("user_prompt", "system_prompt", "model"):
        value = payload.get(key)
        hasher.update((value or "").encode("utf-8"))
        hasher.update(b"\0")
    return hasher.hexdigest()


def _normalize_coding_task_payload(payload: CodingTaskCreate | dict[str, Any]) -> dict[str, Any]:
    data = _model_dump(payload)
    if "env" in data and "env_json" not in data:
        data["env_json"] = data.pop("env") or {}
    if "mcp_config" in data and "mcp_config_json" not in data:
        data["mcp_config_json"] = data.pop("mcp_config") or {}
    if not data.get("prompt_hash"):
        data["prompt_hash"] = _prompt_hash(data)
    return data


async def create_coding_task(payload: CodingTaskCreate | dict[str, Any]) -> dict[str, Any]:
    """Create a persisted coding task with worker-oriented normalized fields."""

    data = _normalize_coding_task_payload(payload)
    project = await db.get_project(data["project_id"])
    if project is None:
        raise ValueError(f"Project not found: {data['project_id']}")
    data["workspace_path"] = str(resolve_coding_workspace_path(data, project))
    return await db.create_coding_task(data)


def _task_value(row: dict[str, Any], key: str, default: Any = None) -> Any:
    value = row.get(key, default)
    return default if value is None else value


def _normalize_codex_mcp_config(value: Any) -> dict[str, Any] | None:
    if not value:
        return None
    if value == {"servers": {}} or value == {"mcpServers": {}}:
        return None
    if isinstance(value, dict) and all(
        item in ({}, None) for item in value.values()
    ):
        return None
    raise ValueError("unsupported_mcp_config: CodexProvider v1 does not support MCP config")


def _build_exec_options(task: dict[str, Any]) -> CodingExecOptions:
    cwd = task.get("workspace_path") or task.get("cwd")
    if not cwd:
        raise ValueError("workspace_path is required to run coding task")
    project = {"id": task["project_id"], "default_workspace_path": cwd}
    cwd = str(resolve_coding_workspace_path(task, project))

    return CodingExecOptions(
        cwd=cwd,
        model=task.get("model"),
        system_prompt=task.get("system_prompt"),
        thread_name=task.get("thread_name"),
        timeout_sec=task.get("timeout_sec"),
        semantic_inactivity_timeout_sec=task.get("semantic_inactivity_timeout_sec"),
        resume_session_id=task.get("provider_session_id"),
        extra_args=list(_task_value(task, "extra_args", [])),
        custom_args=list(_task_value(task, "custom_args", [])),
        env=dict(_task_value(task, "env_json", {})),
        mcp_config=_normalize_codex_mcp_config(task.get("mcp_config_json")),
        thinking_level=task.get("thinking_level"),
    )


def _normalize_coding_event(
    *,
    task: dict[str, Any],
    event: CodingAgentEvent,
) -> dict[str, Any]:
    return {
        "coding_task_id": task["id"],
        "run_id": task.get("run_id"),
        "event_type": event.type,
        "content": event.content,
        "tool": event.tool,
        "call_id": event.call_id,
        "input_json": event.input,
        "output_text": event.output,
        "status_text": event.status,
        "level": event.level,
        "provider_raw_json": event.raw or {},
    }


def _status_from_error_event(event: CodingAgentEvent) -> str:
    return "timeout" if event.status == "agent_timeout" else "failed"


def _same_owner(project: dict[str, Any], row: dict[str, Any]) -> bool:
    project_owner = project.get("owner_user_id")
    row_owner = row.get("owner_user_id")
    return project_owner is not None and row_owner is not None and row_owner == project_owner


def _require_same_owner(project: dict[str, Any], row: dict[str, Any], label: str) -> None:
    if not _same_owner(project, row):
        raise ValueError(f"{label} access denied")


def _relative_to_workspace(workspace_root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(workspace_root.resolve()).as_posix()
    except ValueError:
        return str(path)


def _provider_for_task(task: dict[str, Any]) -> Any:
    return provider_for_name(str(task.get("provider") or "codex"))


def _lease_identity(row: dict[str, Any], field_name: str) -> tuple[str | None, str | None]:
    metadata = row.get(field_name) if isinstance(row.get(field_name), dict) else {}
    lease = metadata.get("scheduler_lease") if isinstance(metadata, dict) else None
    worker_id = lease.get("worker_id") if isinstance(lease, dict) else None
    lease_id = lease.get("lease_id") if isinstance(lease, dict) else None
    return (
        str(worker_id) if worker_id else None,
        str(lease_id) if lease_id else None,
    )


async def _update_coding_task_final(
    task_id: UUID,
    updates: dict[str, Any],
    task: dict[str, Any],
) -> tuple[dict[str, Any] | None, bool]:
    worker_id, lease_id = _lease_identity(task, "metadata_json")
    guarded_update = getattr(db, "update_coding_task_if_lease", None)
    if worker_id and lease_id and callable(guarded_update):
        row = await guarded_update(task_id, updates, worker_id=worker_id, lease_id=lease_id)
        if row is not None:
            return row, True
        return await db.get_coding_task(task_id), False
    return await db.update_coding_task(task_id, updates), True


async def _update_experiment_job_final(
    job_id: UUID,
    updates: dict[str, Any],
    job: dict[str, Any],
) -> tuple[dict[str, Any] | None, bool]:
    worker_id, lease_id = _lease_identity(job, "metrics_json")
    guarded_update = getattr(db, "update_experiment_job_if_lease", None)
    if worker_id and lease_id and callable(guarded_update):
        row = await guarded_update(job_id, updates, worker_id=worker_id, lease_id=lease_id)
        if row is not None:
            return row, True
        return await db.get_experiment_job(job_id), False
    return await db.update_experiment_job(job_id, updates), True


async def run_codex_task(
    task_id: UUID,
    provider: Any | None = None,
    *,
    preclaimed: bool = False,
    claimed_task: dict[str, Any] | None = None,
) -> CodexTaskRun:
    """Run a coding task via a streaming provider and persist task/event state."""

    task = claimed_task or await db.get_coding_task(task_id)
    if task is None:
        raise ValueError(f"Coding task not found: {task_id}")

    try:
        options = _build_exec_options(task)
        prompt = task.get("user_prompt")
        if not prompt:
            raise ValueError("user_prompt is required to run coding task")
    except ValueError as exc:
        failure_text = str(exc)
        if "workspace_path escapes workspace root" in failure_text:
            failure_reason = "workspace_path_escaped"
        elif "workspace_path is required" in failure_text or "Project not found" in failure_text:
            failure_reason = "workspace_unavailable"
        elif failure_text.startswith("unsupported_mcp_config"):
            failure_reason = "unsupported_mcp_config"
        else:
            failure_reason = "preflight_error"
        now = _utcnow()
        final_row, _lease_owned = await _update_coding_task_final(
            task_id,
            {
                "status": "failed",
                "completed_at": now,
                "failure_reason": failure_reason,
                "failure_detail": failure_text,
            },
            task,
        )
        return CodexTaskRun(
            task=final_row or task,
            events=[],
            output="",
            status="failed",
            failure_reason=failure_reason,
            failure_detail=failure_text,
        )

    provider = provider or _provider_for_task(task)
    started_at = _utcnow()
    monotonic_started = time.monotonic()
    if preclaimed:
        task = {
            **task,
            "status": "running",
            "started_at": task.get("started_at") or started_at,
        }
    else:
        running_row = await db.update_coding_task(task_id, {"status": "running", "started_at": started_at})
        task = running_row or task

    events: list[dict[str, Any]] = []
    output_parts: list[str] = []
    session_id = task.get("provider_session_id")
    usage: dict[str, Any] = {}
    status = "failed"
    failure_reason: str | None = None
    failure_detail: str | None = None

    try:
        async for event in provider.execute(prompt, options):
            if event.session_id:
                session_id = event.session_id
            if event.type == "text" and event.content:
                output_parts.append(event.content)
            if event.type == "status" and event.status == "completed":
                status = "completed"
                if isinstance(event.raw, dict) and isinstance(event.raw.get("usage"), dict):
                    usage = event.raw["usage"]
            if event.type == "error":
                status = _status_from_error_event(event)
                failure_reason = event.status or "provider_error"
                failure_detail = event.content

            persisted_event = await db.create_coding_event(
                _normalize_coding_event(task=task, event=event)
            )
            events.append(persisted_event)
    except Exception as exc:
        status = "failed"
        failure_reason = "provider_error"
        failure_detail = str(exc)

    if status != "completed" and failure_reason is None:
        failure_reason = "provider_no_completion"

    completed_at = _utcnow()
    duration_ms = int((time.monotonic() - monotonic_started) * 1000)
    final_updates = {
        "status": status,
        "completed_at": completed_at,
        "duration_ms": duration_ms,
        "token_usage_json": usage,
        "provider_session_id": session_id,
        "failure_reason": failure_reason,
        "failure_detail": failure_detail,
    }
    final_row, lease_owned = await _update_coding_task_final(task_id, final_updates, task)
    if lease_owned:
        await _maybe_regate_submission_after_coding_task(final_row or {**task, **final_updates})
    return CodexTaskRun(
        task=final_row or task,
        events=events,
        output="".join(output_parts),
        status=status,
        failure_reason=failure_reason,
        failure_detail=failure_detail,
    )


async def create_manifest_jobs(manifest_id: UUID) -> list[dict[str, Any]]:
    """Expand an experiment manifest into pending local or SSH experiment jobs."""

    manifest = await db.get_experiment_manifest(manifest_id)
    if manifest is None:
        raise ValueError(f"Experiment manifest not found: {manifest_id}")
    manifest_status = manifest.get("status")
    if manifest_status and manifest_status not in {"accepted", "running"}:
        raise ValueError("accepted manifest is required before job expansion")

    manifest_json = manifest.get("manifest_json", {})
    expanded_jobs = expand_manifest_jobs(manifest_json)
    resources = manifest_json.get("resources") if isinstance(manifest_json, dict) else {}
    resources = resources if isinstance(resources, dict) else {}
    remote_host_id = resources.get("remote_host_id")
    executor_type = resources.get("executor_type")
    if executor_type is None:
        executor_type = "ssh" if remote_host_id and resources.get("local_first") is False else "local"
    remote_host_uuid = UUID(str(remote_host_id)) if executor_type == "ssh" and remote_host_id else None
    if executor_type == "ssh" and remote_host_uuid is None:
        raise ValueError("remote_host_id is required for ssh manifest resources")
    if remote_host_uuid is not None:
        project = await db.get_project(manifest["project_id"])
        if project is None:
            raise ValueError(f"Project not found: {manifest['project_id']}")
        remote_host = await db.get_remote_host(remote_host_uuid)
        if remote_host is None:
            raise ValueError(f"Remote host not found: {remote_host_uuid}")
        _require_same_owner(project, remote_host, "Remote host")

    created: list[dict[str, Any]] = []
    for job in expanded_jobs:
        row = await db.create_experiment_job(
            {
                "manifest_id": manifest_id,
                "experiment_plan_id": manifest["experiment_plan_id"],
                "project_id": manifest["project_id"],
                "phase_name": job.phase_name,
                "job_name": job.job_name,
                "executor_type": executor_type,
                "remote_host_id": remote_host_uuid,
                "cmd": job.cmd,
                "cwd": job.cwd,
                "status": "pending",
                "expected_outputs_json": list(job.expected_outputs),
                "max_attempts": job.max_attempts,
                "metrics_json": {
                    "timeout_sec": job.timeout_sec,
                    "phase_index": job.phase_index,
                    "job_index": job.job_index,
                    "oom_retry": job.oom_retry,
                    "phase_dependencies": list(job.phase_dependencies),
                },
            }
        )
        created.append(row)
    return created


def _resolve_job_cwd(raw_cwd: str | None, workspace_root: Path) -> Path:
    if not raw_cwd:
        raw_cwd = "."
    try:
        return resolve_under_workspace(workspace_root, raw_cwd, field_name="cwd")
    except ValueError as exc:
        if "workspace-relative" in str(exc):
            raise ValueError("cwd escapes workspace_root") from exc
        raise


def _resolve_log_dir(job: dict[str, Any], workspace_root: Path, job_id: UUID) -> Path:
    metrics = job.get("metrics_json") if isinstance(job.get("metrics_json"), dict) else {}
    configured = metrics.get("log_dir") if isinstance(metrics, dict) else None
    if configured:
        try:
            return resolve_path_reference(workspace_root, configured, field_name="log_dir")
        except ValueError as exc:
            raise ValueError("log_dir escapes workspace_root") from exc
    default_log_dir = (workspace_root / ".research-os" / "jobs" / str(job_id) / "logs").resolve()
    try:
        default_log_dir.relative_to(workspace_root)
    except ValueError as exc:
        raise ValueError("log_dir escapes workspace_root")
    return default_log_dir


def _resolve_job_artifact_dir(workspace_root: Path, job_id: UUID) -> Path:
    artifact_dir = (workspace_root / ".research-os" / "jobs" / str(job_id) / "artifacts").resolve()
    try:
        artifact_dir.relative_to(workspace_root)
    except ValueError as exc:
        raise ValueError("artifact_dir escapes workspace_root") from exc
    return artifact_dir


def _resolve_job_research_dir(workspace_root: Path, job_id: UUID) -> Path:
    research_dir = (workspace_root / ".research-os" / "jobs" / str(job_id) / "research").resolve()
    try:
        research_dir.relative_to(workspace_root)
    except ValueError as exc:
        raise ValueError("research_dir escapes workspace_root") from exc
    return research_dir


def _expected_output_paths(job: dict[str, Any]) -> list[Path]:
    outputs = job.get("expected_outputs_json") or []
    return [Path(str(output)) for output in outputs]


def _job_timeout(job: dict[str, Any]) -> float:
    metrics = job.get("metrics_json") if isinstance(job.get("metrics_json"), dict) else {}
    value = metrics.get("timeout_sec") if isinstance(metrics, dict) else None
    return float(value or DEFAULT_LOCAL_JOB_TIMEOUT_SEC)


def _string_paths(paths: list[Path]) -> list[str]:
    return [str(path) for path in paths]


def _result_metrics(job: dict[str, Any], result: LocalJobResult) -> dict[str, Any]:
    metrics = dict(job.get("metrics_json") or {})
    metrics.update(
        {
            "returncode": result.returncode,
            "duration_ms": result.duration_ms,
            "expected_outputs_found": _string_paths(result.expected_outputs_found),
            "missing_expected_outputs": _string_paths(result.missing_expected_outputs),
        }
    )
    return metrics


def _job_env(job: dict[str, Any]) -> dict[str, Any]:
    metrics = job.get("metrics_json") if isinstance(job.get("metrics_json"), dict) else {}
    value = metrics.get("env_json") or metrics.get("env") or {}
    if not isinstance(value, dict):
        raise ValueError("job env_json must be an object")
    return dict(value)


def _ssh_remote_host(row: dict[str, Any]) -> SSHRemoteHost:
    return SSHRemoteHost(
        host=str(row["host"]),
        port=int(row.get("port") or 22),
        username=row.get("username"),
        auth_type=str(row.get("auth_type") or "agent"),
        key_ref=row.get("key_ref"),
        default_workdir=row.get("default_workdir"),
        default_env_json=dict(row.get("default_env_json") or {}),
    )


def _experiment_research_queries(job: dict[str, Any], result: LocalJobResult) -> list[str]:
    metrics = job.get("metrics_json") if isinstance(job.get("metrics_json"), dict) else {}
    reason = metrics.get("error") or result.failure_reason or job.get("failure_reason") or result.status
    return [
        f"{job.get('phase_name', 'experiment')} {job.get('job_name', 'job')} failure {reason} mitigation",
        f"{job.get('job_name', 'experiment')} missing outputs reproducibility debugging",
        f"{job.get('job_name', 'experiment')} metric regression ablation solution",
    ]


async def _search_library_for_experiment_failure(
    queries: list[str],
    *,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Search the existing paper library/vector index for failure-specific fixes."""

    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    try:
        from services.library.tools_db import search_library_text, search_library_vectors
    except Exception:
        return results

    try:
        from services.library.tools_embedding import embed_paper_chunks, rerank_papers
    except Exception:
        embed_paper_chunks = None
        rerank_papers = None

    for query in queries:
        candidates: list[dict[str, Any]] = []
        if embed_paper_chunks is not None:
            try:
                vectors = await embed_paper_chunks([query])
                if vectors:
                    candidates.extend(await search_library_vectors(vectors[0], limit=limit * 3))
            except Exception:
                candidates = []

        try:
            text_results = await search_library_text(query, limit=limit)
        except Exception:
            text_results = []

        candidate_ids = {str(candidate.get("id")) for candidate in candidates}
        for paper in text_results:
            if str(paper.get("id")) not in candidate_ids:
                candidates.append(paper)
                candidate_ids.add(str(paper.get("id")))

        if candidates:
            if rerank_papers is None:
                ordered = candidates[:limit]
            else:
                try:
                    reranked = await rerank_papers(
                        query,
                        [str(candidate.get("title") or "") for candidate in candidates],
                        top_n=limit,
                    )
                    ordered = [
                        candidates[item.get("index", 0)]
                        for item in reranked
                        if item.get("index", 0) < len(candidates)
                    ]
                except Exception:
                    ordered = candidates[:limit]
        else:
            ordered = []

        for paper in ordered:
            paper_id = str(paper.get("id") or paper.get("paper_id") or paper.get("title"))
            if paper_id in seen:
                continue
            seen.add(paper_id)
            results.append(paper)
            if len(results) >= limit:
                return results
    return results


def _repair_manifest_payload(
    *,
    job: dict[str, Any],
    result: LocalJobResult,
    queries: list[str],
    library_results: list[dict[str, Any]],
) -> dict[str, Any]:
    metrics = job.get("metrics_json") if isinstance(job.get("metrics_json"), dict) else {}
    repair_phase = f"repair-{job.get('job_name') or job['id']}"
    return {
        "project": f"repair for {job.get('job_name') or job['id']}",
        "workspace": ".",
        "resources": {
            "local_first": (job.get("executor_type") or "local") == "local",
            "executor_type": job.get("executor_type") or "local",
            "remote_host_id": str(job["remote_host_id"]) if job.get("remote_host_id") else None,
        },
        "research_context": {
            "failed_job_id": str(job["id"]),
            "failure_reason": result.failure_reason or job.get("failure_reason"),
            "queries": queries,
            "library_result_ids": [
                str(item.get("id") or item.get("paper_id") or item.get("title"))
                for item in library_results
            ],
        },
        "phases": [
            {
                "name": repair_phase,
                "depends_on": [],
                "jobs": [
                    {
                        "name": "repair-run",
                        "cmd": job.get("cmd") or "python -m pytest",
                        "cwd": job.get("cwd") or ".",
                        "expected_outputs": list(job.get("expected_outputs_json") or []),
                        "timeout_sec": metrics.get("timeout_sec") or DEFAULT_LOCAL_JOB_TIMEOUT_SEC,
                        "retry": {
                            "max_attempts": max(int(job.get("max_attempts") or 1), 2),
                            "oom_retry": bool(metrics.get("oom_retry")),
                        },
                    }
                ],
            }
        ],
    }


async def _write_experiment_research_outputs(
    *,
    job: dict[str, Any],
    result: LocalJobResult,
    workspace_root: Path,
    context: dict[str, Any],
) -> None:
    research_dir = _resolve_job_research_dir(workspace_root, job["id"])
    research_dir.mkdir(parents=True, exist_ok=True)
    report_path = research_dir / "research_plan.json"
    report_path.write_text(json.dumps(_jsonable(context), indent=2, sort_keys=True), encoding="utf-8")

    await db.create_code_artifact(
        {
            "project_id": job["project_id"],
            "experiment_plan_id": job.get("experiment_plan_id"),
            "artifact_type": "review_report",
            "path": _relative_to_workspace(workspace_root, report_path),
            "summary": "Experiment failure research plan with literature-backed repair directions.",
            "validation_status": "pending",
            "metadata_json": {
                "stage": "experiment_research",
                "job_id": str(job["id"]),
                "failure_reason": result.failure_reason or job.get("failure_reason"),
            },
        }
    )

    if job.get("experiment_plan_id") is not None:
        repair_manifest = _repair_manifest_payload(
            job=job,
            result=result,
            queries=context["queries"],
            library_results=context.get("library_results") or [],
        )
        await db.create_experiment_manifest(
            {
                "experiment_plan_id": job["experiment_plan_id"],
                "project_id": job["project_id"],
                "manifest_json": repair_manifest,
                "manifest_version": f"repair-{_short_uuid(job['id'])}-{int(job.get('attempt') or 1)}",
                "generated_by_coding_task_id": None,
                "status": "accepted",
            }
        )


def _short_uuid(value: Any) -> str:
    return str(value).split("-")[0]


async def _queue_experiment_research_task(
    *,
    job: dict[str, Any],
    result: LocalJobResult,
    workspace_root: Path,
) -> dict[str, Any] | None:
    if result.status == "completed":
        return None

    queries = _experiment_research_queries(job, result)
    library_results = await _search_library_for_experiment_failure(queries, limit=5)
    metrics = job.get("metrics_json") if isinstance(job.get("metrics_json"), dict) else {}
    with_context = {
        "stage": "experiment_research",
        "job_id": str(job["id"]),
        "phase_name": job.get("phase_name"),
        "job_name": job.get("job_name"),
        "status": result.status,
        "failure_reason": result.failure_reason or job.get("failure_reason"),
        "error": metrics.get("error"),
        "returncode": result.returncode,
        "missing_expected_outputs": [str(path) for path in result.missing_expected_outputs],
        "stdout_log": str(result.stdout_log),
        "stderr_log": str(result.stderr_log),
        "queries": queries,
        "library_results": _jsonable(library_results),
    }
    await _write_experiment_research_outputs(
        job=job,
        result=result,
        workspace_root=workspace_root,
        context=with_context,
    )
    await db.create_project_query_pack(
        {
            "project_id": job["project_id"],
            "source_run_id": job.get("run_id"),
            "topic": f"Experiment failure research: {job.get('job_name', 'job')}",
            "query_pack_json": with_context,
        }
    )
    prompt = (
        "Analyze the failed experiment job and propose concrete fixes or follow-up experiments.\n"
        f"Job: {job.get('phase_name', 'experiment')} / {job.get('job_name', 'job')}\n"
        f"Command: {job.get('cmd')}\n"
        f"Status: {result.status}; failure: {result.failure_reason or job.get('failure_reason')}\n"
        f"Error detail: {metrics.get('error') or 'none'}\n"
        f"Return code: {result.returncode}\n"
        f"Missing outputs: {', '.join(str(path) for path in result.missing_expected_outputs) or 'none'}\n"
        f"Logs: stdout={result.stdout_log}, stderr={result.stderr_log}\n"
        "Use the local workspace plus Research OS paper-search tools if available. "
        "Write a short diagnosis, candidate literature/search queries, and a patch/experiment plan."
    )
    return await create_coding_task(
        {
            "project_id": job["project_id"],
            "experiment_plan_id": job.get("experiment_plan_id"),
            "provider": "codex",
            "workspace_path": str(workspace_root),
            "thread_name": f"experiment-research-{job['id']}",
            "system_prompt": "You are the experiment-side research agent for Research OS.",
            "user_prompt": prompt,
            "metadata_json": with_context,
            "status": "queued",
        }
    )


async def queue_experiment_research_for_job(
    job_id: UUID,
    *,
    failure_reason: str = "scheduler_stale_heartbeat",
) -> dict[str, Any] | None:
    """Queue experiment-side research for a job that failed outside executor flow."""

    job = await db.get_experiment_job(job_id)
    if job is None:
        raise ValueError(f"Experiment job not found: {job_id}")
    project = await db.get_project(job["project_id"])
    if project is None:
        raise ValueError(f"Project not found: {job['project_id']}")
    workspace_root = resolve_project_workspace_path(project)
    log_dir = _resolve_log_dir(job, workspace_root, job_id)
    result = LocalJobResult(
        job_id=str(job_id),
        status="stuck" if "stale" in failure_reason else "failed",
        returncode=None,
        stdout_log=_safe_log_path(workspace_root, job.get("stdout_log_path"), log_dir / "stdout.log"),
        stderr_log=_safe_log_path(workspace_root, job.get("stderr_log_path"), log_dir / "stderr.log"),
        expected_outputs_found=[],
        missing_expected_outputs=_expected_output_paths(job),
        failure_reason=failure_reason,
        duration_ms=0,
    )
    metrics = dict(job.get("metrics_json") or {})
    metrics.setdefault("error", failure_reason)
    enriched_job = {**job, "failure_reason": failure_reason, "metrics_json": metrics}
    return await _queue_experiment_research_task(
        job=enriched_job,
        result=result,
        workspace_root=workspace_root,
    )


def _safe_log_path(workspace_root: Path, stored: Any, default: Path) -> Path:
    if stored:
        try:
            return resolve_path_reference(workspace_root, stored, field_name="log_path")
        except ValueError:
            return default
    return default


async def _queue_manuscript_writing_task(
    *,
    manuscript: dict[str, Any],
    paper_dir: Path,
    audit: dict[str, Any],
) -> dict[str, Any] | None:
    if await _has_active_stage_task(
        project_id=manuscript["project_id"],
        stage="manuscript_writing",
        manuscript_id=str(manuscript["id"]),
    ):
        return None
    prompt = (
        "Edit the manuscript draft in this directory using the generated snapshots.\n"
        "Required files: paper.md, claims_snapshot.json, artifact_snapshot.json, bib_snapshot.json.\n"
        f"Target venue: {manuscript.get('venue_target') or 'unspecified'}.\n"
        f"Unsupported claims: {audit.get('unsupported_claims', 0)}.\n"
        "Turn supported claims into paper-quality prose, mark weak claims as limitations, "
        "and leave submission-blocking TODOs explicit."
    )
    return await create_coding_task(
        {
            "project_id": manuscript["project_id"],
            "provider": "codex",
            "workspace_path": str(paper_dir),
            "thread_name": f"manuscript-writing-{manuscript['id']}",
            "system_prompt": "You are the manuscript writing agent for Research OS.",
            "user_prompt": prompt,
            "metadata_json": {
                "stage": "manuscript_writing",
                "manuscript_id": str(manuscript["id"]),
                "paper_dir": str(paper_dir),
                "claim_audit": audit,
            },
            "status": "queued",
        }
    )


async def _queue_submission_revision_task(
    *,
    submission: dict[str, Any],
    manuscript: dict[str, Any],
    reports: dict[str, Any],
) -> dict[str, Any] | None:
    if await _has_active_stage_task(
        project_id=manuscript["project_id"],
        stage="submission_revision",
        submission_id=str(submission["id"]),
    ):
        return None
    project = await db.get_project(manuscript["project_id"])
    if project is None:
        return None
    paper_dir = _paper_dir(manuscript, resolve_project_workspace_path(project))
    if paper_dir is None:
        return None
    prompt = (
        "Revise the submission package so it can pass the Research OS submission gate.\n"
        f"Venue: {submission.get('venue')}.\n"
        f"Reports: {json.dumps(_jsonable(reports), indent=2, sort_keys=True)}\n"
        "Update paper.md and any local checklist/report files needed for another gate run."
    )
    return await create_coding_task(
        {
            "project_id": manuscript["project_id"],
            "provider": "codex",
            "workspace_path": str(paper_dir),
            "thread_name": f"submission-revision-{submission['id']}",
            "system_prompt": "You are the submission revision agent for Research OS.",
            "user_prompt": prompt,
            "metadata_json": {
                "stage": "submission_revision",
                "submission_id": str(submission["id"]),
                "manuscript_id": str(manuscript["id"]),
                "reports": reports,
            },
            "status": "queued",
        }
    )


async def _has_active_stage_task(
    *,
    project_id: UUID,
    stage: str,
    **metadata_match: str,
) -> bool:
    for status in ("queued", "running"):
        tasks = await db.list_coding_tasks(
            project_id=project_id,
            status=status,
            limit=100,
            offset=0,
        )
        for task in tasks:
            metadata = task.get("metadata_json") if isinstance(task.get("metadata_json"), dict) else {}
            if metadata.get("stage") != stage:
                continue
            if all(str(metadata.get(key)) == value for key, value in metadata_match.items()):
                return True
    return False


async def _maybe_regate_submission_after_coding_task(task: dict[str, Any]) -> None:
    if task.get("status") != "completed":
        return
    metadata = task.get("metadata_json") if isinstance(task.get("metadata_json"), dict) else {}
    if metadata.get("stage") != "submission_revision":
        return
    submission_id = metadata.get("submission_id")
    if not submission_id:
        return
    try:
        await gate_submission_package(UUID(str(submission_id)))
    except (ValueError, TypeError):
        return


async def run_local_job(
    job_id: UUID,
    executor: Any | None = None,
    workspace_root: str | Path | None = None,
    *,
    preclaimed: bool = False,
    claimed_job: dict[str, Any] | None = None,
) -> LocalJobRun:
    """Run one local or SSH experiment job and persist execution metadata."""

    job = claimed_job or await db.get_experiment_job(job_id)
    if job is None:
        raise ValueError(f"Experiment job not found: {job_id}")

    if workspace_root is not None:
        project = await db.get_project(job["project_id"])
        if project is None:
            raise ValueError(f"Project not found: {job['project_id']}")
        root = Path(workspace_root).expanduser().resolve()
        configured_root = resolve_project_workspace_path(project)
        if root != configured_root:
            raise ValueError("workspace_root must match trusted project workspace")
    else:
        project = await db.get_project(job["project_id"])
        if project is None:
            raise ValueError(f"Project not found: {job['project_id']}")
        root = resolve_project_workspace_path(project)

    log_dir = _resolve_log_dir(job, root, job_id)
    executor_type = job.get("executor_type") or "local"
    if executor_type == "ssh":
        remote_host_id = job.get("remote_host_id")
        if remote_host_id is None:
            raise ValueError("remote_host_id is required for ssh experiment jobs")
        remote_host_row = await db.get_remote_host(remote_host_id)
        if remote_host_row is None:
            raise ValueError(f"Remote host not found: {remote_host_id}")
        _require_same_owner(project, remote_host_row, "Remote host")
        remote_cwd = resolve_remote_cwd(remote_host_row.get("default_workdir"), job.get("cwd"))
        local_artifact_dir = _resolve_job_artifact_dir(root, job_id)
        spec = SSHJobSpec(
            job_id=str(job_id),
            remote_host=_ssh_remote_host(remote_host_row),
            remote_cwd=remote_cwd,
            command=job["cmd"],
            log_dir=log_dir,
            expected_outputs=_expected_output_paths(job),
            timeout_sec=_job_timeout(job),
            env=_job_env(job),
            local_artifact_dir=local_artifact_dir,
        )
        artifact_dir = str(local_artifact_dir)
        executor = executor or SSHExperimentExecutor()
    elif executor_type == "local":
        cwd = _resolve_job_cwd(job.get("cwd"), root)
        spec = LocalJobSpec(
            job_id=str(job_id),
            cwd=cwd,
            command=job["cmd"],
            log_dir=log_dir,
            expected_outputs=_expected_output_paths(job),
            timeout_sec=_job_timeout(job),
        )
        artifact_dir = str(cwd)
        executor = executor or LocalExperimentExecutor()
    else:
        raise ValueError(f"Unsupported experiment executor_type: {executor_type}")

    started_at = _utcnow()
    if preclaimed:
        job = {
            **job,
            "status": "running",
            "started_at": job.get("started_at") or started_at,
            "last_heartbeat_at": job.get("last_heartbeat_at") or started_at,
        }
    else:
        running_row = await db.update_experiment_job(
            job_id,
            {
                "status": "running",
                "started_at": started_at,
                "last_heartbeat_at": started_at,
            },
        )
        job = running_row or job

    try:
        result = await executor.run(spec)
    except Exception as exc:
        completed_at = _utcnow()
        result = LocalJobResult(
            job_id=str(job_id),
            status="failed",
            returncode=None,
            stdout_log=log_dir / "stdout.log",
            stderr_log=log_dir / "stderr.log",
            expected_outputs_found=[],
            missing_expected_outputs=[],
            failure_reason="executor_error",
            duration_ms=0,
        )
        metrics = _result_metrics(job, result)
        metrics["error"] = str(exc)
        final_row, lease_owned = await _update_experiment_job_final(
            job_id,
            {
                "status": "failed",
                "completed_at": completed_at,
                "last_heartbeat_at": completed_at,
                "failure_reason": "executor_error",
                "stdout_log_path": str(result.stdout_log),
                "stderr_log_path": str(result.stderr_log),
                "artifact_dir": artifact_dir,
                "metrics_json": metrics,
            },
            job,
        )
        if lease_owned:
            await _queue_experiment_research_task(
                job=final_row or job,
                result=result,
                workspace_root=root,
            )
        return LocalJobRun(result=result, row=final_row or job)

    completed_at = _utcnow()
    final_row, lease_owned = await _update_experiment_job_final(
        job_id,
        {
            "status": result.status,
            "completed_at": completed_at,
            "last_heartbeat_at": completed_at,
            "failure_reason": result.failure_reason,
            "stdout_log_path": str(result.stdout_log),
            "stderr_log_path": str(result.stderr_log),
            "artifact_dir": artifact_dir,
            "metrics_json": _result_metrics(job, result),
        },
        job,
    )
    if lease_owned:
        await _queue_experiment_research_task(
            job=final_row or job,
            result=result,
            workspace_root=root,
        )
    return LocalJobRun(result=result, row=final_row or job)


async def run_job(
    job_id: UUID,
    executor: Any | None = None,
    workspace_root: str | Path | None = None,
    *,
    preclaimed: bool = False,
    claimed_job: dict[str, Any] | None = None,
) -> LocalJobRun:
    """Dispatch an experiment job to its configured executor."""

    return await run_local_job(
        job_id,
        executor=executor,
        workspace_root=workspace_root,
        preclaimed=preclaimed,
        claimed_job=claimed_job,
    )


async def generate_claims_from_results(
    experiment_plan_id: UUID,
    *,
    project_id: UUID | None = None,
) -> ClaimGenerationRun:
    """Create claim ledger entries from completed/failed experiment job records."""

    jobs = await db.list_experiment_jobs(
        project_id=project_id,
        experiment_plan_id=experiment_plan_id,
        limit=100,
        offset=0,
    )
    if not jobs:
        raise ValueError("No experiment jobs available for claim generation")

    claims: list[dict[str, Any]] = []
    evidence_rows: list[dict[str, Any]] = []
    for job in jobs:
        project = await db.get_project(job["project_id"])
        if project is None:
            raise ValueError(f"Project not found: {job['project_id']}")
        workspace_root = resolve_project_workspace_path(project)
        artifacts = await db.list_code_artifacts(
            project_id=job["project_id"],
            experiment_plan_id=job.get("experiment_plan_id"),
            limit=100,
            offset=0,
        )
        for payload in claim_payloads_from_job_audit(
            job=job,
            workspace_root=workspace_root,
            artifacts=artifacts,
        ):
            claim = await db.create_claim_ledger_entry(payload)
            claims.append(claim)
            evidence = await db.create_claim_evidence(claim_evidence_payload(claim=claim, job=job))
            evidence_rows.append(evidence)
    return ClaimGenerationRun(claims=claims, evidence=evidence_rows)


async def advance_completed_experiment_pipeline(
    *,
    project_id: UUID,
    experiment_plan_id: UUID,
) -> dict[str, Any]:
    """Advance completed experiment evidence into claims, writing, and submission gates."""

    claims = await db.list_claim_ledger(
        project_id=project_id,
        experiment_plan_id=experiment_plan_id,
        limit=1,
        offset=0,
    )
    generated: ClaimGenerationRun | None = None
    if not claims:
        generated = await generate_claims_from_results(
            experiment_plan_id,
            project_id=project_id,
        )
        claims = generated.claims

    manuscripts = await db.list_manuscript_packages(
        project_id=project_id,
        limit=10,
        offset=0,
    )
    manuscript = manuscripts[0] if manuscripts else None
    if manuscript is None:
        plan = await db.get_experiment_plan(experiment_plan_id)
        title = (plan or {}).get("title") or "Research manuscript"
        manuscript = await db.create_manuscript_package(
            {
                "project_id": project_id,
                "title": f"{title} manuscript",
                "venue_target": None,
                "paper_dir": None,
                "status": "outline",
            }
        )

    if manuscript.get("status") in {None, "outline", "reviewing"} or not manuscript.get("paper_dir"):
        manuscript = await prepare_manuscript_drafting(manuscript["id"])

    submissions = await db.list_submission_packages(
        manuscript_package_id=manuscript["id"],
        limit=10,
        offset=0,
    )
    submission = submissions[0] if submissions else None
    if submission is None:
        submission = await db.create_submission_package(
            {
                "manuscript_package_id": manuscript["id"],
                "venue": manuscript.get("venue_target") or "TBD",
                "checklist_json": {
                    "required_files": [
                        "paper.md",
                        "claims_snapshot.json",
                        "artifact_snapshot.json",
                    ],
                },
                "status": "preparing",
            }
        )
    if submission.get("status") in {"preparing", "gated"}:
        submission = await gate_submission_package(submission["id"])

    return {
        "claims_generated": len(generated.claims) if generated else 0,
        "manuscript_id": manuscript["id"],
        "submission_id": submission["id"],
        "submission_status": submission.get("status"),
    }


async def prepare_manuscript_drafting(manuscript_id: UUID) -> dict[str, Any]:
    manuscript = await db.get_manuscript_package(manuscript_id)
    if manuscript is None:
        raise ValueError(f"Manuscript package not found: {manuscript_id}")
    project = await db.get_project(manuscript["project_id"])
    if project is None:
        raise ValueError(f"Project not found: {manuscript['project_id']}")
    claims = await db.list_claim_ledger(project_id=manuscript["project_id"], limit=100, offset=0)
    artifacts = await db.list_code_artifacts(project_id=manuscript["project_id"], limit=100, offset=0)
    audit = audit_claims(claims)
    next_status = "drafting" if claims and not audit["blockers"] else "reviewing"
    workspace_root = resolve_project_workspace_path(project)
    paper_dir = workspace_root / "manuscripts" / str(manuscript_id)
    paper_dir.mkdir(parents=True, exist_ok=True)
    claims_snapshot = paper_dir / "claims_snapshot.json"
    artifact_snapshot = paper_dir / "artifact_snapshot.json"
    bib_snapshot = paper_dir / "bib_snapshot.json"
    paper_md = paper_dir / "paper.md"
    claims_snapshot.write_text(json.dumps(_jsonable(claims), indent=2, sort_keys=True), encoding="utf-8")
    artifact_snapshot.write_text(json.dumps(_jsonable(artifacts), indent=2, sort_keys=True), encoding="utf-8")
    bib_snapshot_payload = _bib_snapshot_from_claims(claims)
    bib_snapshot.write_text(json.dumps(_jsonable(bib_snapshot_payload), indent=2, sort_keys=True), encoding="utf-8")
    paper_md.write_text(_draft_manuscript_markdown(manuscript, claims, artifacts, audit), encoding="utf-8")
    updates = {
        "status": next_status,
        "paper_dir": _relative_to_workspace(workspace_root, paper_dir),
        "claim_ledger_snapshot_id": claims[0]["id"] if claims else None,
        "artifact_snapshot_id": artifacts[0]["id"] if artifacts else None,
        "bib_snapshot_id": UUID(bib_snapshot_payload["id"]),
    }
    row = await db.update_manuscript_package(manuscript_id, updates)
    await _queue_manuscript_writing_task(
        manuscript=row or {**manuscript, **updates},
        paper_dir=paper_dir,
        audit=audit,
    )
    return row or manuscript


async def gate_submission_package(submission_id: UUID) -> dict[str, Any]:
    submission = await db.get_submission_package(submission_id)
    if submission is None:
        raise ValueError(f"Submission package not found: {submission_id}")
    manuscript = await db.get_manuscript_package(submission["manuscript_package_id"])
    if manuscript is None:
        raise ValueError(f"Manuscript package not found: {submission['manuscript_package_id']}")
    project = await db.get_project(manuscript["project_id"])
    if project is None:
        raise ValueError(f"Project not found: {manuscript['project_id']}")
    workspace_root = resolve_project_workspace_path(project)

    claims = await db.list_claim_ledger(project_id=manuscript["project_id"], limit=100, offset=0)
    artifacts = await db.list_code_artifacts(project_id=manuscript["project_id"], limit=100, offset=0)
    audit = audit_claims(claims)
    checklist_report = _submission_checklist_report(submission, manuscript, workspace_root)
    compile_report = _submission_compile_report(submission, manuscript, workspace_root)
    anonymity_report = _submission_anonymity_report(submission, manuscript, workspace_root)
    citation_report = _submission_citation_report(submission, claims, manuscript, workspace_root)
    provenance_report = _artifact_provenance_report(artifacts, manuscript, workspace_root)
    blocker_count = (
        len(audit["blockers"])
        + len(checklist_report["missing_required_files"])
        + (0 if compile_report["passed"] else 1)
        + (0 if anonymity_report["passed"] else 1)
        + (0 if citation_report["passed"] else 1)
        + (0 if provenance_report["passed"] else 1)
    )
    next_status = "ready" if claims and blocker_count == 0 else "gated"
    reports = {
        "claim_audit_report_json": audit,
        "checklist_json": checklist_report,
        "compile_report_json": compile_report,
        "anonymity_report_json": anonymity_report,
        "citation_audit_report_json": citation_report,
        "artifact_provenance_report_json": provenance_report,
    }
    row = await db.update_submission_package(
        submission_id,
        {
            "status": next_status,
            **reports,
        },
    )
    _write_submission_gate_outputs(
        manuscript=manuscript,
        workspace_root=workspace_root,
        status=next_status,
        reports=reports,
    )
    if next_status != "ready":
        await _queue_submission_revision_task(
            submission=row or {**submission, "status": next_status},
            manuscript=manuscript,
            reports=reports,
        )
    return row or submission


def _jsonable(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


def _draft_manuscript_markdown(
    manuscript: dict[str, Any],
    claims: list[dict[str, Any]],
    artifacts: list[dict[str, Any]],
    audit: dict[str, Any],
) -> str:
    title = manuscript.get("title") or "Research Manuscript"
    supported = [claim for claim in claims if claim.get("status") in {"supported", "partially_supported"}]
    limitations = [claim for claim in claims if claim.get("status") in {"unsupported", "contradicted"}]
    lines = [
        f"# {title}",
        "",
        "## Abstract",
        f"This draft is generated from {len(supported)} supported or partially supported claim(s).",
        "",
        "## Claims",
    ]
    for claim in supported:
        lines.append(f"- {claim['claim_text']} ({claim.get('status')}, support={claim.get('support_level')})")
    lines.extend(["", "## Evidence Artifacts"])
    for artifact in artifacts:
        lines.append(f"- {artifact.get('path')} - {artifact.get('summary') or artifact.get('artifact_type')}")
    lines.extend(["", "## Limitations"])
    if limitations:
        for claim in limitations:
            lines.append(f"- {claim['claim_text']} ({claim.get('status')})")
    else:
        lines.append("- No unsupported or contradicted claims in the current ledger.")
    lines.extend(["", "## Claim Audit", f"- Unsupported claims: {audit['unsupported_claims']}"])
    return "\n".join(lines) + "\n"


def _paper_dir(manuscript: dict[str, Any], workspace_root: Path | None = None) -> Path | None:
    raw = manuscript.get("paper_dir")
    if not raw:
        return None
    if workspace_root is not None:
        try:
            path = resolve_path_reference(workspace_root, raw, field_name="paper_dir")
        except ValueError:
            return None
    else:
        path = Path(str(raw)).expanduser().resolve()
    return path if path.is_dir() else None


def _submission_checklist_report(
    submission: dict[str, Any],
    manuscript: dict[str, Any],
    workspace_root: Path,
) -> dict[str, Any]:
    configured = submission.get("checklist_json") if isinstance(submission.get("checklist_json"), dict) else {}
    required = configured.get("required_files") or ["paper.md", "claims_snapshot.json", "artifact_snapshot.json"]
    paper_dir = _paper_dir(manuscript, workspace_root)
    missing = [
        str(item)
        for item in required
        if paper_dir is None or not (paper_dir / str(item)).is_file()
    ]
    return {"required_files": required, "missing_required_files": missing, "passed": not missing}


def _submission_compile_report(
    submission: dict[str, Any],
    manuscript: dict[str, Any],
    workspace_root: Path,
) -> dict[str, Any]:
    existing = submission.get("compile_report_json") if isinstance(submission.get("compile_report_json"), dict) else {}
    paper_dir = _paper_dir(manuscript, workspace_root)
    paper_path = paper_dir / "paper.md" if paper_dir is not None else None
    paper_exists = paper_path is not None and paper_path.is_file()
    paper_nonempty = paper_exists and paper_path.stat().st_size > 0
    content = paper_path.read_text(encoding="utf-8", errors="replace") if paper_exists else ""
    todo_markers = [
        marker
        for marker in ("TODO", "TBD", "FIXME")
        if marker.lower() in content.lower()
    ]
    checklist = submission.get("checklist_json") if isinstance(submission.get("checklist_json"), dict) else {}
    page_limit_words = checklist.get("page_limit_words")
    word_count = len(content.split()) if content else 0
    over_word_limit = (
        isinstance(page_limit_words, int)
        and page_limit_words > 0
        and word_count > page_limit_words
    )
    external_passed = existing.get("passed") is True
    return {
        **existing,
        "passed": bool(
            paper_nonempty
            and not todo_markers
            and not over_word_limit
            and (external_passed or existing.get("passed") is not False)
        ),
        "auto_checked": True,
        "missing_external_report": False,
        "outputs": existing.get("outputs") or (["paper.md"] if paper_exists else []),
        "compiler": existing.get("compiler") or "markdown-static-check",
        "word_count": word_count,
        "todo_markers": todo_markers,
        "page_limit_words": page_limit_words,
        "over_word_limit": over_word_limit,
    }


def _submission_anonymity_report(
    submission: dict[str, Any],
    manuscript: dict[str, Any],
    workspace_root: Path,
) -> dict[str, Any]:
    existing = submission.get("anonymity_report_json") if isinstance(submission.get("anonymity_report_json"), dict) else {}
    paper_dir = _paper_dir(manuscript, workspace_root)
    content = ""
    if paper_dir and (paper_dir / "paper.md").is_file():
        content = (paper_dir / "paper.md").read_text(encoding="utf-8", errors="replace").lower()
    issues = list(existing.get("issues") or [])
    if "todo deanonymize" in content:
        issues.append("deanonymization marker found")
    return {
        **existing,
        "passed": not issues and existing.get("passed") is not False,
        "auto_checked": True,
        "missing_external_report": False,
        "issues": issues,
    }


def _submission_citation_report(
    submission: dict[str, Any],
    claims: list[dict[str, Any]],
    manuscript: dict[str, Any],
    workspace_root: Path,
) -> dict[str, Any]:
    existing = submission.get("citation_audit_report_json") if isinstance(submission.get("citation_audit_report_json"), dict) else {}
    missing = list(existing.get("missing_citations") or [])
    if not claims:
        missing.append("claim ledger is empty")
    paper_dir = _paper_dir(manuscript, workspace_root)
    content = ""
    if paper_dir and (paper_dir / "paper.md").is_file():
        content = (paper_dir / "paper.md").read_text(encoding="utf-8", errors="replace")
    has_citation_marker = any(marker in content for marker in ("[", "@", "doi:", "arxiv"))
    if claims and content and not has_citation_marker and existing.get("passed") is not True:
        missing.append("paper.md has no citation markers")
    return {
        **existing,
        "passed": not missing and existing.get("passed") is not False,
        "auto_checked": True,
        "missing_external_report": False,
        "missing_citations": missing,
    }


def _write_submission_gate_outputs(
    *,
    manuscript: dict[str, Any],
    workspace_root: Path,
    status: str,
    reports: dict[str, Any],
) -> None:
    paper_dir = _paper_dir(manuscript, workspace_root)
    if paper_dir is None:
        return
    payload = {
        "status": status,
        "generated_at": _utcnow().isoformat(),
        "reports": _jsonable(reports),
    }
    (paper_dir / "SUBMISSION_GATE_REPORT.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    if status != "ready":
        (paper_dir / "RESUBMIT_REPORT.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )


def _artifact_provenance_report(
    artifacts: list[dict[str, Any]],
    manuscript: dict[str, Any],
    workspace_root: Path,
) -> dict[str, Any]:
    missing: list[str] = []
    for artifact in artifacts:
        path = artifact.get("path")
        if not path:
            continue
        try:
            candidate = resolve_path_reference(workspace_root, path, field_name="artifact_path")
        except ValueError:
            exists = False
        else:
            exists = candidate.is_file()
        if not exists:
            missing.append(str(path))
    return {"passed": not missing, "artifact_count": len(artifacts), "missing_artifacts": missing}


def _bib_snapshot_from_claims(claims: list[dict[str, Any]]) -> dict[str, Any]:
    hasher = hashlib.sha256()
    for claim in claims:
        hasher.update(str(claim.get("id")).encode("utf-8"))
        hasher.update(str(claim.get("claim_text", "")).encode("utf-8"))
    digest = hasher.hexdigest()
    snapshot_id = UUID(digest[:32])
    return {
        "id": str(snapshot_id),
        "entries": [],
        "source": "claim-ledger",
        "claim_count": len(claims),
    }
