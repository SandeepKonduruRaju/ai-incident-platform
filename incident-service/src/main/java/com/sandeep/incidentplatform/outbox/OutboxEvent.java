package com.sandeep.incidentplatform.outbox;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

import java.time.Instant;
import java.util.UUID;

// One event waiting to be (or already) sent to Kafka. Written in the same transaction as the incident.
@Entity
@Table(name = "outbox_events")
public class OutboxEvent {

    // The event's eventId, so a consumer can dedupe on the same id the relay sends.
    @Id
    private UUID id;

    // The incident this event is about; also the Kafka key, so its events stay in order on one partition.
    @Column(nullable = false, updatable = false)
    private UUID aggregateId;

    @Column(nullable = false, updatable = false)
    private String eventType;

    @Column(nullable = false, updatable = false)
    private String topic;

    // The serialized event (JSON), exactly what goes to Kafka.
    @Column(nullable = false, updatable = false, columnDefinition = "text")
    private String payload;

    @Column(nullable = false, updatable = false)
    private Instant createdAt;

    // Null until the relay has sent the event.
    private Instant publishedAt;

    @Column(nullable = false)
    private int attempts;

    protected OutboxEvent() {
        // Required by JPA.
    }

    public OutboxEvent(UUID id, UUID aggregateId, String eventType, String topic, String payload, Instant createdAt) {
        this.id = id;
        this.aggregateId = aggregateId;
        this.eventType = eventType;
        this.topic = topic;
        this.payload = payload;
        this.createdAt = createdAt;
    }

    public UUID id() {
        return id;
    }

    public UUID aggregateId() {
        return aggregateId;
    }

    public String eventType() {
        return eventType;
    }

    public String topic() {
        return topic;
    }

    public String payload() {
        return payload;
    }

    public Instant createdAt() {
        return createdAt;
    }

    public Instant publishedAt() {
        return publishedAt;
    }

    public int attempts() {
        return attempts;
    }

    public void markPublished(Instant when) {
        this.publishedAt = when;
    }

    public void recordFailedAttempt() {
        this.attempts++;
    }
}
