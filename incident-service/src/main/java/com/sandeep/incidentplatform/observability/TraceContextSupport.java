package com.sandeep.incidentplatform.observability;

import io.micrometer.tracing.Span;
import io.micrometer.tracing.Tracer;
import io.micrometer.tracing.propagation.Propagator;
import org.apache.kafka.common.header.Headers;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Component;

import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.Map;

/**
 * Carries a trace across the transactional outbox. The POST request's trace is captured as a W3C
 * {@code traceparent} string and stored with the outbox row; the relay (a scheduler thread, much later)
 * starts a span that continues that trace and writes its {@code traceparent} into the Kafka record
 * headers, where the worker picks it up. Only ids travel this way, never payload content.
 */
@Component
public class TraceContextSupport {

    public static final String TRACEPARENT = "traceparent";

    private final Tracer tracer;
    private final Propagator propagator;

    // ObjectProvider: tests without tracing auto-configuration get the no-op implementations.
    @Autowired
    public TraceContextSupport(ObjectProvider<Tracer> tracer, ObjectProvider<Propagator> propagator) {
        this(tracer.getIfAvailable(() -> Tracer.NOOP), propagator.getIfAvailable(() -> Propagator.NOOP));
    }

    TraceContextSupport(Tracer tracer, Propagator propagator) {
        this.tracer = tracer;
        this.propagator = propagator;
    }

    /** For unit tests that build services by hand. */
    public static TraceContextSupport noop() {
        return new TraceContextSupport(Tracer.NOOP, Propagator.NOOP);
    }

    /** The current span as a W3C traceparent, or null when there is no active trace. */
    public String currentTraceparent() {
        Span span = tracer.currentSpan();
        if (span == null || span.isNoop()) {
            return null;
        }
        Map<String, String> carrier = new HashMap<>();
        propagator.inject(span.context(), carrier, Map::put);
        return carrier.get(TRACEPARENT);
    }

    /** Starts a PRODUCER span that continues the stored trace (a new trace when there is none). */
    public Span startContinuing(String traceparent, String name) {
        Map<String, String> carrier = traceparent == null ? Map.of() : Map.of(TRACEPARENT, traceparent);
        return propagator.extract(carrier, Map::get).name(name).kind(Span.Kind.PRODUCER).start();
    }

    public Tracer.SpanInScope inScope(Span span) {
        return tracer.withSpan(span);
    }

    /** Writes the span's context (traceparent, plus tracestate if any) into the Kafka record headers. */
    public void injectInto(Span span, Headers headers) {
        propagator.inject(span.context(), headers, (target, key, value) -> {
            target.remove(key);
            target.add(key, value.getBytes(StandardCharsets.UTF_8));
        });
    }
}
