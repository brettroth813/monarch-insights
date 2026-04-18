"""Asyncio-driven scheduler that owns the recurring jobs.

Why hand-rolled instead of APScheduler? Two reasons: (1) one fewer dependency to ship to
HAOS, (2) we get clean integration with the existing event log / structured logger.

Job lifecycle
-------------

Each job is an async callable plus a ``next_run_at`` cursor. ``run_forever`` sleeps until
the soonest cursor, fires that job, records start/finish events, recomputes the cursor,
and loops. Failures are logged + recorded, never re-raised — one bad job shouldn't tear
down the daemon. We use a ``2 ** attempts`` backoff capped at 30 minutes so a flapping
service doesn't wake us up every minute.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Awaitable, Callable

from monarch_insights.observability import EventLog, get_logger

log = get_logger(__name__)


JobFn = Callable[[], Awaitable[None]]


@dataclass
class Job:
    name: str
    fn: JobFn
    interval: timedelta | None = None  # None for daily-at jobs
    daily_at: time | None = None
    next_run_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    consecutive_failures: int = 0

    def schedule_next(self) -> None:
        now = datetime.now(timezone.utc)
        if self.interval is not None:
            self.next_run_at = now + self.interval
        elif self.daily_at is not None:
            target = datetime.combine(date.today(), self.daily_at, tzinfo=timezone.utc)
            if target <= now:
                target += timedelta(days=1)
            self.next_run_at = target

    def schedule_backoff(self) -> None:
        delay_seconds = min(60 * (2 ** min(self.consecutive_failures, 5)), 1800)
        self.next_run_at = datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)


@dataclass
class DaemonConfig:
    sync_interval: timedelta = timedelta(hours=1)
    alerts_interval: timedelta = timedelta(hours=1)
    digest_at: time = time(7, 0)
    watchlist_at: time = time(8, 30)
    gap_scan_at: time = time(6, 0)


class MonarchDaemon:
    """Coordinates the recurring jobs.

    The daemon does not know how to do *any* of the work itself — callers register job
    functions before calling :meth:`run_forever`. This keeps the scheduler pure and the
    business logic mockable.
    """

    def __init__(self, config: DaemonConfig | None = None, *, event_log: EventLog | None = None) -> None:
        self.config = config or DaemonConfig()
        self.event_log = event_log or EventLog()
        self.jobs: dict[str, Job] = {}
        self._stop = asyncio.Event()

    # ------------------------------------------------------------------ registration

    def register_interval(self, name: str, fn: JobFn, interval: timedelta) -> None:
        self.jobs[name] = Job(name=name, fn=fn, interval=interval)

    def register_daily(self, name: str, fn: JobFn, at: time) -> None:
        self.jobs[name] = Job(name=name, fn=fn, daily_at=at)
        self.jobs[name].schedule_next()

    # ------------------------------------------------------------------ control

    def stop(self) -> None:
        """Ask :meth:`run_forever` to exit at its next loop iteration."""
        self._stop.set()

    async def run_forever(self) -> None:
        """Main loop. Sleeps until the next due job, fires it, repeats until stopped."""
        if not self.jobs:
            log.warning("daemon.start", extra={"jobs": 0})
            return
        log.info("daemon.start", extra={"jobs": list(self.jobs.keys())})
        self.event_log.record("daemon", "start", {"jobs": list(self.jobs.keys())})
        try:
            while not self._stop.is_set():
                job = self._next_job()
                wait_seconds = max(0.0, (job.next_run_at - datetime.now(timezone.utc)).total_seconds())
                if wait_seconds > 0:
                    try:
                        await asyncio.wait_for(self._stop.wait(), timeout=wait_seconds)
                        # ``wait`` returned because stop was set — exit cleanly.
                        break
                    except asyncio.TimeoutError:
                        pass
                await self._run_job(job)
        finally:
            log.info("daemon.stop")
            self.event_log.record("daemon", "stop")

    # ------------------------------------------------------------------ internal

    def _next_job(self) -> Job:
        return min(self.jobs.values(), key=lambda j: j.next_run_at)

    async def _run_job(self, job: Job) -> None:
        started = datetime.now(timezone.utc)
        log.info("daemon.job.start", extra={"job": job.name})
        run_id = self.event_log.record("daemon.job", "started", {"job": job.name})
        try:
            await job.fn()
        except Exception as exc:  # noqa: BLE001 — we deliberately swallow + record
            job.consecutive_failures += 1
            elapsed = (datetime.now(timezone.utc) - started).total_seconds()
            log.exception("daemon.job.failed", extra={"job": job.name, "elapsed_s": elapsed})
            self.event_log.record(
                "daemon.job",
                "failed",
                {"job": job.name, "error": repr(exc), "elapsed_s": elapsed},
                ref=str(run_id),
                severity="warn",
            )
            job.schedule_backoff()
            return
        job.consecutive_failures = 0
        elapsed = (datetime.now(timezone.utc) - started).total_seconds()
        log.info("daemon.job.completed", extra={"job": job.name, "elapsed_s": elapsed})
        self.event_log.record(
            "daemon.job",
            "completed",
            {"job": job.name, "elapsed_s": elapsed},
            ref=str(run_id),
        )
        job.schedule_next()
