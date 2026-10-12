package com.sandeep.incidentplatform;

import com.jayway.jsonpath.JsonPath;
import com.sandeep.incidentplatform.model.Incident;
import com.sandeep.incidentplatform.model.IncidentSeverity;
import com.sandeep.incidentplatform.model.IncidentStatus;
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
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;
import org.testcontainers.postgresql.PostgreSQLContainer;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertEquals;
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

    @BeforeEach
    void cleanDatabase() {
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
}
