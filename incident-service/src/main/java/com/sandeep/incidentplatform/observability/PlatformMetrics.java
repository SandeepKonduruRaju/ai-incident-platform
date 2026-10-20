package com.sandeep.incidentplatform.observability;

import com.sandeep.incidentplatform.investigation.InvestigationStatus;
import com.sandeep.incidentplatform.model.IncidentSeverity;
import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.springframework.stereotype.Component;

/**
 * The service's custom metrics, in one place so their names and labels stay consistent.
 * Labels are LOW-CARDINALITY enums only (severity, status, result, kind): never incident, tenant or
 * request ids, which would create one time series per value and overload Prometheus.
 * Prometheus names: dots become underscores and counters get "_total", e.g. incidents_opened_total.
 */
@Component
public class PlatformMetrics {

    /** Why a call to the investigation worker failed (the label values of worker_client_errors_total). */
    public enum WorkerErrorKind {
        TIMEOUT, CONNECTION, UNAUTHORIZED, SERVER_ERROR, HTTP_ERROR, BAD_RESPONSE;

        String label() {
            return name().toLowerCase();
        }
    }

    private final MeterRegistry registry;

    public PlatformMetrics(MeterRegistry registry) {
        this.registry = registry;
    }

    /** For unit tests that build services by hand. */
    public static PlatformMetrics inMemory() {
        return new PlatformMetrics(new SimpleMeterRegistry());
    }

    public void incidentCreated(IncidentSeverity severity) {
        counter("incidents.opened", "Incidents created (they start OPEN)", "severity", severity.name()).increment();
    }

    public void outboxPublished(boolean success) {
        counter("outbox.publish", "Outbox events sent to Kafka (or failed)", "result", success ? "success" : "failure")
                .increment();
    }

    public void investigationRead(InvestigationStatus status) {
        counter("investigation.reads", "Investigation reads by returned status", "status", status.name()).increment();
    }

    public void workerClientError(WorkerErrorKind kind) {
        counter("worker.client.errors", "Failed calls to the investigation worker", "kind", kind.label()).increment();
    }

    private Counter counter(String name, String description, String tagKey, String tagValue) {
        return Counter.builder(name).description(description).tag(tagKey, tagValue).register(registry);
    }
}
