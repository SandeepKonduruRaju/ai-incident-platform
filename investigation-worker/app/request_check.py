"""Is this event still the incident's latest investigation request?

Every request for an investigation (incident created, or a retry from POST .../investigation/retry) is one row in
incident-service's transactional outbox, public.outbox_events (id = the event's eventId, aggregate_id = incident id),
written in the same transaction as the change that caused it. Events are keyed by incidentId, so an original event
that waited in a Kafka backlog is consumed BEFORE the retry that replaced it. At that moment the worker's own tables
cannot know about the retry (its event is still queued behind this one); the outbox already does. So the worker
reads the outbox: if a newer request of the same type exists for the incident, this one is superseded and is not
run (the retry's own event will run it, once).

Read-only, one indexed lookup (V5__index_outbox_aggregate), tenant-checked through public.incidents. It is a read
of another service's table, accepted here because both services already share this database and the outbox is the
only record of requests that the worker has not consumed yet.

FAILS TOWARD RUNNING: if the outbox cannot be read, or this event is not in it (CLI runs, tests), the event counts as
the latest. A superseded check that fails must never drop a legitimate investigation; the worst case is the
pre-existing behaviour (one extra run).
"""

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.events import IncidentCreatedEvent

log = logging.getLogger(__name__)

# Newest first; created_at is written by incident-service when the request is made (the retry holds a row lock on
# the incident, so two requests for one incident are never written concurrently).
_REQUESTS = text(
    """
    SELECT o.id
    FROM public.outbox_events o
    JOIN public.incidents i ON i.id = o.aggregate_id
    WHERE o.aggregate_id = :incident_id AND i.tenant_id = :tenant_id AND o.event_type = :event_type
    ORDER BY o.created_at DESC, o.id DESC
    """
)


async def is_superseded(engine: AsyncEngine, event: IncidentCreatedEvent) -> bool:
    """True only when this event is in the outbox AND a newer request for the same incident exists."""
    try:
        async with engine.connect() as conn:
            ids = (
                (
                    await conn.execute(
                        _REQUESTS,
                        {"incident_id": event.payload.incidentId, "tenant_id": event.tenantId, "event_type": event.eventType},
                    )
                )
                .scalars()
                .all()
            )
    except Exception as exc:  # noqa: BLE001 - any failure: run it (see module docstring)
        log.warning("could not read the latest investigation request, running this one: %r", exc)
        return False
    return event.eventId in ids and ids[0] != event.eventId
