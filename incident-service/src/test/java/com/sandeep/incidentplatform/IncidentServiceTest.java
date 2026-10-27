package com.sandeep.incidentplatform;

import com.sandeep.incidentplatform.observability.PlatformMetrics;
import com.sandeep.incidentplatform.observability.TraceContextSupport;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import com.sandeep.incidentplatform.dto.CreateIncidentRequest;
import com.sandeep.incidentplatform.outbox.OutboxEventRepository;
import com.sandeep.incidentplatform.model.Incident;
import com.sandeep.incidentplatform.model.IncidentSeverity;
import com.sandeep.incidentplatform.model.IncidentStatus;
import com.sandeep.incidentplatform.repository.IncidentRepository;
import com.sandeep.incidentplatform.service.IncidentService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageImpl;
import org.springframework.data.domain.Pageable;
import org.springframework.data.domain.Sort;
import tools.jackson.databind.json.JsonMapper;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertSame;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

// Unit test: IncidentRepository is a Mockito mock, so no database and no Spring context.
@ExtendWith(MockitoExtension.class)
class IncidentServiceTest {

    private static final String TENANT = "acme";

    @Mock
    private IncidentRepository incidentRepository;

    @Mock
    private OutboxEventRepository outboxEventRepository;

    private IncidentService service;

    private SimpleMeterRegistry metrics;

    @BeforeEach
    void setUp() {
        metrics = new SimpleMeterRegistry();
        service = new IncidentService(incidentRepository, outboxEventRepository, JsonMapper.builder().build(),
                new PlatformMetrics(metrics), TraceContextSupport.noop());
    }

    @Test
    void shouldCreateIncidentWithExpectedValues() {
        // Arrange: save() returns whatever it is given, like a real repository
        when(incidentRepository.saveAndFlush(any(Incident.class))).thenAnswer(call -> call.getArgument(0));
        CreateIncidentRequest request = new CreateIncidentRequest(
                "Payments failing",
                "Customers cannot complete checkout",
                IncidentSeverity.HIGH,
                "payment-service"
        );

        // Act
        Incident incident = service.create(TENANT, request);

        // Assert
        assertNotNull(incident.id());
        assertEquals(TENANT, incident.tenantId());
        assertNotNull(incident.createdAt());
        assertEquals(0, incident.createdAt().getNano() % 1_000, "createdAt is truncated to microseconds");
        assertEquals(IncidentStatus.OPEN, incident.status());
        assertEquals(request.title(), incident.title());
        assertEquals(request.description(), incident.description());
        assertEquals(request.severity(), incident.severity());
        assertEquals(request.affectedService(), incident.affectedService());
        verify(incidentRepository).saveAndFlush(incident);
    }

    @Test
    void shouldReturnEmptyWhenIncidentDoesNotExistForTenant() {
        // Arrange
        UUID unknownId = UUID.randomUUID();
        when(incidentRepository.findByIdAndTenantId(unknownId, TENANT)).thenReturn(Optional.empty());

        // Act
        Optional<Incident> found = service.findById(TENANT, unknownId);

        // Assert
        assertTrue(found.isEmpty());
    }

    @Test
    void shouldFindIncidentByIdWithinTenant() {
        // Arrange
        Incident existing = incident(IncidentStatus.OPEN);
        when(incidentRepository.findByIdAndTenantId(existing.id(), TENANT)).thenReturn(Optional.of(existing));

        // Act
        Optional<Incident> found = service.findById(TENANT, existing.id());

        // Assert
        assertTrue(found.isPresent());
        assertSame(existing, found.get());
    }

    @Test
    void shouldReturnEmptyPageWhenTenantHasNoIncidents() {
        // Arrange
        when(incidentRepository.findAllByTenantId(eq(TENANT), any(Pageable.class))).thenReturn(Page.empty());

        // Act
        Page<Incident> incidents = service.findAll(TENANT, 0, 20);

        // Assert
        assertNotNull(incidents);
        assertTrue(incidents.isEmpty());
    }

    @Test
    void shouldRequestPageNewestFirstWithStableTieBreaker() {
        // Arrange
        Incident first = incident(IncidentStatus.OPEN);
        Incident second = incident(IncidentStatus.INVESTIGATING);
        when(incidentRepository.findAllByTenantId(eq(TENANT), any(Pageable.class)))
                .thenReturn(new PageImpl<>(List.of(first, second)));

        // Act
        Page<Incident> incidents = service.findAll(TENANT, 2, 10);

        // Assert: the service asks for the right page, size and order
        ArgumentCaptor<Pageable> pageable = ArgumentCaptor.forClass(Pageable.class);
        verify(incidentRepository).findAllByTenantId(eq(TENANT), pageable.capture());
        assertEquals(2, pageable.getValue().getPageNumber());
        assertEquals(10, pageable.getValue().getPageSize());
        assertEquals(Sort.by(Sort.Direction.DESC, "createdAt").and(Sort.by("id")), pageable.getValue().getSort());
        assertEquals(List.of(first, second), incidents.getContent());
    }

    @Test
    void shouldUpdateIncidentStatus() {
        // Arrange
        Incident existing = incident(IncidentStatus.OPEN);
        when(incidentRepository.findByIdAndTenantId(existing.id(), TENANT)).thenReturn(Optional.of(existing));

        // Act
        Optional<Incident> updated = service.updateStatus(TENANT, existing.id(), IncidentStatus.MITIGATED);

        // Assert: the same loaded entity is changed in place (JPA dirty checking persists it)
        assertTrue(updated.isPresent());
        assertSame(existing, updated.get());
        assertEquals(IncidentStatus.MITIGATED, existing.status());
    }

    @Test
    void shouldReturnEmptyWhenUpdatingIncidentOutsideTenant() {
        // Arrange
        UUID unknownId = UUID.randomUUID();
        when(incidentRepository.findByIdAndTenantId(unknownId, TENANT)).thenReturn(Optional.empty());

        // Act
        Optional<Incident> updated = service.updateStatus(TENANT, unknownId, IncidentStatus.RESOLVED);

        // Assert
        assertTrue(updated.isEmpty());
    }

    private Incident incident(IncidentStatus status) {
        return new Incident(
                UUID.randomUUID(),
                TENANT,
                "Payments failing",
                "Customers cannot complete checkout",
                IncidentSeverity.HIGH,
                status,
                "payment-service",
                Instant.now()
        );
    }
}
