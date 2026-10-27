package com.sandeep.incidentplatform;

import com.jayway.jsonpath.JsonPath;
import com.sandeep.incidentplatform.investigation.InvestigationStatus;
import com.sandeep.incidentplatform.investigation.WorkerInvestigationClient;
import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.http.MediaType;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;

import java.util.Optional;
import java.util.UUID;

import static com.sandeep.incidentplatform.TestJwt.asTenant;
import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * Milestone 4, graceful degradation: cache and rate limit are ON but Redis is unreachable (nothing listens
 * on port 1). Reads still work (straight from the worker), incident creation and investigation retries are not
 * limited (fail open),
 * and every failure is counted in redis_errors_total. Needs no Docker.
 * failure-cooldown=0: Redis is retried on every request, so each one exercises the error path.
 */
@SpringBootTest(properties = {
        "spring.data.redis.host=127.0.0.1",
        "spring.data.redis.port=1",
        "app.redis.cache.enabled=true",
        "app.redis.rate-limit.enabled=true",
        "app.redis.rate-limit.create-incident-per-minute=1",
        "app.redis.failure-cooldown=0s"})
@AutoConfigureMockMvc
class RedisDownTest {

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private MeterRegistry meters;

    @MockitoBean
    private WorkerInvestigationClient worker;

    @Test
    void withRedisDownReadsComeFromTheWorkerAndIncidentCreationFailsOpen() throws Exception {
        String tenant = "tenant-" + UUID.randomUUID();

        // Limit is 1/min, but Redis cannot count: all three creations are allowed (fail open).
        UUID id = null;
        for (int i = 0; i < 3; i++) {
            String body = mockMvc.perform(post("/api/v1/incidents").contentType(MediaType.APPLICATION_JSON)
                            .content(RedisIntegrationTest.INCIDENT_JSON).with(asTenant(tenant)))
                    .andExpect(status().isCreated())
                    .andReturn().getResponse().getContentAsString();
            id = UUID.fromString(JsonPath.read(body, "$.id"));
        }
        when(worker.fetch(tenant, id))
                .thenReturn(Optional.of(RedisIntegrationTest.investigation(id, InvestigationStatus.COMPLETED)));

        for (int i = 0; i < 2; i++) {
            mockMvc.perform(get("/api/v1/incidents/{id}/investigation", id).with(asTenant(tenant)))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.status").value("COMPLETED"));
        }

        verify(worker, times(2)).fetch(tenant, id); // no cache: every read went to the worker

        // Retry has its own limit (also 1/min here): it fails open too, so both reach the controller, which
        // refuses them because the investigation is COMPLETED (409), never 429.
        for (int i = 0; i < 2; i++) {
            mockMvc.perform(post("/api/v1/incidents/{id}/investigation/retry", id).with(asTenant(tenant)))
                    .andExpect(status().isConflict());
        }
        assertThat(count("rate_limit")).isGreaterThanOrEqualTo(5);
        assertThat(count("cache_get")).isGreaterThanOrEqualTo(2);
        assertThat(count("cache_put")).isGreaterThanOrEqualTo(2);
    }

    private double count(String operation) {
        Counter counter = meters.find("redis.errors").tag("operation", operation).counter();
        return counter == null ? 0 : counter.count();
    }
}
