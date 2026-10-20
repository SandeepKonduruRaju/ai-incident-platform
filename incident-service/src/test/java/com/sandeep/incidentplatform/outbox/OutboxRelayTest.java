package com.sandeep.incidentplatform.outbox;

import com.sandeep.incidentplatform.observability.PlatformMetrics;
import com.sandeep.incidentplatform.observability.TraceContextSupport;
import org.apache.kafka.clients.producer.ProducerRecord;
import org.apache.kafka.common.header.Header;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.kafka.support.SendResult;
import tools.jackson.databind.json.JsonMapper;

import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

// Unit test: repository and KafkaTemplate are mocks; a completed/failed future stands in for Kafka.
// Same package as OutboxRelay so it can use BATCH_SIZE and toRecord().
@ExtendWith(MockitoExtension.class)
class OutboxRelayTest {

    @Mock
    private OutboxEventRepository outboxEventRepository;

    @Mock
    private KafkaTemplate<String, String> kafkaTemplate;

    private final JsonMapper jsonMapper = JsonMapper.builder().build();

    @Test
    void shouldMarkRowPublishedWhenSendSucceeds() {
        // Arrange
        OutboxEvent row = row("req-1");
        when(outboxEventRepository.lockUnpublishedBatch(OutboxRelay.BATCH_SIZE)).thenReturn(List.of(row));
        when(kafkaTemplate.send(any(ProducerRecord.class))).thenReturn(sent());

        // Act
        relay().relayBatch();

        // Assert: dirty checking writes this on commit
        assertNotNull(row.publishedAt());
        assertEquals(0, row.attempts());
    }

    @Test
    void shouldCountAttemptAndStopBatchWhenSendFails() {
        // Arrange: first row is sent, second fails, third must not be tried
        OutboxEvent first = row("req-1");
        OutboxEvent failing = row("req-2");
        OutboxEvent third = row("req-3");
        when(outboxEventRepository.lockUnpublishedBatch(OutboxRelay.BATCH_SIZE))
                .thenReturn(List.of(first, failing, third));
        when(kafkaTemplate.send(any(ProducerRecord.class))).thenAnswer(call -> {
            ProducerRecord<String, String> record = call.getArgument(0);
            return record.key().equals(failing.aggregateId().toString())
                    ? CompletableFuture.failedFuture(new RuntimeException("broker down"))
                    : sent();
        });

        // Act
        relay().relayBatch();

        // Assert
        assertNotNull(first.publishedAt());
        assertNull(failing.publishedAt());
        assertEquals(1, failing.attempts());
        assertNull(third.publishedAt());
        ArgumentCaptor<ProducerRecord<String, String>> sentRecords = ArgumentCaptor.captor();
        verify(kafkaTemplate, times(2)).send(sentRecords.capture());
        assertEquals(List.of(first.aggregateId().toString(), failing.aggregateId().toString()),
                sentRecords.getAllValues().stream().map(ProducerRecord::key).toList());
    }

    @Test
    void shouldSendKeyAndContextHeaders() {
        OutboxEvent row = row("req-1");

        ProducerRecord<String, String> record = relay().toRecord(row);

        assertEquals("incident-events", record.topic());
        assertEquals(row.aggregateId().toString(), record.key());
        assertEquals(row.payload(), record.value());
        assertEquals(row.id().toString(), header(record, "eventId"));
        assertEquals("IncidentCreated", header(record, "eventType"));
        assertEquals("acme", header(record, "tenantId"));
        assertEquals("req-1", header(record, "requestId"));
    }

    @Test
    void shouldLeaveOutRequestIdHeaderWhenEventHasNone() {
        ProducerRecord<String, String> record = relay().toRecord(row(null));

        assertEquals("acme", header(record, "tenantId"));
        assertNull(record.headers().lastHeader("requestId"));
    }

    @Test
    void shouldStillSendWhenPayloadIsNotJson() {
        OutboxEvent row = new OutboxEvent(UUID.randomUUID(), UUID.randomUUID(), "IncidentCreated", "incident-events",
                "not json", Instant.now());

        ProducerRecord<String, String> record = relay().toRecord(row);

        assertEquals(row.id().toString(), header(record, "eventId"));
        assertNull(record.headers().lastHeader("tenantId"));
    }

    private OutboxRelay relay() {
        return new OutboxRelay(outboxEventRepository, kafkaTemplate, jsonMapper,
                PlatformMetrics.inMemory(), TraceContextSupport.noop());
    }

    private static OutboxEvent row(String requestId) {
        String requestIdJson = requestId == null ? "null" : "\"" + requestId + "\"";
        String payload = """
                {"eventType":"IncidentCreated","schemaVersion":1,"tenantId":"acme","requestId":%s}
                """.formatted(requestIdJson);
        return new OutboxEvent(UUID.randomUUID(), UUID.randomUUID(), "IncidentCreated", "incident-events",
                payload, Instant.now());
    }

    private static String header(ProducerRecord<String, String> record, String key) {
        Header header = record.headers().lastHeader(key);
        return header == null ? null : new String(header.value(), StandardCharsets.UTF_8);
    }

    private static CompletableFuture<SendResult<String, String>> sent() {
        return CompletableFuture.completedFuture(null);
    }
}
