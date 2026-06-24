#!/usr/bin/env python3
"""Run the production research scheduler."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from apps.worker.production.scheduler import ProductionScheduler  # noqa: E402


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the production research scheduler.")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single scheduler tick and exit.",
    )
    parser.add_argument(
        "--idle-sleep-sec",
        type=float,
        default=5.0,
        help="Seconds to sleep between idle ticks in long-running mode.",
    )
    parser.add_argument(
        "--max-concurrent-tasks",
        type=int,
        default=1,
        help="Maximum queued coding tasks to start per tick.",
    )
    parser.add_argument(
        "--max-concurrent-jobs",
        type=int,
        default=1,
        help="Maximum pending experiment jobs to start per tick.",
    )
    parser.add_argument(
        "--worker-id",
        default=None,
        help="Scheduler worker id written into task/job leases.",
    )
    parser.add_argument(
        "--lease-seconds",
        type=int,
        default=3600,
        help="Seconds claimed work is leased to this scheduler worker.",
    )
    parser.add_argument(
        "--heartbeat-interval-sec",
        type=float,
        default=30.0,
        help="Seconds between scheduler heartbeats for running work.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"),
        help="Python logging level.",
    )
    return parser.parse_args(argv)


async def _run(args: argparse.Namespace) -> int:
    scheduler = ProductionScheduler(
        idle_sleep_sec=args.idle_sleep_sec,
        max_concurrent_tasks=args.max_concurrent_tasks,
        max_concurrent_jobs=args.max_concurrent_jobs,
        worker_id=args.worker_id,
        lease_seconds=args.lease_seconds,
        heartbeat_interval_sec=args.heartbeat_interval_sec,
    )
    if args.once:
        result = await scheduler.run_once()
        logging.getLogger(__name__).info(
            "scheduler tick complete: coding_tasks=%s experiment_jobs=%s errors=%s idle=%s",
            result.coding_tasks_started,
            result.experiment_jobs_started,
            len(result.errors),
            result.idle,
        )
        return 1 if result.errors else 0

    await scheduler.run_forever()
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        return asyncio.run(_run(args))
    except KeyboardInterrupt:
        logging.getLogger(__name__).info("production scheduler stopped")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
