package com.sandeep.incidentplatform.service;

import org.slf4j.MDC;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Sort;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import com.sandeep.incidentplatform.dto.CreateIncidentRequest;
import com.sandeep.incidentplatform.event.IncidentCreatedEvent;
import com.sandeep.incidentplatform.event.KafkaTopics;
import com.sandeep.incidentplatform.exception.InvestigationRetryConflictException;
import com.sandeep.incidentplatform.model.Incident;
import com.sandeep.incidentplatform.model.IncidentStatus;
import com.sandeep.incidentplatform.observability.RequestIdFilter;
import com.sandeep.incidentplatform.observability.PlatformMetrics;
import com.sandeep.incidentplatform.observability.TraceContextSupport;
import com.sandeep.incidentplatform.outbox.OutboxEvent;
import com.sandeep.incidentplatform.outbox.OutboxEventRepository;
import com.sandeep.incidentplatform.repository.IncidentRepository;
import tools.jackson.databind.json.JsonMapper;

import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.UUID;
import java.util.Optional;

/**
 * Every method is scoped to a tenant. The tenantId always comes from the
 * caller's verified JWT
 * (see TenantResolver), never from the request body, so one tenant can never
 * read or change
 * another tenant's incidents: such an incident simply looks "not found".
 */
@Service
public class IncidentService {

    private final IncidentRepository incidentRepository;
    private final OutboxEventRepository outboxEventRepository;
    private final PlatformMetrics metrics;
    private final TraceContextSupport traceContext;
    private final JsonMapper jsonMapper;

    public IncidentService(IncidentRepository incidentRepository,
            OutboxEventRepository outboxEventRepository, JsonMapper jsonMapper,
            PlatformMetrics metrics, TraceContextSupport traceContext) {
        this.incidentRepository = incidentRepository;
        this.outboxEventRepository = outboxEventRepository;
        this.jsonMapper = jsonMapper;
        this.metrics = metrics;
        this.traceContext = traceContext;
    }

    // One transaction for both inserts: either the incident AND its event are stored, or neither is.
    @Transactional
    public Incident create(String tenantId, CreateIncidentRequest request) {
        return create(tenantId, request, null);
    }

    /**
     * idempotencyKey (nullable) is stored with the incident under a unique (tenant_id, idempotency_key) index. The
     * insert is flushed here, so a concurrent request that used the same key first fails inside this transaction
     * (DataIntegrityViolationException): nothing of it is kept, neither the incident nor its outbox event.
     * See IdempotentIncidentCreator for the replay logic.
     */
    @Transactional
    public Incident create(String tenantId, CreateIncidentRequest request, String idempotencyKey) {
        Incident incident = new Incident(
                UUID.randomUUID(),
                tenantId,
                request.title(),
                request.description(),
                request.severity(),
                // every new incident starts OPEN
                IncidentStatus.OPEN,
                request.affectedService(),
                // PostgreSQL stores microseconds; truncate so the POST response matches later
                // GETs
                Instant.now().truncatedTo(ChronoUnit.MICROS),
                idempotencyKey);

        Incident saved = incidentRepository.saveAndFlush(incident);
        enqueueInvestigation(saved);
        metrics.incidentCreated(saved.severity());
        return saved;
    }

    /**
     * The newest investigation request of an incident (empty: never requested, e.g. created before the outbox). Only
     * IncidentCreated events count, like the worker's superseded check: another event type for the same incident
     * (none exists yet) must not look like a newer investigation request.
     */
    public Optional<InvestigationRequest> latestInvestigationRequest(UUID incidentId) {
        return outboxEventRepository.findFirstByAggregateIdAndEventTypeOrderByCreatedAtDesc(incidentId,
                        IncidentCreatedEvent.TYPE)
                .map(event -> new InvestigationRequest(event.id(), event.createdAt(), event.publishedAt() != null));
    }

    /**
     * Re-requests the investigation: a NEW IncidentCreated event through the same transactional outbox (new event id,
     * so the worker's idempotency treats it as new work and creates a fresh investigation row; older rows keep their
     * own run_count fencing). The incident row is locked, and the request is refused (409) when the
     * newest request is no longer the one the caller based its decision on: two concurrent retries enqueue ONE run.
     * Empty when the incident does not exist for this tenant.
     */
    @Transactional
    public Optional<Incident> retryInvestigation(String tenantId, UUID id, Optional<UUID> expectedLatestRequestId) {
        Optional<Incident> incident = incidentRepository.lockByIdAndTenantId(id, tenantId);
        incident.ifPresent(locked -> {
            Optional<UUID> latest = latestInvestigationRequest(locked.id()).map(InvestigationRequest::eventId);
            if (!latest.equals(expectedLatestRequestId)) {
                throw new InvestigationRetryConflictException(
                        "The investigation was requested again in the meantime. Reload and check its status.");
            }
            enqueueInvestigation(locked);
        });
        return incident;
    }

    // Transactional outbox: no Kafka call here. The event is stored as a row (in the caller's transaction) and
    // OutboxRelay sends it later. requestId is read here, on the HTTP request thread, because the MDC is thread-local.
    private void enqueueInvestigation(Incident incident) {
        IncidentCreatedEvent event = IncidentCreatedEvent.from(incident, MDC.get(RequestIdFilter.MDC_KEY));
        outboxEventRepository.save(new OutboxEvent(
                event.eventId(),
                incident.id(),
                event.eventType(),
                KafkaTopics.INCIDENT_EVENTS,
                jsonMapper.writeValueAsString(event),
                event.occurredAt(),
                // Like requestId: captured on the request thread, re-attached by the relay later.
                traceContext.currentTraceparent()));
    }

    /** One investigation request: the outbox event, when it was made, and whether the relay has sent it. */
    public record InvestigationRequest(UUID eventId, Instant createdAt, boolean published) {
    }

    public Optional<Incident> findByIdempotencyKey(String tenantId, String idempotencyKey) {
        return incidentRepository.findByTenantIdAndIdempotencyKey(tenantId, idempotencyKey);
    }

    public Optional<Incident> findById(String tenantId, UUID id) {
        return incidentRepository.findByIdAndTenantId(id, tenantId);
    }

    // Newest first; id breaks ties so the order is stable and no row repeats or
    // skips across pages.
    public Page<Incident> findAll(String tenantId, int page, int size) {
        Sort newestFirst = Sort.by(Sort.Direction.DESC, "createdAt").and(Sort.by("id"));
        return incidentRepository.findAllByTenantId(tenantId, PageRequest.of(page, size, newestFirst));
    }

    // Load -> change -> commit. The loaded entity is managed inside this
    // transaction, so
    // Hibernate's dirty checking writes the new status on commit; no explicit
    // save() needed.
    @Transactional
    public Optional<Incident> updateStatus(String tenantId, UUID id, IncidentStatus status) {
        return incidentRepository.findByIdAndTenantId(id, tenantId)
                .map(incident -> {
                    incident.changeStatus(status);
                    return incident;
                });
    }
}