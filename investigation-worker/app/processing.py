"""Stub processing: record the event and open a PENDING investigation (no AI yet)."""

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db import investigations, processed_events
from app.events import IncidentCreatedEvent

log = logging.getLogger(__name__)


async def create_investigation(engine: AsyncEngine, event: IncidentCreatedEvent) -> bool:
    """Idempotent: returns True if an investigation was created, False if the event was a duplicate.

    Both inserts run in ONE transaction (engine.begin() commits at the end, rolls back on error),
    like a @Transactional method: either the event is marked processed AND the investigation
    exists, or neither.
    """
    now = datetime.now(UTC)
    async with engine.begin() as conn:
        # ON CONFLICT DO NOTHING + RETURNING: returns the row only if WE inserted it. If another
        # transaction is inserting the same event_id concurrently, Postgres makes us wait for it,
        # then does nothing, so exactly one of them creates the investigation.
        inserted = await conn.execute(
            pg_insert(processed_events)
            .values(event_id=event.eventId, event_type=event.eventType, processed_at=now)
            .on_conflict_do_nothing(index_elements=[processed_events.c.event_id])
            .returning(processed_events.c.event_id)
        )
        if inserted.first() is None:
            log.info("duplicate, skipping")
            return False

        investigation_id = uuid.uuid4()
        await conn.execute(
            investigations.insert().values(
                id=investigation_id,
                incident_id=event.payload.incidentId,
                tenant_id=event.tenantId,
                status="PENDING",
                request_id=event.requestId,
                created_at=now,
            )
        )
    log.info("investigation %s created for incident %s", investigation_id, event.payload.incidentId)
    return True
