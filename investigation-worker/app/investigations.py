"""Repository for worker.investigations: create, claim, save. SQLAlchemy Core, one short transaction each.

Lifecycle:  PENDING --claim--> RUNNING --save--> COMPLETED | FAILED
               |                 |  ^
               +--supersede--> SUPERSEDED  (a newer request exists for the incident: never run, no LLM call)
                                 |  ^
                                 |  +-- claim again (crash recovery: the run died before saving)
                                 +--release--> PENDING  (LLM config error: not this incident's fault)

run_count is a fencing token (optimistic locking, like JPA @Version): every claim increments it, and a
claim or a save only succeeds when run_count still has the value this run saw. Two concurrent claims
therefore cannot both win, and a stale run can never overwrite the result of a newer one.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db import investigations, processed_events
from app.events import IncidentCreatedEvent, IncidentCreatedPayload

CLAIMABLE = ("PENDING", "RUNNING")
TERMINAL = ("COMPLETED", "FAILED", "SUPERSEDED")
SUPERSEDED_REASON = "superseded by a newer investigation request for this incident"


@dataclass(frozen=True)
class InvestigationRef:
    id: UUID
    tenant_id: str
    status: str
    run_count: int


@dataclass(frozen=True)
class Usage:
    model: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    llm_latency_ms: int = 0


def _ref(row: Any) -> InvestigationRef:
    return InvestigationRef(id=row.id, tenant_id=row.tenant_id, status=row.status, run_count=row.run_count)


_REF_COLUMNS = (investigations.c.id, investigations.c.tenant_id, investigations.c.status, investigations.c.run_count)


async def ensure_investigation(engine: AsyncEngine, event: IncidentCreatedEvent) -> tuple[InvestigationRef, bool]:
    """(investigation, created). A redelivered event returns the existing investigation, whatever its status.

    Same transaction as before 2.6: the processed_events row and the PENDING investigation are written
    together or not at all.
    """
    now = datetime.now(UTC)
    async with engine.begin() as conn:
        inserted = await conn.execute(
            pg_insert(processed_events)
            .values(event_id=event.eventId, event_type=event.eventType, processed_at=now)
            .on_conflict_do_nothing(index_elements=[processed_events.c.event_id])
            .returning(processed_events.c.event_id)
        )
        if inserted.first() is not None:
            row = await conn.execute(
                investigations.insert()
                .values(
                    id=uuid4(),
                    incident_id=event.payload.incidentId,
                    tenant_id=event.tenantId,
                    status="PENDING",
                    request_id=event.requestId,
                    created_at=now,
                    incident=event.payload.model_dump(mode="json"),
                )
                .returning(*_REF_COLUMNS)
            )
            return _ref(row.one()), True

        row = await conn.execute(
            select(*_REF_COLUMNS)
            .where(investigations.c.tenant_id == event.tenantId, investigations.c.incident_id == event.payload.incidentId)
            .order_by(investigations.c.created_at.desc())
            .limit(1)
        )
        return _ref(row.one()), False


async def create_pending(engine: AsyncEngine, *, tenant_id: str, incident: IncidentCreatedPayload, request_id: str) -> InvestigationRef:
    """A new PENDING investigation without a Kafka event (CLI runs)."""
    async with engine.begin() as conn:
        row = await conn.execute(
            investigations.insert()
            .values(
                id=uuid4(),
                incident_id=incident.incidentId,
                tenant_id=tenant_id,
                status="PENDING",
                request_id=request_id,
                created_at=datetime.now(UTC),
                incident=incident.model_dump(mode="json"),
            )
            .returning(*_REF_COLUMNS)
        )
        return _ref(row.one())


async def claim(engine: AsyncEngine, ref: InvestigationRef, allowed: tuple[str, ...] = CLAIMABLE) -> InvestigationRef | None:
    """Conditional UPDATE: RUNNING for this run, or None when someone else changed the row first."""
    async with engine.begin() as conn:
        row = await conn.execute(
            update(investigations)
            .where(
                investigations.c.id == ref.id,
                investigations.c.status.in_(allowed),
                investigations.c.run_count == ref.run_count,  # fencing: only the run that saw this version wins
            )
            .values(
                status="RUNNING",
                run_count=investigations.c.run_count + 1,
                started_at=datetime.now(UTC),
                completed_at=None,
                failure_reason=None,
                attempts=0,
            )
            .returning(*_REF_COLUMNS)
        )
        found = row.first()
        return _ref(found) if found is not None else None


async def _finish(engine: AsyncEngine, ref: InvestigationRef, values: dict[str, Any]) -> bool:
    """UPDATE guarded by status RUNNING + run_count: False means a newer run owns the row (result discarded)."""
    async with engine.begin() as conn:
        result = await conn.execute(
            update(investigations)
            .where(
                investigations.c.id == ref.id,
                investigations.c.status == "RUNNING",
                investigations.c.run_count == ref.run_count,
            )
            .values(**values)
        )
        return result.rowcount == 1


def _usage_values(usage: Usage, attempts: int, prompt_version: str | None) -> dict[str, Any]:
    return {
        "model": usage.model,
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "llm_latency_ms": usage.llm_latency_ms,
        "attempts": attempts,
        "prompt_version": prompt_version,
        "completed_at": datetime.now(UTC),
    }


async def save_completed(
    engine: AsyncEngine,
    ref: InvestigationRef,
    *,
    result: dict[str, Any],
    evidence: list[dict[str, Any]],
    usage: Usage,
    attempts: int,
    prompt_version: str | None,
) -> bool:
    values = {"status": "COMPLETED", "result": result, "evidence": evidence, "failure_reason": None}
    return await _finish(engine, ref, values | _usage_values(usage, attempts, prompt_version))


async def save_failed(
    engine: AsyncEngine,
    ref: InvestigationRef,
    *,
    reason: str,
    evidence: list[dict[str, Any]],
    usage: Usage,
    attempts: int,
    prompt_version: str | None,
) -> bool:
    # The evidence is stored even on failure: the engineer still gets the retrieved logs and runbooks.
    values = {"status": "FAILED", "result": None, "evidence": evidence, "failure_reason": reason[:2000]}
    return await _finish(engine, ref, values | _usage_values(usage, attempts, prompt_version))


async def mark_superseded(engine: AsyncEngine, ref: InvestigationRef) -> bool:
    """PENDING/RUNNING -> SUPERSEDED, fenced like a claim (False: another run took the row meanwhile)."""
    async with engine.begin() as conn:
        result = await conn.execute(
            update(investigations)
            .where(
                investigations.c.id == ref.id,
                investigations.c.status.in_(CLAIMABLE),
                investigations.c.run_count == ref.run_count,
            )
            .values(status="SUPERSEDED", failure_reason=SUPERSEDED_REASON, completed_at=datetime.now(UTC))
        )
        return result.rowcount == 1


async def release(engine: AsyncEngine, ref: InvestigationRef) -> bool:
    """Back to PENDING (e.g. bad API key): re-runnable later with app.rerun, and never marked FAILED."""
    async with engine.begin() as conn:
        result = await conn.execute(
            update(investigations)
            .where(investigations.c.id == ref.id, investigations.c.run_count == ref.run_count)
            .values(status="PENDING", started_at=None)
        )
        return result.rowcount == 1


async def find_stale_running(engine: AsyncEngine, *, started_before: datetime, limit: int = 100) -> list[InvestigationRef]:
    """RUNNING rows whose run started before the cutoff, oldest first (milestone 4: the stale-run reaper).

    Across all tenants on purpose: this is a system maintenance query (it reads ids only, no tenant data), and
    every row it touches is then updated by id + run_count.
    """
    query = (
        select(*_REF_COLUMNS)
        .where(investigations.c.status == "RUNNING", investigations.c.started_at < started_before)
        .order_by(investigations.c.started_at, investigations.c.id)
        .limit(limit)
    )
    async with engine.connect() as conn:
        return [_ref(row) for row in (await conn.execute(query)).all()]


async def mark_stale_failed(engine: AsyncEngine, ref: InvestigationRef, reason: str) -> bool:
    """FAILED for a run that stopped making progress. Fenced like every save: if the row was claimed again in the
    meantime (run_count changed) or finished, nothing is updated and False is returned."""
    return await _finish(engine, ref, {"status": "FAILED", "failure_reason": reason, "completed_at": datetime.now(UTC)})


async def find_by_status(
    engine: AsyncEngine, status: str, *, tenant_id: str | None = None, limit: int = 10
) -> list[tuple[InvestigationRef, dict[str, Any] | None]]:
    """Oldest first, with the stored incident JSON (None for rows created before migration 0004)."""
    query = (
        select(*_REF_COLUMNS, investigations.c.incident)
        .where(investigations.c.status == status)
        .order_by(investigations.c.created_at, investigations.c.id)
        .limit(limit)
    )
    if tenant_id is not None:
        query = query.where(investigations.c.tenant_id == tenant_id)
    async with engine.connect() as conn:
        rows = (await conn.execute(query)).all()
    return [(_ref(row), row.incident) for row in rows]


async def get(engine: AsyncEngine, investigation_id: UUID) -> dict[str, Any]:
    async with engine.connect() as conn:
        row = (await conn.execute(select(investigations).where(investigations.c.id == investigation_id))).one()
    return dict(row._mapping)


@dataclass(frozen=True)
class PostgresInvestigationStore:
    """The graph's view of the repository (graph tests swap in an in-memory store)."""

    engine: AsyncEngine

    async def save_completed(self, ref: InvestigationRef, **values: Any) -> bool:
        return await save_completed(self.engine, ref, **values)

    async def save_failed(self, ref: InvestigationRef, **values: Any) -> bool:
        return await save_failed(self.engine, ref, **values)
