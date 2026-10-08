package com.sandeep.incidentplatform.controller;

import com.sandeep.incidentplatform.dto.CreateIncidentRequest;
import com.sandeep.incidentplatform.dto.IncidentResponse;
import com.sandeep.incidentplatform.dto.UpdateIncidentStatusRequest;
import com.sandeep.incidentplatform.exception.IncidentNotFoundException;
import com.sandeep.incidentplatform.model.Incident;
import com.sandeep.incidentplatform.service.IncidentService;
import jakarta.validation.Valid;
import org.springframework.http.HttpStatus;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import java.util.List;
import java.util.UUID;

import static com.sandeep.incidentplatform.security.TenantResolver.tenantOf;

@RestController
@RequestMapping("/api/v1/incidents")
public class IncidentController {

    private final IncidentService incidentService;

    public IncidentController(IncidentService incidentService) {
        this.incidentService = incidentService;
    }

    // @AuthenticationPrincipal injects the caller's verified JWT; the tenant is taken from it,
    // never from the request, so a client cannot act on behalf of another tenant.
    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public IncidentResponse createIncident(
            @AuthenticationPrincipal Jwt jwt,
            @Valid @RequestBody CreateIncidentRequest request) {

        Incident incident = incidentService.create(tenantOf(jwt), request);

        return toResponse(incident);
    }

    @GetMapping
    public List<IncidentResponse> listIncidents(@AuthenticationPrincipal Jwt jwt) {
        return incidentService.findAll(tenantOf(jwt))
                .stream()
                .map(this::toResponse)
                .toList();
    }

    // An empty Optional becomes IncidentNotFoundException; GlobalExceptionHandler turns it into a 404 body.
    // Another tenant's incident is also "not found" (404, not 403) so its existence is not revealed.
    @GetMapping("/{id}")
    public IncidentResponse getIncident(@AuthenticationPrincipal Jwt jwt, @PathVariable UUID id) {
        return incidentService.findById(tenantOf(jwt), id)
                .map(this::toResponse)
                .orElseThrow(() -> new IncidentNotFoundException(id));
    }

    @PatchMapping("/{id}/status")
    public IncidentResponse updateIncidentStatus(
            @AuthenticationPrincipal Jwt jwt,
            @PathVariable UUID id,
            @Valid @RequestBody UpdateIncidentStatusRequest request) {

        return incidentService.updateStatus(tenantOf(jwt), id, request.status())
                .map(this::toResponse)
                .orElseThrow(() -> new IncidentNotFoundException(id));
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
