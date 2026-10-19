package com.sandeep.incidentplatform;

import com.jayway.jsonpath.JsonPath;
import com.sandeep.incidentplatform.model.Incident;
import com.sandeep.incidentplatform.model.IncidentSeverity;
import com.sandeep.incidentplatform.model.IncidentStatus;
import com.sandeep.incidentplatform.outbox.OutboxEvent;
import com.sandeep.incidentplatform.outbox.OutboxEventRepository;
import com.sandeep.incidentplatform.repository.IncidentRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.testcontainers.service.connection.ServiceConnection;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.http.MediaType;
import org.springframework.orm.ObjectOptimisticLockingFailureException;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;
import org.testcontainers.postgresql.PostgreSQLContainer;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static com.sandeep.incidentplatform.TestJwt.asTenant;
import static com.sandeep.incidentplatform.TestJwt.asUser;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.patch;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * Full stack against a real PostgreSQL started in Docker: HTTP → controller → service →
 * JPA → PostgreSQL, with the real Flyway migrations. Skipped (not failed) when Docker is not running.
 */
@SpringBootTest
@AutoConfigureMockMvc
@Testcontainers(disabledWithoutDocker = true)
class IncidentApiIntegrationTest {

    // @ServiceConnection points the app's DataSource at this container (overrides the H2 test config).
    @Container
    @ServiceConnection
    static PostgreSQLContainer postgres = new PostgreSQLContainer("postgres:18-alpine");

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private IncidentRepository incidentRepository;

    @Autowired
    private OutboxEventRepository outboxEventRepository;

    @Autowired
    private PlatformTransactionManager transactionManager;

    @BeforeEach
    void cleanDatabase() {
        outboxEventRepository.deleteAll();
        incidentRepository.deleteAll();
    }

    @Test
    void shouldCreateReadAndUpdateIncidentInPostgres() throws Exception {
        // Create
        MvcResult created = mockMvc.perform(post("/api/v1/incidents")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "title": "Payments failing",
                                  "description": "Customers cannot complete checkout",
                                  "severity": "HIGH",
                                  "affectedService": "payment-service"
                                }
                                """).with(asUser()))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.status").value("OPEN"))
                .andReturn();
        String id = JsonPath.read(created.getResponse().getContentAsString(), "$.id");

        // The same transaction stored one unsent outbox row for this incident (the relay is off in tests)
        List<OutboxEvent> outbox = outboxEventRepository.findAll();
        assertEquals(1, outbox.size());
        assertEquals(UUID.fromString(id), outbox.get(0).aggregateId());
        assertEquals("IncidentCreated", outbox.get(0).eventType());
        assertNull(outbox.get(0).publishedAt());
        assertEquals(1, outboxEventRepository.countByPublishedAtIsNull());

        // Read back
        mockMvc.perform(get("/api/v1/incidents/{id}", id).with(asUser()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.title").value("Payments failing"));

        // Update status (dirty checking inside @Transactional)
        mockMvc.perform(patch("/api/v1/incidents/{id}/status", id)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{ \"status\": \"MITIGATED\" }").with(asUser()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("MITIGATED"));

        // The change really is in the database
        Incident stored = incidentRepository.findById(UUID.fromString(id)).orElseThrow();
        assertEquals(IncidentStatus.MITIGATED, stored.status());

        mockMvc.perform(get("/api/v1/incidents").with(asUser()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.items.length()").value(1));
    }

    @Test
    void shouldNotStoreAnythingWhenRequestIsInvalid() throws Exception {
        mockMvc.perform(post("/api/v1/incidents")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{ \"title\": \"\" }").with(asUser()))
                .andExpect(status().isBadRequest());

        assertEquals(0, incidentRepository.count());
    }

    @Test
    void shouldRejectStaleUpdateWithOptimisticLocking() {
        Incident saved = incidentRepository.save(new Incident(
                UUID.randomUUID(), "acme", "Login errors", null, IncidentSeverity.MEDIUM,
                IncidentStatus.OPEN, "auth-service", Instant.now().truncatedTo(ChronoUnit.MICROS)));

        // Two independent copies of the same row, both at version 0
        Incident first = incidentRepository.findById(saved.id()).orElseThrow();
        Incident second = incidentRepository.findById(saved.id()).orElseThrow();

        first.changeStatus(IncidentStatus.INVESTIGATING);
        incidentRepository.save(first); // row is now version 1

        second.changeStatus(IncidentStatus.RESOLVED);
        assertThrows(ObjectOptimisticLockingFailureException.class, () -> incidentRepository.save(second));
    }

    @Test
    void shouldPaginateNewestFirstInPostgres() throws Exception {
        Instant base = Instant.now().truncatedTo(ChronoUnit.MICROS);
        for (int i = 1; i <= 3; i++) {
            incidentRepository.save(new Incident(UUID.randomUUID(), "acme", "Incident " + i, null,
                    IncidentSeverity.LOW, IncidentStatus.OPEN, "svc", base.plusSeconds(i)));
        }

        // Page 0, size 2: the two newest
        mockMvc.perform(get("/api/v1/incidents").param("page", "0").param("size", "2").with(asUser()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.items.length()").value(2))
                .andExpect(jsonPath("$.items[0].title").value("Incident 3"))
                .andExpect(jsonPath("$.items[1].title").value("Incident 2"))
                .andExpect(jsonPath("$.totalElements").value(3))
                .andExpect(jsonPath("$.totalPages").value(2));

        // Page 1: the remaining oldest one
        mockMvc.perform(get("/api/v1/incidents").param("page", "1").param("size", "2").with(asUser()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.items.length()").value(1))
                .andExpect(jsonPath("$.items[0].title").value("Incident 1"));
    }

    @Test
    void shouldIsolateIncidentsBetweenTenants() throws Exception {
        // Tenant "acme" creates an incident
        MvcResult created = mockMvc.perform(post("/api/v1/incidents")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                { "title": "Acme outage", "severity": "HIGH", "affectedService": "billing" }
                                """).with(asTenant("acme")))
                .andExpect(status().isCreated())
                .andReturn();
        String id = JsonPath.read(created.getResponse().getContentAsString(), "$.id");

        // Tenant "globex" can neither see nor change it: it looks like it does not exist
        mockMvc.perform(get("/api/v1/incidents/{id}", id).with(asTenant("globex")))
                .andExpect(status().isNotFound());
        mockMvc.perform(get("/api/v1/incidents").with(asTenant("globex")))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.items.length()").value(0));
        mockMvc.perform(patch("/api/v1/incidents/{id}/status", id)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{ \"status\": \"RESOLVED\" }").with(asTenant("globex")))
                .andExpect(status().isNotFound());

        // The owner still sees it, unchanged
        mockMvc.perform(get("/api/v1/incidents/{id}", id).with(asTenant("acme")))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("OPEN"));
        assertEquals("acme", incidentRepository.findById(UUID.fromString(id)).orElseThrow().tenantId());
    }

    // Lives here, not in OutboxKafkaIntegrationTest: the relay is off in this class, so the test is
    // the only one locking outbox rows. With the relay running it would race us for the same rows.
    @Test
    void shouldSkipOutboxRowsLockedByAnotherTransaction() throws Exception {
        Instant now = Instant.now().truncatedTo(ChronoUnit.MICROS);
        for (int i = 0; i < 3; i++) {
            outboxEventRepository.save(new OutboxEvent(UUID.randomUUID(), UUID.randomUUID(),
                    "IncidentCreated", "incident-events", "{}", now.plusMillis(i)));
        }
        TransactionTemplate tx = new TransactionTemplate(transactionManager);
        CountDownLatch locked = new CountDownLatch(1);
        CountDownLatch release = new CountDownLatch(1);
        ExecutorService threads = Executors.newFixedThreadPool(2);
        try {
            // Transaction A locks all 3 rows and holds the locks until we release it
            Future<Integer> first = threads.submit(() -> tx.execute(status -> {
                int size = outboxEventRepository.lockUnpublishedBatch(50).size();
                locked.countDown();
                await(release);
                return size;
            }));
            assertTrue(locked.await(10, TimeUnit.SECONDS), "transaction A locked the rows");

            // Transaction B, while A still holds the locks: SKIP LOCKED returns nothing instead of waiting.
            // Without SKIP LOCKED it would block until A ends, and get() fails after 5 s instead of hanging.
            Future<Integer> second = threads.submit(() ->
                    tx.execute(status -> outboxEventRepository.lockUnpublishedBatch(50).size()));
            assertEquals(0, second.get(5, TimeUnit.SECONDS));

            release.countDown();
            assertEquals(3, first.get(5, TimeUnit.SECONDS));
        } finally {
            release.countDown();
            threads.shutdownNow();
        }
    }

    private static void await(CountDownLatch latch) {
        try {
            latch.await(10, TimeUnit.SECONDS);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }
}
