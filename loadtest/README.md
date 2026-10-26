# Load tests (k6)

k6 scenarios against the local compose stack. k6 runs in Docker (`grafana/k6:2.2.0`, pinned) on the compose
network, so nothing is installed on the host. Results and analysis: [docs/load-test.md](../docs/load-test.md).

| Script | Scenario | Shape |
|---|---|---|
| `api-mix.js` | (a) API mix | 10 → 100 VUs over 2 min, hold 2 min; 10% create, 30% list, 20% get, 40% investigation |
| `e2e.js` | (b) end to end | constant arrival rate (`RATE` per minute, default 30) of POST → poll until COMPLETED/FAILED |
| `spike.js` | (c) spike | 10 VUs → 200 within 10 s, hold 1 min, back to 10 (recovery) |
| `cache.js` | (d) cache effect | `RATE` req/s (default 200; the report uses 20) of investigation reads of finished incidents; `cache-compare.ps1` runs it with the cache on and off |

Thresholds for every scenario: `http_req_duration p(95) < 300 ms` and `http_req_failed < 1%`
(k6 exits with code 99 when one fails; the measurement is still valid).

## Run (PowerShell, from the repo root)

```powershell
# 1. Stack with the observability profile (Prometheus for the server-side numbers), fake LLM, dev profile
#    (k6 gets its tokens from POST /api/v1/dev/token). The per-tenant limit (30/min) is raised for load tests:
#    otherwise most creations are 429 by design.
cd incident-service
$env:LLM_PROVIDER = "fake"; $env:RATE_LIMIT_CREATE_INCIDENT_PER_MINUTE = "100000"
docker compose --profile observability up -d --build
cd ..

# 2. Scenarios
.\loadtest\run.ps1 -Script api-mix.js -Name a-api-mix
.\loadtest\run.ps1 -Script e2e.js     -Name b-e2e -K6Env @{ RATE = "30" }
.\loadtest\run.ps1 -Script spike.js   -Name c-spike

# 3. Cache on vs off, fairly: recreates incident-service per mode, warms the JVM, then measures
.\loadtest\cache-compare.ps1 -Rate 20
```

Between scenarios, wait until the Kafka lag is back to 0 (`sum(kafka_consumer_lag)` in Prometheus): a backlog
from one run steals worker CPU from the next.

Each run writes to `loadtest/results/` (gitignored): `<name>.json` (full k6 summary), `<name>.prom.json`
(Kafka lag peak, investigations/min, cache hit ratio, CPU and pool peaks from Prometheus, via `prom_report.py`)
and `<name>.docker-stats.csv` (CPU/memory of every container every 5 s).

Note: each scenario's `setup()` creates and waits for its own seed incidents; that time is inside the window
`prom_report.py` reads, so investigations/min includes the seeding.
