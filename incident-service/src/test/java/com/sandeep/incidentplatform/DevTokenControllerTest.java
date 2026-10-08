package com.sandeep.incidentplatform;

import com.jayway.jsonpath.JsonPath;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.web.servlet.MockMvc;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

// With the "dev" profile, the issued token must be accepted by the real JwtDecoder.
@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("dev")
class DevTokenControllerTest {

    @Autowired
    private MockMvc mockMvc;

    @Test
    void shouldIssueTokenThatTheApiAccepts() throws Exception {
        String body = mockMvc.perform(post("/api/v1/dev/token")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{ \"subject\": \"alice\", \"tenantId\": \"acme\" }"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.tokenType").value("Bearer"))
                .andExpect(jsonPath("$.expiresIn").value(3600))
                .andReturn().getResponse().getContentAsString();
        String token = JsonPath.read(body, "$.accessToken");

        mockMvc.perform(get("/api/v1/incidents").header(HttpHeaders.AUTHORIZATION, "Bearer " + token))
                .andExpect(status().isOk());
    }
}
