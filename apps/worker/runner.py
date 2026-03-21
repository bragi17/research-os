"""
Research OS - Worker Runner

Standalone worker process that consumes research run jobs from the Redis
queue and executes them through the LangGraph workflow engine.

Usage:
    python -m apps.worker.runner
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys
from datetime import datetime
from typing import Any
from uuid import UUID

from dotenv import load_dotenv
load_dotenv()

from structlog import get_logger

logger = get_logger(__name__)


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

    def __init__(self, concurrency: int = 2):
        self.concurrency = concurrency
        self._shutdown = False
        self._tasks: set[asyncio.Task] = set()

    async def start(self) -> None:
        """Start the worker loop."""
        logger.info("worker.starting", concurrency=self.concurrency)

        # Import here to avoid circular deps
        from apps.api.database import init_pool, close_pool
        from apps.worker.task_queue import close_redis

        await init_pool()

        try:
            workers = [
                asyncio.create_task(self._worker_loop(i))
                for i in range(self.concurrency)
            ]
            self._tasks = set(workers)
            await asyncio.gather(*workers)
        finally:
            await close_pool()
            await close_redis()
            logger.info("worker.stopped")

    async def _worker_loop(self, worker_id: int) -> None:
        """Main loop for a single worker."""
        from apps.worker.task_queue import dequeue_run

        logger.info("worker.loop_started", worker_id=worker_id)

        while not self._shutdown:
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

            # Determine mode from job payload (backward-compat: default "frontier")
            mode = job.get("mode", run.get("mode", "frontier"))

            # Update status to running
            now = datetime.utcnow()
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
            context_bundle = job.get("context_bundle", {})

            # -----------------------------------------------------------------
            # Route to mode-specific graph or fall back to v1
            # -----------------------------------------------------------------
            if mode == "intake":
                # Route first, then create child run
                from apps.worker.modes.router import classify_mode, build_mode_config
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
                library_seeds = await library_prefetch(topic, keywords, limit=10)
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

            now = datetime.utcnow()
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

        except Exception as exc:
            import traceback
            logger.error("worker.run_failed", run_id=str(run_id), error=str(exc),
                         traceback=traceback.format_exc())
            try:
                now = datetime.utcnow()
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

    async def _persist_results(self, run_id: UUID, state) -> None:
        """Persist workflow results (pain points, comparison, context bundle) to DB."""
        from apps.api.database import create_context_bundle, create_pain_point

        try:
            # Save pain points
            for pp in (state.pain_points or []):
                try:
                    await create_pain_point(run_id, {
                        "statement": pp.get("statement", ""),
                        "pain_type": pp.get("pain_type", ""),
                        "severity_score": pp.get("severity_score", 0),
                        "novelty_potential": pp.get("novelty_potential", 0),
                    })
                except Exception:
                    pass  # best-effort

            # Save context bundle (comparison matrix, mindmap, etc.)
            bundle_data = state.context_bundle or {}
            if bundle_data:
                try:
                    bundle = await create_context_bundle({
                        "source_run_id": str(run_id),
                        "source_mode": state.mode or "frontier",
                        "summary_text": state.report_markdown[:5000] if state.report_markdown else "",
                        "benchmark_data": {
                            "comparison_matrix": state.comparison_matrix or [],
                            "gaps": state.gaps or [],
                            "pain_points_count": len(state.pain_points or []),
                            "papers_read": state.papers_read,
                            "papers_discovered": state.papers_discovered,
                        },
                        "mindmap_json": bundle_data.get("mindmap_json", {}),
                    })
                    # Link bundle to run
                    from apps.api.database import update_run
                    await update_run(run_id, {"output_bundle_id": bundle["id"]})
                except Exception as exc:
                    logger.debug("persist_bundle_failed", error=str(exc))

            logger.info("worker.results_persisted", run_id=str(run_id),
                        pain_points=len(state.pain_points or []),
                        has_comparison=bool(state.comparison_matrix))
        except Exception as exc:
            logger.error("worker.persist_results_failed", error=str(exc))

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


async def main() -> None:
    """Entry point for the worker process."""
    runner = WorkerRunner(
        concurrency=int(os.getenv("WORKER_CONCURRENCY", "2")),
    )

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, runner.request_shutdown)

    await runner.start()


if __name__ == "__main__":
    asyncio.run(main())
