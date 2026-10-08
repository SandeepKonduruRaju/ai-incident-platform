package com.sandeep.incidentplatform.dto;

import com.sandeep.incidentplatform.model.IncidentSeverity;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;

// Size limits match the column lengths in V1__create_incidents_table.sql.
public record CreateIncidentRequest(@NotBlank @Size(max = 255) String title,
                                    @Size(max = 2000) String description,
                                    @NotNull IncidentSeverity severity,
                                    @NotBlank @Size(max = 255) String affectedService){
}
