# ADR 0006: NOT_STARTED status and retry through the outbox

Status: accepted (milestone 4)

## Context

An incident whose investigation request never reached the worker (incidents created before the outbox existed, or an
event lost to an operational mistake) showed "PENDING" forever, and the UI polled it forever. Users had no way to
recover except asking an operator.

## Decision

incident-service derives the status from the newest investigation request (an `IncidentCreated` row in the outbox)
and the worker's newest run:

- no run, request unsent or younger than `investigation.not-started-after` (default 30 min) → `PENDING`;
- no run and no request, or a request older than that → `NOT_STARTED` (never cached; no `Retry-After`, so clients stop
  polling).

`POST /api/v1/incidents/{id}/investigation/retry` (RESPONDER or ADMIN, tenant-scoped, rate limited per tenant) is
allowed only from `NOT_STARTED` or `FAILED` (409 Problem Details otherwise). It locks the incident row, checks that the
newest request is still the one the decision was based on (two concurrent retries enqueue one run), writes a new
`IncidentCreated` event through the outbox (ADR 0001), evicts the cached answer and returns 202 with `Retry-After`.
The UI shows "No investigation started." with a Retry button.

## Consequences

- Stuck incidents become visible and recoverable by the people who own them.
- A retry made during a Kafka backlog would otherwise cost a second investigation when the original arrives; ADR 0002
  handles that.
- The 30-minute threshold assumes the two services' clocks are NTP-synchronised.

## Alternatives considered

- **Reaper that re-enqueues old requests automatically**: hides the problem and can loop on a poison incident.
- **Retry by re-sending the same event id**: the worker's idempotency would skip it.
- **Retry inside the worker's API**: the worker does not own incidents or authorization; the outbox keeps one path.
