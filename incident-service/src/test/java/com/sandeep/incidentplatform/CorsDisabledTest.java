package com.sandeep.incidentplatform;

import com.sandeep.incidentplatform.service.IdempotentIncidentCreator;
import com.sandeep.incidentplatform.controller.IncidentController;
import com.sandeep.incidentplatform.security.SecurityConfig;
import com.sandeep.incidentplatform.service.IncidentService;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.webmvc.test.autoconfigure.WebMvcTest;
import org.springframework.context.annotation.Import;
import org.springframework.data.domain.Page;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;

import static com.sandeep.incidentplatform.TestJwt.asUser;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * Milestone 4B regression: with NO allowed origins (the default), CORS processing is off. The UI's calls come through
 * nginx with the browser's Origin (http://localhost:3001) while the Host the service sees may differ; they must not be
 * mistaken for cross-origin calls and refused (found by the Playwright e2e test).
 */
@WebMvcTest(IncidentController.class)
@Import({SecurityConfig.class, IdempotentIncidentCreator.class}) // the creator is real; IncidentService is mocked
class CorsDisabledTest {

    @Autowired
    private MockMvc mockMvc;

    @MockitoBean
    private IncidentService incidentService;

    @Test
    void requestWithAnOriginHeaderThroughTheSameOriginProxyIsServedWithoutCorsHeaders() throws Exception {
        when(incidentService.findAll(any(), anyInt(), anyInt())).thenReturn(Page.empty());

        mockMvc.perform(get("/api/v1/incidents").with(asUser())
                        .header("Host", "incident-service:8080")
                        .header("Origin", "http://localhost:3001"))
                .andExpect(status().isOk())
                .andExpect(header().doesNotExist("Access-Control-Allow-Origin"));
    }
}
