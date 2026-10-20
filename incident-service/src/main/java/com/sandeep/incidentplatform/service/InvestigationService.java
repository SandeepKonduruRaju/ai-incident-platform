package com.sandeep.incidentplatform.service;

import com.sandeep.incidentplatform.dto.InvestigationResponse;
import com.sandeep.incidentplatform.investigation.WorkerInvestigation;
import com.sandeep.incidentplatform.investigation.WorkerInvestigationClient;
import com.sandeep.incidentplatform.observability.PlatformMetrics;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.Optional;
import java.util.UUID;

/**
 * Reads the AI investigation of an incident from the investigation worker.
 * The tenant check happens HERE, in our own database, before the worker is called: an incident of
 * another tenant (or no incident at all) is "not found", and the worker is never asked about it.
 */
@Service
public class InvestigationService {

    private final IncidentService incidentService;
    private final WorkerInvestigationClient workerClient;
    private final PlatformMetrics metrics;

    public InvestigationService(IncidentService incidentService, WorkerInvestigationClient workerClient,
                                PlatformMetrics metrics) {
        this.incidentService = incidentService;
        this.workerClient = workerClient;
        this.metrics = metrics;
    }

    /** Empty = no such incident for this tenant (404). Otherwise always an answer, PENDING at the least. */
    public Optional<InvestigationResponse> findForIncident(String tenantId, UUID incidentId) {
        if (incidentService.findById(tenantId, incidentId).isEmpty()) {
            return Optional.empty();
        }
        InvestigationResponse response = workerClient.fetch(tenantId, incidentId)
                .map(investigation -> toResponse(incidentId, investigation))
                // The incident exists but the worker has not consumed its event yet.
                .orElseGet(() -> InvestigationResponse.pending(incidentId));
        metrics.investigationRead(response.status());
        return Optional.of(response);
    }

    private static InvestigationResponse toResponse(UUID incidentId, WorkerInvestigation worker) {
        WorkerInvestigation.Result result = worker.result();
        return new InvestigationResponse(
                incidentId,
                worker.status(),
                result != null ? result.summary() : null,
                result != null ? result.confidence() : null,
                result != null ? result.rootCause() : null,
                result != null ? orEmpty(result.contributingFactors()) : null,
                result != null ? orEmpty(result.remediation()) : null,
                result != null ? orEmpty(worker.citations()) : null,
                worker.model(),
                worker.promptVersion(),
                worker.createdAt(),
                worker.completedAt(),
                worker.failureReason());
    }

    private static <T> List<T> orEmpty(List<T> list) {
        return list != null ? list : List.of();
    }
}
