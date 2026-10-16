package com.sandeep.incidentplatform.outbox;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

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

    public OutboxRelay(OutboxEventRepository outboxEventRepository, KafkaTemplate<String, String> kafkaTemplate) {
        this.outboxEventRepository = outboxEventRepository;
        this.kafkaTemplate = kafkaTemplate;
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
                kafkaTemplate.send(event.topic(), event.aggregateId().toString(), event.payload())
                        .get(SEND_TIMEOUT_SECONDS, TimeUnit.SECONDS);
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
}
