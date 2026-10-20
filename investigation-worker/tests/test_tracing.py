"""OpenTelemetry tracing of the worker (section 3.4), with an in-memory span exporter (no collector):
the Kafka traceparent header makes the consume span a child of the producer's span, the graph and the
LLM call get spans, and no prompt / evidence / answer text ever lands in a span attribute."""

import json
import uuid
from datetime import UTC, datetime

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.config import Settings
from app.consumer import IncidentEventConsumer
from app.llm import FakeLLM
from app.llm_observed import ObservedLLM
from app.prompt import SYSTEM_PROMPT
from tests.test_graph import EVIDENCE, INCIDENT, VALID, _deps, _run

TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
PARENT_SPAN_ID = "00f067aa0ba902b7"


@pytest.fixture(scope="module")
def spans():
    """Adds an in-memory exporter to the SDK provider (installs one if the app has not yet)."""
    provider = trace.get_tracer_provider()
    if not isinstance(provider, TracerProvider):
        provider = TracerProvider()
        trace.set_tracer_provider(provider)
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    yield exporter
    exporter.shutdown()


def _event_bytes() -> bytes:
    return json.dumps({
        "eventId": str(uuid.uuid4()), "eventType": "IncidentCreated", "schemaVersion": 1,
        "occurredAt": datetime.now(UTC).isoformat(), "tenantId": "acme", "requestId": "req-1",
        "payload": json.loads(INCIDENT.model_dump_json()),
    }).encode()


class _Kafka:
    async def commit(self, offsets):
        return None


async def test_traceparent_header_makes_the_consume_span_a_child_of_the_producer(spans):
    spans.clear()
    seen = {}

    async def processor(event):
        seen["context"] = trace.get_current_span().get_span_context()

    consumer = IncidentEventConsumer(Settings(database_url="unused"), processor=processor)
    record = type("Record", (), dict(
        topic="incident-events", partition=1, offset=42, key=b"k", value=_event_bytes(),
        headers=[("traceparent", f"00-{TRACE_ID}-{PARENT_SPAN_ID}-01".encode()), ("eventId", b"e-1")],
    ))()

    await consumer._handle(_Kafka(), producer=None, record=record)

    [consume] = [s for s in spans.get_finished_spans() if s.name == "incident-events process"]
    assert format(consume.context.trace_id, "032x") == TRACE_ID  # same trace as incident-service
    assert format(consume.parent.span_id, "016x") == PARENT_SPAN_ID  # child of the relay's span
    assert consume.kind == trace.SpanKind.CONSUMER
    assert consume.attributes["messaging.kafka.offset"] == 42
    assert seen["context"].span_id == consume.context.span_id  # processing runs inside the consume span


async def test_without_traceparent_the_consume_span_starts_a_new_trace(spans):
    spans.clear()
    consumer = IncidentEventConsumer(Settings(database_url="unused"), processor=lambda event: _noop())
    record = type("Record", (), dict(topic="incident-events", partition=0, offset=1, key=None,
                                     value=_event_bytes(), headers=[]))()

    await consumer._handle(_Kafka(), producer=None, record=record)

    [consume] = [s for s in spans.get_finished_spans() if s.name == "incident-events process"]
    assert consume.parent is None


async def _noop():
    return None


async def test_graph_spans_carry_ids_and_counts_but_never_prompt_or_evidence_text(spans):
    spans.clear()
    llm = ObservedLLM(inner=FakeLLM([VALID]), model="fake-llm", prompt_version="v1", price_in_per_m=0, price_out_per_m=0)
    deps, _, _ = _deps(llm)

    await _run(deps)

    finished = spans.get_finished_spans()
    names = {s.name for s in finished}
    assert {"investigation", "graph.retrieve", "graph.analyse", "graph.validate", "graph.save", "llm.generate"} <= names
    [call] = [s for s in finished if s.name == "llm.generate"]
    assert call.attributes["gen_ai.request.model"] == "fake-llm"
    assert call.attributes["prompt_version"] == "v1"
    assert call.attributes["gen_ai.usage.input_tokens"] > 0
    assert call.attributes["gen_ai.response.finish_reason"] == "end_turn"
    parents = {s.context.span_id: s.name for s in finished}
    assert parents[call.parent.span_id] == "graph.analyse"

    forbidden = [SYSTEM_PROMPT[:60], INCIDENT.title, INCIDENT.description, "Connection pool exhausted",
                 *(item.content for item in EVIDENCE)]
    for span in finished:
        for value in span.attributes.values():
            text = str(value)
            assert not any(snippet in text for snippet in forbidden), (span.name, text[:80])
