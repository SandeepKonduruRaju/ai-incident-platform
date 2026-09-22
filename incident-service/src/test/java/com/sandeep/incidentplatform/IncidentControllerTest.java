package com.sandeep.incidentplatform;

import com.sandeep.incidentplatform.controller.IncidentController;
import com.sandeep.incidentplatform.dto.CreateIncidentRequest;
import com.sandeep.incidentplatform.dto.IncidentResponse;
import com.sandeep.incidentplatform.dto.UpdateIncidentStatusRequest;
import com.sandeep.incidentplatform.model.IncidentSeverity;
import com.sandeep.incidentplatform.model.IncidentStatus;
import com.sandeep.incidentplatform.service.IncidentService;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import java.util.List;
import java.util.UUID;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import static org.junit.jupiter.api.Assertions.assertEquals;

class IncidentControllerTest {

    @Test
    void shouldReturn200WithIncidentWhenIdExists() {
        // Arrange
        IncidentController controller = new IncidentController(new IncidentService());
        IncidentResponse created = controller.createIncident(new CreateIncidentRequest(
                "Payments failing",
                "Customers cannot complete checkout",
                IncidentSeverity.HIGH,
                "payment-service"
        ));

        // Act
        ResponseEntity<IncidentResponse> response = controller.getIncident(created.id());

        // Assert
        assertEquals(HttpStatus.OK, response.getStatusCode());
        assertEquals(created, response.getBody());
    }

    @Test
    void shouldReturn404WhenIdDoesNotExist() {
        // Arrange
        IncidentController controller = new IncidentController(new IncidentService());

        // Act
        ResponseEntity<IncidentResponse> response = controller.getIncident(UUID.randomUUID());

        // Assert
        assertEquals(HttpStatus.NOT_FOUND, response.getStatusCode());
        assertNull(response.getBody());
    }

    @Test
    void shouldReturnAllIncidents() {
        // Arrange
        IncidentController controller = new IncidentController(new IncidentService());
        IncidentResponse first = controller.createIncident(new CreateIncidentRequest(
                "Payments failing",
                "Customers cannot complete checkout",
                IncidentSeverity.HIGH,
                "payment-service"
        ));
        IncidentResponse second = controller.createIncident(new CreateIncidentRequest(
                "Login errors",
                "Users cannot sign in",
                IncidentSeverity.MEDIUM,
                "auth-service"
        ));

        // Act
        List<IncidentResponse> incidents = controller.listIncidents();

        // Assert
        assertEquals(2, incidents.size());
        assertTrue(incidents.contains(first));
        assertTrue(incidents.contains(second));
    }

    @Test
    void shouldUpdateIncidentStatusWhenIdExists() {
        // Arrange
        IncidentController controller = new IncidentController(new IncidentService());
        IncidentResponse created = controller.createIncident(new CreateIncidentRequest(
                "Payments failing",
                "Customers cannot complete checkout",
                IncidentSeverity.HIGH,
                "payment-service"
        ));

        // Act
        ResponseEntity<IncidentResponse> response = controller.updateIncidentStatus(
                created.id(),
                new UpdateIncidentStatusRequest(IncidentStatus.INVESTIGATING)
        );

        // Assert
        assertEquals(HttpStatus.OK, response.getStatusCode());
        assertEquals(IncidentStatus.INVESTIGATING, response.getBody().status());
    }

    @Test
    void shouldReturn404WhenUpdatingMissingIncidentStatus() {
        // Arrange
        IncidentController controller = new IncidentController(new IncidentService());

        // Act
        ResponseEntity<IncidentResponse> response = controller.updateIncidentStatus(
                UUID.randomUUID(),
                new UpdateIncidentStatusRequest(IncidentStatus.RESOLVED)
        );

        // Assert
        assertEquals(HttpStatus.NOT_FOUND, response.getStatusCode());
        assertNull(response.getBody());
    }
}
