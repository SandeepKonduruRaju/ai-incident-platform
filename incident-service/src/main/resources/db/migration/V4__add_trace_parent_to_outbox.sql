-- W3C trace context of the request that created the event (section 3.4). The relay runs later on a
-- scheduler thread, so the trace is stored with the row and re-attached when the event is sent to Kafka.
-- Format: "00-<32 hex trace id>-<16 hex span id>-<2 hex flags>" (55 chars). Null for rows written
-- before this migration or without an active trace.
ALTER TABLE outbox_events ADD COLUMN trace_parent VARCHAR(55);
