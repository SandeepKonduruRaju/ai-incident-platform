package com.sandeep.incidentplatform;

import com.jayway.jsonpath.JsonPath;
import com.sandeep.incidentplatform.investigation.InvestigationStatus;
import com.sandeep.incidentplatform.investigation.WorkerInvestigation;
import com.sandeep.incidentplatform.investigation.WorkerInvestigationClient;
import com.sandeep.incidentplatform.outbox.OutboxEvent;
import com.sandeep.incidentplatform.outbox.OutboxEventRepository;
import com.sandeep.incidentplatform.security.Role;
import com.sandeep.incidentplatform.service.IncidentService;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;

import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

import static com.sandeep.incidentplatform.TestJwt.as;
import static com.sandeep.incidentplatform.TestJwt.asTenant;
import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * NOT_STARTED and POST /api/v1/incidents/{id}/investigation/retry through the real stack (H2, the real outbox), with
 * the worker client mocked. Each test uses its own tenant. The outbox relay is off in tests, so new events stay unsent.
 */
@SpringBootTest(properties = "investigation.not-started-after=10m")
@AutoConfigureMockMvc
class InvestigationRetryTest {

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private OutboxEventRepository outbox;

    @Autowired
    private JdbcTemplate jdbc;

    @Autowired
    private IncidentService incidents;

    @MockitoBean
    private WorkerInvestigationClient worker;

    @Test
    void incidentWithoutAnyInvestigationRequestIsNotStartedWithoutRetryAfter() throws Exception {
        String tenant = newTenant();
        UUID id = createIncident(tenant);
        jdbc.update("DELETE FROM outbox_events WHERE aggregate_id = ?", id); // like an incident created before the outbox
        when(worker.fetch(tenant, id)).thenReturn(Optional.empty());

        mockMvc.perform(get("/api/v1/incidents/{id}/investigation", id).with(asTenant(tenant)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("NOT_STARTED"))
                .andExpect(header().doesNotExist("Retry-After")); // not in progress: the client stops polling
    }

    @Test
    void requestStillComingIsPendingAndOneSentLongAgoWithoutARunIsNotStarted() throws Exception {
        String tenant = newTenant();
        UUID id = createIncident(tenant);
        when(worker.fetch(tenant, id)).thenReturn(Optional.empty());

        // Fresh (unsent) request: PENDING, poll again.
        mockMvc.perform(get("/api/v1/incidents/{id}/investigation", id).with(asTenant(tenant)))
                .andExpect(jsonPath("$.status").value("PENDING"))
                .andExpect(header().string("Retry-After", "2"));

        // Sent an hour ago and the worker still has nothing: lost, NOT_STARTED.
        jdbc.update("UPDATE outbox_events SET published_at = ?, created_at = ? WHERE aggregate_id = ?",
                java.sql.Timestamp.from(Instant.now().minus(1, ChronoUnit.HOURS)),
                java.sql.Timestamp.from(Instant.now().minus(1, ChronoUnit.HOURS)), id);
        mockMvc.perform(get("/api/v1/incidents/{id}/investigation", id).with(asTenant(tenant)))
                .andExpect(jsonPath("$.status").value("NOT_STARTED"));
    }

    @Test
    void retryOfANotStartedInvestigationEnqueuesANewEventThroughTheOutbox() throws Exception {
        String tenant = newTenant();
        UUID id = createIncident(tenant);
        jdbc.update("DELETE FROM outbox_events WHERE aggregate_id = ?", id);
        when(worker.fetch(tenant, id)).thenReturn(Optional.empty());

        mockMvc.perform(post("/api/v1/incidents/{id}/investigation/retry", id).with(asTenant(tenant)))
                .andExpect(status().isAccepted())
                .andExpect(header().string("Retry-After", "2"))
                .andExpect(jsonPath("$.status").value("PENDING"));

        assertThat(outboxRows(id)).isEqualTo(1);
        String payload = jdbc.queryForObject("SELECT payload FROM outbox_events WHERE aggregate_id = ?", String.class, id);
        assertThat((String) JsonPath.read(payload, "$.payload.incidentId")).isEqualTo(id.toString());
        assertThat((String) JsonPath.read(payload, "$.tenantId")).isEqualTo(tenant);
        // Now on its way: PENDING, and a second retry is refused.
        mockMvc.perform(get("/api/v1/incidents/{id}/investigation", id).with(asTenant(tenant)))
                .andExpect(jsonPath("$.status").value("PENDING"));
        mockMvc.perform(post("/api/v1/incidents/{id}/investigation/retry", id).with(asTenant(tenant)))
                .andExpect(status().isConflict());
        assertThat(outboxRows(id)).isEqualTo(1);
    }

    @Test
    void retryOfAFailedInvestigationIsPendingUntilTheWorkerPicksTheNewRequestUp() throws Exception {
        String tenant = newTenant();
        UUID id = createIncident(tenant);
        // The run was created after the original request (as the worker does), before the retry.
        WorkerInvestigation failed = run(id, InvestigationStatus.FAILED, Instant.now());
        when(worker.fetch(tenant, id)).thenReturn(Optional.of(failed));
        mockMvc.perform(get("/api/v1/incidents/{id}/investigation", id).with(asTenant(tenant)))
                .andExpect(jsonPath("$.status").value("FAILED"));

        mockMvc.perform(post("/api/v1/incidents/{id}/investigation/retry", id).with(asTenant(tenant)))
                .andExpect(status().isAccepted());

        assertThat(outboxRows(id)).isEqualTo(2); // the original request + the retry
        // The worker still returns the old FAILED run, but a newer request exists: PENDING, not the stale FAILED.
        mockMvc.perform(get("/api/v1/incidents/{id}/investigation", id).with(asTenant(tenant)))
                .andExpect(jsonPath("$.status").value("PENDING"));
    }

    @Test
    void retryIsRefusedWith409WhileRunningOrOnceCompleted() throws Exception {
        for (InvestigationStatus status : List.of(InvestigationStatus.RUNNING, InvestigationStatus.COMPLETED)) {
            String tenant = newTenant();
            UUID id = createIncident(tenant);
            when(worker.fetch(tenant, id)).thenReturn(Optional.of(run(id, status, Instant.now())));

            mockMvc.perform(post("/api/v1/incidents/{id}/investigation/retry", id).with(asTenant(tenant)))
                    .andExpect(status().isConflict())
                    .andExpect(header().string("Content-Type", MediaType.APPLICATION_PROBLEM_JSON_VALUE))
                    .andExpect(jsonPath("$.title").value("Investigation cannot be retried"))
                    .andExpect(jsonPath("$.status").value(409))
                    .andExpect(jsonPath("$.detail").value(org.hamcrest.Matchers.containsString(status.name())));
            assertThat(outboxRows(id)).isEqualTo(1); // nothing new enqueued
        }
    }

    @Test
    void anotherTenantGets404AndCannotTriggerAnything() throws Exception {
        String owner = newTenant();
        UUID id = createIncident(owner);
        jdbc.update("DELETE FROM outbox_events WHERE aggregate_id = ?", id);

        mockMvc.perform(post("/api/v1/incidents/{id}/investigation/retry", id).with(asTenant(newTenant())))
                .andExpect(status().isNotFound());

        assertThat(outboxRows(id)).isZero();
        verify(worker, never()).fetch(any(), eq(id));
    }

    @Test
    void onlyIncidentCreatedEventsCountAsInvestigationRequests() throws Exception {
        String tenant = newTenant();
        UUID id = createIncident(tenant);
        UUID original = incidents.latestInvestigationRequest(id).orElseThrow().eventId();

        // A newer event of another type for the same incident (none exists in the product yet) is not a request.
        outbox.save(new OutboxEvent(UUID.randomUUID(), id, "IncidentStatusChanged", "incident-events", "{}",
                Instant.now().plusSeconds(60)));

        assertThat(incidents.latestInvestigationRequest(id).orElseThrow().eventId()).isEqualTo(original);
    }

    @Test
    void viewersCannotRetry() throws Exception {
        String tenant = newTenant();
        UUID id = createIncident(tenant);

        mockMvc.perform(post("/api/v1/incidents/{id}/investigation/retry", id).with(as(tenant, Role.VIEWER)))
                .andExpect(status().isForbidden());
    }

    private UUID createIncident(String tenant) throws Exception {
        String body = mockMvc.perform(post("/api/v1/incidents").contentType(MediaType.APPLICATION_JSON)
                        .content(RedisIntegrationTest.INCIDENT_JSON).with(asTenant(tenant)))
                .andExpect(status().isCreated())
                .andReturn().getResponse().getContentAsString();
        return UUID.fromString(JsonPath.read(body, "$.id"));
    }

    private long outboxRows(UUID incidentId) {
        return outbox.findAll().stream().filter(e -> e.aggregateId().equals(incidentId)).count();
    }

    private static WorkerInvestigation run(UUID id, InvestigationStatus status, Instant createdAt) {
        return new WorkerInvestigation(id, status, null, List.of(), "fake", "v1", 1, createdAt, createdAt,
                status == InvestigationStatus.RUNNING ? null : createdAt,
                status == InvestigationStatus.FAILED ? "timeout" : null);
    }

    private static String newTenant() {
        return "tenant-" + UUID.randomUUID();
    }
}
