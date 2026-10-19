"""End-to-end consumer tests against real Kafka and PostgreSQL containers (skipped without Docker)."""

import asyncio
import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from functools import partial

import pytest
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from aiokafka.admin import AIOKafkaAdminClient
from aiokafka.errors import KafkaError
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy import exc as sa_exc

from app.config import Settings, get_settings
from app.consumer import IncidentEventConsumer
from app.db import investigations, processed_events
from app.events import IncidentCreatedEvent
from app.logging_context import install_context_fields
from app.processing import create_investigation

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------- helpers


@pytest.fixture(autouse=True)
def context_fields(caplog):
    install_context_fields()
    caplog.set_level(logging.INFO)


def make_event(incident_id: uuid.UUID, request_id: str = "req-1", tenant_id: str = "acme") -> dict:
    return {
        "eventId": str(uuid.uuid4()),
        "eventType": "IncidentCreated",
        "schemaVersion": 1,
        "occurredAt": "2026-10-16T16:51:50.641109500Z",
        "tenantId": tenant_id,
        "requestId": request_id,
        "payload": {
            "incidentId": str(incident_id),
            "title": "Checkout API 500 errors",
            "description": None,
            "severity": "HIGH",
            "status": "OPEN",
            "affectedService": "payment-service",
            "createdAt": "2026-10-16T16:51:50.524628Z",
        },
    }


def as_record(event: dict) -> tuple[bytes, bytes, list[tuple[str, bytes]]]:
    """Key, value and headers exactly as incident-service's OutboxRelay sends them."""
    headers = [
        ("eventId", event["eventId"].encode()),
        ("eventType", event["eventType"].encode()),
        ("tenantId", event["tenantId"].encode()),
        ("requestId", event["requestId"].encode()),
    ]
    return event["payload"]["incidentId"].encode(), json.dumps(event).encode(), headers


async def produce(bootstrap: str, topic: str, records: list[tuple[bytes, bytes, list]]) -> None:
    producer = AIOKafkaProducer(bootstrap_servers=bootstrap)
    await producer.start()
    try:
        for key, value, headers in records:
            await producer.send_and_wait(topic, value=value, key=key, headers=headers)
    finally:
        await producer.stop()


async def committed_total(bootstrap: str, group: str, topic: str) -> int:
    """Sum of the group's committed offsets for the topic = number of messages it has finished."""
    admin = AIOKafkaAdminClient(bootstrap_servers=bootstrap)
    await admin.start()
    try:
        offsets = await admin.list_consumer_group_offsets(group)
    except KafkaError:
        return 0  # the group does not exist yet (no member has joined)
    finally:
        await admin.close()
    return sum(meta.offset for tp, meta in offsets.items() if tp.topic == topic and meta.offset > 0)


async def wait_until(condition: Callable[[], Awaitable[bool]], timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while not await condition():
        if time.monotonic() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.2)


async def count_rows(engine, table) -> int:
    async with engine.connect() as conn:
        return (await conn.execute(select(func.count()).select_from(table))).scalar_one()


async def read_one(bootstrap: str, topic: str):
    consumer = AIOKafkaConsumer(topic, bootstrap_servers=bootstrap, auto_offset_reset="earliest")
    await consumer.start()
    try:
        return await asyncio.wait_for(consumer.getone(), timeout=15)
    finally:
        await consumer.stop()


def worker_settings(kafka_bootstrap, topics, database_url, group: str | None = None, **overrides) -> Settings:
    topic, dlq = topics
    values = {
        "kafka_bootstrap_servers": kafka_bootstrap,
        "kafka_topic": topic,
        "kafka_dlq_topic": dlq,
        "kafka_group_id": group or f"test-{uuid.uuid4().hex[:8]}",
        "database_url": database_url,
        "retry_base_delay_seconds": 0.01,  # keep retries fast in tests
        "retry_max_delay_seconds": 0.05,
    }
    return Settings(_env_file=None, **(values | overrides))


@asynccontextmanager
async def running(settings: Settings, processor):
    consumer = IncidentEventConsumer(settings, processor)
    await consumer.start()
    try:
        yield consumer
    finally:
        await consumer.stop()


def messages(caplog) -> list[str]:
    return [record.getMessage() for record in caplog.records]


# ---------------------------------------------------------------- tests


async def test_a_happy_path_creates_one_investigation_and_commits(kafka_bootstrap, topics, database_url, engine, caplog):
    settings = worker_settings(kafka_bootstrap, topics, database_url)
    incident_id = uuid.uuid4()
    await produce(kafka_bootstrap, settings.kafka_topic, [as_record(make_event(incident_id, request_id="req-a"))])

    async with running(settings, partial(create_investigation, engine)):
        await wait_until(lambda: _committed(settings, 1))

    async with engine.connect() as conn:
        row = (await conn.execute(select(investigations))).one()
    assert (row.incident_id, row.tenant_id, row.status, row.request_id) == (incident_id, "acme", "PENDING", "req-a")
    # Every log line about this message carries its context (Phase B)
    created = next(r for r in caplog.records if r.getMessage().startswith("investigation "))
    assert (created.request_id, created.tenant_id) == ("req-a", "acme")


async def test_b_same_event_twice_creates_one_investigation(kafka_bootstrap, topics, database_url, engine, caplog):
    settings = worker_settings(kafka_bootstrap, topics, database_url)
    record = as_record(make_event(uuid.uuid4()))
    await produce(kafka_bootstrap, settings.kafka_topic, [record, record])  # redelivery of the same event

    async with running(settings, partial(create_investigation, engine)):
        await wait_until(lambda: _committed(settings, 2))

    assert await count_rows(engine, investigations) == 1
    assert await count_rows(engine, processed_events) == 1
    assert "duplicate, skipping" in messages(caplog)


async def test_c_malformed_json_goes_to_dlq_with_headers(kafka_bootstrap, topics, database_url, engine):
    settings = worker_settings(kafka_bootstrap, topics, database_url)
    await produce(kafka_bootstrap, settings.kafka_topic, [(b"incident-1", b"{not json", [("requestId", b"req-c")])])

    async with running(settings, partial(create_investigation, engine)):
        await wait_until(lambda: _committed(settings, 1))  # the partition moved on

    dead = await read_one(kafka_bootstrap, settings.kafka_dlq_topic)
    headers = {key: value.decode() for key, value in dead.headers}
    assert dead.value == b"{not json"  # original bytes, untouched
    assert dead.key == b"incident-1"
    assert headers["dlq-original-topic"] == settings.kafka_topic
    assert headers["dlq-original-offset"] == "0"
    assert headers["dlq-original-partition"].isdigit()
    assert headers["dlq-error-category"] == "PERMANENT"
    assert headers["dlq-error-type"] == "JSONDecodeError"
    assert headers["dlq-error-message"]
    assert headers["dlq-attempts"] == "1"  # permanent: no retries
    assert headers["dlq-failed-at"]
    assert headers["requestId"] == "req-c"  # original headers are kept
    assert await count_rows(engine, investigations) == 0


async def test_d_transient_db_failure_succeeds_on_third_attempt(kafka_bootstrap, topics, database_url, engine, caplog):
    settings = worker_settings(kafka_bootstrap, topics, database_url)
    calls = 0

    async def flaky(event: IncidentCreatedEvent):
        nonlocal calls
        calls += 1
        if calls <= 2:  # injected fault: the database is unreachable for the first two attempts
            raise sa_exc.OperationalError("INSERT", {}, ConnectionRefusedError("db down"))
        return await create_investigation(engine, event)

    await produce(kafka_bootstrap, settings.kafka_topic, [as_record(make_event(uuid.uuid4()))])

    async with running(settings, flaky):
        await wait_until(lambda: _committed(settings, 1))

    assert calls == 3
    assert await count_rows(engine, investigations) == 1
    assert sum("transient failure on attempt" in m for m in messages(caplog)) == 2


async def test_transient_failure_that_never_recovers_goes_to_dlq(kafka_bootstrap, topics, database_url, engine):
    settings = worker_settings(kafka_bootstrap, topics, database_url, retry_max_attempts=3)

    async def always_down(event):
        raise sa_exc.OperationalError("INSERT", {}, ConnectionRefusedError("db down"))

    await produce(kafka_bootstrap, settings.kafka_topic, [as_record(make_event(uuid.uuid4()))])

    async with running(settings, always_down):
        await wait_until(lambda: _committed(settings, 1))

    headers = {k: v.decode() for k, v in (await read_one(kafka_bootstrap, settings.kafka_dlq_topic)).headers}
    assert headers["dlq-error-category"] == "TRANSIENT"
    assert headers["dlq-error-type"] == "OperationalError"
    assert headers["dlq-attempts"] == "3"


async def test_e_crash_before_commit_reprocesses_but_stays_idempotent(kafka_bootstrap, topics, database_url, engine, caplog):
    group = f"restart-{uuid.uuid4().hex[:8]}"
    settings = worker_settings(kafka_bootstrap, topics, database_url, group=group)
    incident_id = uuid.uuid4()
    first, second = make_event(incident_id), make_event(incident_id)  # same key: same partition, in order
    await produce(kafka_bootstrap, settings.kafka_topic, [as_record(first), as_record(second)])

    reached = asyncio.Event()

    async def crash_after_db_commit(event: IncidentCreatedEvent):
        await create_investigation(engine, event)  # DB transaction committed...
        if str(event.eventId) == second["eventId"]:
            reached.set()
            await asyncio.Event().wait()  # ...then "crash" before the Kafka offset commit

    # Run 1: first message fully done, second written to the DB but its offset never committed
    async with running(settings, crash_after_db_commit):
        await asyncio.wait_for(reached.wait(), timeout=30)
    assert await committed_total(kafka_bootstrap, group, settings.kafka_topic) == 1
    assert await count_rows(engine, investigations) == 2

    # Run 2 (restart, same group): the second message is delivered again, the DB says "already done"
    async with running(settings, partial(create_investigation, engine)):
        await wait_until(lambda: _committed(settings, 2))

    assert await count_rows(engine, investigations) == 2  # still one per event
    assert "duplicate, skipping" in messages(caplog)


async def test_f_events_with_the_same_key_are_processed_in_order(kafka_bootstrap, topics, database_url, engine):
    settings = worker_settings(kafka_bootstrap, topics, database_url)
    incident_id = uuid.uuid4()
    events = [make_event(incident_id, request_id=f"req-{i}") for i in range(3)]
    processed: list[str] = []

    async def recording(event: IncidentCreatedEvent):
        processed.append(str(event.eventId))
        await asyncio.sleep(0.05)  # slow processing must not let the next message overtake
        return await create_investigation(engine, event)

    await produce(kafka_bootstrap, settings.kafka_topic, [as_record(e) for e in events])

    async with running(settings, recording):
        await wait_until(lambda: _committed(settings, 3))

    assert processed == [e["eventId"] for e in events]


async def test_lifespan_starts_and_stops_the_consumer(kafka_bootstrap, topics, database_url, monkeypatch):
    """Phase A: the real FastAPI app starts the consumer on startup and stops it on shutdown.

    (TestClient runs the app on its own thread and event loop, so blocking calls here are fine.)
    """
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", kafka_bootstrap)
    monkeypatch.setenv("KAFKA_TOPIC", topics[0])  # must exist: auto-create is off
    monkeypatch.setenv("KAFKA_GROUP_ID", f"lifespan-{uuid.uuid4().hex[:8]}")
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    from app.main import app

    try:
        with TestClient(app) as client:  # "with" runs the lifespan (startup ... shutdown)
            deadline = time.monotonic() + 30
            while client.get("/health").json()["consumer"] != "running":
                assert time.monotonic() < deadline, "consumer did not reach 'running'"
                time.sleep(0.2)
            assert client.get("/health").status_code == 200
            consumer = app.state.consumer
        assert consumer.state == "stopped"
        assert not consumer.is_alive
    finally:
        get_settings.cache_clear()
        for name in ("consumer", "consumer_enabled"):
            if hasattr(app.state, name):
                delattr(app.state, name)


async def _committed(settings: Settings, expected: int) -> bool:
    return await committed_total(settings.kafka_bootstrap_servers, settings.kafka_group_id, settings.kafka_topic) >= expected
