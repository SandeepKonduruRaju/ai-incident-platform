package com.sandeep.incidentplatform.service;

import com.sandeep.incidentplatform.dto.InvestigationResponse;
import com.sandeep.incidentplatform.exception.InvestigationRetryConflictException;
import com.sandeep.incidentplatform.investigation.InvestigationStatus;
import com.sandeep.incidentplatform.investigation.WorkerInvestigation;
import com.sandeep.incidentplatform.investigation.WorkerInvestigationClient;
import com.sandeep.incidentplatform.observability.PlatformMetrics;
import com.sandeep.incidentplatform.redis.InvestigationCache;
import com.sandeep.incidentplatform.service.IncidentService.InvestigationRequest;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.time.Clock;
import java.time.Duration;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

/**
 * Reads the AI investigation of an incident from the investigation worker.
 * The tenant check happens HERE, in our own database, before the worker is called: an incident of
 * another tenant (or no incident at all) is "not found", and the worker is never asked about it.
 *
 * Cache-aside (milestone 4): a FINISHED investigation (COMPLETED/FAILED) is kept in Redis for an hour and
 * served from there, saving the worker HTTP call and the worker's database query. The tenant check above
 * still runs on every read, cache hit or not. PENDING/RUNNING are never cached. Redis down = cache miss.
 *
 * NOT_STARTED and retry: the worker's newest run answers, unless a NEWER investigation request (outbox event) exists
 * that it has not picked up yet. Such a request is PENDING while unsent or younger than investigation.not-started-after
 * (Kafka lag can be minutes under load), then NOT_STARTED. No request at all (incidents created before the outbox
 * existed) is NOT_STARTED at once. NOT_STARTED and FAILED can be retried: a new event through the same outbox.
 * "Newer" compares the event time (incident-service clock) with the run's creation time (worker clock): both are
 * expected to be NTP-synced, as everywhere else in the platform.
 */
@Service
public class InvestigationService {

    private final IncidentService incidentService;
    private final WorkerInvestigationClient workerClient;
    private final PlatformMetrics metrics;
    private final InvestigationCache cache;
    private final Duration notStartedAfter;
    private final Clock clock = Clock.systemUTC();

    // ObjectProvider: no cache bean (app.redis.cache.enabled=false, slice tests) means no caching.
    public InvestigationService(IncidentService incidentService, WorkerInvestigationClient workerClient,
                                PlatformMetrics metrics, ObjectProvider<InvestigationCache> cache,
                                @Value("${investigation.not-started-after:30m}") Duration notStartedAfter) {
        this.incidentService = incidentService;
        this.workerClient = workerClient;
        this.metrics = metrics;
        this.cache = cache.getIfAvailable(() -> InvestigationCache.NONE);
        this.notStartedAfter = notStartedAfter;
    }

    /** Empty = no such incident for this tenant (404). Otherwise always an answer, PENDING at the least. */
    public Optional<InvestigationResponse> findForIncident(String tenantId, UUID incidentId) {
        if (incidentService.findById(tenantId, incidentId).isEmpty()) {
            return Optional.empty();
        }
        Optional<InvestigationResponse> cached = cache.get(tenantId, incidentId);
        if (cached.isPresent()) {
            metrics.investigationRead(cached.get().status());
            return cached;
        }
        InvestigationResponse response = resolve(tenantId, incidentId).response();
        cache.putIfFinished(tenantId, response);
        metrics.investigationRead(response.status());
        return Optional.of(response);
    }

    /**
     * Requests the investigation again (POST .../investigation/retry). Empty = no such incident for this tenant (404).
     * Only from NOT_STARTED or FAILED (409 otherwise). The state is read fresh (no cache), and IncidentService
     * re-checks it under a row lock, so concurrent retries enqueue at most one new run.
     */
    public Optional<InvestigationResponse> retry(String tenantId, UUID incidentId) {
        if (incidentService.findById(tenantId, incidentId).isEmpty()) {
            return Optional.empty();
        }
        Resolved current = resolve(tenantId, incidentId);
        InvestigationStatus status = current.response().status();
        if (!status.retryable()) {
            throw new InvestigationRetryConflictException(
                    "The investigation is " + status + "; only NOT_STARTED or FAILED investigations can be retried.");
        }
        if (incidentService.retryInvestigation(tenantId, incidentId, current.latestRequestId()).isEmpty()) {
            return Optional.empty(); // deleted in the meantime
        }
        cache.evict(tenantId, incidentId); // a cached FAILED must not hide the new run
        return Optional.of(InvestigationResponse.pending(incidentId));
    }

    private Resolved resolve(String tenantId, UUID incidentId) {
        Optional<InvestigationRequest> request = incidentService.latestInvestigationRequest(incidentId);
        Optional<UUID> requestId = request.map(InvestigationRequest::eventId);
        Optional<WorkerInvestigation> run = workerClient.fetch(tenantId, incidentId);

        boolean newerRequestPending = request.isPresent() && run.isPresent() && run.get().createdAt() != null
                && request.get().createdAt().isAfter(run.get().createdAt());
        if (run.isPresent() && !newerRequestPending) {
            return new Resolved(toResponse(incidentId, run.get()), requestId);
        }
        // No run for the newest request (yet).
        boolean stillComing = request.isPresent() && (!request.get().published()
                || request.get().createdAt().isAfter(clock.instant().minus(notStartedAfter)));
        return new Resolved(stillComing ? InvestigationResponse.pending(incidentId)
                : InvestigationResponse.notStarted(incidentId), requestId);
    }

    private record Resolved(InvestigationResponse response, Optional<UUID> latestRequestId) {
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
