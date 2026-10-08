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
import java.util.UUID;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

// HTTP-level test: requests go through Spring MVC, so @Valid and @ResponseStatus are applied.
@WebMvcTest(IncidentController.class)
class IncidentControllerValidationTest {

    @Autowired
    private MockMvc mockMvc;

    @MockitoBean
    private IncidentService incidentService;

    @Test
    void shouldReturn400WhenTitleIsBlank() throws Exception {
        // Act + Assert
        mockMvc.perform(post("/api/v1/incidents")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "title": "   ",
                                  "description": "Customers cannot complete checkout",
                                  "severity": "HIGH",
                                  "affectedService": "payment-service"
                                }
                                """))
                .andExpect(status().isBadRequest());

        verify(incidentService, never()).create(any());
    }

    @Test
    void shouldReturn400WhenSeverityIsMissing() throws Exception {
        // Act + Assert
        mockMvc.perform(post("/api/v1/incidents")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "title": "Payments failing",
                                  "affectedService": "payment-service"
                                }
                                """))
                .andExpect(status().isBadRequest());

        verify(incidentService, never()).create(any());
    }

    @Test
    void shouldReturn201WhenRequestIsValid() throws Exception {
        // Arrange
        when(incidentService.create(any())).thenReturn(new Incident(
                UUID.randomUUID(),
                "Payments failing",
                "Customers cannot complete checkout",
                IncidentSeverity.HIGH,
                IncidentStatus.OPEN,
                "payment-service",
                Instant.now()
        ));

        // Act + Assert
        mockMvc.perform(post("/api/v1/incidents")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "title": "Payments failing",
                                  "description": "Customers cannot complete checkout",
                                  "severity": "HIGH",
                                  "affectedService": "payment-service"
                                }
                                """))
                .andExpect(status().isCreated());
    }
}
