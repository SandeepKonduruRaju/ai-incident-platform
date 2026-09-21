package com.sandeep.incidentplatform;

import com.sandeep.incidentplatform.controller.IncidentController;
import com.sandeep.incidentplatform.dto.CreateIncidentRequest;
import com.sandeep.incidentplatform.dto.IncidentResponse;
import com.sandeep.incidentplatform.model.IncidentSeverity;
import com.sandeep.incidentplatform.service.IncidentService;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import java.util.UUID;
import static org.junit.jupiter.api.Assertions.assertNull;

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
}