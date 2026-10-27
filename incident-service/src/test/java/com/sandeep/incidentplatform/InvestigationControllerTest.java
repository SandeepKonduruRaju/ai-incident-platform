package com.sandeep.incidentplatform;

import com.sandeep.incidentplatform.observability.PlatformMetrics;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import com.sandeep.incidentplatform.controller.InvestigationController;
import com.sandeep.incidentplatform.investigation.WorkerInvestigationClient;
import com.sandeep.incidentplatform.investigation.WorkerProperties;
import com.sandeep.incidentplatform.model.Incident;
import com.sandeep.incidentplatform.model.IncidentSeverity;
import com.sandeep.incidentplatform.model.IncidentStatus;
import com.sandeep.incidentplatform.security.Role;
import com.sandeep.incidentplatform.security.SecurityConfig;
import com.sandeep.incidentplatform.service.IncidentService;
import com.sandeep.incidentplatform.service.InvestigationService;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.boot.test.system.CapturedOutput;
import org.springframework.boot.test.system.OutputCaptureExtension;
import org.springframework.boot.webmvc.test.autoconfigure.WebMvcTest;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.web.client.RestClient;

import java.net.SocketTimeoutException;
import java.net.URI;
import java.time.Instant;
import java.util.Optional;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static com.sandeep.incidentplatform.TestJwt.TENANT;
import static com.sandeep.incidentplatform.TestJwt.as;
import static com.sandeep.incidentplatform.TestJwt.asUser;
import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.header;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.method;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.queryParam;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withException;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withStatus;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

// GET /api/v1/incidents/{id}/investigation through real Spring MVC + Security, with the incident
// lookup mocked and the worker's HTTP API replaced by MockRestServiceServer (no network).
@WebMvcTest(InvestigationController.class)
@Import({SecurityConfig.class, InvestigationService.class, InvestigationControllerTest.WorkerMock.class})
@ExtendWith(OutputCaptureExtension.class)
class InvestigationControllerTest {

    static final String WORKER_TOKEN = "test-only-internal-token";
    static final String WORKER_URL = "http://investigation-worker.test/internal/v1/investigations";

    @TestConfiguration
    static class WorkerMock {
        private final RestClient.Builder builder = RestClient.builder();
        private final MockRestServiceServer server = MockRestServiceServer.bindTo(builder).build();

        @Bean
        MockRestServiceServer workerServer() {
            return server;
        }

        @Bean
        SimpleMeterRegistry meterRegistry() {
            return new SimpleMeterRegistry();
        }

        @Bean
        PlatformMetrics platformMetrics(SimpleMeterRegistry registry) {
            return new PlatformMetrics(registry);
        }

        @Bean
        WorkerInvestigationClient workerInvestigationClient(PlatformMetrics metrics) {
            WorkerProperties properties = new WorkerProperties(
                    URI.create("http://investigation-worker.test"), WORKER_TOKEN, null, null);
            return new WorkerInvestigationClient(builder, properties, metrics);
        }
    }

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private MockRestServiceServer worker;

    @Autowired
    private SimpleMeterRegistry meters;

    @MockitoBean
    private IncidentService incidentService;

    @AfterEach
    void verifyAndReset() {
        worker.verify(); // every expected worker call happened, and no unexpected one
        worker.reset();
    }

    @Test
    void completedInvestigationIsMappedWithCitations() throws Exception {
        double readsBefore = count("investigation.reads", "status", "COMPLETED");
        UUID id = existingIncident();
        worker.expect(requestTo(workerUrl(id)))
                .andExpect(method(org.springframework.http.HttpMethod.GET))
                .andExpect(queryParam("tenantId", TENANT)) // from the JWT, never from the client
                .andExpect(header("X-Internal-Token", WORKER_TOKEN))
                .andExpect(header("X-Request-Id", "req-abc"))
                .andRespond(withSuccess(completedJson(id), MediaType.APPLICATION_JSON));

        mockMvc.perform(get("/api/v1/incidents/{id}/investigation", id).with(asUser()).header("X-Request-Id", "req-abc"))
                .andExpect(status().isOk())
                .andExpect(header().doesNotExist("Retry-After"))
                .andExpect(jsonPath("$.incidentId").value(id.toString()))
                .andExpect(jsonPath("$.status").value("COMPLETED"))
                .andExpect(jsonPath("$.summary").value("Pool exhaustion [C1]."))
                .andExpect(jsonPath("$.confidence").value("medium"))
                .andExpect(jsonPath("$.rootCause.text").value("Connection pool exhausted [C1]"))
                .andExpect(jsonPath("$.rootCause.citations[0]").value("C1"))
                .andExpect(jsonPath("$.remediation[0].citations[0]").value("C2"))
                .andExpect(jsonPath("$.contributingFactors.length()").value(0))
                .andExpect(jsonPath("$.citations[0].label").value("C1"))
                .andExpect(jsonPath("$.citations[0].sourceType").value("log"))
                .andExpect(jsonPath("$.citations[0].sourceId").value("LOG-acme-db_pool_exhausted-payment-service"))
                .andExpect(jsonPath("$.citations[0].snippet").value("Logs from payment-service: HikariPool timeout"))
                .andExpect(jsonPath("$.model").value("claude-haiku-5-5"))
                .andExpect(jsonPath("$.promptVersion").value("v1"))
                .andExpect(jsonPath("$.completedAt").value("2026-10-19T15:49:46.428Z"))
                .andExpect(jsonPath("$.failureReason").doesNotExist()); // null fields are omitted
        assertEquals(readsBefore + 1, count("investigation.reads", "status", "COMPLETED"));
    }

    private double count(String name, String tag, String value) {
        var counter = meters.find(name).tag(tag, value).counter();
        return counter == null ? 0 : counter.count();
    }

    @Test
    void workerHasNoInvestigationYetMeansPending() throws Exception {
        UUID id = existingIncident();
        worker.expect(requestTo(workerUrl(id))).andRespond(withStatus(HttpStatus.NOT_FOUND));

        mockMvc.perform(get("/api/v1/incidents/{id}/investigation", id).with(asUser()))
                .andExpect(status().isOk())
                .andExpect(header().string("Retry-After", "2"))
                .andExpect(jsonPath("$.status").value("PENDING"))
                .andExpect(jsonPath("$.incidentId").value(id.toString()))
                .andExpect(jsonPath("$.summary").doesNotExist())
                .andExpect(jsonPath("$.citations").doesNotExist());
    }

    @Test
    void runningInvestigationAsksTheClientToPollAgain() throws Exception {
        UUID id = existingIncident();
        worker.expect(requestTo(workerUrl(id))).andRespond(withSuccess("""
                {"incidentId": "%s", "status": "RUNNING", "result": null, "citations": [], "attempts": 0,
                 "createdAt": "2026-10-19T15:49:42.180Z", "startedAt": "2026-10-19T15:49:42.190Z"}
                """.formatted(id), MediaType.APPLICATION_JSON));

        mockMvc.perform(get("/api/v1/incidents/{id}/investigation", id).with(asUser()))
                .andExpect(status().isOk())
                .andExpect(header().string("Retry-After", "2"))
                .andExpect(jsonPath("$.status").value("RUNNING"))
                .andExpect(jsonPath("$.rootCause").doesNotExist());
    }

    @Test
    void failedInvestigationReturnsTheReason() throws Exception {
        UUID id = existingIncident();
        worker.expect(requestTo(workerUrl(id))).andRespond(withSuccess("""
                {"incidentId": "%s", "status": "FAILED", "result": null, "citations": [], "attempts": 2,
                 "model": "claude-haiku-5-5", "promptVersion": "v1",
                 "createdAt": "2026-10-19T15:49:42.180Z", "completedAt": "2026-10-19T15:49:50.000Z",
                 "failureReason": "invalid LLM output after 2 attempts"}
                """.formatted(id), MediaType.APPLICATION_JSON));

        mockMvc.perform(get("/api/v1/incidents/{id}/investigation", id).with(asUser()))
                .andExpect(status().isOk())
                .andExpect(header().doesNotExist("Retry-After"))
                .andExpect(jsonPath("$.status").value("FAILED"))
                .andExpect(jsonPath("$.failureReason").value("invalid LLM output after 2 attempts"))
                .andExpect(jsonPath("$.rootCause").doesNotExist())
                .andExpect(jsonPath("$.citations").doesNotExist());
    }

    @Test
    void workerTimeoutIs503WithRetryAfterAndNoStackTrace() throws Exception {
        double timeoutsBefore = count("worker.client.errors", "kind", "timeout");
        UUID id = existingIncident();
        worker.expect(requestTo(workerUrl(id))).andRespond(withException(new SocketTimeoutException("Read timed out")));

        mockMvc.perform(get("/api/v1/incidents/{id}/investigation", id).with(asUser()))
                .andExpect(status().isServiceUnavailable())
                .andExpect(header().string("Retry-After", "5"))
                .andExpect(header().string("Content-Type", "application/problem+json"))
                .andExpect(jsonPath("$.title").value("Investigation unavailable"))
                .andExpect(jsonPath("$.requestId").exists())
                .andExpect(jsonPath("$.trace").doesNotExist())
                .andExpect(jsonPath("$.detail").value("The investigation service is temporarily unavailable. Try again shortly."));
        assertEquals(timeoutsBefore + 1, count("worker.client.errors", "kind", "timeout"));
    }

    @Test
    void workerRejectingOurTokenIs503AndLoggedAsMisconfiguration(CapturedOutput output) throws Exception {
        UUID id = existingIncident();
        worker.expect(requestTo(workerUrl(id))).andRespond(withStatus(HttpStatus.UNAUTHORIZED));

        mockMvc.perform(get("/api/v1/incidents/{id}/investigation", id).with(asUser()))
                .andExpect(status().isServiceUnavailable())
                .andExpect(header().string("Retry-After", "5"));

        assertThat(output).contains("ERROR").contains("misconfiguration").contains("INTERNAL_API_TOKEN");
        assertThat(output).doesNotContain(WORKER_TOKEN); // the secret itself is never logged
    }

    @Test
    void workerServerErrorIs503() throws Exception {
        UUID id = existingIncident();
        worker.expect(requestTo(workerUrl(id))).andRespond(withStatus(HttpStatus.INTERNAL_SERVER_ERROR));

        mockMvc.perform(get("/api/v1/incidents/{id}/investigation", id).with(asUser()))
                .andExpect(status().isServiceUnavailable());
    }

    @Test
    void incidentOfAnotherTenantIs404AndTheWorkerIsNeverCalled() throws Exception {
        UUID otherTenantsIncident = UUID.randomUUID();
        when(incidentService.findById(TENANT, otherTenantsIncident)).thenReturn(Optional.empty());

        mockMvc.perform(get("/api/v1/incidents/{id}/investigation", otherTenantsIncident).with(asUser()))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.title").value("Incident not found"));
        // verify() in @AfterEach fails if the worker was called
    }

    @Test
    void noJwtIs401() throws Exception {
        mockMvc.perform(get("/api/v1/incidents/{id}/investigation", UUID.randomUUID()))
                .andExpect(status().isUnauthorized());
    }

    @Test
    void viewerCanReadTheInvestigation() throws Exception {
        UUID id = existingIncident();
        worker.expect(requestTo(workerUrl(id))).andRespond(withStatus(HttpStatus.NOT_FOUND));

        mockMvc.perform(get("/api/v1/incidents/{id}/investigation", id).with(as(TENANT, Role.VIEWER)))
                .andExpect(status().isOk());
    }

    private UUID existingIncident() {
        Incident incident = new Incident(UUID.randomUUID(), TENANT, "payment-service timing out", "Requests hang",
                IncidentSeverity.HIGH, IncidentStatus.OPEN, "payment-service", Instant.now());
        when(incidentService.findById(TENANT, incident.id())).thenReturn(Optional.of(incident));
        // Its investigation request: older than the worker runs in these tests, and not sent yet (so "no run" = PENDING).
        when(incidentService.latestInvestigationRequest(incident.id())).thenReturn(Optional.of(
                new IncidentService.InvestigationRequest(UUID.randomUUID(), Instant.parse("2026-10-19T15:49:00Z"), false)));
        return incident.id();
    }

    private static String workerUrl(UUID incidentId) {
        return WORKER_URL + "?tenantId=" + TENANT + "&incidentId=" + incidentId;
    }

    private static String completedJson(UUID id) {
        return """
                {
                  "incidentId": "%s",
                  "status": "COMPLETED",
                  "result": {
                    "root_cause": {"text": "Connection pool exhausted [C1]", "citations": ["C1"]},
                    "contributing_factors": [],
                    "remediation": [{"text": "Kill idle sessions [C2]", "citations": ["C2"]}],
                    "confidence": "medium",
                    "summary": "Pool exhaustion [C1]."
                  },
                  "citations": [
                    {"label": "C1", "sourceType": "log", "sourceId": "LOG-acme-db_pool_exhausted-payment-service",
                     "snippet": "Logs from payment-service: HikariPool timeout"},
                    {"label": "C2", "sourceType": "runbook", "sourceId": "RB-acme-db_pool_exhausted",
                     "snippet": "Database connection pool exhausted — Mitigation"}
                  ],
                  "model": "claude-haiku-5-5",
                  "promptVersion": "v1",
                  "attempts": 1,
                  "createdAt": "2026-10-19T15:49:42.180Z",
                  "startedAt": "2026-10-19T15:49:42.190Z",
                  "completedAt": "2026-10-19T15:49:46.428Z",
                  "failureReason": null,
                  "someFutureField": "ignored by the tolerant reader"
                }
                """.formatted(id);
    }
}
