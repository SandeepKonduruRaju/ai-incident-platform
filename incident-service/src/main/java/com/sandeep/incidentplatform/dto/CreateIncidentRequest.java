package com.sandeep.incidentplatform.dto;

import com.sandeep.incidentplatform.model.IncidentSeverity;

public record CreateIncidentRequest(String title, String description,
                                    IncidentSeverity severity, String affectedService){
}
