"""Tests for the long-running production scheduler."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest

from apps.worker.production.scheduler import ProductionScheduler


@dataclass
class FakeSchedulerDb:
    coding_tasks: list[dict[str, Any]] = field(default_factory=list)
    experiment_jobs: list[dict[str, Any]] = field(default_factory=list)
    experiment_manifests: list[dict[str, Any]] = field(default_factory=list)
    claim_entries: list[dict[str, Any]] = field(default_factory=list)
    coding_task_updates: list[tuple[UUID, dict[str, Any]]] = field(default_factory=list)
    experiment_job_updates: list[tuple[UUID, dict[str, Any]]] = field(default_factory=list)
    coding_events: list[dict[str, Any]] = field(default_factory=list)
    coding_task_list_calls: list[dict[str, Any]] = field(default_factory=list)
    experiment_job_list_calls: list[dict[str, Any]] = field(default_factory=list)
    coding_task_claim_calls: list[int] = field(default_factory=list)
    coding_task_claim_options: list[dict[str, Any]] = field(default_factory=list)
    experiment_job_claim_calls: list[tuple[list[UUID], int]] = field(default_factory=list)
    experiment_job_claim_options: list[dict[str, Any]] = field(default_factory=list)
    recovered_coding_tasks: list[dict[str, Any]] = field(default_factory=list)
    recovered_experiment_jobs: list[dict[str, Any]] = field(default_factory=list)
    lease_guard_allows_update: bool = True

    async def list_coding_tasks(
        self,
        project_id: UUID | None = None,
        run_id: UUID | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        self.coding_task_list_calls.append(
            {
                "project_id": project_id,
                "run_id": run_id,
                "status": status,
                "limit": limit,
                "offset": offset,
            }
        )
        rows = list(self.coding_tasks)
        if status is not None:
            rows = [row for row in rows if row.get("status") == status]
        return rows[offset : offset + limit]

    async def claim_queued_coding_tasks(
        self,
        limit: int = 1,
        worker_id: str | None = None,
        lease_seconds: int = 3600,
    ) -> list[dict[str, Any]]:
        self.coding_task_claim_calls.append(limit)
        self.coding_task_claim_options.append({
            "worker_id": worker_id,
            "lease_seconds": lease_seconds,
        })
        claimed = [
            row for row in self.coding_tasks
            if row.get("status") == "queued"
        ][:limit]
        for row in claimed:
            row["status"] = "running"
        return [dict(row) for row in claimed]

    async def list_experiment_jobs(
        self,
        project_id: UUID | None = None,
        experiment_plan_id: UUID | None = None,
        manifest_id: UUID | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        self.experiment_job_list_calls.append(
            {
                "project_id": project_id,
                "experiment_plan_id": experiment_plan_id,
                "manifest_id": manifest_id,
                "status": status,
                "limit": limit,
                "offset": offset,
            }
        )
        rows = list(self.experiment_jobs)
        if status is not None:
            rows = [row for row in rows if row.get("status") == status]
        if manifest_id is not None:
            rows = [row for row in rows if row.get("manifest_id") == manifest_id]
        return rows[offset : offset + limit]

    async def list_experiment_manifests(
        self,
        project_id: UUID | None = None,
        experiment_plan_id: UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        rows = list(self.experiment_manifests)
        if project_id is not None:
            rows = [row for row in rows if row.get("project_id") == project_id]
        if experiment_plan_id is not None:
            rows = [row for row in rows if row.get("experiment_plan_id") == experiment_plan_id]
        return rows[offset : offset + limit]

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

    async def claim_experiment_jobs(
        self,
        job_ids: list[UUID],
        limit: int = 1,
        worker_id: str | None = None,
        lease_seconds: int = 3600,
    ) -> list[dict[str, Any]]:
        self.experiment_job_claim_calls.append((list(job_ids), limit))
        self.experiment_job_claim_options.append({
            "worker_id": worker_id,
            "lease_seconds": lease_seconds,
        })
        allowed = set(job_ids)
        claimed: list[dict[str, Any]] = []
        for row in self.experiment_jobs:
            if len(claimed) >= limit:
                break
            if row.get("id") in allowed and row.get("status") == "pending":
                row["status"] = "running"
                claimed.append(dict(row))
        return claimed

    async def recover_stale_coding_tasks(self, stale_before: datetime) -> list[dict[str, Any]]:
        for row in self.coding_tasks:
            heartbeat = row.get("updated_at") or row.get("started_at")
            if row.get("status") == "running" and heartbeat and heartbeat < stale_before:
                row["status"] = "queued"
                row["failure_reason"] = "scheduler_recovered_stale_running"
                self.recovered_coding_tasks.append(dict(row))
        return list(self.recovered_coding_tasks)

    async def recover_stale_experiment_jobs(self, stale_before: datetime) -> list[dict[str, Any]]:
        for row in self.experiment_jobs:
            heartbeat = row.get("last_heartbeat_at") or row.get("updated_at")
            if row.get("status") == "running" and heartbeat and heartbeat < stale_before:
                row["status"] = "stuck"
                row["failure_reason"] = "scheduler_stale_heartbeat"
                self.recovered_experiment_jobs.append(dict(row))
        return list(self.recovered_experiment_jobs)

    async def update_coding_task(
        self,
        task_id: UUID,
        updates: dict[str, Any],
    ) -> dict[str, Any] | None:
        self.coding_task_updates.append((task_id, updates))
        for row in self.coding_tasks:
            if row.get("id") == task_id:
                row.update(updates)
                return dict(row)
        return {"id": task_id, **updates}

    async def create_coding_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        row = {"id": len(self.coding_events) + 1, **payload}
        self.coding_events.append(row)
        return row

    async def update_experiment_job(
        self,
        job_id: UUID,
        updates: dict[str, Any],
    ) -> dict[str, Any] | None:
        self.experiment_job_updates.append((job_id, updates))
        for row in self.experiment_jobs:
            if row.get("id") == job_id:
                row.update(updates)
                return dict(row)
        return {"id": job_id, **updates}

    async def update_experiment_job_if_lease(
        self,
        job_id: UUID,
        updates: dict[str, Any],
        *,
        worker_id: str,
        lease_id: str,
    ) -> dict[str, Any] | None:
        if not self.lease_guard_allows_update:
            return None
        return await self.update_experiment_job(job_id, updates)


class FakeSchedulerOrchestrator:
    def __init__(self) -> None:
        self.codex_calls: list[UUID] = []
        self.local_job_calls: list[UUID] = []
        self.research_calls: list[dict[str, Any]] = []
        self.manifest_expansion_calls: list[UUID] = []
        self.pipeline_advance_calls: list[dict[str, UUID]] = []

    async def run_codex_task(
        self,
        task_id: UUID,
        *,
        preclaimed: bool = False,
        claimed_task: dict[str, Any] | None = None,
    ) -> None:
        self.codex_calls.append(task_id)

    async def run_local_job(
        self,
        job_id: UUID,
        *,
        preclaimed: bool = False,
        claimed_job: dict[str, Any] | None = None,
    ) -> None:
        self.local_job_calls.append(job_id)

    async def queue_experiment_research_for_job(
        self,
        job_id: UUID,
        *,
        failure_reason: str,
    ) -> None:
        self.research_calls.append({"job_id": job_id, "failure_reason": failure_reason})

    async def create_manifest_jobs(self, manifest_id: UUID) -> list[dict[str, Any]]:
        self.manifest_expansion_calls.append(manifest_id)
        return []

    async def advance_completed_experiment_pipeline(
        self,
        *,
        project_id: UUID,
        experiment_plan_id: UUID,
    ) -> None:
        self.pipeline_advance_calls.append({
            "project_id": project_id,
            "experiment_plan_id": experiment_plan_id,
        })


class BlockingSchedulerOrchestrator(FakeSchedulerOrchestrator):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def run_codex_task(
        self,
        task_id: UUID,
        *,
        preclaimed: bool = False,
        claimed_task: dict[str, Any] | None = None,
    ) -> None:
        self.codex_calls.append(task_id)
        self.started.set()
        await self.release.wait()

    async def run_local_job(
        self,
        job_id: UUID,
        *,
        preclaimed: bool = False,
        claimed_job: dict[str, Any] | None = None,
    ) -> None:
        self.local_job_calls.append(job_id)
        self.started.set()
        await self.release.wait()


class DispatcherOrchestrator(FakeSchedulerOrchestrator):
    def __init__(self) -> None:
        super().__init__()
        self.dispatch_calls: list[UUID] = []

    async def run_job(
        self,
        job_id: UUID,
        *,
        preclaimed: bool = False,
        claimed_job: dict[str, Any] | None = None,
    ) -> None:
        self.dispatch_calls.append(job_id)


class ExplodingSchedulerOrchestrator(FakeSchedulerOrchestrator):
    def __init__(self, *, task_to_fail: UUID, job_to_fail: UUID) -> None:
        super().__init__()
        self.task_to_fail = task_to_fail
        self.job_to_fail = job_to_fail

    async def run_codex_task(
        self,
        task_id: UUID,
        *,
        preclaimed: bool = False,
        claimed_task: dict[str, Any] | None = None,
    ) -> None:
        await super().run_codex_task(task_id, preclaimed=preclaimed, claimed_task=claimed_task)
        if task_id == self.task_to_fail:
            raise RuntimeError("codex scheduler boom")

    async def run_local_job(
        self,
        job_id: UUID,
        *,
        preclaimed: bool = False,
        claimed_job: dict[str, Any] | None = None,
    ) -> None:
        await super().run_local_job(job_id, preclaimed=preclaimed, claimed_job=claimed_job)
        if job_id == self.job_to_fail:
            raise RuntimeError("job scheduler boom")


@pytest.mark.asyncio
async def test_tick_consumes_queued_coding_tasks_and_pending_jobs_with_caps() -> None:
    task_ids = [uuid4(), uuid4()]
    job_ids = [uuid4(), uuid4(), uuid4()]
    fake_db = FakeSchedulerDb(
        coding_tasks=[{"id": task_id, "status": "queued"} for task_id in task_ids],
        experiment_jobs=[
            {"id": job_id, "status": "pending", "executor_type": "local"}
            for job_id in job_ids
        ],
    )
    fake_orchestrator = FakeSchedulerOrchestrator()
    scheduler = ProductionScheduler(
        db=fake_db,
        orchestrator=fake_orchestrator,
        max_concurrent_tasks=1,
        max_concurrent_jobs=2,
        worker_id="scheduler-a",
        lease_seconds=120,
    )

    result = await scheduler.tick()

    assert fake_db.coding_task_claim_calls == [1]
    assert fake_db.coding_task_claim_options == [
        {"worker_id": "scheduler-a", "lease_seconds": 120}
    ]
    assert any(call["status"] == "pending" for call in fake_db.experiment_job_list_calls)
    assert fake_db.experiment_job_list_calls[-1]["limit"] >= 2
    assert fake_db.experiment_job_claim_calls == [(job_ids[:2], 2)]
    assert fake_db.experiment_job_claim_options == [
        {"worker_id": "scheduler-a", "lease_seconds": 120}
    ]
    assert fake_orchestrator.codex_calls == [task_ids[0]]
    assert fake_orchestrator.local_job_calls == job_ids[:2]
    assert result.coding_tasks_started == 1
    assert result.experiment_jobs_started == 2
    assert result.idle is False
    assert result.errors == []


@pytest.mark.asyncio
async def test_scheduler_can_disable_coding_or_experiment_work_classes() -> None:
    task_id = uuid4()
    job_id = uuid4()
    coding_only_db = FakeSchedulerDb(
        coding_tasks=[{"id": task_id, "status": "queued"}],
        experiment_jobs=[{"id": job_id, "status": "pending", "executor_type": "local"}],
    )
    coding_only_orchestrator = FakeSchedulerOrchestrator()
    coding_only_scheduler = ProductionScheduler(
        db=coding_only_db,
        orchestrator=coding_only_orchestrator,
        max_concurrent_tasks=1,
        max_concurrent_jobs=1,
        enable_experiment_jobs=False,
    )

    coding_only_result = await coding_only_scheduler.tick()

    assert coding_only_db.coding_task_claim_calls == [1]
    assert coding_only_db.experiment_job_list_calls == []
    assert coding_only_db.experiment_job_claim_calls == []
    assert coding_only_orchestrator.codex_calls == [task_id]
    assert coding_only_orchestrator.local_job_calls == []
    assert coding_only_result.coding_tasks_started == 1
    assert coding_only_result.experiment_jobs_started == 0

    job_only_db = FakeSchedulerDb(
        coding_tasks=[{"id": uuid4(), "status": "queued"}],
        experiment_jobs=[{"id": job_id, "status": "pending", "executor_type": "local"}],
    )
    job_only_orchestrator = FakeSchedulerOrchestrator()
    job_only_scheduler = ProductionScheduler(
        db=job_only_db,
        orchestrator=job_only_orchestrator,
        max_concurrent_tasks=1,
        max_concurrent_jobs=1,
        enable_coding_tasks=False,
    )

    job_only_result = await job_only_scheduler.tick()

    assert job_only_db.coding_task_claim_calls == []
    assert job_only_db.experiment_job_claim_calls == [([job_id], 1)]
    assert job_only_orchestrator.codex_calls == []
    assert job_only_orchestrator.local_job_calls == [job_id]
    assert job_only_result.coding_tasks_started == 0
    assert job_only_result.experiment_jobs_started == 1


@pytest.mark.asyncio
async def test_scheduler_heartbeats_long_running_work() -> None:
    task_id = uuid4()
    job_id = uuid4()
    fake_db = FakeSchedulerDb(
        coding_tasks=[{"id": task_id, "status": "queued", "metadata_json": {}}],
        experiment_jobs=[
            {
                "id": job_id,
                "status": "pending",
                "executor_type": "local",
                "metrics_json": {},
            }
        ],
    )
    fake_orchestrator = BlockingSchedulerOrchestrator()
    scheduler = ProductionScheduler(
        db=fake_db,
        orchestrator=fake_orchestrator,
        max_concurrent_tasks=1,
        max_concurrent_jobs=1,
        worker_id="scheduler-heartbeat",
        heartbeat_interval_sec=0.01,
    )

    tick_task = asyncio.create_task(scheduler.tick())
    await asyncio.wait_for(fake_orchestrator.started.wait(), timeout=1)
    for _ in range(100):
        coding_heartbeats = [
            updates
            for _, updates in fake_db.coding_task_updates
            if "metadata_json" in updates
        ]
        job_heartbeats = [
            updates
            for _, updates in fake_db.experiment_job_updates
            if updates.get("metrics_json", {}).get("scheduler_heartbeat")
        ]
        if coding_heartbeats and job_heartbeats:
            break
        await asyncio.sleep(0.01)
    fake_orchestrator.release.set()
    await asyncio.wait_for(tick_task, timeout=1)

    coding_heartbeat = next(
        updates["metadata_json"]["scheduler_heartbeat"]
        for _, updates in fake_db.coding_task_updates
        if "metadata_json" in updates
    )
    job_heartbeat = next(
        updates["metrics_json"]["scheduler_heartbeat"]
        for _, updates in fake_db.experiment_job_updates
        if updates.get("metrics_json", {}).get("scheduler_heartbeat")
    )
    assert coding_heartbeat["worker_id"] == "scheduler-heartbeat"
    assert job_heartbeat["worker_id"] == "scheduler-heartbeat"


@pytest.mark.asyncio
async def test_tick_sleeps_when_idle_if_requested() -> None:
    slept: list[float] = []

    async def fake_sleep(delay: float) -> None:
        slept.append(delay)

    scheduler = ProductionScheduler(
        db=FakeSchedulerDb(),
        orchestrator=FakeSchedulerOrchestrator(),
        idle_sleep_sec=0.25,
        sleeper=fake_sleep,
    )

    result = await scheduler.tick(sleep_when_idle=True)

    assert result.coding_tasks_started == 0
    assert result.experiment_jobs_started == 0
    assert result.idle is True
    assert slept == [0.25]


@pytest.mark.asyncio
async def test_tick_records_scheduler_errors_and_keeps_processing() -> None:
    failing_task_id = uuid4()
    succeeding_task_id = uuid4()
    failing_job_id = uuid4()
    succeeding_job_id = uuid4()
    fake_db = FakeSchedulerDb(
        coding_tasks=[
            {"id": failing_task_id, "status": "queued"},
            {"id": succeeding_task_id, "status": "queued"},
        ],
        experiment_jobs=[
            {"id": failing_job_id, "status": "pending", "executor_type": "local"},
            {"id": succeeding_job_id, "status": "pending", "executor_type": "local"},
        ],
    )
    fake_orchestrator = ExplodingSchedulerOrchestrator(
        task_to_fail=failing_task_id,
        job_to_fail=failing_job_id,
    )
    scheduler = ProductionScheduler(
        db=fake_db,
        orchestrator=fake_orchestrator,
        max_concurrent_tasks=2,
        max_concurrent_jobs=2,
    )

    result = await scheduler.tick()

    assert fake_orchestrator.codex_calls == [failing_task_id, succeeding_task_id]
    assert fake_orchestrator.local_job_calls == [failing_job_id, succeeding_job_id]
    assert len(result.errors) == 2
    assert len(fake_db.coding_task_updates) == 1
    updated_task_id, task_updates = fake_db.coding_task_updates[0]
    assert updated_task_id == failing_task_id
    assert task_updates["status"] == "failed"
    assert task_updates["failure_reason"] == "scheduler_error"
    assert task_updates["failure_detail"] == "codex scheduler boom"
    assert task_updates["completed_at"] is not None
    assert fake_db.coding_events == [
        {
            "id": 1,
            "coding_task_id": failing_task_id,
            "run_id": None,
            "event_type": "log",
            "content": "codex scheduler boom",
            "status_text": "scheduler_error",
            "level": "error",
            "provider_raw_json": {"source": "ProductionScheduler"},
        }
    ]
    assert len(fake_db.experiment_job_updates) == 1
    updated_job_id, job_updates = fake_db.experiment_job_updates[0]
    assert updated_job_id == failing_job_id
    assert job_updates["status"] == "failed"
    assert job_updates["failure_reason"] == "scheduler_error"
    assert job_updates["metrics_json"] == {
        "scheduler_error": "job scheduler boom",
        "scheduler": "ProductionScheduler",
    }
    assert job_updates["completed_at"] is not None
    assert job_updates["last_heartbeat_at"] is not None
    assert fake_orchestrator.research_calls == [
        {"job_id": failing_job_id, "failure_reason": "scheduler_error"}
    ]


@pytest.mark.asyncio
async def test_scheduler_job_error_skips_research_when_lease_guard_fails() -> None:
    job_id = uuid4()
    fake_db = FakeSchedulerDb(lease_guard_allows_update=False)
    fake_orchestrator = FakeSchedulerOrchestrator()
    scheduler = ProductionScheduler(db=fake_db, orchestrator=fake_orchestrator)
    job = {
        "id": job_id,
        "metrics_json": {
            "scheduler_lease": {
                "worker_id": scheduler.worker_id,
                "lease_id": "old-lease",
            }
        },
    }

    await scheduler._record_job_scheduler_error(job, "job scheduler boom")

    assert fake_db.experiment_job_updates == []
    assert fake_orchestrator.research_calls == []


@pytest.mark.asyncio
async def test_job_dispatcher_prefers_run_job_when_available() -> None:
    job_id = uuid4()
    fake_db = FakeSchedulerDb(
        experiment_jobs=[{"id": job_id, "status": "pending", "executor_type": "ssh"}]
    )
    fake_orchestrator = DispatcherOrchestrator()
    scheduler = ProductionScheduler(
        db=fake_db,
        orchestrator=fake_orchestrator,
        max_concurrent_jobs=1,
    )

    result = await scheduler.tick()

    assert fake_orchestrator.dispatch_calls == [job_id]
    assert fake_orchestrator.local_job_calls == []
    assert result.experiment_jobs_started == 1
    assert result.errors == []


@pytest.mark.asyncio
async def test_scheduler_only_claims_jobs_whose_phase_dependencies_are_complete() -> None:
    manifest_id = uuid4()
    sanity_job_id = uuid4()
    full_job_id = uuid4()
    fake_db = FakeSchedulerDb(
        experiment_jobs=[
            {
                "id": sanity_job_id,
                "manifest_id": manifest_id,
                "phase_name": "sanity",
                "status": "running",
                "metrics_json": {"phase_dependencies": []},
            },
            {
                "id": full_job_id,
                "manifest_id": manifest_id,
                "phase_name": "full",
                "status": "pending",
                "metrics_json": {"phase_dependencies": ["sanity"]},
            },
        ],
    )
    fake_orchestrator = FakeSchedulerOrchestrator()
    scheduler = ProductionScheduler(
        db=fake_db,
        orchestrator=fake_orchestrator,
        max_concurrent_jobs=1,
    )

    result = await scheduler.tick()

    assert fake_db.experiment_job_claim_calls == []
    assert fake_orchestrator.local_job_calls == []
    assert result.experiment_jobs_started == 0
    assert result.idle is True

    fake_db.experiment_jobs[0]["status"] = "completed"
    result = await scheduler.tick()

    assert fake_db.experiment_job_claim_calls[-1] == ([full_job_id], 1)
    assert fake_orchestrator.local_job_calls == [full_job_id]
    assert result.experiment_jobs_started == 1


@pytest.mark.asyncio
async def test_scheduler_retries_oom_and_stale_jobs_before_claiming_pending_work() -> None:
    now = datetime.now(timezone.utc)
    stale_running_job_id = uuid4()
    oom_job_id = uuid4()
    fresh_running_task_id = uuid4()
    stale_running_task_id = uuid4()
    fake_db = FakeSchedulerDb(
        coding_tasks=[
            {
                "id": fresh_running_task_id,
                "status": "running",
                "updated_at": now,
            },
            {
                "id": stale_running_task_id,
                "status": "running",
                "updated_at": now - timedelta(hours=3),
            },
        ],
        experiment_jobs=[
            {
                "id": stale_running_job_id,
                "status": "running",
                "last_heartbeat_at": now - timedelta(hours=3),
                "attempt": 1,
                "max_attempts": 2,
                "metrics_json": {"phase_dependencies": []},
            },
            {
                "id": oom_job_id,
                "status": "failed_oom",
                "attempt": 1,
                "max_attempts": 2,
                "failure_reason": "out of memory",
                "metrics_json": {"oom_retry": True, "phase_dependencies": []},
            },
        ],
    )
    fake_orchestrator = FakeSchedulerOrchestrator()
    scheduler = ProductionScheduler(
        db=fake_db,
        orchestrator=fake_orchestrator,
        max_concurrent_tasks=1,
        max_concurrent_jobs=2,
        stale_after_sec=3600,
    )

    result = await scheduler.tick()

    assert fake_db.recovered_coding_tasks[0]["id"] == stale_running_task_id
    assert fake_orchestrator.codex_calls == [stale_running_task_id]
    assert fake_db.recovered_experiment_jobs[0]["id"] == stale_running_job_id
    assert fake_orchestrator.research_calls == [
        {
            "job_id": stale_running_job_id,
            "failure_reason": "scheduler_stale_heartbeat",
        }
    ]
    retried_job_ids = {
        job_id
        for job_id, updates in fake_db.experiment_job_updates
        if updates.get("status") == "pending"
    }
    assert retried_job_ids == {stale_running_job_id, oom_job_id}
    assert fake_db.experiment_job_claim_calls[-1][0] == [stale_running_job_id, oom_job_id]
    assert fake_orchestrator.local_job_calls == [stale_running_job_id, oom_job_id]
    assert result.coding_tasks_started == 1
    assert result.experiment_jobs_started == 2


@pytest.mark.asyncio
async def test_scheduler_expands_accepted_manifests_and_advances_completed_plans() -> None:
    project_id = uuid4()
    plan_id = uuid4()
    manifest_id = uuid4()
    completed_job_id = uuid4()
    fake_db = FakeSchedulerDb(
        experiment_manifests=[
            {
                "id": manifest_id,
                "project_id": project_id,
                "experiment_plan_id": plan_id,
                "status": "accepted",
            }
        ],
        experiment_jobs=[
            {
                "id": completed_job_id,
                "manifest_id": uuid4(),
                "project_id": project_id,
                "experiment_plan_id": plan_id,
                "status": "completed",
                "metrics_json": {"phase_dependencies": []},
            }
        ],
    )
    fake_orchestrator = FakeSchedulerOrchestrator()
    scheduler = ProductionScheduler(
        db=fake_db,
        orchestrator=fake_orchestrator,
        max_concurrent_tasks=1,
        max_concurrent_jobs=1,
    )

    result = await scheduler.tick()

    assert fake_orchestrator.manifest_expansion_calls == [manifest_id]
    assert fake_orchestrator.pipeline_advance_calls == [
        {"project_id": project_id, "experiment_plan_id": plan_id}
    ]
    assert result.idle is True


@pytest.mark.asyncio
async def test_scheduler_advances_completed_plan_even_when_claims_exist() -> None:
    project_id = uuid4()
    plan_id = uuid4()
    fake_db = FakeSchedulerDb(
        claim_entries=[{"id": uuid4(), "project_id": project_id, "experiment_plan_id": plan_id}],
        experiment_jobs=[
            {
                "id": uuid4(),
                "manifest_id": uuid4(),
                "project_id": project_id,
                "experiment_plan_id": plan_id,
                "status": "completed",
                "metrics_json": {"phase_dependencies": []},
            }
        ],
    )
    fake_orchestrator = FakeSchedulerOrchestrator()
    scheduler = ProductionScheduler(
        db=fake_db,
        orchestrator=fake_orchestrator,
        max_concurrent_tasks=1,
        max_concurrent_jobs=1,
    )

    result = await scheduler.tick()

    assert fake_orchestrator.pipeline_advance_calls == [
        {"project_id": project_id, "experiment_plan_id": plan_id}
    ]
    assert result.idle is True
