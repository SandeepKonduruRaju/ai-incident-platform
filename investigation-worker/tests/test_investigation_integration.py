"""Section 2.6 against real PostgreSQL (+ Kafka for the consumer tests); skipped without Docker.

Covers migration 0004, status-aware idempotency (process_event + the fenced claim) and the consumer
end to end with FakeLLM: event -> COMPLETED row; LLM config error -> row stays PENDING and /health 503.
"""

import asyncio
import json
import uuid
from functools import partial

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import exc as sa_exc
from sqlalchemy import select, text

from app.db import investigations
from app.embedding import FakeEmbedder
from app.errors import LLMConfigError
from app.events import IncidentCreatedEvent
from app.graph import GraphDeps
from app.ingest import DEFAULT_DATA_DIR, ingest
from app.investigations import (
    InvestigationRef,
    PostgresInvestigationStore,
    Usage,
    claim,
    ensure_investigation,
    get,
    save_completed,
)
from app.investigator import build_retriever, make_investigate
from app.llm import FakeLLM
from app.main import app
from app.processing import process_event
from app.rerank import FakeReranker
from tests.conftest import PROJECT_ROOT
from tests.test_consumer_integration import (
    as_record,
    committed_total,
    produce,
    running,
    wait_until,
    worker_settings,
)

pytestmark = pytest.mark.integration


def _event(tenant: str = "acme", scenario: str = "db_pool_exhausted") -> IncidentCreatedEvent:
    """An IncidentCreated event carrying one of the evaluation incidents (so retrieval finds evidence)."""
    cases = json.loads((DEFAULT_DATA_DIR / "eval_incidents.json").read_text(encoding="utf-8"))
    case = next(c for c in cases if c["tenantId"] == tenant and c["scenario"] == scenario)
    return IncidentCreatedEvent.model_validate(
        {
            "eventId": str(uuid.uuid4()),
            "eventType": "IncidentCreated",
            "schemaVersion": 1,
            "occurredAt": case["incident"]["createdAt"],
            "tenantId": tenant,
            "requestId": f"req-{uuid.uuid4().hex[:6]}",
            "payload": case["incident"] | {"incidentId": str(uuid.uuid4())},
        }
    )


async def _status(engine, investigation_id) -> str:
    return (await get(engine, investigation_id))["status"]


def _recording_investigate(engine, outcome: str = "COMPLETED", calls: list | None = None):
    """A stand-in for the graph: records the call and saves a minimal result through the fenced save."""

    async def investigate(ref: InvestigationRef, incident) -> str:
        if calls is not None:
            calls.append(ref)
        await save_completed(
            engine, ref, result={"summary": "stub"}, evidence=[], usage=Usage(), attempts=1, prompt_version="v1"
        )
        return outcome

    return investigate


# ---------------------------------------------------------------- migration 0004


def _alembic_config(database_url: str) -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    config.attributes["database_url"] = database_url
    config.attributes["configure_logging"] = False
    return config


async def test_migration_0004_down_and_up_again_keeps_pending_rows_valid(database_url, engine):
    pending = (await ensure_investigation(engine, _event()))[0]
    config = _alembic_config(database_url)

    await asyncio.to_thread(command.downgrade, config, "0003")
    async with engine.connect() as conn:
        columns = (
            await conn.execute(
                text("SELECT column_name FROM information_schema.columns WHERE table_schema='worker' AND table_name='investigations'")
            )
        ).scalars().all()
    assert "result" not in columns and "run_count" not in columns

    await asyncio.to_thread(command.upgrade, config, "head")
    await engine.dispose()  # drop pooled connections that cached the old table shape
    assert await _status(engine, pending.id) == "PENDING"  # the old row is still valid under the CHECK

    with pytest.raises(sa_exc.IntegrityError, match="ck_investigations_status"):
        async with engine.begin() as conn:
            await conn.execute(investigations.update().where(investigations.c.id == pending.id).values(status="DONE"))


# ---------------------------------------------------------------- status-aware idempotency


async def test_new_event_creates_claims_and_runs(engine):
    calls: list[InvestigationRef] = []
    event = _event()
    outcome = await process_event(engine, _recording_investigate(engine, calls=calls), event)

    assert outcome == "COMPLETED"
    [ref] = calls
    row = await get(engine, ref.id)
    assert (row["status"], row["run_count"]) == ("COMPLETED", 1)
    assert row["incident"]["title"] == event.payload.title  # stored for app.rerun
    assert row["started_at"] is not None and row["completed_at"] is not None


async def test_redelivered_event_of_a_completed_investigation_is_skipped(engine):
    event, calls = _event(), []
    await process_event(engine, _recording_investigate(engine, calls=calls), event)

    outcome = await process_event(engine, _recording_investigate(engine, calls=calls), event)

    assert outcome == "SKIPPED"
    assert len(calls) == 1


async def test_running_investigation_left_by_a_crash_is_run_again(engine):
    event = _event()
    ref, _ = await ensure_investigation(engine, event)
    crashed = await claim(engine, ref)  # RUNNING, then the worker "dies" before saving
    assert crashed is not None and await _status(engine, ref.id) == "RUNNING"

    calls: list[InvestigationRef] = []
    outcome = await process_event(engine, _recording_investigate(engine, calls=calls), event)

    assert outcome == "COMPLETED"
    assert calls[0].run_count == 2  # a new claim took over from the crashed run
    # The crashed run can no longer save over the new result (fencing token).
    assert not await save_completed(engine, crashed, result={}, evidence=[], usage=Usage(), attempts=1, prompt_version="v1")


async def test_only_one_of_two_concurrent_claims_wins(engine):
    ref, _ = await ensure_investigation(engine, _event())

    first, second = await asyncio.gather(claim(engine, ref), claim(engine, ref))

    winners = [result for result in (first, second) if result is not None]
    assert len(winners) == 1
    assert winners[0].run_count == 1
    assert (await get(engine, ref.id))["run_count"] == 1


async def test_failed_investigation_is_not_rerun_by_redelivery(engine):
    event = _event()
    await process_event(engine, _recording_investigate(engine), event)
    async with engine.begin() as conn:
        await conn.execute(text("UPDATE worker.investigations SET status = 'FAILED'"))

    calls: list = []
    assert await process_event(engine, _recording_investigate(engine, calls=calls), event) == "SKIPPED"
    assert calls == []


async def test_llm_config_error_releases_the_claim_back_to_pending(engine):
    async def broken(ref, incident):
        raise LLMConfigError("bad key")

    event = _event()
    with pytest.raises(LLMConfigError):
        await process_event(engine, broken, event)

    async with engine.connect() as conn:
        row = (await conn.execute(select(investigations))).one()
    assert (row.status, row.result, row.failure_reason) == ("PENDING", None, None)


# ---------------------------------------------------------------- consumer end to end (FakeLLM)


@pytest.fixture
async def acme_chunks(engine):
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE worker.chunks"))
    await ingest(engine, FakeEmbedder(), tenant="acme")
    return engine


def _processor(engine, settings, llm: FakeLLM):
    retriever = build_retriever(engine, FakeEmbedder(), FakeReranker(), settings)
    deps = GraphDeps(retrieve=retriever, llm=llm, store=PostgresInvestigationStore(engine))
    return partial(process_event, engine, make_investigate(deps, settings))


async def test_consumer_event_to_completed_investigation(kafka_bootstrap, topics, database_url, acme_chunks):
    engine = acme_chunks
    settings = worker_settings(kafka_bootstrap, topics, database_url)
    event = _event()
    await produce(kafka_bootstrap, settings.kafka_topic, [as_record(event.model_dump(mode="json"))])

    llm = FakeLLM()
    async with running(settings, _processor(engine, settings, llm)):
        await wait_until(lambda: _committed(settings, 1))

    async with engine.connect() as conn:
        row = (await conn.execute(select(investigations))).one()
    assert row.status == "COMPLETED"
    assert row.result["root_cause"]["citations"] == ["C1"]
    assert row.evidence and {item["label"] for item in row.evidence} >= {"C1"}
    assert all(item["source_id"].startswith(("LOG-acme", "MET-acme", "RB-acme", "INC-acme")) for item in row.evidence)
    assert (row.model, row.prompt_version, row.attempts) == ("fake-llm", "v1", 1)
    assert len(llm.calls) == 1


async def test_consumer_llm_config_error_leaves_pending_and_health_503(kafka_bootstrap, topics, database_url, acme_chunks):
    engine = acme_chunks
    settings = worker_settings(kafka_bootstrap, topics, database_url)
    await produce(kafka_bootstrap, settings.kafka_topic, [as_record(_event().model_dump(mode="json"))])

    async with running(settings, _processor(engine, settings, FakeLLM([LLMConfigError("bad key")]))) as consumer:
        await wait_until(lambda: _committed(settings, 1))  # committed: the EVENT is fine, no DLQ
        app.state.consumer, app.state.consumer_enabled = consumer, True
        try:
            response = TestClient(app).get("/health")
        finally:
            del app.state.consumer, app.state.consumer_enabled

    async with engine.connect() as conn:
        row = (await conn.execute(select(investigations))).one()
    assert (row.status, row.failure_reason) == ("PENDING", None)
    assert response.status_code == 503
    assert response.json()["reason"] == "bad key"


async def _committed(settings, expected: int) -> bool:
    return await committed_total(settings.kafka_bootstrap_servers, settings.kafka_group_id, settings.kafka_topic) >= expected
