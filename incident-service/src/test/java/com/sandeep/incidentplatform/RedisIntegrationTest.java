package com.sandeep.incidentplatform;

import com.jayway.jsonpath.JsonPath;
import com.sandeep.incidentplatform.investigation.InvestigationStatus;
import com.sandeep.incidentplatform.investigation.WorkerInvestigation;
import com.sandeep.incidentplatform.investigation.WorkerInvestigationClient;
import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.testcontainers.service.connection.ServiceConnection;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.http.MediaType;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;
import org.testcontainers.containers.GenericContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

import static com.sandeep.incidentplatform.TestJwt.asTenant;
import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * Milestone 4: investigation cache and per-tenant rate limit against a real Redis in Docker (skipped, not
 * failed, without Docker). Database: the H2 test default. The worker client is a mock, so a test can count
 * how often the worker was really asked. Each test uses its own tenant(s): Redis state never leaks between tests.
 */
@SpringBootTest(properties = {
        "app.redis.cache.enabled=true",
        "app.redis.rate-limit.enabled=true",
        "app.redis.rate-limit.create-incident-per-minute=3"})
@AutoConfigureMockMvc
@Testcontainers(disabledWithoutDocker = true)
class RedisIntegrationTest {

    @Container
    @ServiceConnection
    static GenericContainer<?> redis = new GenericContainer<>("redis:8.8.3-alpine").withExposedPorts(6379);

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private StringRedisTemplate redisTemplate;

    @Autowired
    private MeterRegistry meters;

    @MockitoBean
    private WorkerInvestigationClient worker;

    @Test
    void finishedInvestigationIsServedFromRedisWithoutCallingTheWorkerAgain() throws Exception {
        String tenant = newTenant();
        UUID id = createIncident(tenant);
        when(worker.fetch(tenant, id)).thenReturn(Optional.of(investigation(id, InvestigationStatus.COMPLETED)));
        double hits = count("cache.hits", "cache", "investigation");
        double misses = count("cache.misses", "cache", "investigation");

        for (int i = 0; i < 3; i++) {
            mockMvc.perform(get("/api/v1/incidents/{id}/investigation", id).with(asTenant(tenant)))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.status").value("COMPLETED"))
                    .andExpect(jsonPath("$.summary").value("Pool exhaustion [C1]."))
                    .andExpect(jsonPath("$.rootCause.citations[0]").value("C1"));
        }

        verify(worker, times(1)).fetch(tenant, id); // first read only; the other two were cache hits
        assertThat(count("cache.misses", "cache", "investigation")).isEqualTo(misses + 1);
        assertThat(count("cache.hits", "cache", "investigation")).isEqualTo(hits + 2);
        Long ttl = redisTemplate.getExpire("investigation:v1:" + tenant + ":" + id);
        assertThat(ttl).isBetween(3500L, 3600L); // ~1 h
    }

    @Test
    void pendingAndRunningInvestigationsAreNeverCached() throws Exception {
        String tenant = newTenant();
        UUID id = createIncident(tenant);
        when(worker.fetch(tenant, id))
                .thenReturn(Optional.empty()) // not consumed yet: PENDING
                .thenReturn(Optional.of(investigation(id, InvestigationStatus.RUNNING)))
                .thenReturn(Optional.of(investigation(id, InvestigationStatus.COMPLETED)));

        mockMvc.perform(get("/api/v1/incidents/{id}/investigation", id).with(asTenant(tenant)))
                .andExpect(jsonPath("$.status").value("PENDING"));
        assertThat(redisTemplate.hasKey("investigation:v1:" + tenant + ":" + id)).isFalse();
        mockMvc.perform(get("/api/v1/incidents/{id}/investigation", id).with(asTenant(tenant)))
                .andExpect(jsonPath("$.status").value("RUNNING"));
        assertThat(redisTemplate.hasKey("investigation:v1:" + tenant + ":" + id)).isFalse();
        // The client polls again and sees the fresh result, not a cached RUNNING.
        mockMvc.perform(get("/api/v1/incidents/{id}/investigation", id).with(asTenant(tenant)))
                .andExpect(jsonPath("$.status").value("COMPLETED"));

        verify(worker, times(3)).fetch(tenant, id);
        assertThat(redisTemplate.hasKey("investigation:v1:" + tenant + ":" + id)).isTrue();
    }

    @Test
    void cachedInvestigationOfOneTenantIsNeverServedToAnother() throws Exception {
        String owner = newTenant();
        String other = newTenant();
        UUID id = createIncident(owner);
        when(worker.fetch(owner, id)).thenReturn(Optional.of(investigation(id, InvestigationStatus.COMPLETED)));
        mockMvc.perform(get("/api/v1/incidents/{id}/investigation", id).with(asTenant(owner)))
                .andExpect(status().isOk());
        assertThat(redisTemplate.hasKey("investigation:v1:" + owner + ":" + id)).isTrue();

        // Another tenant with the same incident id: 404 from the database tenant check, before the cache.
        mockMvc.perform(get("/api/v1/incidents/{id}/investigation", id).with(asTenant(other)))
                .andExpect(status().isNotFound());
        // The key is per tenant: nothing was (or could be) stored or read under the other tenant.
        assertThat(redisTemplate.hasKey("investigation:v1:" + other + ":" + id)).isFalse();
        verify(worker, never()).fetch(eq(other), any());
    }

    @Test
    void creatingMoreIncidentsThanTheLimitReturns429WithRetryAfterForThatTenantOnly() throws Exception {
        String noisy = newTenant();
        double limited = count("rate.limited", "endpoint", "create_incident");
        for (int i = 0; i < 3; i++) {
            createIncident(noisy);
        }

        mockMvc.perform(post("/api/v1/incidents").contentType(MediaType.APPLICATION_JSON).content(INCIDENT_JSON)
                        .with(asTenant(noisy)))
                .andExpect(status().isTooManyRequests())
                .andExpect(header().exists("Retry-After"))
                .andExpect(jsonPath("$.title").value("Too many requests"))
                .andExpect(jsonPath("$.status").value(429))
                .andExpect(jsonPath("$.limitPerMinute").value(3));

        String retryAfter = mockMvc.perform(post("/api/v1/incidents").contentType(MediaType.APPLICATION_JSON)
                        .content(INCIDENT_JSON).with(asTenant(noisy)))
                .andReturn().getResponse().getHeader("Retry-After");
        assertThat(Long.parseLong(retryAfter)).isBetween(1L, 60L);
        assertThat(count("rate.limited", "endpoint", "create_incident")).isEqualTo(limited + 2);
        // Reads are not limited, and another tenant still has its own full budget.
        mockMvc.perform(get("/api/v1/incidents").with(asTenant(noisy))).andExpect(status().isOk());
        createIncident(newTenant());
    }

    @Test
    void retryingTooOftenReturns429WithRetryAfterAndLeavesIncidentCreationItsOwnBudget() throws Exception {
        String tenant = newTenant();
        UUID id = createIncident(tenant); // 1 of 3 creations used
        double limited = count("rate.limited", "endpoint", "retry_investigation");

        // The request is fresh (PENDING), so the controller refuses these retries with 409; they still count.
        for (int i = 0; i < 3; i++) {
            mockMvc.perform(post("/api/v1/incidents/{id}/investigation/retry", id).with(asTenant(tenant)))
                    .andExpect(status().isConflict());
        }
        String retryAfter = mockMvc.perform(post("/api/v1/incidents/{id}/investigation/retry", id)
                        .with(asTenant(tenant)))
                .andExpect(status().isTooManyRequests())
                .andExpect(header().exists("Retry-After"))
                .andExpect(jsonPath("$.title").value("Too many requests"))
                .andExpect(jsonPath("$.limitPerMinute").value(3))
                .andReturn().getResponse().getHeader("Retry-After");
        assertThat(Long.parseLong(retryAfter)).isBetween(1L, 60L);
        assertThat(count("rate.limited", "endpoint", "retry_investigation")).isEqualTo(limited + 1);

        // Separate budgets: the tenant can still report incidents, and other tenants can still retry.
        createIncident(tenant);
        String other = newTenant();
        UUID otherId = createIncident(other);
        mockMvc.perform(post("/api/v1/incidents/{id}/investigation/retry", otherId).with(asTenant(other)))
                .andExpect(status().isConflict());
    }

    static final String INCIDENT_JSON = """
            { "title": "Payments failing", "severity": "HIGH", "affectedService": "payment-service" }
            """;

    private UUID createIncident(String tenant) throws Exception {
        String body = mockMvc.perform(post("/api/v1/incidents").contentType(MediaType.APPLICATION_JSON)
                        .content(INCIDENT_JSON).with(asTenant(tenant)))
                .andExpect(status().isCreated())
                .andReturn().getResponse().getContentAsString();
        return UUID.fromString(JsonPath.read(body, "$.id"));
    }

    private static String newTenant() {
        return "tenant-" + UUID.randomUUID();
    }

    static WorkerInvestigation investigation(UUID id, InvestigationStatus status) {
        WorkerInvestigation.Result result = status == InvestigationStatus.COMPLETED
                ? new WorkerInvestigation.Result(
                        new com.sandeep.incidentplatform.dto.Finding("Connection pool exhausted [C1]", List.of("C1")),
                        List.of(), List.of(), "medium", "Pool exhaustion [C1].")
                : null;
        Instant now = Instant.now();
        return new WorkerInvestigation(id, status, result, List.of(), "fake", "v1", 1, now, now,
                status == InvestigationStatus.COMPLETED ? now : null, null);
    }

    private double count(String name, String tagKey, String tagValue) {
        Counter counter = meters.find(name).tag(tagKey, tagValue).counter();
        return counter == null ? 0 : counter.count();
    }
}
