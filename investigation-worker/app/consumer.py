"""Reliable Kafka consumer for incident events.

Guarantees, per message:
  1. processed one at a time (so per-partition order = per-incident order, because key = incidentId)
  2. offset committed only AFTER processing succeeded, or after the message was safely dead-lettered
  3. transient failures retried with backoff; permanent ones dead-lettered immediately

Delivery is at-least-once (a crash before the commit means redelivery), and processing is
idempotent (status-aware, see app/processing.py), so the end result is "effectively once".

Investigation outcomes are NOT failures here: an invalid LLM answer or an LLM outage ends as a FAILED
investigation row and a normal commit. Only a bad event (or a database that stays down) goes to the DLQ.
"""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer, ConsumerRecord, TopicPartition
from aiokafka.abc import ConsumerRebalanceListener
from aiokafka.errors import KafkaError

from app.config import Settings
from app.errors import ErrorCategory, LLMConfigError, UnsupportedEventError, classify
from app.events import IncidentCreatedEvent
from app.logging_context import log_context
from app.retry import backoff_delay

log = logging.getLogger(__name__)

SUPPORTED_EVENT_TYPE = "IncidentCreated"
SUPPORTED_SCHEMA_VERSIONS = {1}
MAX_ERROR_MESSAGE_LENGTH = 1000

Processor = Callable[[IncidentCreatedEvent], Awaitable[object]]


@dataclass(frozen=True)
class Failure:
    category: ErrorCategory
    error: Exception
    attempts: int


def parse_event(value: bytes | None) -> IncidentCreatedEvent:
    """Bytes -> validated event. Every error raised here is PERMANENT: the bytes will never change."""
    if value is None:
        raise UnsupportedEventError("message has no value")
    data = json.loads(value)  # JSONDecodeError / UnicodeDecodeError
    if not isinstance(data, dict):
        raise UnsupportedEventError("event JSON is not an object")
    # Check type and version BEFORE full validation, so the error says what is really wrong.
    if data.get("eventType") != SUPPORTED_EVENT_TYPE:
        raise UnsupportedEventError(f"unsupported eventType {data.get('eventType')!r}")
    if data.get("schemaVersion") not in SUPPORTED_SCHEMA_VERSIONS:
        raise UnsupportedEventError(f"unsupported schemaVersion {data.get('schemaVersion')!r}")
    return IncidentCreatedEvent.model_validate(data)  # ValidationError


def decode_headers(headers) -> dict[str, str]:
    return {key: value.decode("utf-8", "replace") for key, value in headers or () if value is not None}


class _WaitForInFlightMessage(ConsumerRebalanceListener):
    """Called by aiokafka when partitions move to another consumer (a rebalance).

    aiokafka rebalances in a background task, so without this a partition could be taken away
    while we are still processing one of its messages: our commit would then fail and the new
    owner would process the message again. Taking the same lock as the processing loop makes the
    rebalance wait until the in-flight message is processed AND committed.
    """

    def __init__(self, lock: asyncio.Lock):
        self._lock = lock

    async def on_partitions_revoked(self, revoked):
        async with self._lock:
            log.info("partitions revoked: %s", sorted(str(tp) for tp in revoked))

    async def on_partitions_assigned(self, assigned):
        log.info("partitions assigned: %s", sorted(str(tp) for tp in assigned))


class IncidentEventConsumer:
    """Runs the consume loop as a background asyncio task (started/stopped by FastAPI's lifespan)."""

    def __init__(self, settings: Settings, processor: Processor):
        self._settings = settings
        self._processor = processor
        self._lock = asyncio.Lock()
        self._task: asyncio.Task | None = None
        self.state = "not started"
        # Set when processing hit a system-wide problem (LLM auth/config): the loop keeps running, but
        # /health reports 503 with this reason until the worker is fixed and restarted.
        self.unhealthy_reason: str | None = None

    @property
    def is_alive(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="kafka-consumer")

    async def stop(self) -> None:
        # Cancelling raises CancelledError at the current await. If that is in the middle of a
        # message, the offset is NOT committed, so the message is redelivered after a restart.
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        except Exception:
            pass  # already logged in _run

    # ---------------------------------------------------------------- loop

    async def _run(self) -> None:
        self.state = "starting"
        consumer = producer = None
        try:
            consumer, producer = await self._connect()
            self.state = "running"
            log.info("consuming %s as group %s", self._settings.kafka_topic, self._settings.kafka_group_id)
            while True:
                record = await consumer.getone()
                async with self._lock:
                    await self._handle(consumer, producer, record)
        except asyncio.CancelledError:
            raise
        except Exception:
            self.state = "failed"
            log.exception("consumer loop crashed")
            raise
        finally:
            await self._close(consumer, producer)
            if self.state != "failed":
                self.state = "stopped"

    async def _connect(self) -> tuple[AIOKafkaConsumer, AIOKafkaProducer]:
        """Start the clients, retrying while Kafka is not reachable yet (e.g. still booting)."""
        attempt = 0
        while True:
            attempt += 1
            consumer = AIOKafkaConsumer(
                bootstrap_servers=self._settings.kafka_bootstrap_servers,
                group_id=self._settings.kafka_group_id,
                enable_auto_commit=False,  # we commit ourselves, only after success
                auto_offset_reset="earliest",  # a NEW group starts at the oldest message, not the newest
                max_poll_interval_ms=self._settings.kafka_max_poll_interval_ms,
            )
            consumer.subscribe([self._settings.kafka_topic], listener=_WaitForInFlightMessage(self._lock))
            # Used only for the DLQ. acks=all + idempotence: a DLQ write is never lost or duplicated by retries.
            producer = AIOKafkaProducer(
                bootstrap_servers=self._settings.kafka_bootstrap_servers,
                acks="all",
                enable_idempotence=True,
            )
            try:
                await producer.start()
                await consumer.start()
                return consumer, producer
            except KafkaError as exc:
                await self._close(consumer, producer)
                delay = backoff_delay(attempt, 1.0, 30.0)
                log.warning("cannot connect to Kafka (%s); retrying in %.1fs", exc, delay)
                await asyncio.sleep(delay)

    @staticmethod
    async def _close(consumer: AIOKafkaConsumer | None, producer: AIOKafkaProducer | None) -> None:
        for client in (consumer, producer):
            if client is not None:
                try:
                    await client.stop()
                except Exception:
                    log.warning("error while stopping %s", type(client).__name__, exc_info=True)

    # ---------------------------------------------------------------- one message

    async def _handle(self, consumer: AIOKafkaConsumer, producer: AIOKafkaProducer, record: ConsumerRecord) -> None:
        headers = decode_headers(record.headers)
        # Context from the headers first: available even when the body is not valid JSON.
        with log_context(
            request_id=headers.get("requestId"),
            tenant_id=headers.get("tenantId"),
            event_id=headers.get("eventId"),
        ):
            log.info("received %s-%d@%d key=%s", record.topic, record.partition, record.offset, _text(record.key))
            event: IncidentCreatedEvent | None = None
            failure: Failure | None = None
            try:
                event = parse_event(record.value)
            except Exception as exc:
                failure = Failure(ErrorCategory.PERMANENT, exc, attempts=1)

            # Fall back to the JSON envelope for anything the headers did not carry.
            with log_context(
                request_id=headers.get("requestId") or (event.requestId if event else None),
                tenant_id=headers.get("tenantId") or (event.tenantId if event else None),
                event_id=headers.get("eventId") or (str(event.eventId) if event else None),
            ):
                if event is not None:
                    failure = await self._process_with_retries(event)
                if failure is not None:
                    await self._dead_letter(producer, record, failure)
                await self._commit(consumer, record)

    async def _process_with_retries(self, event: IncidentCreatedEvent) -> Failure | None:
        max_attempts = self._settings.retry_max_attempts
        for attempt in range(1, max_attempts + 1):
            try:
                await self._processor(event)
                return None
            except LLMConfigError as exc:
                # The worker is misconfigured (bad key / model id), not this event: no DLQ, no FAILED
                # investigation (it was put back to PENDING), offset committed. /health turns 503 so
                # the operator notices; fix the key, restart, then re-run with: python -m app.rerun --status PENDING
                log.error("LLM auth/config error — check ANTHROPIC_API_KEY: %s", exc)
                self.unhealthy_reason = str(exc)
                return None
            except Exception as exc:  # CancelledError is not an Exception, so shutdown still works
                category = classify(exc)
                if category is ErrorCategory.PERMANENT or attempt == max_attempts:
                    log.error("processing failed (%s) after %d attempt(s): %r", category, attempt, exc)
                    return Failure(category, exc, attempt)
                delay = backoff_delay(
                    attempt, self._settings.retry_base_delay_seconds, self._settings.retry_max_delay_seconds
                )
                log.warning("transient failure on attempt %d/%d: %r; retrying in %.2fs", attempt, max_attempts, exc, delay)
                await asyncio.sleep(delay)
        raise AssertionError("unreachable")

    async def _dead_letter(self, producer: AIOKafkaProducer, record: ConsumerRecord, failure: Failure) -> None:
        """Send the ORIGINAL bytes and key to the DLQ. Retries until it works: if the DLQ is down we
        must not commit (the message would be lost), so this partition waits instead."""
        headers = [(key, value) for key, value in record.headers or () if not key.startswith("dlq-")]
        headers += [
            ("dlq-original-topic", record.topic.encode()),
            ("dlq-original-partition", str(record.partition).encode()),
            ("dlq-original-offset", str(record.offset).encode()),
            ("dlq-error-category", failure.category.value.encode()),
            ("dlq-error-type", type(failure.error).__name__.encode()),
            ("dlq-error-message", str(failure.error)[:MAX_ERROR_MESSAGE_LENGTH].encode()),
            ("dlq-attempts", str(failure.attempts).encode()),
            ("dlq-failed-at", datetime.now(UTC).isoformat().encode()),
        ]
        attempt = 0
        while True:
            attempt += 1
            try:
                await producer.send_and_wait(
                    self._settings.kafka_dlq_topic, value=record.value, key=record.key, headers=headers
                )
                log.warning(
                    "sent %s-%d@%d to %s (%s %s)",
                    record.topic, record.partition, record.offset,
                    self._settings.kafka_dlq_topic, failure.category, type(failure.error).__name__,
                )
                return
            except Exception as exc:
                delay = backoff_delay(attempt, 1.0, 30.0)
                log.error("DLQ send failed (attempt %d): %r; offset NOT committed, retrying in %.1fs", attempt, exc, delay)
                await asyncio.sleep(delay)

    async def _commit(self, consumer: AIOKafkaConsumer, record: ConsumerRecord) -> None:
        # The committed offset is the NEXT message to read, hence +1.
        next_offset = record.offset + 1
        try:
            await consumer.commit({TopicPartition(record.topic, record.partition): next_offset})
            log.debug("committed %s-%d offset %d", record.topic, record.partition, next_offset)
        except KafkaError as exc:
            # E.g. the partition was reassigned. The new owner will redeliver this message and
            # create_investigation's idempotency check turns it into "duplicate, skipping".
            log.warning("offset commit failed, message may be redelivered: %r", exc)


def _text(value: bytes | None) -> str | None:
    return value.decode("utf-8", "replace") if value is not None else None
