package com.sandeep.incidentplatform.controller;

import com.sandeep.incidentplatform.dto.CreateIncidentRequest;
import com.sandeep.incidentplatform.dto.IncidentResponse;
import com.sandeep.incidentplatform.model.Incident;
import com.sandeep.incidentplatform.service.IncidentService;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/incidents")
public class IncidentController {

    private final IncidentService incidentService;

    public IncidentController(IncidentService incidentService) {
        this.incidentService = incidentService;
    }

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public IncidentResponse createIncident(
            @RequestBody CreateIncidentRequest request) {

        Incident incident = incidentService.create(request);

        return new IncidentResponse(
                incident.id(),
                incident.title(),
                incident.description(),
                incident.severity(),
                incident.status(),
                incident.affectedService(),
                incident.createdAt()
        );
    }
}