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
        Incident incident = service.create(request);

        // Assert
        assertNotNull(incident.id());
        assertNotNull(incident.createdAt());
        assertEquals(IncidentStatus.OPEN, incident.status());
        assertEquals(request.title(), incident.title());
        assertEquals(request.description(), incident.description());
        assertEquals(request.severity(), incident.severity());
        assertEquals(request.affectedService(), incident.affectedService());
        verify(incidentRepository).save(incident);
    }

    @Test
    void shouldReturnEmptyWhenIncidentDoesNotExist() {
        // Arrange
        UUID unknownId = UUID.randomUUID();
        when(incidentRepository.findById(unknownId)).thenReturn(Optional.empty());

        // Act
        Optional<Incident> found = service.findById(unknownId);

        // Assert
        assertTrue(found.isEmpty());
    }

    @Test
    void shouldFindIncidentById() {
        // Arrange
        Incident existing = incident(IncidentStatus.OPEN);
        when(incidentRepository.findById(existing.id())).thenReturn(Optional.of(existing));

        // Act
        Optional<Incident> found = service.findById(existing.id());

        // Assert
        assertTrue(found.isPresent());
        assertSame(existing, found.get());
    }

    @Test
    void shouldReturnEmptyListWhenNoIncidentsExist() {
        // Arrange
        when(incidentRepository.findAll()).thenReturn(List.of());

        // Act
        List<Incident> incidents = service.findAll();

        // Assert
        assertNotNull(incidents);
        assertTrue(incidents.isEmpty());
    }

    @Test
    void shouldReturnAllIncidents() {
        // Arrange
        Incident first = incident(IncidentStatus.OPEN);
        Incident second = incident(IncidentStatus.INVESTIGATING);
        when(incidentRepository.findAll()).thenReturn(List.of(first, second));

        // Act
        List<Incident> incidents = service.findAll();

        // Assert
        assertEquals(List.of(first, second), incidents);
    }

    @Test
    void shouldUpdateIncidentStatus() {
        // Arrange
        Incident existing = incident(IncidentStatus.OPEN);
        when(incidentRepository.findById(existing.id())).thenReturn(Optional.of(existing));

        // Act
        Optional<Incident> updated = service.updateStatus(existing.id(), IncidentStatus.MITIGATED);

        // Assert: the same loaded entity is changed in place (JPA dirty checking persists it)
        assertTrue(updated.isPresent());
        assertSame(existing, updated.get());
        assertEquals(IncidentStatus.MITIGATED, existing.status());
    }

    @Test
    void shouldReturnEmptyWhenUpdatingMissingIncidentStatus() {
        // Arrange
        UUID unknownId = UUID.randomUUID();
        when(incidentRepository.findById(unknownId)).thenReturn(Optional.empty());

        // Act
        Optional<Incident> updated = service.updateStatus(unknownId, IncidentStatus.RESOLVED);

        // Assert
        assertTrue(updated.isEmpty());
    }

    private Incident incident(IncidentStatus status) {
        return new Incident(
                UUID.randomUUID(),
                "Payments failing",
                "Customers cannot complete checkout",
                IncidentSeverity.HIGH,
                status,
                "payment-service",
                Instant.now()
        );
    }
}
