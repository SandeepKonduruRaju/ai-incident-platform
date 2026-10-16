package com.sandeep.incidentplatform.event;

import com.sandeep.incidentplatform.model.IncidentSeverity;
import com.sandeep.incidentplatform.model.IncidentStatus;

import java.time.Instant;
import java.util.UUID;

// The data part of the event: only what consumers need. No JPA, no @Version.
public record IncidentCreatedPayload(
                UUID incidentId,
                String title,
                String description,
                IncidentSeverity severity, // Jackson writes enums as strings, e.g. "HIGH"
                IncidentStatus status,
                String affectedService, // lets the investigation worker look up the service's history
                Instant createdAt) {
}
