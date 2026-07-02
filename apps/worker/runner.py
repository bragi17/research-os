"""
Research OS - Worker Runner

Standalone worker process that consumes research run jobs from the Redis
queue and executes them through the LangGraph workflow engine.

Usage:
    python -m apps.worker.runner
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from dotenv import load_dotenv
load_dotenv()

from structlog import get_logger

from apps.worker.run_persistence import persist_results, write_workspace_outputs
from services.research_memory import persist_run_memory
from services.workspace_context import workspace_context

logger = get_logger(__name__)

DEFAULT_WORKER_CONCURRENCY = 2
MIN_WORKER_CONCURRENCY = 1
MAX_WORKER_CONCURRENCY = 16
CONCURRENCY_POLL_SECONDS = 5


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_worker_concurrency(value: Any, default: int = DEFAULT_WORKER_CONCURRENCY) -> int:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        parsed = default
    return max(MIN_WORKER_CONCURRENCY, min(MAX_WORKER_CONCURRENCY, parsed))


def _env_file_value(key: str) -> str | None:
    env_path = Path(os.getenv("ENV_FILE_PATH", "/root/research-os/.env"))
    if not env_path.exists():
        return None
    try:
        for raw_line in env_path.read_text().splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, _, value = line.partition("=")
            if name.strip() == key:
                return value.strip()
    except OSError as exc:
        logger.warning("worker.env_read_failed", path=str(env_path), error=str(exc))
    return None


def read_worker_concurrency(default: int = DEFAULT_WORKER_CONCURRENCY) -> int:
    value = _env_file_value("WORKER_CONCURRENCY")
    if value is None:
        value = os.getenv("WORKER_CONCURRENCY")
    return _normalize_worker_concurrency(value, default=default)


def _coerce_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return dict(parsed) if isinstance(parsed, dict) else {}
    return {}


def _should_auto_spawn_next_mode(
    run: dict[str, Any],
    mode: str,
    final_status: str,
) -> bool:
    if mode != "frontier" or final_status != "completed":
        return False
    policy = _coerce_mapping(run.get("policy_json"))
    if policy.get("auto_continue") is False:
        return False
    if policy.get("auto_spawn_next") is False:
        return False
    goal_type = run.get("goal_type") or "survey_plus_innovations"
    return goal_type == "survey_plus_innovations"


def _context_bundle_for_child(
    parent_run_id: UUID,
    source_mode: str,
    state: Any,
) -> dict[str, Any]:
    context_bundle = _coerce_mapping(getattr(state, "context_bundle", {}))
    context_bundle.setdefault("source_run_id", str(parent_run_id))
    context_bundle.setdefault("source_mode", source_mode)
    if getattr(state, "gaps", None) and "gaps" not in context_bundle:
        context_bundle["gaps"] = list(state.gaps)
    if getattr(state, "pain_points", None) and "pain_points" not in context_bundle:
        context_bundle["pain_points"] = list(state.pain_points)
    if getattr(state, "paper_summaries", None) and "paper_summaries" not in context_bundle:
        context_bundle["paper_summaries"] = list(state.paper_summaries)
    return context_bundle


class WorkerRunner:
    """
    Consumes research run jobs from Redis queue and executes LangGraph workflows.

    Lifecycle:
    1. Dequeue job from Redis
    2. Update DB: status -> running
    3. Initialize LangGraph workflow
    4. Execute workflow (emitting events along the way)
    5. On completion: update DB status -> completed, write report
    6. On failure: update DB status -> failed, log error
    7. On pause: leave DB status as paused, checkpointed
    """

    def __init__(self, concurrency: int = DEFAULT_WORKER_CONCURRENCY):
        self.concurrency = _normalize_worker_concurrency(concurrency)
        self._shutdown = False
        self._tasks: set[asyncio.Task] = set()
        self._worker_tasks: dict[int, asyncio.Task] = {}
        self._retiring_workers: set[int] = set()
        self._next_worker_id = 0

    async def start(self) -> None:
        """Start the worker loop."""
        self.concurrency = read_worker_concurrency(default=self.concurrency)
        logger.info("worker.starting", concurrency=self.concurrency)

        # Import here to avoid circular deps
        from apps.api.database import init_pool, close_pool
        from apps.worker.task_queue import close_redis

        await init_pool()

        try:
            await self._resize_workers(self.concurrency)
            supervisor = asyncio.create_task(self._concurrency_supervisor())
            self._tasks.add(supervisor)
            while not self._shutdown:
                self._prune_worker_tasks()
                await asyncio.sleep(1)
        finally:
            self.request_shutdown()
            await asyncio.gather(
                *self._tasks,
                *self._worker_tasks.values(),
                return_exceptions=True,
            )
            await close_pool()
            await close_redis()
            logger.info("worker.stopped")

    def _start_worker(self) -> None:
        worker_id = self._next_worker_id
        self._next_worker_id += 1
        task = asyncio.create_task(self._worker_loop(worker_id))
        self._worker_tasks[worker_id] = task

    def _prune_worker_tasks(self) -> None:
        for worker_id, task in list(self._worker_tasks.items()):
            if not task.done():
                continue
            self._worker_tasks.pop(worker_id, None)
            self._retiring_workers.discard(worker_id)
            try:
                task.result()
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.error("worker.loop_task_failed", worker_id=worker_id, error=str(exc))

    async def _resize_workers(self, target: int) -> None:
        target = _normalize_worker_concurrency(target, default=self.concurrency)
        self._prune_worker_tasks()
        active_workers = [
            worker_id
            for worker_id, task in self._worker_tasks.items()
            if not task.done() and worker_id not in self._retiring_workers
        ]
        current = len(active_workers)
        if target > current:
            for _ in range(target - current):
                self._start_worker()
        elif target < current:
            for worker_id in sorted(active_workers, reverse=True)[: current - target]:
                self._retiring_workers.add(worker_id)
        if target != self.concurrency:
            logger.info("worker.concurrency_updated", previous=self.concurrency, target=target)
        self.concurrency = target

    async def _concurrency_supervisor(self) -> None:
        while not self._shutdown:
            await self._resize_workers(read_worker_concurrency(default=self.concurrency))
            await asyncio.sleep(CONCURRENCY_POLL_SECONDS)

    async def _worker_loop(self, worker_id: int) -> None:
        """Main loop for a single worker."""
        from apps.worker.task_queue import dequeue_run

        logger.info("worker.loop_started", worker_id=worker_id)

        while not self._shutdown and worker_id not in self._retiring_workers:
            try:
                job = await dequeue_run(timeout=5)
                if job is None:
                    continue

                run_id = UUID(job["run_id"])
                logger.info("worker.job_received", worker_id=worker_id, run_id=str(run_id))

                await self._execute_run(run_id, job)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("worker.loop_error", worker_id=worker_id, error=str(exc))
                await asyncio.sleep(2)
        logger.info("worker.loop_stopped", worker_id=worker_id)

    async def _execute_run(self, run_id: UUID, job: dict[str, Any]) -> None:
        """Execute a single research run, dispatching to mode-specific graphs."""
        from apps.api.database import (
            get_run, update_run, create_event,
        )
        from apps.worker.task_queue import mark_active, mark_inactive, publish_event

        await mark_active(run_id)

        try:
            # Get run config from database
            run = await get_run(run_id)
            if run is None:
                logger.error("worker.run_not_found", run_id=str(run_id))
                return

            workspace_id = run.get("workspace_id")
            if workspace_id is None:
                raise ValueError("Run workspace_id is required")

            with workspace_context(workspace_id):
                await self._execute_run_in_workspace(run_id, job, run)

        except Exception as exc:
            import traceback
            logger.error("worker.run_failed", run_id=str(run_id), error=str(exc),
                         traceback=traceback.format_exc())
            try:
                now = _utcnow()
                await update_run(run_id, {
                    "status": "failed",
                    "updated_at": now,
                    "completed_at": now,
                })
                await create_event(
                    run_id=run_id,
                    event_type="run.failed",
                    severity="error",
                    payload={"error": str(exc)[:500]},
                )
                await publish_event(run_id, {
                    "event_type": "run.failed",
                    "error": str(exc)[:200],
                })
            except Exception as inner:
                logger.error("worker.status_update_failed", error=str(inner))
        finally:
            await mark_inactive(run_id)

    async def _execute_run_in_workspace(
        self,
        run_id: UUID,
        job: dict[str, Any],
        run: dict[str, Any],
    ) -> None:
        """Execute a loaded run inside its workspace context."""
        from apps.api.database import (
            update_run, create_event,
        )
        from apps.worker.task_queue import publish_event

        # Determine mode from job payload (backward-compat: default "frontier")
        mode = job.get("mode", run.get("mode", "frontier"))

        # Update status to running
        now = _utcnow()
        await update_run(run_id, {
            "status": "running",
            "started_at": run.get("started_at") or now,
            "updated_at": now,
            "current_step": f"{mode}_init",
        })

        await create_event(
            run_id=run_id,
            event_type="run.started",
            severity="info",
            payload={"worker": "runner", "mode": mode},
        )
        await publish_event(run_id, {"event_type": "run.started", "mode": mode})

        # Extract config from run and job
        topic = run["topic"]
        budget = run.get("budget_json", {})
        policy = run.get("policy_json", {})
        keywords = job.get("keywords", [])
        seed_paper_ids = job.get("seed_paper_ids", [])
        library_pool_ids = job.get(
            "library_pool_ids",
            policy.get("library_pool_ids", []),
        )
        context_bundle = job.get("context_bundle", {})

        # -----------------------------------------------------------------
        # Route to mode-specific graph or fall back to v1
        # -----------------------------------------------------------------
        if mode == "intake":
            # Route first, then create child run
            from apps.worker.modes.router import build_mode_config
            mode_config = build_mode_config(
                user_input=topic,
                keywords=keywords,
                seed_paper_ids=seed_paper_ids,
            )
            # Re-dispatch as the classified mode
            mode = mode_config.mode.value
            logger.info("worker.intake_routed", run_id=str(run_id), routed_mode=mode)
            # Fall through to the resolved mode below

        from apps.worker.llm_gateway import get_gateway
        gateway = get_gateway()

        # ── Library Prefetch ──
        library_seeds = []
        try:
            from services.library.prefetch import library_prefetch
            library_seeds = await library_prefetch(
                topic,
                keywords,
                pool_ids=library_pool_ids,
                limit=10,
            )
            if library_seeds:
                from apps.worker.modes.base import emit_progress
                await emit_progress(run_id, "library_prefetch", "matched",
                                    f"Found {len(library_seeds)} relevant papers in library")
        except Exception as exc:
            logger.debug("library_prefetch_skipped", error=str(exc))

        result_state = await self._run_mode_graph(
            mode=mode,
            run_id=run_id,
            topic=topic,
            keywords=keywords,
            seed_paper_ids=seed_paper_ids,
            context_bundle=context_bundle,
            budget=budget,
            run_record=run,
            library_seeds=library_seeds,
        )

        # Determine final status
        if result_state.should_pause:
            final_status = "paused"
            final_step = result_state.current_step
            await create_event(
                run_id=run_id,
                event_type="run.paused",
                severity="info",
                payload={
                    "reason": result_state.pause_reason or "budget_or_policy",
                    "papers_read": result_state.papers_read,
                    "cost": result_state.current_cost_usd,
                    "mode": mode,
                },
            )
        elif result_state.should_stop and result_state.stop_reason == "completed":
            final_status = "completed"
            final_step = result_state.current_step
            await create_event(
                run_id=run_id,
                event_type="run.completed",
                severity="info",
                payload={
                    "mode": mode,
                    "papers_discovered": result_state.papers_discovered,
                    "papers_read": result_state.papers_read,
                    "hypotheses": len(result_state.hypotheses),
                    "verified": len(result_state.verified_hypothesis_ids),
                    "iterations": result_state.iteration_count,
                    "cost": result_state.current_cost_usd,
                    "report_length": len(result_state.report_markdown),
                    "total_tokens": gateway.total_tokens if gateway else 0,
                    "llm_calls": gateway.call_count if gateway else 0,
                },
            )
        else:
            final_status = "completed"
            final_step = result_state.current_step

        now = _utcnow()
        update_fields: dict[str, Any] = {
            "status": final_status,
            "current_step": final_step,
            "updated_at": now,
            "progress_pct": 100 if final_status == "completed" else
                min(95, int((result_state.papers_read / max(result_state.max_fulltext_reads, 1)) * 100)),
        }
        if final_status == "completed":
            update_fields["completed_at"] = now
        if result_state.pause_reason:
            update_fields["pause_reason"] = result_state.pause_reason

        await update_run(run_id, update_fields)

        # ── Persist results to database ──
        await self._persist_results(run_id, result_state)
        self._write_workspace_outputs(run_id, run, result_state)
        await self._maybe_spawn_next_mode(
            parent_run_id=run_id,
            parent_run=run,
            mode=mode,
            final_status=final_status,
            result_state=result_state,
        )

        await publish_event(run_id, {
            "event_type": f"run.{final_status}",
            "mode": mode,
            "papers_read": result_state.papers_read,
            "cost": result_state.current_cost_usd,
        })

        logger.info(
            "worker.run_finished",
            run_id=str(run_id),
            mode=mode,
            status=final_status,
            papers=result_state.papers_read,
            cost=f"${result_state.current_cost_usd:.2f}",
        )

    async def _persist_results(self, run_id: UUID, state) -> None:
        """Persist workflow results (pain points, comparison, context bundle) to DB."""
        await persist_results(
            run_id,
            state,
            memory_persister=persist_run_memory,
            log=logger,
        )

    def _write_workspace_outputs(
        self,
        run_id: UUID,
        run: dict[str, Any],
        state,
    ) -> None:
        """Write run outputs into the configured experiment workspace."""
        write_workspace_outputs(run_id, run, state, log=logger)

    async def _maybe_spawn_next_mode(
        self,
        *,
        parent_run_id: UUID,
        parent_run: dict[str, Any],
        mode: str,
        final_status: str,
        result_state: Any,
    ) -> dict[str, Any] | None:
        """Automatically continue the default frontier pipeline into divergent mode."""
        if not _should_auto_spawn_next_mode(parent_run, mode, final_status):
            return None

        from apps.api.database import (
            create_event,
            create_run,
            list_child_runs,
        )
        from apps.worker.task_queue import enqueue_run, publish_event

        existing = await list_child_runs(parent_run_id, mode="divergent")
        if existing:
            logger.info(
                "worker.auto_spawn.skipped_existing",
                parent_id=str(parent_run_id),
                child_id=str(existing[0].get("id")),
                target_mode="divergent",
            )
            return existing[0]

        child_id = uuid4()
        now = _utcnow()
        policy = _coerce_mapping(parent_run.get("policy_json"))
        budget = _coerce_mapping(parent_run.get("budget_json"))
        context_bundle = _context_bundle_for_child(parent_run_id, mode, result_state)

        child_data: dict[str, Any] = {
            "id": child_id,
            "title": f"[divergent] child of {parent_run.get('title', 'unknown')}",
            "topic": parent_run.get("topic", ""),
            "status": "queued",
            "goal_type": parent_run.get("goal_type", "survey_plus_innovations"),
            "autonomy_mode": parent_run.get("autonomy_mode", "default_autonomous"),
            "budget_json": budget,
            "policy_json": policy,
            "progress_pct": 0,
            "current_step": None,
            "started_at": None,
            "completed_at": None,
            "created_at": now,
            "updated_at": now,
            "workspace_id": parent_run.get("workspace_id"),
            "created_by": parent_run.get("created_by"),
            "project_id": parent_run.get("project_id"),
            "mode": "divergent",
            "parent_run_id": parent_run_id,
            "context_bundle_id": parent_run.get("context_bundle_id"),
            "current_stage": "init",
        }

        try:
            child = await create_run(child_data)
            await create_event(
                run_id=child_id,
                event_type="run.created",
                severity="info",
                payload={
                    "title": child_data["title"],
                    "mode": "divergent",
                    "parent_run_id": str(parent_run_id),
                    "auto_spawned": True,
                },
            )

            queue_payload = {
                "project_id": str(parent_run["project_id"]) if parent_run.get("project_id") else None,
                "topic": child_data["topic"],
                "goal_type": child_data["goal_type"],
                "mode": "divergent",
                "keywords": policy.get("keywords", []),
                "seed_paper_ids": policy.get("seed_papers", []),
                "library_pool_ids": policy.get("library_pool_ids", []),
                "budget": budget,
                "context_bundle": context_bundle,
                "parent_run_id": str(parent_run_id),
                "auto_spawned": True,
            }
            await enqueue_run(child_id, queue_payload)
            await create_event(
                run_id=child_id,
                event_type="run.enqueued",
                severity="info",
                payload={"enqueued": True, "auto_spawned": True},
            )
            await create_event(
                run_id=parent_run_id,
                event_type="run.child_spawned",
                severity="info",
                payload={
                    "child_run_id": str(child_id),
                    "target_mode": "divergent",
                    "auto": True,
                },
            )
            await publish_event(
                parent_run_id,
                {
                    "event_type": "run.child_spawned",
                    "severity": "info",
                    "payload": {
                        "child_run_id": str(child_id),
                        "target_mode": "divergent",
                        "auto": True,
                    },
                    "timestamp": now.isoformat(),
                },
            )
            await publish_event(
                child_id,
                {
                    "event_type": "run.enqueued",
                    "severity": "info",
                    "payload": {"enqueued": True, "auto_spawned": True},
                    "timestamp": now.isoformat(),
                },
            )
            logger.info(
                "worker.auto_spawned_child",
                parent_id=str(parent_run_id),
                child_id=str(child_id),
                target_mode="divergent",
            )
            return child
        except Exception as exc:
            logger.error(
                "worker.auto_spawn_failed",
                parent_id=str(parent_run_id),
                target_mode="divergent",
                error=str(exc),
            )
            try:
                await create_event(
                    run_id=parent_run_id,
                    event_type="run.child_spawn_failed",
                    severity="error",
                    payload={"target_mode": "divergent", "error": str(exc)[:500]},
                )
            except Exception:
                pass
            return None

    async def _run_mode_graph(
        self,
        mode: str,
        run_id: UUID,
        topic: str,
        keywords: list[str],
        seed_paper_ids: list[str],
        context_bundle: dict[str, Any],
        budget: dict[str, Any],
        run_record: dict[str, Any],
        library_seeds: list[dict[str, Any]] | None = None,
    ):
        """
        Create, compile, and invoke the appropriate mode-specific graph.

        Falls back to the v1 ResearchWorkflowRunner for unrecognized modes.
        """
        from langgraph.checkpoint.memory import MemorySaver
        from apps.worker.modes.base import ModeGraphState

        # Build common initial state
        initial_state = ModeGraphState(
            run_id=run_id,
            project_id=run_record.get("project_id"),
            thread_id=str(run_id),
            mode=mode,
            topic=topic,
            keywords=keywords,
            seed_paper_ids=seed_paper_ids,
            context_bundle=context_bundle,
            max_papers=budget.get("max_new_papers", 150),
            max_fulltext_reads=budget.get("max_fulltext_reads", 40),
            max_cost_usd=budget.get("max_estimated_cost_usd", 30.0),
            goal_type=run_record.get("goal_type", "survey_plus_innovations"),
            library_seeds=library_seeds or [],
        )

        config = {"configurable": {"thread_id": str(run_id)}}
        checkpointer = MemorySaver()

        if mode == "atlas":
            from apps.worker.modes.atlas import create_atlas_graph
            graph_builder = create_atlas_graph
        elif mode == "frontier":
            from apps.worker.modes.frontier import create_frontier_graph
            graph_builder = create_frontier_graph
        elif mode == "divergent":
            from apps.worker.modes.divergent import create_divergent_graph
            graph_builder = create_divergent_graph
        elif mode == "review":
            from apps.worker.modes.review import create_review_graph
            graph_builder = create_review_graph
        else:
            raise ValueError(
                f"Unrecognized research mode: {mode!r}. "
                f"Valid modes are: atlas, frontier, divergent, review."
            )

        workflow = graph_builder()
        compiled = workflow.compile(checkpointer=checkpointer)

        result = await compiled.ainvoke(
            initial_state.model_dump(),
            config=config,
        )

        # Sanitize messages — LangGraph may inject AIMessage objects
        # that Pydantic cannot directly parse
        if "messages" in result:
            sanitized_msgs = []
            for msg in result["messages"]:
                if isinstance(msg, dict):
                    sanitized_msgs.append(msg)
                elif hasattr(msg, "content"):
                    sanitized_msgs.append({
                        "role": getattr(msg, "type", "assistant"),
                        "content": str(msg.content),
                    })
            result["messages"] = sanitized_msgs

        return ModeGraphState(**result)

    def request_shutdown(self) -> None:
        """Request graceful shutdown."""
        self._shutdown = True
        for task in self._tasks:
            task.cancel()
        for task in self._worker_tasks.values():
            task.cancel()


async def main() -> None:
    """Entry point for the worker process."""
    runner = WorkerRunner(
        concurrency=read_worker_concurrency(),
    )

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, runner.request_shutdown)

    await runner.start()


if __name__ == "__main__":
    asyncio.run(main())
