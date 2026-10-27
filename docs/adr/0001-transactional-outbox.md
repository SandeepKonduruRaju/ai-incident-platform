# ADR 0001: Transactional outbox for investigation requests

Status: accepted (milestone 2)

## Context

Creating an incident must start its AI investigation. incident-service writes the incident to PostgreSQL and the
worker learns about it from Kafka. Writing to the database and then publishing to Kafka are two separate systems with
no shared transaction:

- publish after commit, and a crash in between loses the event: the incident never gets investigated;
- publish before commit, and a rollback leaves an event for an incident that does not exist.

## Decision

`IncidentService.create` writes the incident **and** an `IncidentCreated` row in `outbox_events` in one database
transaction. `OutboxRelay` (a scheduled job in incident-service) reads unsent rows with `FOR UPDATE SKIP LOCKED`,
sends them to Kafka (key = incident id, so one incident's events stay in order), waits for the broker's
acknowledgement and only then sets `published_at`. The outbox row id is the event id.

The worker is an idempotent consumer: `processed_events` (event id) and the PENDING investigation row are inserted in
one transaction, the offset is committed only after processing or dead-lettering, and `run_count` fencing stops a
stale run from overwriting a newer one. Delivery is at least once; processing is effectively once.

A retry (`POST .../investigation/retry`, ADR 0006) goes through the same outbox as a new event.

## Consequences

- No lost and no phantom investigation requests; the API keeps accepting incidents while Kafka or the worker is
  slow (the load test grew a 1,833-message backlog without a failed creation, `docs/load-test.md`).
- The trace context (`traceparent`) is stored with the row, so one trace covers HTTP request → relay → worker.
- Extra latency between commit and publish (the relay's polling interval), and the relay holds row locks while it
  sends a batch to Kafka (see "What I'd do next" in the README).
- The outbox table grows forever: there is no retention job yet (future work).

## Alternatives considered

- **Publish in the request, after commit**: simplest, but loses events on a crash between commit and send.
- **Change data capture (Debezium) on the outbox table**: no polling and no locks in the service, but another
  component to run and operate; not worth it at this scale.
- **Kafka transactions / XA**: Kafka does not take part in a database transaction; XA is not an option here.
