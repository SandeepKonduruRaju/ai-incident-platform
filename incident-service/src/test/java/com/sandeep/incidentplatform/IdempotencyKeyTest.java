package com.sandeep.incidentplatform;

import com.jayway.jsonpath.JsonPath;
import com.sandeep.incidentplatform.outbox.OutboxEventRepository;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.mock.web.MockHttpServletResponse;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.request.MockHttpServletRequestBuilder;

import java.util.List;
import java.util.UUID;
import java.util.concurrent.Callable;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;

import static com.sandeep.incidentplatform.TestJwt.asTenant;
import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * POST /api/v1/incidents with an Idempotency-Key, through the real stack (H2 with the Flyway migrations, the real
 * outbox; the relay is off in tests). Each test uses its own tenant.
 */
@SpringBootTest
@AutoConfigureMockMvc
class IdempotencyKeyTest {

    private static final String OTHER_JSON = """
            { "title": "Search is slow", "severity": "LOW", "affectedService": "search-service" }
            """;

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private OutboxEventRepository outbox;

    @Autowired
    private JdbcTemplate jdbc;

    @Test
    void sameKeyReturnsTheOriginalIncidentWith200AndCreatesNothingNew() throws Exception {
        String tenant = newTenant();
        String key = UUID.randomUUID().toString();

        String first = mockMvc.perform(create(tenant, key, RedisIntegrationTest.INCIDENT_JSON))
                .andExpect(status().isCreated())
                .andExpect(header().doesNotExist("Idempotent-Replayed"))
                .andReturn().getResponse().getContentAsString();
        UUID id = UUID.fromString(JsonPath.read(first, "$.id"));

        mockMvc.perform(create(tenant, key, RedisIntegrationTest.INCIDENT_JSON))
                .andExpect(status().isOk())
                .andExpect(header().string("Idempotent-Replayed", "true"))
                .andExpect(jsonPath("$.id").value(id.toString()))
                .andExpect(jsonPath("$.title").value("Payments failing"))
                .andExpect(jsonPath("$.createdAt").value((String) JsonPath.read(first, "$.createdAt")));

        assertThat(incidentsOf(tenant)).isEqualTo(1);
        assertThat(outboxRows(id)).isEqualTo(1); // one investigation request, not two
    }

    @Test
    void keysArePerTenant() throws Exception {
        String key = "shared-key-" + UUID.randomUUID();
        String a = newTenant();
        String b = newTenant();

        mockMvc.perform(create(a, key, RedisIntegrationTest.INCIDENT_JSON)).andExpect(status().isCreated());
        mockMvc.perform(create(b, key, RedisIntegrationTest.INCIDENT_JSON)).andExpect(status().isCreated());

        assertThat(incidentsOf(a)).isEqualTo(1);
        assertThat(incidentsOf(b)).isEqualTo(1);
    }

    @Test
    void sameKeyWithADifferentBodyIs422AndCreatesNothing() throws Exception {
        String tenant = newTenant();
        String key = UUID.randomUUID().toString();
        mockMvc.perform(create(tenant, key, RedisIntegrationTest.INCIDENT_JSON)).andExpect(status().isCreated());

        mockMvc.perform(create(tenant, key, OTHER_JSON))
                .andExpect(status().isUnprocessableContent())
                .andExpect(jsonPath("$.title").value("Idempotency-Key reused"));

        assertThat(incidentsOf(tenant)).isEqualTo(1);
    }

    @Test
    void withoutAKeyEveryRequestCreatesAnIncident() throws Exception {
        String tenant = newTenant();
        mockMvc.perform(create(tenant, null, RedisIntegrationTest.INCIDENT_JSON)).andExpect(status().isCreated());
        mockMvc.perform(create(tenant, null, RedisIntegrationTest.INCIDENT_JSON)).andExpect(status().isCreated());

        assertThat(incidentsOf(tenant)).isEqualTo(2);
    }

    @Test
    void invalidKeysAre400() throws Exception {
        String tenant = newTenant();
        for (String bad : List.of("x".repeat(256), "has space", "")) {
            mockMvc.perform(create(tenant, bad, RedisIntegrationTest.INCIDENT_JSON)).andExpect(status().isBadRequest());
        }
        assertThat(incidentsOf(tenant)).isZero();
    }

    @Test
    void twoConcurrentRequestsWithTheSameKeyCreateOneIncidentAndOneOutboxEvent() throws Exception {
        String tenant = newTenant();
        String key = UUID.randomUUID().toString();
        CountDownLatch start = new CountDownLatch(1);
        Callable<MockHttpServletResponse> call = () -> {
            start.await();
            return mockMvc.perform(create(tenant, key, RedisIntegrationTest.INCIDENT_JSON)).andReturn().getResponse();
        };
        ExecutorService pool = Executors.newFixedThreadPool(2);
        try {
            Future<MockHttpServletResponse> one = pool.submit(call);
            Future<MockHttpServletResponse> two = pool.submit(call);
            start.countDown();
            MockHttpServletResponse r1 = one.get();
            MockHttpServletResponse r2 = two.get();

            assertThat(List.of(r1.getStatus(), r2.getStatus())).containsExactlyInAnyOrder(201, 200);
            String id1 = JsonPath.read(r1.getContentAsString(), "$.id");
            String id2 = JsonPath.read(r2.getContentAsString(), "$.id");
            assertThat(id1).isEqualTo(id2);
            assertThat(incidentsOf(tenant)).isEqualTo(1);
            assertThat(outboxRows(UUID.fromString(id1))).isEqualTo(1);
        } finally {
            pool.shutdownNow();
        }
    }

    private static MockHttpServletRequestBuilder create(String tenant, String key, String json) {
        MockHttpServletRequestBuilder request = post("/api/v1/incidents").contentType(MediaType.APPLICATION_JSON)
                .content(json).with(asTenant(tenant));
        return key == null ? request : request.header("Idempotency-Key", key);
    }

    private int incidentsOf(String tenant) {
        return jdbc.queryForObject("SELECT count(*) FROM incidents WHERE tenant_id = ?", Integer.class, tenant);
    }

    private long outboxRows(UUID incidentId) {
        return outbox.findAll().stream().filter(e -> e.aggregateId().equals(incidentId)).count();
    }

    private static String newTenant() {
        return "tenant-" + UUID.randomUUID();
    }
}
