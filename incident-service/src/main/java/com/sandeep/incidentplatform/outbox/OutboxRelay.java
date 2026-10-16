package com.sandeep.incidentplatform.outbox;

import org.apache.kafka.clients.producer.ProducerRecord;
import org.apache.kafka.common.header.Headers;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;
import tools.jackson.core.JacksonException;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.node.MissingNode;

import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.List;
import java.util.concurrent.TimeUnit;

/**
 * Sends unsent outbox rows to Kafka, oldest first. Delivery is at-least-once: if the app dies after
 * a send but before the commit, the row is sent again on the next run, so consumers dedupe on eventId.
 */
@Component
@ConditionalOnProperty(name = "outbox.relay.enabled", havingValue = "true", matchIfMissing = true)
public class OutboxRelay {

    private static final Logger log = LoggerFactory.getLogger(OutboxRelay.class);
    static final int BATCH_SIZE = 50;
    static final long SEND_TIMEOUT_SECONDS = 5;

    private final OutboxEventRepository outboxEventRepository;
    private final KafkaTemplate<String, String> kafkaTemplate;
    private final JsonMapper jsonMapper;

    public OutboxRelay(OutboxEventRepository outboxEventRepository, KafkaTemplate<String, String> kafkaTemplate,
                       JsonMapper jsonMapper) {
        this.outboxEventRepository = outboxEventRepository;
        this.kafkaTemplate = kafkaTemplate;
        this.jsonMapper = jsonMapper;
    }

    // One transaction per batch: rows stay locked while we send, and the changes below
    // (publishedAt, attempts) are written by dirty checking on commit, so no save() is needed.
    @Scheduled(fixedDelayString = "${outbox.relay.delay-ms:1000}")
    @Transactional
    public void relayBatch() {
        List<OutboxEvent> batch = outboxEventRepository.lockUnpublishedBatch(BATCH_SIZE);
        for (OutboxEvent event : batch) {
            try {
                // Blocking on purpose: we must know the send succeeded before marking the row published.
                kafkaTemplate.send(toRecord(event)).get(SEND_TIMEOUT_SECONDS, TimeUnit.SECONDS);
                event.markPublished(Instant.now());
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                event.recordFailedAttempt();
                return;
            } catch (Exception e) {
                event.recordFailedAttempt();
                log.warn("Outbox send failed eventId={} attempts={}; stopping batch to keep order",
                        event.id(), event.attempts(), e);
                // Stop here: sending later rows now would put them on Kafka before this one.
                return;
            }
        }
    }

    // Key = incidentId (same incident -> same partition -> in order). Headers carry the context a
    // consumer needs before (or without) parsing the body: for routing, dedupe, tracing and logging.
    ProducerRecord<String, String> toRecord(OutboxEvent event) {
        ProducerRecord<String, String> record =
                new ProducerRecord<>(event.topic(), event.aggregateId().toString(), event.payload());
        Headers headers = record.headers();
        addHeader(headers, "eventId", event.id().toString());
        addHeader(headers, "eventType", event.eventType());
        // tenantId and requestId are not outbox columns; they live in the stored event envelope.
        JsonNode envelope = readEnvelope(event);
        envelope.path("tenantId").stringValueOpt().ifPresent(value -> addHeader(headers, "tenantId", value));
        envelope.path("requestId").stringValueOpt().ifPresent(value -> addHeader(headers, "requestId", value));
        return record;
    }

    private JsonNode readEnvelope(OutboxEvent event) {
        try {
            return jsonMapper.readTree(event.payload());
        } catch (JacksonException e) {
            // Still send it: the consumer dead-letters bad payloads; we only lose the optional headers.
            log.warn("Outbox payload is not valid JSON eventId={}; sending without tenantId/requestId headers",
                    event.id());
            return MissingNode.getInstance();
        }
    }

    private static void addHeader(Headers headers, String key, String value) {
        headers.add(key, value.getBytes(StandardCharsets.UTF_8));
    }
}
