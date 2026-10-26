package com.sandeep.incidentplatform;

import com.sandeep.incidentplatform.controller.IncidentController;
import com.sandeep.incidentplatform.security.SecurityConfig;
import com.sandeep.incidentplatform.service.IncidentService;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.webmvc.test.autoconfigure.WebMvcTest;
import org.springframework.context.annotation.Import;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.options;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

// Milestone 4B: only the configured UI origin may call the API cross-origin (preflight checked by Spring Security).
@WebMvcTest(controllers = IncidentController.class, properties = "app.cors.allowed-origins=http://localhost:5173")
@Import(SecurityConfig.class)
class CorsTest {

    @Autowired
    private MockMvc mockMvc;

    @MockitoBean
    private IncidentService incidentService;

    @Test
    void preflightFromTheUiOriginIsAllowedAndExposesRequestIdAndRetryAfter() throws Exception {
        mockMvc.perform(options("/api/v1/incidents")
                        .header("Origin", "http://localhost:5173")
                        .header("Access-Control-Request-Method", "POST")
                        .header("Access-Control-Request-Headers", "authorization,content-type"))
                .andExpect(status().isOk())
                .andExpect(header().string("Access-Control-Allow-Origin", "http://localhost:5173"))
                .andExpect(header().doesNotExist("Access-Control-Allow-Credentials"));
    }

    @Test
    void preflightFromAnyOtherOriginIsRejected() throws Exception {
        mockMvc.perform(options("/api/v1/incidents")
                        .header("Origin", "https://evil.example")
                        .header("Access-Control-Request-Method", "POST"))
                .andExpect(status().isForbidden())
                .andExpect(header().doesNotExist("Access-Control-Allow-Origin"));
    }
}
