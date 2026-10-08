package com.sandeep.incidentplatform;

import com.sandeep.incidentplatform.dto.CreateIncidentRequest;
import com.sandeep.incidentplatform.model.Incident;
import com.sandeep.incidentplatform.model.IncidentSeverity;
import com.sandeep.incidentplatform.model.IncidentStatus;
import com.sandeep.incidentplatform.repository.IncidentRepository;
import com.sandeep.incidentplatform.service.IncidentService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertSame;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

// Unit test: IncidentRepository is a Mockito mock, so no database and no Spring context.
@ExtendWith(MockitoExtension.class)
class IncidentServiceTest {

    private static final String TENANT = "acme";

    @Mock
    private IncidentRepository incidentRepository;

    private IncidentService service;

    @BeforeEach
    void setUp() {
        service = new IncidentService(incidentRepository);
    }

    @Test
    void shouldCreateIncidentWithExpectedValues() {
        // Arrange: save() returns whatever it is given, like a real repository
        when(incidentRepository.save(any(Incident.class))).thenAnswer(call -> call.getArgument(0));
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
        verify(incidentRepository).save(incident);
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
    void shouldReturnEmptyListWhenTenantHasNoIncidents() {
        // Arrange
        when(incidentRepository.findAllByTenantIdOrderByCreatedAtDesc(TENANT)).thenReturn(List.of());

        // Act
        List<Incident> incidents = service.findAll(TENANT);

        // Assert
        assertNotNull(incidents);
        assertTrue(incidents.isEmpty());
    }

    @Test
    void shouldReturnAllIncidentsOfTenant() {
        // Arrange
        Incident first = incident(IncidentStatus.OPEN);
        Incident second = incident(IncidentStatus.INVESTIGATING);
        when(incidentRepository.findAllByTenantIdOrderByCreatedAtDesc(TENANT)).thenReturn(List.of(first, second));

        // Act
        List<Incident> incidents = service.findAll(TENANT);

        // Assert
        assertEquals(List.of(first, second), incidents);
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
