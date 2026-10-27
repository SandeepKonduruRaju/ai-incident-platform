# ADR 0003: Redis is optional: fail open behind a circuit breaker

Status: accepted (milestone 4)

## Context

Redis serves two features in incident-service: the investigation cache (ADR 0004) and the per-tenant rate limits on
`POST /api/v1/incidents` and `POST .../investigation/retry`. Neither is a source of truth. A Redis outage must not
become an outage of creating or reading incidents.

The first version skipped Redis for 5 seconds after any single failed call. The load test (`docs/load-test.md`) showed
that on a busy host one slow command was enough: every read in those 5 seconds went to the worker at once, overloaded
it, and the next Redis call timed out again, a flapping loop that made the cache-on run worse than cache-off.

## Decision

Every Redis call goes through `RedisGuard`:

- short command timeouts (500 ms);
- **fail open**: on any error the request continues without Redis (cache miss; rate limit allows the request),
  logged and counted in `redis_errors_total{operation}`;
- a **circuit breaker**: only after `app.redis.failure-threshold` (5) consecutive failures is Redis skipped for
  `app.redis.failure-cooldown` (5 s); a single slow call falls back for that request only.

## Consequences

- Redis down: reads go to the worker, creation is not rate limited (`RedisDownTest`); after recovery the breaker
  closes on the next successful call.
- While open, the rate limit is not enforced: an accepted risk, since the limit protects against runaway clients, not
  against abuse that would need a hard guarantee.
- After the fix the 20 req/s cache run had 0 Redis errors and p95 44 ms (`docs/load-test.md`).

## Alternatives considered

- **Fail closed** (refuse requests without Redis): turns a cache outage into an API outage.
- **Skip Redis after one failure** (the first version): caused the thundering herd described above.
- **In-memory fallback rate limiter per replica**: limits would multiply by the number of replicas; not needed yet.
