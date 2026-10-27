package com.sandeep.incidentplatform.outbox;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.util.List;
import java.util.Optional;
import java.util.UUID;

public interface OutboxEventRepository extends JpaRepository<OutboxEvent, UUID> {

    // Native SQL because JPQL has no SKIP LOCKED. FOR UPDATE locks the rows until the relay's
    // transaction ends; SKIP LOCKED makes a second relay instance take the next rows instead of waiting.
    // Works on PostgreSQL and H2 2.x.
    @Query(value = """
            SELECT * FROM outbox_events
            WHERE published_at IS NULL
            ORDER BY created_at
            LIMIT :limit
            FOR UPDATE SKIP LOCKED
            """, nativeQuery = true)
    List<OutboxEvent> lockUnpublishedBatch(@Param("limit") int limit);

    long countByPublishedAtIsNull();

    // The newest event of one type for an aggregate: with IncidentCreated, the newest investigation request (first or
    // retried) of an incident. Same rule as the worker's superseded check (investigation-worker/app/request_check.py).
    Optional<OutboxEvent> findFirstByAggregateIdAndEventTypeOrderByCreatedAtDesc(UUID aggregateId, String eventType);
}
