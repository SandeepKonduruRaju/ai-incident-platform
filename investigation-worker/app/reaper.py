"""Stale-run reaper (milestone 4): investigations stuck in RUNNING with no live run behind them.

How a row gets stuck: a run is claimed (RUNNING), then the worker is killed mid-run and its Kafka event was
already committed (or later skipped), so no redelivery will ever reclaim it. The graph enforces a time budget on
every live run, so a RUNNING row much older than that budget cannot belong to one. Users would see RUNNING
forever; the reaper turns it into FAILED with an explicit reason instead.

Safety:
  - threshold (default 10 min) > the investigation time budget (2 min), checked at startup by Settings;
  - every update is fenced by run_count: a row claimed again in the meantime (redelivery, app.rerun) is left
    alone, so several worker replicas can run the reaper concurrently;
  - the first pass happens one interval after startup, giving redelivered events the first chance to reclaim
    their own rows after a crash.
"""

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncEngine

from app.investigations import find_stale_running, mark_stale_failed
from app.logging_context import investigation_id_var, value_context
from app.metrics import STALE_INVESTIGATIONS_REAPED

log = logging.getLogger(__name__)


async def reap_stale(
    engine: AsyncEngine, *, threshold: timedelta, now: Callable[[], datetime] = lambda: datetime.now(UTC), batch: int = 100
) -> int:
    """One pass: marks every stale RUNNING investigation FAILED; returns how many this call reaped."""
    cutoff = now() - threshold
    reason = (
        f"stale: still RUNNING more than {threshold.total_seconds() / 60:g} min after its run started "
        "(the worker running it stopped); re-run with python -m app.rerun --status FAILED"
    )
    reaped = 0
    for ref in await find_stale_running(engine, started_before=cutoff, limit=batch):
        with value_context(investigation_id_var, str(ref.id)):
            if await mark_stale_failed(engine, ref, reason):
                reaped += 1
                log.warning("reaped stale RUNNING investigation (tenant %s, run %d)", ref.tenant_id, ref.run_count)
            else:
                log.info("stale candidate was claimed or finished meanwhile; left alone")
    if reaped:
        STALE_INVESTIGATIONS_REAPED.inc(reaped)
    return reaped


class StaleRunReaper:
    """Runs reap_stale every interval as a background task (started/stopped by the FastAPI lifespan)."""

    def __init__(
        self,
        reap: Callable[[], Awaitable[int]],
        *,
        interval_seconds: float,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        self._reap = reap
        self._interval = interval_seconds
        self._sleep = sleep
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="stale-run-reaper")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task

    async def _run(self) -> None:
        while True:
            await self._sleep(self._interval)  # first pass after one interval (see the module docstring)
            try:
                await self._reap()
            except asyncio.CancelledError:
                raise
            except Exception:
                # A failed pass (e.g. the database restarting) is retried next interval; never kill the task.
                log.warning("stale-run reaper pass failed", exc_info=True)
