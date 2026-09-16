package com.sandeep.incidentplatform.dto;

import com.sandeep.incidentplatform.model.IncidentSeverity;
import com.sandeep.incidentplatform.model.IncidentStatus;

import java.time.Instant;
import java.util.UUID;


public record IncidentResponse(UUID id, String title, String description,
                               IncidentSeverity severity, IncidentStatus status,
                               String affectedService, Instant createdAt ){
}
