# Load test report (milestone 4)

k6 (`grafana/k6:2.2.0`, in Docker) against the **local compose stack** with the observability profile, fake LLM
(`LLM_PROVIDER=fake`: no API cost, but retrieval is real: ONNX embeddings + cross-encoder rerank on CPU).
Scripts and how to run them: [loadtest/README.md](../loadtest/README.md). Raw outputs (k6 JSON, Prometheus numbers,
docker stats every 5 s) go to `loadtest/results/` (gitignored).

**Environment, and why it matters:** one Windows laptop, Docker Desktop with **8 vCPUs / 9.7 GB**, shared by *every*
container (Postgres, Kafka, Redis, incident-service, the worker, Prometheus, Grafana, Jaeger, ...) **and** the k6 load
generator. Nothing is isolated, so these numbers describe this box, not the architecture's ceiling: the first
bottleneck is found by watching which component saturates first and drags the others down.
Targets for every scenario: **p95 < 300 ms, errors < 1 %**. The per-tenant rate limit was raised for the runs
(`RATE_LIMIT_CREATE_INCIDENT_PER_MINUTE=100000`), otherwise most creations are 429 by design.

## Results

| Scenario | Load | req/s | p50 | p95 | p99 | Errors | Kafka lag peak | Investigations/min | Cache hit ratio | Targets |
|---|---|---|---|---|---|---|---|---|---|---|
| (a) API mix | 10 → 100 VUs, 6 min | 36.2 | 196 ms | 4,089 ms | 6,879 ms | 17.1 % | 1,286 | 16.6 | 0.98 | ❌ |
| (b) End to end | 30 incidents/min, 5 min | 1.7 | 31 ms | 257 ms | 530 ms | 0 % | 1 | 29.6 | – | ✅ |
| (c) Spike | 10 → 200 VUs in 10 s, 1 min | 96.8 (peak ≈ 275) | 21 ms | 1,491 ms | 3,145 ms | 3.2 % | 1,833 | 95.7 | 0.99 | ❌ |
| (d) Cache **on** | 20 req/s investigation reads | 17.4 | 11 ms | **44 ms** | 114 ms | 0 % | – | – | 0.98 | ✅ |
| (d) Cache **off** | 20 req/s investigation reads | 16.0 | 25 ms | **1,042 ms** | 2,124 ms | 0.1 % | – | – | – | ❌ |

(b) end to end, POST → COMPLETED as the client sees it (polling every 1 s): **median 1.1 s, p95 2.7 s, max 4.3 s**;
150/150 investigations finished, none FAILED. (a) and (c) ran before the Redis guard fix described below.

Per endpoint in (a): list p95 1.55 s, get p95 1.41 s, create p95 3.29 s, **investigation p95 5.43 s**. Every one of the
2,279 failed requests in (a) and the 667 in (c) was `GET .../investigation` answered 503: incident-service's call to
the worker's internal API timed out (3 s).

## First bottleneck: the investigation worker (CPU), and it drags the read path down with it

1. **The worker is CPU-bound.** Each investigation embeds the query and reranks candidates with ONNX models on the
   CPU. Alone, the worker sustains about **100 investigations/min**; while it competes for the same 8 cores with the
   API and k6, it drops to **16.6/min** (a). Peak docker stats in (a): incident-service 683 %, worker 390 %, Kafka
   316 %, Postgres 195 %, k6 114 %.
2. **Writes are decoupled, so the API keeps accepting incidents.** In (a) 10 % of ~13,000 requests created
   incidents (~3.6/s, far above 16.6/min), so the Kafka lag grew to 1,286. That is the outbox + Kafka design working:
   no creation failed or slowed down because the worker was behind.
3. **Reads are NOT decoupled.** `GET /incidents/{id}/investigation` calls the worker synchronously. With the worker
   busy, its internal API answered after more than 3 s, incident-service returned 503 + Retry-After, and the waiting
   Tomcat threads pushed every other endpoint's p95 above 1 s. **This is the first thing that breaks.**
4. **Recovery (c):** p95 went from 23 ms to 3.1 s during the spike. The API was back to a 54 ms p95 within one
   30-second step after the spike ended, but the 1,833-message backlog took **about 18 minutes** to drain.
5. **Below capacity everything passes (b):** at 30 incidents/min the whole pipeline stayed under target (lag peak 1).

**What would move the bottleneck** (in order of value): run the worker's read API in a separate process (or serve
investigations from a read model fed by an `InvestigationCompleted` event: the "Reads couple to the worker"
limitation in the README); scale worker replicas (up to the 3 partitions) on their own nodes; limit ONNX threads per
worker so one process does not take every core; cache-first reads (below) already remove most of the read load.

## Redis: before and after

**Cache effect (d), same read load, cache on vs off** (warm JVM, worker idle, 50 finished investigations read at
random by 10 tenants):

| Investigation read, 20 req/s | p50 | p95 | p99 | Worker calls |
|---|---|---|---|---|
| Without cache | 25 ms | 1,042 ms | 2,124 ms | every read |
| With cache (hit ratio 0.98) | 11 ms | 44 ms | 114 ms | misses only (~2 %) |

The cache takes the worker out of the read path for finished investigations: **p95 24x lower**, and the read
endpoint goes from failing the 300 ms target to passing it. A hit still runs the database tenant check (by design),
which is the remaining ~10 ms.

**A bug the load test found in the fail-open logic (fixed).** The first cache runs at 100-200 req/s were *worse with
the cache on* (up to 88 % errors). The incident-service log showed the reason: on a busy host a single Redis command
sometimes exceeded the 250 ms client timeout, and the guard then **skipped Redis for 5 seconds**, so every read in
those 5 seconds (hundreds) went to the worker at once, overloaded it, and the next Redis call timed out again: a
flapping loop. One slow call turned into a thundering herd on the slowest component. Fix (`RedisGuard`): a **circuit
breaker** that opens only after **5 consecutive** failures (a blip falls back for that one request only), plus a
500 ms command timeout. After the fix: **0 Redis errors** in the 20 req/s run. Unit test:
`RedisGuardTest.aSingleSlowCallFallsBackForThatRequestOnlyAndDoesNotOpenTheCircuit`.

Remaining overload behaviour, for the record: at 50-200 req/s of investigation reads this laptop still degrades
(JIT warm-up of a freshly restarted JVM and the worker's seeding both compete for the same cores), which is why
(d) was measured at 20 req/s on a warm JVM. That is an environment limit, not a cache result.

## Rate limiting under load

The limit itself is covered by tests (`RedisIntegrationTest`: 429 + Retry-After after the limit, other tenants
unaffected). For the load runs it was raised; with the default 30/min, scenario (a) would have rejected most of its
creations with 429 (each k6 tenant creates ~3 incidents/s at 100 VUs), which is the limit doing its job.

## How to reproduce

```powershell
cd incident-service
$env:LLM_PROVIDER = "fake"; $env:RATE_LIMIT_CREATE_INCIDENT_PER_MINUTE = "100000"
docker compose --profile observability up -d --build
cd ..
.\loadtest\run.ps1 -Script api-mix.js -Name a-api-mix
.\loadtest\run.ps1 -Script e2e.js -Name b-e2e -K6Env @{ RATE = "30" }
.\loadtest\run.ps1 -Script spike.js -Name c-spike
.\loadtest\cache-compare.ps1 -Rate 20          # (d): cache on, then off, each after a JVM warm-up
```

Wait for the Kafka lag to return to 0 between scenarios (Grafana, or `sum(kafka_consumer_lag)` in Prometheus):
a backlog left by one run slows the next one's setup and steals worker CPU from it.
