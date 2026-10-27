# ADR 0004: Cache only terminal investigations

Status: accepted (milestone 4)

## Context

`GET /api/v1/incidents/{id}/investigation` calls the worker's internal API synchronously, and the load test showed it
is the first thing to break under load (`docs/load-test.md`). The UI polls this endpoint every 2 seconds until the
investigation finishes, and finished investigations are read many times afterwards.

## Decision

`RedisInvestigationCache` stores an answer only when its status is **COMPLETED or FAILED**, under
`investigation:v1:{tenantId}:{incidentId}` with a 1-hour TTL. PENDING, RUNNING and NOT_STARTED are never cached: they
change, and a cached PENDING would hide the result from the polling client. A retry (ADR 0006) evicts the cached
answer, so the next read sees the new run. The tenant check against the database still runs before the cache is read.

## Consequences

- Same read load, 20 req/s: p95 1,042 ms without the cache, 44 ms with it (hit ratio 0.98).
- Polling clients always see live state; only immutable answers are cached.
- A re-run from the worker's CLI (`app.rerun`) can be served stale for up to the TTL.
- The tenant id is part of the key, and another tenant gets a 404 from the database check before the cache.

## Alternatives considered

- **Cache every status with a short TTL**: clients would see stale PENDING/RUNNING answers for up to the TTL.
- **Event-driven read model** (`InvestigationCompleted` → incident-service's own table): removes the synchronous
  worker call entirely; the better long-term design, listed as future work.
