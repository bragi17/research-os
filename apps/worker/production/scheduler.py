"""Long-running scheduler for production research work."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import apps.api.database as production_db
from apps.worker.production import orchestrator as production_orchestrator


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class SchedulerError:
    """A recoverable scheduler-level error from one tick."""

    kind: str
    row_id: UUID | None
    message: str


@dataclass(frozen=True)
class TickResult:
    """Summary of a single scheduler tick."""

    coding_tasks_started: int = 0
    experiment_jobs_started: int = 0
    errors: list[SchedulerError] = field(default_factory=list)
    idle: bool = False

    @property
    def work_started(self) -> int:
        return self.coding_tasks_started + self.experiment_jobs_started


SleepFn = Callable[[float], Awaitable[None]]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _default_worker_id() -> str:
    return f"{socket.gethostname()}-{os.getpid()}"


class ProductionScheduler:
    """Poll queued production work and dispatch it to orchestrator services."""

    def __init__(
        self,
        *,
        db: Any | None = None,
        orchestrator: Any | None = None,
        idle_sleep_sec: float = 5.0,
        max_concurrent_tasks: int = 1,
        max_concurrent_jobs: int = 1,
        enable_coding_tasks: bool = True,
        enable_experiment_jobs: bool = True,
        stale_after_sec: int = 3600,
        worker_id: str | None = None,
        lease_seconds: int = 3600,
        heartbeat_interval_sec: float = 30.0,
        sleeper: SleepFn = asyncio.sleep,
        logger: logging.Logger | None = None,
    ) -> None:
        if max_concurrent_tasks < 1:
            raise ValueError("max_concurrent_tasks must be at least 1")
        if max_concurrent_jobs < 1:
            raise ValueError("max_concurrent_jobs must be at least 1")
        if idle_sleep_sec < 0:
            raise ValueError("idle_sleep_sec must be non-negative")
        if stale_after_sec < 1:
            raise ValueError("stale_after_sec must be at least 1")
        if lease_seconds < 1:
            raise ValueError("lease_seconds must be at least 1")
        if heartbeat_interval_sec <= 0:
            raise ValueError("heartbeat_interval_sec must be positive")

        self.db = db or production_db
        self.orchestrator = orchestrator or production_orchestrator
        self.idle_sleep_sec = idle_sleep_sec
        self.max_concurrent_tasks = max_concurrent_tasks
        self.max_concurrent_jobs = max_concurrent_jobs
        self.enable_coding_tasks = enable_coding_tasks
        self.enable_experiment_jobs = enable_experiment_jobs
        self.stale_after_sec = stale_after_sec
        self.worker_id = worker_id or _default_worker_id()
        self.lease_seconds = lease_seconds
        self.heartbeat_interval_sec = heartbeat_interval_sec
        self._sleep = sleeper
        self._logger = logger or LOGGER

    async def run_once(self) -> TickResult:
        """Run one scheduler tick without idle sleeping."""

        return await self.tick(sleep_when_idle=False)

    async def run_forever(self) -> None:
        """Run scheduler ticks until cancelled."""

        while True:
            await self.tick(sleep_when_idle=True)

    async def tick(self, *, sleep_when_idle: bool = False) -> TickResult:
        """Run one scheduler tick.

        The tick pulls at most the configured caps from each queue. It waits for
        all work started by the tick to finish before returning.
        """

        errors: list[SchedulerError] = []
        await self._recover_stale_work(errors)
        if self.enable_experiment_jobs:
            await self._prepare_retryable_experiment_jobs(errors)
            await self._expand_accepted_manifests(errors)

        coding_tasks = await self._claim_queued_coding_tasks(errors) if self.enable_coding_tasks else []
        experiment_jobs = (
            await self._claim_eligible_experiment_jobs(errors)
            if self.enable_experiment_jobs
            else []
        )

        work: list[Awaitable[SchedulerError | None]] = []
        work.extend(self._run_coding_task(task) for task in coding_tasks)
        work.extend(self._run_experiment_job(job) for job in experiment_jobs)

        if work:
            results = await asyncio.gather(*work)
            errors.extend(error for error in results if error is not None)
        if self.enable_experiment_jobs:
            await self._advance_completed_experiments(errors)

        idle = not coding_tasks and not experiment_jobs
        if idle and sleep_when_idle and self.idle_sleep_sec > 0:
            await self._sleep(self.idle_sleep_sec)

        return TickResult(
            coding_tasks_started=len(coding_tasks),
            experiment_jobs_started=len(experiment_jobs),
            errors=errors,
            idle=idle,
        )

    async def _expand_accepted_manifests(self, errors: list[SchedulerError]) -> None:
        list_manifests = getattr(self.db, "list_experiment_manifests", None)
        create_jobs = getattr(self.orchestrator, "create_manifest_jobs", None)
        if not callable(list_manifests) or not callable(create_jobs):
            return
        try:
            manifests = await list_manifests(limit=100, offset=0)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._logger.exception("Failed to list experiment manifests for expansion")
            errors.append(SchedulerError(kind="manifest_expand_poll", row_id=None, message=str(exc)))
            return

        for manifest in manifests:
            if manifest.get("status") != "accepted":
                continue
            manifest_id = manifest.get("id")
            try:
                existing_jobs = await self.db.list_experiment_jobs(
                    manifest_id=manifest_id,
                    limit=1,
                    offset=0,
                )
                if existing_jobs:
                    continue
                await create_jobs(manifest_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._logger.exception("Failed to expand accepted manifest %s", manifest_id)
                errors.append(
                    SchedulerError(
                        kind="manifest_expand",
                        row_id=manifest_id,
                        message=str(exc),
                    )
                )

    async def _advance_completed_experiments(self, errors: list[SchedulerError]) -> None:
        advance = getattr(self.orchestrator, "advance_completed_experiment_pipeline", None)
        if not callable(advance):
            return
        try:
            jobs = await self.db.list_experiment_jobs(limit=1000, offset=0)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._logger.exception("Failed to list experiment jobs for pipeline advance")
            errors.append(SchedulerError(kind="pipeline_advance_poll", row_id=None, message=str(exc)))
            return

        by_plan: dict[tuple[UUID, UUID], list[dict[str, Any]]] = {}
        for job in jobs:
            plan_id = job.get("experiment_plan_id")
            project_id = job.get("project_id")
            if plan_id is None or project_id is None:
                continue
            by_plan.setdefault((project_id, plan_id), []).append(job)

        terminal = {"completed", "failed", "failed_oom", "timeout", "stuck", "cancelled"}
        for (project_id, plan_id), plan_jobs in by_plan.items():
            statuses = {job.get("status") for job in plan_jobs}
            if not plan_jobs or not statuses or not statuses.issubset(terminal):
                continue
            if "completed" not in statuses:
                continue
            try:
                await advance(project_id=project_id, experiment_plan_id=plan_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._logger.exception("Failed to advance completed experiment plan %s", plan_id)
                errors.append(
                    SchedulerError(
                        kind="pipeline_advance",
                        row_id=plan_id,
                        message=str(exc),
                    )
                )

    async def _claim_queued_coding_tasks(
        self,
        errors: list[SchedulerError],
    ) -> list[dict[str, Any]]:
        try:
            claim = getattr(self.db, "claim_queued_coding_tasks", None)
            if callable(claim):
                return await claim(
                    limit=self.max_concurrent_tasks,
                    worker_id=self.worker_id,
                    lease_seconds=self.lease_seconds,
                )
            return await self.db.list_coding_tasks(
                status="queued",
                limit=self.max_concurrent_tasks,
                offset=0,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            message = str(exc)
            self._logger.exception("Failed to poll queued coding tasks")
            errors.append(SchedulerError(kind="coding_task_poll", row_id=None, message=message))
            return []

    async def _list_pending_experiment_jobs(
        self,
        errors: list[SchedulerError],
    ) -> list[dict[str, Any]]:
        try:
            return await self.db.list_experiment_jobs(
                status="pending",
                limit=max(self.max_concurrent_jobs * 10, self.max_concurrent_jobs),
                offset=0,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            message = str(exc)
            self._logger.exception("Failed to poll pending experiment jobs")
            errors.append(SchedulerError(kind="experiment_job_poll", row_id=None, message=message))
            return []

    async def _claim_eligible_experiment_jobs(
        self,
        errors: list[SchedulerError],
    ) -> list[dict[str, Any]]:
        candidates = await self._list_pending_experiment_jobs(errors)
        if not candidates:
            return []

        eligible: list[dict[str, Any]] = []
        manifest_cache: dict[Any, list[dict[str, Any]]] = {}
        for job in candidates:
            if await self._job_dependencies_satisfied(job, manifest_cache, errors):
                eligible.append(job)
            if len(eligible) >= self.max_concurrent_jobs:
                break

        if not eligible:
            return []

        job_ids = [job["id"] for job in eligible]
        try:
            claim = getattr(self.db, "claim_experiment_jobs", None)
            if callable(claim):
                return await claim(
                    job_ids,
                    limit=self.max_concurrent_jobs,
                    worker_id=self.worker_id,
                    lease_seconds=self.lease_seconds,
                )
            return eligible[: self.max_concurrent_jobs]
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            message = str(exc)
            self._logger.exception("Failed to claim pending experiment jobs")
            errors.append(SchedulerError(kind="experiment_job_claim", row_id=None, message=message))
            return []

    async def _job_dependencies_satisfied(
        self,
        job: dict[str, Any],
        manifest_cache: dict[Any, list[dict[str, Any]]],
        errors: list[SchedulerError],
    ) -> bool:
        metrics = job.get("metrics_json") if isinstance(job.get("metrics_json"), dict) else {}
        dependencies = metrics.get("phase_dependencies") if isinstance(metrics, dict) else []
        if not dependencies:
            return True
        manifest_id = job.get("manifest_id")
        if manifest_id is None:
            return False

        if manifest_id not in manifest_cache:
            try:
                manifest_cache[manifest_id] = await self.db.list_experiment_jobs(
                    manifest_id=manifest_id,
                    limit=1000,
                    offset=0,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                message = str(exc)
                self._logger.exception("Failed to load manifest jobs for dependency check")
                errors.append(
                    SchedulerError(
                        kind="experiment_job_dependency_poll",
                        row_id=job.get("id"),
                        message=message,
                    )
                )
                return False

        rows = manifest_cache[manifest_id]
        for phase_name in dependencies:
            phase_jobs = [row for row in rows if row.get("phase_name") == phase_name]
            if not phase_jobs or any(row.get("status") != "completed" for row in phase_jobs):
                return False
        return True

    async def _recover_stale_work(self, errors: list[SchedulerError]) -> None:
        stale_before = _utcnow() - timedelta(seconds=self.stale_after_sec)
        recovery_methods = []
        if self.enable_coding_tasks:
            recovery_methods.append(("coding_task_recovery", "recover_stale_coding_tasks"))
        if self.enable_experiment_jobs:
            recovery_methods.append(("experiment_job_recovery", "recover_stale_experiment_jobs"))

        for kind, method_name in recovery_methods:
            method = getattr(self.db, method_name, None)
            if not callable(method):
                continue
            try:
                recovered = await method(stale_before)
                if method_name == "recover_stale_experiment_jobs":
                    for job in recovered or []:
                        await self._queue_experiment_research_for_job(
                            job,
                            failure_reason=job.get("failure_reason")
                            or "scheduler_stale_heartbeat",
                            errors=errors,
                        )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                message = str(exc)
                self._logger.exception("Failed during scheduler stale recovery: %s", method_name)
                errors.append(SchedulerError(kind=kind, row_id=None, message=message))

    async def _prepare_retryable_experiment_jobs(self, errors: list[SchedulerError]) -> None:
        for status in ("failed", "failed_oom", "timeout", "stuck"):
            try:
                rows = await self.db.list_experiment_jobs(
                    status=status,
                    limit=100,
                    offset=0,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                message = str(exc)
                self._logger.exception("Failed to poll retryable experiment jobs")
                errors.append(
                    SchedulerError(
                        kind="experiment_job_retry_poll",
                        row_id=None,
                        message=message,
                    )
                )
                continue

            for job in rows:
                if self._should_retry_job(job):
                    await self._mark_job_pending_for_retry(job, errors)

    def _should_retry_job(self, job: dict[str, Any]) -> bool:
        attempt = int(job.get("attempt") or 1)
        max_attempts = int(job.get("max_attempts") or 1)
        if attempt >= max_attempts:
            return False

        metrics = job.get("metrics_json") if isinstance(job.get("metrics_json"), dict) else {}
        oom_retry = bool(metrics.get("oom_retry")) if isinstance(metrics, dict) else False
        status = job.get("status")
        is_oom = status == "failed_oom" or self._looks_like_oom_failure(job)
        if is_oom:
            return oom_retry
        return status in {"failed", "timeout", "stuck"}

    @staticmethod
    def _looks_like_oom_failure(job: dict[str, Any]) -> bool:
        haystack = " ".join(
            str(part or "")
            for part in (
                job.get("failure_reason"),
                (job.get("metrics_json") or {}).get("error")
                if isinstance(job.get("metrics_json"), dict)
                else None,
            )
        ).lower()
        return "oom" in haystack or "out of memory" in haystack

    async def _mark_job_pending_for_retry(
        self,
        job: dict[str, Any],
        errors: list[SchedulerError],
    ) -> None:
        job_id = job["id"]
        metrics = dict(job.get("metrics_json") or {})
        history = list(metrics.get("retry_history") or [])
        history.append(
            {
                "from_status": job.get("status"),
                "from_attempt": int(job.get("attempt") or 1),
                "failure_reason": job.get("failure_reason"),
                "scheduled_at": _utcnow().isoformat(),
            }
        )
        metrics["retry_history"] = history
        metrics["scheduler_retry"] = True
        try:
            await self.db.update_experiment_job(
                job_id,
                {
                    "status": "pending",
                    "attempt": int(job.get("attempt") or 1) + 1,
                    "started_at": None,
                    "completed_at": None,
                    "last_heartbeat_at": None,
                    "failure_reason": None,
                    "metrics_json": metrics,
                },
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            message = str(exc)
            self._logger.exception("Failed to mark experiment job %s pending for retry", job_id)
            errors.append(
                SchedulerError(kind="experiment_job_retry", row_id=job_id, message=message)
            )

    async def _run_coding_task(self, task: dict[str, Any]) -> SchedulerError | None:
        task_id = task["id"]
        heartbeat_task = self._start_heartbeat("coding_task", task)
        try:
            await self.orchestrator.run_codex_task(task_id, preclaimed=True, claimed_task=task)
            return None
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            message = str(exc)
            self._logger.exception("Scheduler failed while running coding task %s", task_id)
            await self._record_coding_scheduler_error(task, message)
            return SchedulerError(kind="coding_task", row_id=task_id, message=message)
        finally:
            await self._stop_heartbeat(heartbeat_task)

    async def _run_experiment_job(self, job: dict[str, Any]) -> SchedulerError | None:
        job_id = job["id"]
        heartbeat_task = self._start_heartbeat("experiment_job", job)
        try:
            await self._dispatch_experiment_job(job)
            return None
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            message = str(exc)
            self._logger.exception("Scheduler failed while running experiment job %s", job_id)
            await self._record_job_scheduler_error(job, message)
            return SchedulerError(kind="experiment_job", row_id=job_id, message=message)
        finally:
            await self._stop_heartbeat(heartbeat_task)

    def _start_heartbeat(
        self,
        row_type: str,
        row: dict[str, Any],
    ) -> asyncio.Task[None]:
        return asyncio.create_task(self._heartbeat_loop(row_type, row))

    async def _stop_heartbeat(self, task: asyncio.Task[None]) -> None:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def _heartbeat_loop(self, row_type: str, row: dict[str, Any]) -> None:
        while True:
            await self._sleep(self.heartbeat_interval_sec)
            try:
                if row_type == "coding_task":
                    await self._heartbeat_coding_task(row)
                else:
                    await self._heartbeat_experiment_job(row)
            except asyncio.CancelledError:
                raise
            except Exception:
                self._logger.exception("Failed to heartbeat %s %s", row_type, row.get("id"))

    def _heartbeat_payload(self, now: datetime) -> dict[str, Any]:
        return {
            "worker_id": self.worker_id,
            "heartbeat_at": now.isoformat(),
            "claimed_until": (now + timedelta(seconds=self.lease_seconds)).isoformat(),
            "lease_seconds": self.lease_seconds,
        }

    @staticmethod
    def _lease_identity(row: dict[str, Any], field_name: str) -> tuple[str | None, str | None]:
        metadata = row.get(field_name) if isinstance(row.get(field_name), dict) else {}
        lease = metadata.get("scheduler_lease") if isinstance(metadata, dict) else None
        worker_id = lease.get("worker_id") if isinstance(lease, dict) else None
        lease_id = lease.get("lease_id") if isinstance(lease, dict) else None
        return (
            str(worker_id) if worker_id else None,
            str(lease_id) if lease_id else None,
        )

    async def _heartbeat_coding_task(self, task: dict[str, Any]) -> None:
        now = _utcnow()
        heartbeat = self._heartbeat_payload(now)
        worker_id, lease_id = self._lease_identity(task, "metadata_json")
        guarded_heartbeat = getattr(self.db, "heartbeat_coding_task_if_lease", None)
        if worker_id and lease_id and callable(guarded_heartbeat):
            updated = await guarded_heartbeat(
                task["id"],
                worker_id=worker_id,
                lease_id=lease_id,
                heartbeat=heartbeat,
            )
            if updated is None:
                return
        else:
            metadata = dict(task.get("metadata_json") or {})
            metadata["scheduler_heartbeat"] = heartbeat
            updated = await self.db.update_coding_task(task["id"], {"metadata_json": metadata})
        if isinstance(updated, dict):
            task.update(updated)
        else:
            metadata = dict(task.get("metadata_json") or {})
            metadata["scheduler_heartbeat"] = heartbeat
            task["metadata_json"] = metadata

    async def _heartbeat_experiment_job(self, job: dict[str, Any]) -> None:
        now = _utcnow()
        heartbeat = self._heartbeat_payload(now)
        worker_id, lease_id = self._lease_identity(job, "metrics_json")
        guarded_heartbeat = getattr(self.db, "heartbeat_experiment_job_if_lease", None)
        if worker_id and lease_id and callable(guarded_heartbeat):
            updated = await guarded_heartbeat(
                job["id"],
                worker_id=worker_id,
                lease_id=lease_id,
                heartbeat=heartbeat,
                last_heartbeat_at=now,
            )
            if updated is None:
                return
        else:
            metrics = dict(job.get("metrics_json") or {})
            metrics["scheduler_heartbeat"] = heartbeat
            updated = await self.db.update_experiment_job(
                job["id"],
                {"last_heartbeat_at": now, "metrics_json": metrics},
            )
        if isinstance(updated, dict):
            job.update(updated)
        else:
            metrics = dict(job.get("metrics_json") or {})
            metrics["scheduler_heartbeat"] = heartbeat
            job["metrics_json"] = metrics
            job["last_heartbeat_at"] = now

    async def _dispatch_experiment_job(self, job: dict[str, Any]) -> Any:
        run_job = getattr(self.orchestrator, "run_job", None)
        if callable(run_job):
            return await run_job(job["id"], preclaimed=True, claimed_job=job)

        executor_type = job.get("executor_type") or "local"
        if executor_type != "local":
            raise RuntimeError(f"no dispatcher available for {executor_type} experiment jobs")
        return await self.orchestrator.run_local_job(job["id"], preclaimed=True, claimed_job=job)

    async def _record_coding_scheduler_error(
        self,
        task: dict[str, Any],
        message: str,
    ) -> None:
        task_id = task["id"]
        now = _utcnow()
        lease_owned = True
        try:
            updates = {
                "status": "failed",
                "failure_reason": "scheduler_error",
                "failure_detail": message,
                "completed_at": now,
            }
            worker_id, lease_id = self._lease_identity(task, "metadata_json")
            guarded_update = getattr(self.db, "update_coding_task_if_lease", None)
            if worker_id and lease_id and callable(guarded_update):
                lease_owned = (
                    await guarded_update(task_id, updates, worker_id=worker_id, lease_id=lease_id)
                ) is not None
            else:
                await self.db.update_coding_task(task_id, updates)
        except asyncio.CancelledError:
            raise
        except Exception:
            lease_owned = False
            self._logger.exception("Failed to mark coding task %s as failed", task_id)

        if lease_owned:
            try:
                await self.db.create_coding_event(
                    {
                        "coding_task_id": task_id,
                        "run_id": task.get("run_id"),
                        "event_type": "log",
                        "content": message,
                        "status_text": "scheduler_error",
                        "level": "error",
                        "provider_raw_json": {"source": "ProductionScheduler"},
                    }
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                self._logger.exception("Failed to record scheduler event for coding task %s", task_id)

    async def _record_job_scheduler_error(
        self,
        job: dict[str, Any],
        message: str,
    ) -> None:
        job_id = job["id"]
        now = _utcnow()
        lease_owned = True
        metrics = dict(job.get("metrics_json") or {})
        metrics.update(
            {
                "scheduler_error": message,
                "scheduler": "ProductionScheduler",
            }
        )
        try:
            updates = {
                "status": "failed",
                "failure_reason": "scheduler_error",
                "completed_at": now,
                "last_heartbeat_at": now,
                "metrics_json": metrics,
            }
            worker_id, lease_id = self._lease_identity(job, "metrics_json")
            guarded_update = getattr(self.db, "update_experiment_job_if_lease", None)
            if worker_id and lease_id and callable(guarded_update):
                lease_owned = (
                    await guarded_update(job_id, updates, worker_id=worker_id, lease_id=lease_id)
                ) is not None
            else:
                await self.db.update_experiment_job(job_id, updates)
        except asyncio.CancelledError:
            raise
        except Exception:
            lease_owned = False
            self._logger.exception("Failed to mark experiment job %s as failed", job_id)
        if lease_owned:
            await self._queue_experiment_research_for_job(
                job,
                failure_reason="scheduler_error",
                errors=None,
            )

    async def _queue_experiment_research_for_job(
        self,
        job: dict[str, Any],
        *,
        failure_reason: str,
        errors: list[SchedulerError] | None,
    ) -> None:
        queue_research = getattr(self.orchestrator, "queue_experiment_research_for_job", None)
        if not callable(queue_research):
            return
        job_id = job.get("id")
        try:
            await queue_research(job_id, failure_reason=failure_reason)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._logger.exception("Failed to queue experiment research for job %s", job_id)
            if errors is not None:
                errors.append(
                    SchedulerError(
                        kind="experiment_job_research",
                        row_id=job_id,
                        message=str(exc),
                    )
                )
