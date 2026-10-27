# ADR 0002: The worker checks `outbox_events` before running an investigation (superseded requests)

Status: accepted (milestone 4)

## Context

An investigation request that is published but not consumed within 30 minutes (a Kafka backlog) shows as
`NOT_STARTED`, and a user may retry it (ADR 0006). The retry is a new event for the same incident. Events are keyed by
incident id, so the **original event is consumed first**, and the worker's idempotency is per event id: without a
check, the original runs an LLM investigation and then the retry runs a second one. Both cost money; the first is
already obsolete.

When the original is consumed, the retry is still queued behind it in the same partition, so the worker's own tables
cannot know it exists. The only place that already knows is the outbox row incident-service wrote, in the same
transaction as the retry.

## Decision

Before claiming an event, the worker (`app/request_check.py`) reads, read-only:

```sql
SELECT o.id FROM public.outbox_events o
JOIN public.incidents i ON i.id = o.aggregate_id
WHERE o.aggregate_id = :incident_id AND i.tenant_id = :tenant_id AND o.event_type = :event_type
ORDER BY o.created_at DESC, o.id DESC
```

If this event is in the outbox **and** a newer request of the same type exists, the investigation row is marked
`SUPERSEDED` (no LLM call, worker migration 0005) and the offset is committed as usual. The newer event runs once.
The internal API ignores `SUPERSEDED` rows, so incident-service shows `PENDING` until the newer request runs.
incident-service's own "latest request" lookup applies the same rule (only `IncidentCreated` events), and Flyway
V5 indexes `(aggregate_id, created_at)` for both.

**Fails toward running**: if the outbox cannot be read, or the event is not in it (CLI runs, tests), the event counts
as the latest. A failed check never drops an investigation; the worst case is the old behaviour (one extra run).

## Consequences

- One paid investigation per latest request, tested end to end (`tests/test_superseded_integration.py`:
  original-then-retry runs exactly one investigation; a single request is unaffected).
- **Accepted coupling**: the worker reads a table owned by incident-service (`public` schema, same database and
  user). A column rename in `outbox_events` or `incidents` must keep this query working; the failure mode is benign
  (it falls back to running), and the query is covered by an integration test.
- One extra indexed query per consumed event.

## Alternatives considered

- **Carry a "superseded" flag in the event**: impossible, the original is written before the retry exists.
- **Ask incident-service over HTTP** ("is this the latest request?"): no table coupling, but a synchronous call on the
  consume path, another failure mode and an endpoint to secure.
- **Cancel the original in the relay** (do not publish superseded rows): only helps while the original is still
  unsent; in the backlog case it was already published.
- **Let the worker look ahead in the partition**: not possible with a normal consumer, and fragile.
- **Accept the double run**: correct results, but pays twice exactly when the system is already overloaded.
