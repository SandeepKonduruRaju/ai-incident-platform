package com.sandeep.incidentplatform;

import com.sandeep.incidentplatform.dto.CreateIncidentRequest;
import com.sandeep.incidentplatform.model.Incident;
import com.sandeep.incidentplatform.model.IncidentSeverity;
import com.sandeep.incidentplatform.model.IncidentStatus;
import com.sandeep.incidentplatform.service.IncidentService;
import org.junit.jupiter.api.Test;
import java.util.Optional;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import java.util.UUID;

class IncidentServiceTest {

    @Test
    void shouldCreateIncidentWithExpectedValues() {
        // Arrange: prepare the service and input
        IncidentService service = new IncidentService();

        CreateIncidentRequest request = new CreateIncidentRequest(
                "Payments failing",
                "Customers cannot complete checkout",
                IncidentSeverity.HIGH,
                "payment-service"
        );

        // Act: perform the operation
        Incident incident = service.create(request);

        // Assert: check the result
        assertNotNull(incident.id());
        assertNotNull(incident.createdAt());
        assertEquals(IncidentStatus.OPEN, incident.status());
        assertEquals(request.title(), incident.title());

        assertEquals(request.description(), incident.description());
        assertEquals(request.severity(), incident.severity());
        assertEquals(request.affectedService(), incident.affectedService());
    }

    @Test
    void shouldReturnEmptyWhenIncidentDoesNotExist() {
        // Arrange
        IncidentService service = new IncidentService();
        UUID unknownId = UUID.randomUUID();

        // Act
        Optional<Incident> found = service.findById(unknownId);

        // Assert
        assertTrue(found.isEmpty());
    }

    @Test
    void shouldFindIncidentById() {
        // Arrange
        IncidentService service = new IncidentService();
        CreateIncidentRequest request = new CreateIncidentRequest(
                "Payments failing",
                "Customers cannot complete checkout",
                IncidentSeverity.HIGH,
                "payment-service"
        );
        Incident created = service.create(request);

        // Act
        Optional<Incident> found = service.findById(created.id());

        // Assert
        assertTrue(found.isPresent());
        assertEquals(created, found.get());
    }
}