package com.sandeep.incidentplatform.event;

import com.sandeep.incidentplatform.model.Incident;

import java.time.Instant;
import java.util.UUID;

// Envelope + payload. A record = immutable, matching "events are immutable facts".
public record IncidentCreatedEvent(
        UUID eventId,          // unique per event → idempotency (2.3)
        String eventType,      // lets consumers route/parse
        int schemaVersion,     // safe evolution
        Instant occurredAt,    // when it happened
        String tenantId,       // tenancy carries into the worker
        String requestId,      // tracing across services
        IncidentCreatedPayload payload
) {
    public static final String TYPE = "IncidentCreated";
    public static final int CURRENT_VERSION = 1;

    public static IncidentCreatedEvent from(Incident incident, String requestId) {
        var payload = new IncidentCreatedPayload(
                incident.id(),
                incident.title(),
                incident.description(),
                incident.severity(),
                incident.status(),
                incident.affectedService(),
                incident.createdAt()
        );
        return new IncidentCreatedEvent(
                UUID.randomUUID(),   // NEW id per event, never the incident id
                TYPE,
                CURRENT_VERSION,
                Instant.now(),
                incident.tenantId(),
                requestId,
                payload
        );
    }
}
