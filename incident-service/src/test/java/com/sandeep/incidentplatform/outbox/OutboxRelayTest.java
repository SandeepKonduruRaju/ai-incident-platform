package com.sandeep.incidentplatform.outbox;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.kafka.support.SendResult;

import java.time.Instant;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

// Unit test: repository and KafkaTemplate are mocks; a completed/failed future stands in for Kafka.
// Same package as OutboxRelay so it can use BATCH_SIZE.
@ExtendWith(MockitoExtension.class)
class OutboxRelayTest {

    @Mock
    private OutboxEventRepository outboxEventRepository;

    @Mock
    private KafkaTemplate<String, String> kafkaTemplate;

    @Test
    void shouldMarkRowPublishedWhenSendSucceeds() {
        // Arrange
        OutboxEvent row = row();
        when(outboxEventRepository.lockUnpublishedBatch(OutboxRelay.BATCH_SIZE)).thenReturn(List.of(row));
        when(kafkaTemplate.send("incident-events", row.aggregateId().toString(), row.payload()))
                .thenReturn(sent());

        // Act
        new OutboxRelay(outboxEventRepository, kafkaTemplate).relayBatch();

        // Assert: dirty checking writes this on commit
        assertNotNull(row.publishedAt());
        assertEquals(0, row.attempts());
    }

    @Test
    void shouldCountAttemptAndStopBatchWhenSendFails() {
        // Arrange: first row is sent, second fails, third must not be tried
        OutboxEvent first = row();
        OutboxEvent failing = row();
        OutboxEvent third = row();
        when(outboxEventRepository.lockUnpublishedBatch(OutboxRelay.BATCH_SIZE))
                .thenReturn(List.of(first, failing, third));
        when(kafkaTemplate.send("incident-events", first.aggregateId().toString(), first.payload()))
                .thenReturn(sent());
        when(kafkaTemplate.send("incident-events", failing.aggregateId().toString(), failing.payload()))
                .thenReturn(CompletableFuture.failedFuture(new RuntimeException("broker down")));

        // Act
        new OutboxRelay(outboxEventRepository, kafkaTemplate).relayBatch();

        // Assert
        assertNotNull(first.publishedAt());
        assertNull(failing.publishedAt());
        assertEquals(1, failing.attempts());
        assertNull(third.publishedAt());
        verify(kafkaTemplate, never()).send(eq("incident-events"), eq(third.aggregateId().toString()), anyString());
    }

    private static OutboxEvent row() {
        return new OutboxEvent(UUID.randomUUID(), UUID.randomUUID(), "IncidentCreated", "incident-events",
                "{\"eventType\":\"IncidentCreated\"}", Instant.now());
    }

    private static CompletableFuture<SendResult<String, String>> sent() {
        return CompletableFuture.completedFuture(null);
    }
}
