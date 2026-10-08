package com.sandeep.incidentplatform;

import com.sandeep.incidentplatform.controller.IncidentController;
import com.sandeep.incidentplatform.model.Incident;
import com.sandeep.incidentplatform.model.IncidentSeverity;
import com.sandeep.incidentplatform.model.IncidentStatus;
import com.sandeep.incidentplatform.service.IncidentService;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.webmvc.test.autoconfigure.WebMvcTest;
import org.springframework.http.MediaType;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.patch;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

// HTTP-level test of IncidentController: real Spring MVC (routing, JSON, status codes),
// with IncidentService mocked so the test does not depend on how incidents are stored.
@WebMvcTest(IncidentController.class)
class IncidentControllerTest {

    @Autowired
    private MockMvc mockMvc;

    @MockitoBean
    private IncidentService incidentService;

    @Test
    void shouldReturn200WithIncidentWhenIdExists() throws Exception {
        // Arrange
        Incident incident = incident("Payments failing", IncidentStatus.OPEN);
        when(incidentService.findById(incident.id())).thenReturn(Optional.of(incident));

        // Act + Assert
        mockMvc.perform(get("/api/v1/incidents/{id}", incident.id()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.id").value(incident.id().toString()))
                .andExpect(jsonPath("$.title").value("Payments failing"))
                .andExpect(jsonPath("$.status").value("OPEN"));
    }

    @Test
    void shouldReturn404WhenIdDoesNotExist() throws Exception {
        // Arrange
        UUID unknownId = UUID.randomUUID();
        when(incidentService.findById(unknownId)).thenReturn(Optional.empty());

        // Act + Assert
        mockMvc.perform(get("/api/v1/incidents/{id}", unknownId))
                .andExpect(status().isNotFound());
    }

    @Test
    void shouldReturnAllIncidents() throws Exception {
        // Arrange
        when(incidentService.findAll()).thenReturn(List.of(
                incident("Payments failing", IncidentStatus.OPEN),
                incident("Login errors", IncidentStatus.INVESTIGATING)
        ));

        // Act + Assert
        mockMvc.perform(get("/api/v1/incidents"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.length()").value(2))
                .andExpect(jsonPath("$[0].title").value("Payments failing"))
                .andExpect(jsonPath("$[1].title").value("Login errors"));
    }

    @Test
    void shouldUpdateIncidentStatusWhenIdExists() throws Exception {
        // Arrange
        Incident updated = incident("Payments failing", IncidentStatus.INVESTIGATING);
        when(incidentService.updateStatus(updated.id(), IncidentStatus.INVESTIGATING))
                .thenReturn(Optional.of(updated));

        // Act + Assert
        mockMvc.perform(patch("/api/v1/incidents/{id}/status", updated.id())
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                { "status": "INVESTIGATING" }
                                """))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("INVESTIGATING"));
    }

    @Test
    void shouldReturn404WhenUpdatingMissingIncidentStatus() throws Exception {
        // Arrange
        UUID unknownId = UUID.randomUUID();
        when(incidentService.updateStatus(unknownId, IncidentStatus.RESOLVED)).thenReturn(Optional.empty());

        // Act + Assert
        mockMvc.perform(patch("/api/v1/incidents/{id}/status", unknownId)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                { "status": "RESOLVED" }
                                """))
                .andExpect(status().isNotFound());
    }

    @Test
    void shouldReturn400WhenStatusIsMissing() throws Exception {
        // Act + Assert
        mockMvc.perform(patch("/api/v1/incidents/{id}/status", UUID.randomUUID())
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{}"))
                .andExpect(status().isBadRequest());

        verify(incidentService, never()).updateStatus(any(), any());
    }

    private Incident incident(String title, IncidentStatus status) {
        return new Incident(
                UUID.randomUUID(),
                title,
                "Some description",
                IncidentSeverity.HIGH,
                status,
                "payment-service",
                Instant.now()
        );
    }
}
