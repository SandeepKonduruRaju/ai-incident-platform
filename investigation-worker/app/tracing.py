"""OpenTelemetry tracing (section 3.4).

    incident-service POST ─► outbox row (traceparent stored) ─► relay span ─► Kafka header "traceparent"
        ─► worker "incident-events process" (CONSUMER span, child of the relay span)
            ─► investigation ─► graph.retrieve ─► retrieval ─► SQL spans
                             ─► graph.analyse ─► llm.generate ─► graph.validate ─► graph.save ...

Spans carry ids, counts, timings and outcomes only: NEVER prompt, evidence, log or incident text
(tests/test_tracing.py checks this). Export goes to the OpenTelemetry collector over OTLP/HTTP only
when TRACING_EXPORT_ENABLED=true; otherwise spans still exist (trace ids in the logs) and are dropped.
"""

import logging

from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

log = logging.getLogger(__name__)

# A proxy until a provider is installed, so modules can create it at import time.
tracer = trace.get_tracer("investigation-worker")
_W3C = TraceContextTextMapPropagator()


def configure_tracing(*, service_name: str, export_enabled: bool, otlp_endpoint: str) -> None:
    """Installs the SDK provider once per process (a test may already have installed its own)."""
    if isinstance(trace.get_tracer_provider(), TracerProvider):
        return
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    if export_enabled:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{otlp_endpoint.rstrip('/')}/v1/traces")))
        log.info("exporting traces to %s", otlp_endpoint)
    trace.set_tracer_provider(provider)


def shutdown_tracing() -> None:
    """Flushes spans still in the batch queue (on application shutdown)."""
    provider = trace.get_tracer_provider()
    if isinstance(provider, TracerProvider):
        provider.force_flush()


def context_from_headers(headers: dict[str, str]) -> Context:
    """The trace context in a Kafka message's W3C "traceparent" header (empty context if absent/invalid)."""
    return _W3C.extract(carrier=headers)


def current_trace_id() -> str | None:
    context = trace.get_current_span().get_span_context()
    return format(context.trace_id, "032x") if context.is_valid else None
