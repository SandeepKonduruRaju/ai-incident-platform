package com.sandeep.incidentplatform.model;

import java.time.Instant;
import java.util.UUID;

public record Incident(UUID id, String title, String description,
                       IncidentSeverity severity, IncidentStatus status,
                       String affectedService, Instant createdAt ){
}
