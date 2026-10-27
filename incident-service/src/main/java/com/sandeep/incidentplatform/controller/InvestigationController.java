package com.sandeep.incidentplatform.controller;

import com.sandeep.incidentplatform.dto.InvestigationResponse;
import com.sandeep.incidentplatform.exception.IncidentNotFoundException;
import com.sandeep.incidentplatform.service.InvestigationService;
import org.springframework.http.HttpHeaders;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.UUID;

import static com.sandeep.incidentplatform.security.TenantResolver.tenantOf;

/**
 * GET /api/v1/incidents/{id}/investigation: the AI investigation of one incident.
 * Separate from IncidentController so the incident endpoints do not depend on the worker client.
 */
@RestController
@RequestMapping("/api/v1/incidents")
public class InvestigationController {

    // Seconds a client should wait before polling again while the investigation is PENDING/RUNNING.
    static final String POLL_AFTER_SECONDS = "2";

    private final InvestigationService investigationService;

    public InvestigationController(InvestigationService investigationService) {
        this.investigationService = investigationService;
    }

    @GetMapping("/{id}/investigation")
    public ResponseEntity<InvestigationResponse> getInvestigation(@AuthenticationPrincipal Jwt jwt,
                                                                  @PathVariable UUID id) {
        InvestigationResponse investigation = investigationService.findForIncident(tenantOf(jwt), id)
                .orElseThrow(() -> new IncidentNotFoundException(id));

        ResponseEntity.BodyBuilder ok = ResponseEntity.ok();
        if (investigation.status().inProgress()) {
            ok.header(HttpHeaders.RETRY_AFTER, POLL_AFTER_SECONDS);
        }
        return ok.body(investigation);
    }

    /**
     * POST /api/v1/incidents/{id}/investigation/retry: requests the investigation again, only when it is NOT_STARTED
     * or FAILED (409 otherwise). 202 Accepted: the new run starts asynchronously; poll the GET above.
     */
    @PostMapping("/{id}/investigation/retry")
    public ResponseEntity<InvestigationResponse> retryInvestigation(@AuthenticationPrincipal Jwt jwt,
                                                                    @PathVariable UUID id) {
        InvestigationResponse pending = investigationService.retry(tenantOf(jwt), id)
                .orElseThrow(() -> new IncidentNotFoundException(id));
        return ResponseEntity.accepted().header(HttpHeaders.RETRY_AFTER, POLL_AFTER_SECONDS).body(pending);
    }
}
