package com.sandeep.incidentplatform.dto;

import com.sandeep.incidentplatform.model.IncidentStatus;
import jakarta.validation.constraints.NotNull;

public record UpdateIncidentStatusRequest(@NotNull IncidentStatus status) {
}
