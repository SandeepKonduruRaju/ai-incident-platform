"""Stale-run reaper (milestone 4): RUNNING rows with no live run become FAILED, fenced by run_count.
Integration tests use the PostgreSQL container (skipped without Docker); the loop test needs nothing."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from prometheus_client import REGISTRY
from pydantic import ValidationError
from sqlalchemy import update

from app.config import Settings
from app.db import investigations
from app.investigations import claim, ensure_investigation, find_stale_running, get, mark_stale_failed
from app.reaper import StaleRunReaper, reap_stale
from tests.test_investigation_integration import _event

THRESHOLD = timedelta(minutes=10)


def _reaped_total() -> float:
    return REGISTRY.get_sample_value("stale_investigations_reaped_total") or 0.0


async def _running(engine, started_minutes_ago: float):
    ref, _ = await ensure_investigation(engine, _event())
    running = await claim(engine, ref)
    async with engine.begin() as conn:
        await conn.execute(
            update(investigations)
            .where(investigations.c.id == running.id)
            .values(started_at=datetime.now(UTC) - timedelta(minutes=started_minutes_ago))
        )
    return running


@pytest.mark.integration
async def test_stale_running_investigation_is_marked_failed_with_a_reason(engine):
    stale = await _running(engine, started_minutes_ago=30)
    before = _reaped_total()

    assert await reap_stale(engine, threshold=THRESHOLD) == 1

    row = await get(engine, stale.id)
    assert row["status"] == "FAILED"
    assert row["failure_reason"].startswith("stale: still RUNNING more than 10 min")
    assert row["completed_at"] is not None
    assert _reaped_total() == before + 1


@pytest.mark.integration
async def test_recent_running_and_finished_investigations_are_left_alone(engine):
    recent = await _running(engine, started_minutes_ago=2)  # still within any sane time budget
    pending, _ = await ensure_investigation(engine, _event())
    done = await _running(engine, started_minutes_ago=60)
    async with engine.begin() as conn:
        await conn.execute(update(investigations).where(investigations.c.id == done.id).values(status="COMPLETED"))

    assert await reap_stale(engine, threshold=THRESHOLD) == 0

    assert (await get(engine, recent.id))["status"] == "RUNNING"
    assert (await get(engine, pending.id))["status"] == "PENDING"
    assert (await get(engine, done.id))["status"] == "COMPLETED"


@pytest.mark.integration
async def test_a_row_claimed_again_after_it_was_found_is_not_reaped(engine):
    """Fencing: between finding a stale row and updating it, a redelivery claims it (run_count + 1)."""
    stale = await _running(engine, started_minutes_ago=30)
    [found] = await find_stale_running(engine, started_before=datetime.now(UTC) - THRESHOLD)

    reclaimed = await claim(engine, found)  # the new run wins the row first

    assert reclaimed is not None and reclaimed.run_count == found.run_count + 1
    assert not await mark_stale_failed(engine, found, "stale")
    assert (await get(engine, stale.id))["status"] == "RUNNING"  # the live run keeps its row


async def test_reaper_loop_runs_each_interval_survives_errors_and_stops():
    calls: list[int] = []
    four_passes = asyncio.Event()

    async def reap() -> int:
        calls.append(1)
        if len(calls) == 4:
            four_passes.set()
        if len(calls) == 2:
            raise RuntimeError("database restarting")
        return 0

    async def fast_sleep(_seconds: float) -> None:
        await asyncio.sleep(0)

    reaper = StaleRunReaper(reap, interval_seconds=60, sleep=fast_sleep)
    await reaper.start()
    await asyncio.wait_for(four_passes.wait(), timeout=5)  # the failed second pass did not stop the loop
    await reaper.stop()
    count = len(calls)
    await asyncio.sleep(0.05)
    assert len(calls) == count  # stopped


def test_threshold_must_exceed_the_investigation_time_budget():
    with pytest.raises(ValidationError, match="STALE_RUNNING_THRESHOLD_MINUTES"):
        Settings(database_url="unused", stale_running_threshold_minutes=2, investigation_time_budget_seconds=120)
    assert Settings(database_url="unused").stale_running_threshold_minutes * 60 > 120
