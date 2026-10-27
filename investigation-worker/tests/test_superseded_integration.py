"""Superseded requests against real PostgreSQL (skipped without Docker).

Events are keyed by incidentId, so an original event stuck in a Kafka backlog is consumed BEFORE the retry that
replaced it. The worker reads incident-service's outbox (public.outbox_events) to see that a newer request exists,
marks the original SUPERSEDED without an LLM call, and runs only the retry.

The fixture creates the two incident-service tables the check reads (the columns it uses; Flyway owns the real
ones) and drops them afterwards, so the other tests keep exercising the "outbox not readable" path.
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from alembic import command
from sqlalchemy import select, text

from app.db import investigations
from app.events import IncidentCreatedEvent
from app.internal_api import latest_investigation
from app.investigations import SUPERSEDED_REASON, InvestigationRef
from app.processing import process_event
from app.request_check import is_superseded
from tests.test_investigation_integration import _alembic_config, _event, _recording_investigate

pytestmark = pytest.mark.integration

T0 = datetime(2026, 10, 27, 9, 0, tzinfo=UTC)


@pytest.fixture
async def outbox(engine):
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE public.incidents (id UUID PRIMARY KEY, tenant_id VARCHAR(64) NOT NULL)"))
        await conn.execute(
            text(
                "CREATE TABLE public.outbox_events (id UUID PRIMARY KEY, aggregate_id UUID NOT NULL, "
                "event_type VARCHAR(100) NOT NULL, created_at TIMESTAMP WITH TIME ZONE NOT NULL)"
            )
        )
    yield
    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE public.outbox_events"))
        await conn.execute(text("DROP TABLE public.incidents"))


async def _incident(engine, event: IncidentCreatedEvent, tenant: str | None = None) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO public.incidents (id, tenant_id) VALUES (:id, :tenant)"),
            {"id": event.payload.incidentId, "tenant": tenant or event.tenantId},
        )


async def _request(engine, event: IncidentCreatedEvent, created_at: datetime) -> None:
    """What incident-service writes for each investigation request (create or retry)."""
    async with engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO public.outbox_events (id, aggregate_id, event_type, created_at) VALUES (:id, :agg, :type, :at)"),
            {"id": event.eventId, "agg": event.payload.incidentId, "type": event.eventType, "at": created_at},
        )


def _retry_of(event: IncidentCreatedEvent) -> IncidentCreatedEvent:
    """A retry: same incident, new event id (incident-service writes a new outbox row)."""
    return event.model_copy(update={"eventId": uuid.uuid4(), "requestId": "req-retry"})


@pytest.mark.usefixtures("outbox")
async def test_original_then_retry_runs_exactly_one_investigation(engine):
    original = _event()
    retry = _retry_of(original)
    await _incident(engine, original)
    await _request(engine, original, T0)
    await _request(engine, retry, T0 + timedelta(minutes=31))  # retried after NOT_STARTED (30 min)
    calls: list[InvestigationRef] = []

    # Kafka order: the original first. A newer request exists: recorded, not run.
    assert await process_event(engine, _recording_investigate(engine, calls=calls), original) == "SUPERSEDED"
    assert calls == []
    # Meanwhile the internal API reports no run yet (incident-service shows PENDING), never SUPERSEDED.
    assert await latest_investigation(engine, original.tenantId, original.payload.incidentId) is None

    assert await process_event(engine, _recording_investigate(engine, calls=calls), retry) == "COMPLETED"
    assert len(calls) == 1  # exactly one investigation (one LLM run) for the two events

    async with engine.connect() as conn:
        rows = (await conn.execute(select(investigations).order_by(investigations.c.created_at))).all()
    assert [(r.status, r.run_count) for r in rows] == [("SUPERSEDED", 0), ("COMPLETED", 1)]
    assert rows[0].failure_reason == SUPERSEDED_REASON and rows[0].completed_at is not None
    latest = await latest_investigation(engine, original.tenantId, original.payload.incidentId)
    assert latest is not None and latest["status"] == "COMPLETED"

    # A redelivered original is skipped (SUPERSEDED is terminal): still one run.
    assert await process_event(engine, _recording_investigate(engine, calls=calls), original) == "SKIPPED"
    assert len(calls) == 1


@pytest.mark.usefixtures("outbox")
async def test_a_single_request_is_unaffected(engine):
    event = _event()
    await _incident(engine, event)
    await _request(engine, event, T0)
    calls: list[InvestigationRef] = []

    assert await process_event(engine, _recording_investigate(engine, calls=calls), event) == "COMPLETED"
    assert len(calls) == 1


@pytest.mark.usefixtures("outbox")
async def test_retry_after_a_finished_run_still_runs(engine):
    """FAILED -> retry: the original was consumed long ago; the retry is the latest request and runs."""
    original = _event()
    await _incident(engine, original)
    await _request(engine, original, T0)
    calls: list[InvestigationRef] = []
    assert await process_event(engine, _recording_investigate(engine, outcome="FAILED", calls=calls), original) == "FAILED"

    retry = _retry_of(original)
    await _request(engine, retry, T0 + timedelta(hours=1))
    assert await process_event(engine, _recording_investigate(engine, calls=calls), retry) == "COMPLETED"
    assert len(calls) == 2


@pytest.mark.usefixtures("outbox")
async def test_check_is_tenant_scoped_and_fails_toward_running(engine):
    original = _event()
    retry = _retry_of(original)
    await _request(engine, original, T0)
    await _request(engine, retry, T0 + timedelta(minutes=1))

    # The incident belongs to another tenant: this tenant's event is not superseded by those rows.
    await _incident(engine, original, tenant="globex")
    assert not await is_superseded(engine, original)

    # An event that is not in the outbox at all (CLI run, older producer) counts as the latest.
    assert not await is_superseded(engine, _event())


async def test_unreadable_outbox_runs_the_investigation(engine):
    """No outbox table (or no permission): the check fails open and the event runs as before."""
    calls: list[InvestigationRef] = []
    assert await process_event(engine, _recording_investigate(engine, calls=calls), _event()) == "COMPLETED"
    assert len(calls) == 1


async def test_migration_0005_down_maps_superseded_to_failed_and_up_again(database_url, engine):
    event = _event()
    async with engine.begin() as conn:
        await conn.execute(
            investigations.insert().values(
                id=uuid.uuid4(),
                incident_id=event.payload.incidentId,
                tenant_id=event.tenantId,
                status="SUPERSEDED",
                created_at=T0,
                failure_reason=SUPERSEDED_REASON,
            )
        )
    config = _alembic_config(database_url)

    await asyncio.to_thread(command.downgrade, config, "0004")
    async with engine.connect() as conn:
        assert (await conn.execute(select(investigations.c.status))).scalar_one() == "FAILED"
    await asyncio.to_thread(command.upgrade, config, "head")
    await engine.dispose()
    async with engine.connect() as conn:
        version = (await conn.execute(text("SELECT version_num FROM worker.alembic_version"))).scalar_one()
    assert version == "0005"
