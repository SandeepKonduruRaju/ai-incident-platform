-- Transactional outbox: events are written here in the same transaction as the business change,
-- then OutboxRelay sends them to Kafka. id is the event's eventId (consumers dedupe on it).
CREATE TABLE outbox_events (
    id           UUID                     PRIMARY KEY,
    aggregate_id UUID                     NOT NULL,
    event_type   VARCHAR(100)             NOT NULL,
    topic        VARCHAR(255)             NOT NULL,
    payload      TEXT                     NOT NULL,
    created_at   TIMESTAMP WITH TIME ZONE NOT NULL,
    published_at TIMESTAMP WITH TIME ZONE,
    attempts     INT                      NOT NULL DEFAULT 0
);

-- The relay asks for unsent rows (published_at IS NULL), oldest first.
-- A PostgreSQL partial index (WHERE published_at IS NULL) would be smaller, but H2 does not support it.
CREATE INDEX idx_outbox_events_unpublished ON outbox_events (published_at, created_at);
