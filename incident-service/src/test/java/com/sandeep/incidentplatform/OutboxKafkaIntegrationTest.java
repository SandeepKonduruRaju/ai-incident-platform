package com.sandeep.incidentplatform;

import com.jayway.jsonpath.JsonPath;
import com.sandeep.incidentplatform.event.IncidentCreatedEvent;
import com.sandeep.incidentplatform.event.KafkaTopics;
import com.sandeep.incidentplatform.outbox.OutboxEvent;
import com.sandeep.incidentplatform.outbox.OutboxEventRepository;
import com.sandeep.incidentplatform.repository.IncidentRepository;
import org.apache.kafka.clients.admin.Admin;
import org.apache.kafka.clients.admin.AdminClientConfig;
import org.apache.kafka.clients.admin.NewTopic;
import org.apache.kafka.clients.consumer.ConsumerConfig;
import org.apache.kafka.clients.consumer.ConsumerRecord;
import org.apache.kafka.clients.consumer.KafkaConsumer;
import org.apache.kafka.common.header.Header;
import org.apache.kafka.common.serialization.StringDeserializer;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.testcontainers.service.connection.ServiceConnection;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.http.MediaType;
import org.springframework.test.annotation.DirtiesContext;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;
import org.testcontainers.kafka.KafkaContainer;
import org.testcontainers.postgresql.PostgreSQLContainer;
import tools.jackson.databind.json.JsonMapper;

import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.TimeUnit;

import static com.sandeep.incidentplatform.TestJwt.asUser;
import static org.awaitility.Awaitility.await;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * End to end with a real PostgreSQL and a real Kafka in Docker: POST → incident + outbox row
 * (one transaction) → OutboxRelay → record on "incident-events". Skipped when Docker is not running.
 */
@SpringBootTest(properties = {
        // The relay is off in the shared test properties; this class is the one place it runs.
        "outbox.relay.enabled=true",
        "outbox.relay.delay-ms=200"
})
@AutoConfigureMockMvc
@Testcontainers(disabledWithoutDocker = true)
// Close this context after the class: otherwise Spring caches it and the scheduled relay keeps
// polling PostgreSQL after the containers have stopped, logging errors during later test classes.
@DirtiesContext
class OutboxKafkaIntegrationTest {

    @Container
    @ServiceConnection
    static PostgreSQLContainer postgres = new PostgreSQLContainer("postgres:18-alpine");

    // Same image as compose.yaml. Auto-create is off there too, so a missing topic fails here as well.
    @Container
    @ServiceConnection
    static KafkaContainer kafka = new KafkaContainer("apache/kafka:4.1.0")
            .withEnv("KAFKA_AUTO_CREATE_TOPICS_ENABLE", "false");

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private IncidentRepository incidentRepository;

    @Autowired
    private OutboxEventRepository outboxEventRepository;

    @Autowired
    private JsonMapper jsonMapper;

    // Runs after the containers start and before the Spring context (and so the relay) exists.
    @BeforeAll
    static void createTopic() throws Exception {
        try (Admin admin = Admin.create(Map.of(AdminClientConfig.BOOTSTRAP_SERVERS_CONFIG, kafka.getBootstrapServers()))) {
            admin.createTopics(List.of(new NewTopic(KafkaTopics.INCIDENT_EVENTS, 3, (short) 1)))
                    .all().get(30, TimeUnit.SECONDS);
        }
    }

    @BeforeEach
    void cleanDatabase() {
        outboxEventRepository.deleteAll();
        incidentRepository.deleteAll();
    }

    @Test
    void shouldRelayCreatedIncidentFromOutboxToKafka() throws Exception {
        // POST: stores the incident and its outbox row
        MvcResult created = mockMvc.perform(post("/api/v1/incidents")
                        .header("X-Request-Id", "it-req-1")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                { "title": "Payments failing", "severity": "HIGH", "affectedService": "payment-service" }
                                """).with(asUser()))
                .andExpect(status().isCreated())
                .andReturn();
        String incidentId = JsonPath.read(created.getResponse().getContentAsString(), "$.id");

        // A plain consumer in its own group, reading the topic from the start
        try (KafkaConsumer<String, String> consumer = newConsumer()) {
            consumer.subscribe(List.of(KafkaTopics.INCIDENT_EVENTS));
            List<ConsumerRecord<String, String>> received = new ArrayList<>();

            // The relay runs every 200 ms; keep polling until our record arrives (or fail after 15 s)
            await().atMost(Duration.ofSeconds(15)).until(() -> {
                consumer.poll(Duration.ofMillis(200)).forEach(received::add);
                return received.stream().anyMatch(r -> incidentId.equals(r.key()));
            });

            ConsumerRecord<String, String> record = received.stream()
                    .filter(r -> incidentId.equals(r.key()))
                    .findFirst().orElseThrow();
            IncidentCreatedEvent event = jsonMapper.readValue(record.value(), IncidentCreatedEvent.class);
            assertEquals(IncidentCreatedEvent.TYPE, event.eventType());
            assertEquals(TestJwt.TENANT, event.tenantId());
            assertEquals("it-req-1", event.requestId());
            assertEquals(UUID.fromString(incidentId), event.payload().incidentId());
            assertNotEquals(UUID.fromString(incidentId), event.eventId());

            // Context headers (read by the investigation worker before it parses the body)
            assertEquals(event.eventId().toString(), header(record, "eventId"));
            assertEquals(IncidentCreatedEvent.TYPE, header(record, "eventType"));
            assertEquals(TestJwt.TENANT, header(record, "tenantId"));
            assertEquals("it-req-1", header(record, "requestId"));
        }

        // The relay commits after the send, so the row may still be unpublished for a moment
        await().atMost(Duration.ofSeconds(5)).untilAsserted(() -> {
            List<OutboxEvent> rows = outboxEventRepository.findAll();
            assertEquals(1, rows.size());
            assertEquals(UUID.fromString(incidentId), rows.get(0).aggregateId());
            assertEquals(0, outboxEventRepository.countByPublishedAtIsNull(), "published_at is set");
        });
    }

    private static String header(ConsumerRecord<String, String> record, String key) {
        Header header = record.headers().lastHeader(key);
        return header == null ? null : new String(header.value(), StandardCharsets.UTF_8);
    }

    private static KafkaConsumer<String, String> newConsumer() {
        return new KafkaConsumer<>(Map.of(
                ConsumerConfig.BOOTSTRAP_SERVERS_CONFIG, kafka.getBootstrapServers(),
                ConsumerConfig.GROUP_ID_CONFIG, "it-" + UUID.randomUUID(),
                ConsumerConfig.AUTO_OFFSET_RESET_CONFIG, "earliest",
                ConsumerConfig.KEY_DESERIALIZER_CLASS_CONFIG, StringDeserializer.class,
                ConsumerConfig.VALUE_DESERIALIZER_CLASS_CONFIG, StringDeserializer.class));
    }
}
