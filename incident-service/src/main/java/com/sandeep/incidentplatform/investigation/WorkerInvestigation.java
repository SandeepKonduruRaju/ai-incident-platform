package com.sandeep.incidentplatform.investigation;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import com.sandeep.incidentplatform.dto.Citation;
import com.sandeep.incidentplatform.dto.Finding;

import java.time.Instant;
import java.util.List;
import java.util.UUID;

/**
 * The worker's internal response, as the worker sends it. Kept separate from the public
 * InvestigationResponse so a change in the worker's contract stays inside this package.
 * ignoreUnknown: the worker may add fields without breaking this service (tolerant reader).
 */
@JsonIgnoreProperties(ignoreUnknown = true)
public record WorkerInvestigation(
        UUID incidentId,
        InvestigationStatus status,
        Result result,
        List<Citation> citations,
        String model,
        String promptVersion,
        Integer attempts,
        Instant createdAt,
        Instant startedAt,
        Instant completedAt,
        String failureReason) {

    /** The stored InvestigationResult (snake_case keys, defined by the worker's app/schemas.py). */
    @JsonIgnoreProperties(ignoreUnknown = true)
    public record Result(
            @JsonProperty("root_cause") Finding rootCause,
            @JsonProperty("contributing_factors") List<Finding> contributingFactors,
            List<Finding> remediation,
            String confidence,
            String summary) {
    }
}
