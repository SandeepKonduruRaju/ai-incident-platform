package com.sandeep.incidentplatform.controller;

import com.sandeep.incidentplatform.dto.CreateIncidentRequest;
import com.sandeep.incidentplatform.dto.IncidentResponse;
import com.sandeep.incidentplatform.dto.UpdateIncidentStatusRequest;
import com.sandeep.incidentplatform.model.Incident;
import com.sandeep.incidentplatform.service.IncidentService;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

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

        return toResponse(incident);
    }

    @GetMapping
    public List<IncidentResponse> listIncidents() {
        return incidentService.findAll()
                .stream()
                .map(this::toResponse)
                .toList();
    }

    @GetMapping("/{id}")
    public ResponseEntity<IncidentResponse> getIncident(@PathVariable UUID id) {
        Optional<Incident> found = incidentService.findById(id);

        if (found.isEmpty()) {
            return ResponseEntity.notFound().build();
        }

        Incident incident = found.get();

        return ResponseEntity.ok(toResponse(incident));
    }

    @PatchMapping("/{id}/status")
    public ResponseEntity<IncidentResponse> updateIncidentStatus(
            @PathVariable UUID id,
            @RequestBody UpdateIncidentStatusRequest request) {

        return incidentService.updateStatus(id, request.status())
                .map(this::toResponse)
                .map(ResponseEntity::ok)
                .orElseGet(() -> ResponseEntity.notFound().build());
    }

    private IncidentResponse toResponse(Incident incident) {
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
