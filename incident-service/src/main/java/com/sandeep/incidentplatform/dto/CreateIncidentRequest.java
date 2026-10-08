package com.sandeep.incidentplatform.dto;

import com.sandeep.incidentplatform.model.IncidentSeverity;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;

public record CreateIncidentRequest(@NotBlank String title, String description,
                                    @NotNull IncidentSeverity severity,
                                    @NotBlank String affectedService){
}
