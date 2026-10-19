package com.sandeep.incidentplatform.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.sandeep.incidentplatform.investigation.InvestigationStatus;

import java.time.Instant;
import java.util.List;
import java.util.UUID;

/**
 * Public view of the AI investigation of an incident. Null fields are omitted from the JSON, so a
 * PENDING answer is just {"incidentId": ..., "status": "PENDING"} and a FAILED one has no findings.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record InvestigationResponse(
        UUID incidentId,
        InvestigationStatus status,
        String summary,
        String confidence,
        Finding rootCause,
        List<Finding> contributingFactors,
        List<Finding> remediation,
        List<Citation> citations,
        String model,
        String promptVersion,
        Instant createdAt,
        Instant completedAt,
        String failureReason) {

    /** The incident exists but the worker has not created its investigation yet. */
    public static InvestigationResponse pending(UUID incidentId) {
        return new InvestigationResponse(incidentId, InvestigationStatus.PENDING,
                null, null, null, null, null, null, null, null, null, null, null);
    }
}
