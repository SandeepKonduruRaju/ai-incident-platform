package com.sandeep.incidentplatform;

import com.sandeep.incidentplatform.controller.IncidentController;
import com.sandeep.incidentplatform.model.Incident;
import com.sandeep.incidentplatform.model.IncidentSeverity;
import com.sandeep.incidentplatform.model.IncidentStatus;
import com.sandeep.incidentplatform.service.IncidentService;
import com.sandeep.incidentplatform.security.SecurityConfig;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.webmvc.test.autoconfigure.WebMvcTest;
import org.springframework.context.annotation.Import;
import org.springframework.data.domain.PageImpl;
import org.springframework.data.domain.PageRequest;
import org.springframework.http.MediaType;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static com.sandeep.incidentplatform.TestJwt.TENANT;
import static com.sandeep.incidentplatform.TestJwt.asUser;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.patch;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

// HTTP-level test of IncidentController: real Spring MVC (routing, JSON, status codes),
// with IncidentService mocked so the test does not depend on how incidents are stored.
@WebMvcTest(IncidentController.class)
@Import(SecurityConfig.class)
class IncidentControllerTest {

    @Autowired
    private MockMvc mockMvc;

    @MockitoBean
    private IncidentService incidentService;

    @Test
    void shouldReturn200WithIncidentWhenIdExists() throws Exception {
        // Arrange
        Incident incident = incident("Payments failing", IncidentStatus.OPEN);
        when(incidentService.findById(TENANT, incident.id())).thenReturn(Optional.of(incident));

        // Act + Assert
        mockMvc.perform(get("/api/v1/incidents/{id}", incident.id()).with(asUser()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.id").value(incident.id().toString()))
                .andExpect(jsonPath("$.title").value("Payments failing"))
                .andExpect(jsonPath("$.status").value("OPEN"));
    }

    @Test
    void shouldReturn404WhenIdDoesNotExist() throws Exception {
        // Arrange
        UUID unknownId = UUID.randomUUID();
        when(incidentService.findById(TENANT, unknownId)).thenReturn(Optional.empty());

        // Act + Assert
        mockMvc.perform(get("/api/v1/incidents/{id}", unknownId).with(asUser()))
                .andExpect(status().isNotFound());
    }

    @Test
    void shouldReturnFirstPageWithDefaultSize() throws Exception {
        // Arrange: 2 incidents on page 0 (default size 20), 2 in total
        when(incidentService.findAll(TENANT, 0, 20)).thenReturn(new PageImpl<>(List.of(
                incident("Payments failing", IncidentStatus.OPEN),
                incident("Login errors", IncidentStatus.INVESTIGATING)
        ), PageRequest.of(0, 20), 2));

        // Act + Assert
        mockMvc.perform(get("/api/v1/incidents").with(asUser()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.items.length()").value(2))
                .andExpect(jsonPath("$.items[0].title").value("Payments failing"))
                .andExpect(jsonPath("$.items[1].title").value("Login errors"))
                .andExpect(jsonPath("$.page").value(0))
                .andExpect(jsonPath("$.size").value(20))
                .andExpect(jsonPath("$.totalElements").value(2))
                .andExpect(jsonPath("$.totalPages").value(1));
    }

    @Test
    void shouldPassRequestedPageAndSizeToService() throws Exception {
        // Arrange: page 1 of size 2 out of 5 incidents
        when(incidentService.findAll(TENANT, 1, 2)).thenReturn(new PageImpl<>(List.of(
                incident("Third", IncidentStatus.OPEN),
                incident("Fourth", IncidentStatus.OPEN)
        ), PageRequest.of(1, 2), 5));

        // Act + Assert
        mockMvc.perform(get("/api/v1/incidents").param("page", "1").param("size", "2").with(asUser()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.page").value(1))
                .andExpect(jsonPath("$.totalElements").value(5))
                .andExpect(jsonPath("$.totalPages").value(3));
    }

    @Test
    void shouldReturn400WhenPageSizeIsTooLarge() throws Exception {
        mockMvc.perform(get("/api/v1/incidents").param("size", "101").with(asUser()))
                .andExpect(status().isBadRequest());

        verify(incidentService, never()).findAll(any(), anyInt(), anyInt());
    }

    @Test
    void shouldReturn400WhenPageIsNegative() throws Exception {
        mockMvc.perform(get("/api/v1/incidents").param("page", "-1").with(asUser()))
                .andExpect(status().isBadRequest());

        verify(incidentService, never()).findAll(any(), anyInt(), anyInt());
    }

    @Test
    void shouldUpdateIncidentStatusWhenIdExists() throws Exception {
        // Arrange
        Incident updated = incident("Payments failing", IncidentStatus.INVESTIGATING);
        when(incidentService.updateStatus(TENANT, updated.id(), IncidentStatus.INVESTIGATING))
                .thenReturn(Optional.of(updated));

        // Act + Assert
        mockMvc.perform(patch("/api/v1/incidents/{id}/status", updated.id())
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                { "status": "INVESTIGATING" }
                                """).with(asUser()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("INVESTIGATING"));
    }

    @Test
    void shouldReturn404WhenUpdatingMissingIncidentStatus() throws Exception {
        // Arrange
        UUID unknownId = UUID.randomUUID();
        when(incidentService.updateStatus(TENANT, unknownId, IncidentStatus.RESOLVED)).thenReturn(Optional.empty());

        // Act + Assert
        mockMvc.perform(patch("/api/v1/incidents/{id}/status", unknownId)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                { "status": "RESOLVED" }
                                """).with(asUser()))
                .andExpect(status().isNotFound());
    }

    @Test
    void shouldReturn400WhenStatusIsMissing() throws Exception {
        // Act + Assert
        mockMvc.perform(patch("/api/v1/incidents/{id}/status", UUID.randomUUID())
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{}").with(asUser()))
                .andExpect(status().isBadRequest());

        verify(incidentService, never()).updateStatus(any(), any(), any());
    }

    private Incident incident(String title, IncidentStatus status) {
        return new Incident(
                UUID.randomUUID(),
                TENANT,
                title,
                "Some description",
                IncidentSeverity.HIGH,
                status,
                "payment-service",
                Instant.now()
        );
    }
}
