package com.sandeep.incidentplatform;

import com.sandeep.incidentplatform.controller.IncidentController;
import com.sandeep.incidentplatform.model.Incident;
import com.sandeep.incidentplatform.model.IncidentSeverity;
import com.sandeep.incidentplatform.model.IncidentStatus;
import com.sandeep.incidentplatform.security.Role;
import com.sandeep.incidentplatform.security.SecurityConfig;
import com.sandeep.incidentplatform.service.IncidentService;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.webmvc.test.autoconfigure.WebMvcTest;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

import static com.sandeep.incidentplatform.TestJwt.TENANT;
import static com.sandeep.incidentplatform.TestJwt.as;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.patch;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

// Who may call what: VIEWER reads; RESPONDER and ADMIN also create and change status.
@WebMvcTest(IncidentController.class)
@Import(SecurityConfig.class)
class RoleBasedAccessTest {

    private static final String CREATE_BODY = """
            { "title": "Payments failing", "severity": "HIGH", "affectedService": "payment-service" }
            """;

    @Autowired
    private MockMvc mockMvc;

    @MockitoBean
    private IncidentService incidentService;

    @Test
    void viewerCanListAndReadIncidents() throws Exception {
        Incident incident = incident();
        when(incidentService.findAll(TENANT)).thenReturn(List.of(incident));
        when(incidentService.findById(TENANT, incident.id())).thenReturn(Optional.of(incident));

        mockMvc.perform(get("/api/v1/incidents").with(as(TENANT, Role.VIEWER)))
                .andExpect(status().isOk());
        mockMvc.perform(get("/api/v1/incidents/{id}", incident.id()).with(as(TENANT, Role.VIEWER)))
                .andExpect(status().isOk());
    }

    @Test
    void viewerCannotCreateIncident() throws Exception {
        mockMvc.perform(post("/api/v1/incidents")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(CREATE_BODY)
                        .with(as(TENANT, Role.VIEWER)))
                .andExpect(status().isForbidden());

        verify(incidentService, never()).create(any(), any());
    }

    @Test
    void viewerCannotChangeStatus() throws Exception {
        mockMvc.perform(patch("/api/v1/incidents/{id}/status", UUID.randomUUID())
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{ \"status\": \"RESOLVED\" }")
                        .with(as(TENANT, Role.VIEWER)))
                .andExpect(status().isForbidden());

        verify(incidentService, never()).updateStatus(any(), any(), any());
    }

    @Test
    void responderCanCreateIncident() throws Exception {
        when(incidentService.create(any(), any())).thenReturn(incident());

        mockMvc.perform(post("/api/v1/incidents")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(CREATE_BODY)
                        .with(as(TENANT, Role.RESPONDER)))
                .andExpect(status().isCreated());
    }

    @Test
    void adminCanChangeStatus() throws Exception {
        Incident incident = incident();
        when(incidentService.updateStatus(TENANT, incident.id(), IncidentStatus.RESOLVED))
                .thenReturn(Optional.of(incident));

        mockMvc.perform(patch("/api/v1/incidents/{id}/status", incident.id())
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{ \"status\": \"RESOLVED\" }")
                        .with(as(TENANT, Role.ADMIN)))
                .andExpect(status().isOk());
    }

    @Test
    void authenticatedUserWithoutRoleIsForbidden() throws Exception {
        mockMvc.perform(get("/api/v1/incidents").with(as(TENANT)))
                .andExpect(status().isForbidden());
    }

    private Incident incident() {
        return new Incident(UUID.randomUUID(), TENANT, "Payments failing", null, IncidentSeverity.HIGH,
                IncidentStatus.OPEN, "payment-service", Instant.now());
    }
}
