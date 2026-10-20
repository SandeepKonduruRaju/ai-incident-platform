package com.sandeep.incidentplatform;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.micrometer.metrics.test.autoconfigure.AutoConfigureMetrics;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalManagementPort;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;

import static com.sandeep.incidentplatform.TestJwt.asUser;
import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * The actuator lives on its own management port (as in production: 8081, reachable only inside the
 * Docker network) and exposes only health and prometheus. The public API port neither serves it nor
 * loses its JWT protection.
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT,
        properties = "management.server.port=0")
@AutoConfigureMetrics // Boot tests disable the Prometheus registry unless asked
@AutoConfigureMockMvc
class ObservabilityEndpointsTest {

    private final HttpClient http = HttpClient.newHttpClient();

    @LocalServerPort
    private int apiPort;

    @LocalManagementPort
    private int managementPort;

    @Autowired
    private MockMvc mockMvc;

    @Test
    void prometheusAndHealthAreServedOnTheManagementPort() throws Exception {
        HttpResponse<String> metrics = get(managementPort, "/actuator/prometheus");
        assertThat(metrics.statusCode()).isEqualTo(200);
        assertThat(metrics.body()).contains("outbox_backlog", "jvm_memory_used_bytes");

        assertThat(get(managementPort, "/actuator/health").statusCode()).isEqualTo(200);
    }

    @Test
    void theApiPortDoesNotServeActuatorAndStillRequiresAJwt() throws Exception {
        HttpResponse<String> metrics = get(apiPort, "/actuator/prometheus");
        assertThat(metrics.statusCode()).isNotEqualTo(200);
        assertThat(metrics.body()).doesNotContain("jvm_memory_used_bytes");

        assertThat(get(apiPort, "/api/v1/incidents").statusCode()).isEqualTo(401);
        // Not exposed: falls through to the API chain (JWT required), never served.
        assertThat(get(managementPort, "/actuator/env").statusCode()).isNotEqualTo(200);
    }

    @Test
    void creatingAnIncidentIncrementsTheCounterBySeverity() throws Exception {
        mockMvc.perform(post("/api/v1/incidents").with(asUser()).contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                { "title": "Disk full", "severity": "CRITICAL", "affectedService": "auth-service" }
                                """))
                .andExpect(status().isCreated());

        String metrics = get(managementPort, "/actuator/prometheus").body();
        assertThat(metrics).containsPattern("incidents_opened_total\\{[^}]*severity=\"CRITICAL\"[^}]*} [1-9]");
        // Low cardinality: no incident or tenant ids as labels.
        assertThat(metrics.lines().filter(line -> line.startsWith("incidents_opened_total")))
                .allSatisfy(line -> assertThat(line).doesNotContainPattern("[0-9a-f]{8}-[0-9a-f]{4}-").doesNotContain("tenant"));
    }

    private HttpResponse<String> get(int port, String path) throws IOException, InterruptedException {
        return http.send(HttpRequest.newBuilder(URI.create("http://localhost:" + port + path)).GET().build(),
                HttpResponse.BodyHandlers.ofString());
    }
}
