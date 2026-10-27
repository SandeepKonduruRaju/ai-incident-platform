package com.sandeep.incidentplatform.controller;

import com.sandeep.incidentplatform.dto.CreateIncidentRequest;
import com.sandeep.incidentplatform.dto.IncidentResponse;
import com.sandeep.incidentplatform.dto.PageResponse;
import com.sandeep.incidentplatform.dto.UpdateIncidentStatusRequest;
import com.sandeep.incidentplatform.exception.IncidentNotFoundException;
import com.sandeep.incidentplatform.exception.InvalidIdempotencyKeyException;
import com.sandeep.incidentplatform.model.Incident;
import com.sandeep.incidentplatform.service.IdempotentIncidentCreator;
import com.sandeep.incidentplatform.service.IncidentService;
import jakarta.validation.Valid;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import java.util.UUID;

import static com.sandeep.incidentplatform.security.TenantResolver.tenantOf;

@RestController
@RequestMapping("/api/v1/incidents")
public class IncidentController {

    static final int DEFAULT_PAGE_SIZE = 20;
    static final int MAX_PAGE_SIZE = 100;

    private final IncidentService incidentService;
    private final IdempotentIncidentCreator idempotentCreator;

    public IncidentController(IncidentService incidentService, IdempotentIncidentCreator idempotentCreator) {
        this.incidentService = incidentService;
        this.idempotentCreator = idempotentCreator;
    }

    static final String IDEMPOTENCY_KEY = "Idempotency-Key";
    static final String REPLAYED = "Idempotent-Replayed";
    private static final java.util.regex.Pattern VALID_KEY = java.util.regex.Pattern.compile("[!-~]{1,255}");

    // @AuthenticationPrincipal injects the caller's verified JWT; the tenant is taken from it,
    // never from the request, so a client cannot act on behalf of another tenant.
    // Optional Idempotency-Key (1-255 visible ASCII characters, per tenant): 201 Created the first time; the same key
    // with the same body again -> 200 OK with the ORIGINAL incident and "Idempotent-Replayed: true" (nothing new is
    // created or enqueued); the same key with a different body -> 422. See IdempotentIncidentCreator.
    @PostMapping
    public ResponseEntity<IncidentResponse> createIncident(
            @AuthenticationPrincipal Jwt jwt,
            @RequestHeader(name = IDEMPOTENCY_KEY, required = false) String idempotencyKey,
            @Valid @RequestBody CreateIncidentRequest request) {

        // Checked here, not with @Size/@Pattern on the parameter: those would switch the whole method to method
        // validation and change the 400 body of an invalid request body (field errors) that clients rely on.
        if (idempotencyKey != null && !VALID_KEY.matcher(idempotencyKey).matches()) {
            throw new InvalidIdempotencyKeyException();
        }
        IdempotentIncidentCreator.Result result = idempotentCreator.create(tenantOf(jwt), request, idempotencyKey);
        if (result.replayed()) {
            return ResponseEntity.ok().header(REPLAYED, "true").body(toResponse(result.incident()));
        }
        return ResponseEntity.status(HttpStatus.CREATED).body(toResponse(result.incident()));
    }

    // Paginated: ?page=0&size=20. Size is capped so one request can't load the whole table;
    // out-of-range values fail method validation and become a 400.
    @GetMapping
    public PageResponse<IncidentResponse> listIncidents(
            @AuthenticationPrincipal Jwt jwt,
            @RequestParam(defaultValue = "0") @Min(0) int page,
            @RequestParam(defaultValue = "" + DEFAULT_PAGE_SIZE) @Min(1) @Max(MAX_PAGE_SIZE) int size) {

        return PageResponse.from(incidentService.findAll(tenantOf(jwt), page, size).map(this::toResponse));
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
