"""Event processing: open (or find) the investigation for an IncidentCreated event, claim it, run it.

Status-aware idempotency (section 2.6). Before, a redelivered event was always skipped, even when the
worker had crashed in the middle of the investigation, which left it PENDING forever. Now:

    no investigation yet   -> create PENDING (with processed_events, one transaction), then claim and run
    PENDING or RUNNING     -> claim and (re)run   (RUNNING here means: a previous run died before saving)
    COMPLETED, FAILED or SUPERSEDED -> skip (the event was fully handled)

Before claiming, a request that a newer one replaced (a retry made while this event waited in a Kafka backlog) is
marked SUPERSEDED and not run: no LLM call, and the offset is committed as usual (see app/request_check.py).

The claim is a conditional UPDATE fenced by run_count, so two concurrent deliveries cannot both run it.
"""

import logging
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncEngine

from app.errors import LLMConfigError
from app.events import IncidentCreatedEvent, IncidentCreatedPayload
from app.investigations import TERMINAL, InvestigationRef, claim, ensure_investigation, mark_superseded, release
from app.logging_context import investigation_id_var, value_context
from app.request_check import is_superseded

log = logging.getLogger(__name__)

# Runs the investigation graph for a claimed investigation and returns its outcome (COMPLETED / FAILED).
Investigate = Callable[[InvestigationRef, IncidentCreatedPayload], Awaitable[str]]


async def create_investigation(engine: AsyncEngine, event: IncidentCreatedEvent) -> bool:
    """Idempotent create only: True if this event created the PENDING investigation, False if it existed."""
    ref, created = await ensure_investigation(engine, event)
    if created:
        log.info("investigation %s created for incident %s", ref.id, event.payload.incidentId)
    else:
        log.info("duplicate, skipping")
    return created


async def process_event(engine: AsyncEngine, investigate: Investigate, event: IncidentCreatedEvent) -> str:
    """Returns what happened: COMPLETED, FAILED, SUPERSEDED or SKIPPED. Raises LLMConfigError after releasing the claim."""
    ref, created = await ensure_investigation(engine, event)
    with value_context(investigation_id_var, str(ref.id)):
        if created:
            log.info("investigation %s created for incident %s", ref.id, event.payload.incidentId)
        if ref.status in TERMINAL:
            log.info("investigation already %s, skipping redelivered event", ref.status)
            return "SKIPPED"
        if await is_superseded(engine, event):
            if await mark_superseded(engine, ref):
                log.info("a newer investigation request exists for incident %s: superseded, not run", event.payload.incidentId)
                return "SUPERSEDED"
            log.info("investigation was claimed by another run, skipping")
            return "SKIPPED"
        if not created:
            log.info("investigation is %s after a redelivery: claiming it again", ref.status)

        claimed = await claim(engine, ref)
        if claimed is None:
            log.info("investigation was claimed by another run, skipping")
            return "SKIPPED"

        try:
            return await investigate(claimed, event.payload)
        except LLMConfigError:
            await release(engine, claimed)  # back to PENDING: re-runnable once the key/model is fixed
            raise
