# investigation-worker

Python service that consumes `IncidentCreated` events from Kafka (topic `incident-events`,
written by incident-service's outbox relay) and opens a PENDING investigation for each one.
No AI yet: processing is a stub that writes to the worker's own `worker` schema in PostgreSQL.

Reliability features: manual offset commits after processing, idempotency on `eventId`,
retries with exponential backoff and jitter for transient errors, a dead-letter topic
(`incident-events.DLQ`) for permanent failures, per-message log context
(`requestId`, `tenantId`, `eventId`), and safe rebalances.

## Code map

| File | What it does |
|---|---|
| `app/main.py` | FastAPI app; lifespan starts/stops the consumer; `GET /health` |
| `app/consumer.py` | Consume loop, parsing, retries, DLQ, commits, rebalance listener |
| `app/processing.py` | Idempotent stub processing (one DB transaction) |
| `app/errors.py` | PERMANENT vs TRANSIENT error classification |
| `app/retry.py` | Exponential backoff with full jitter |
| `app/logging_context.py` | ContextVars + log format (Python's MDC) |
| `app/db.py` | Tables in the `worker` schema, async engine |
| `migrations/` | Alembic migrations (the worker's Flyway) |

## Setup (Windows PowerShell, Python 3.13)

```powershell
cd investigation-worker
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
Copy-Item .env.example .env   # then put the real local password into .env
```

If PowerShell refuses to run `Activate.ps1`, allow local scripts for your user once:
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

## Run locally (port 8001)

Needs the compose PostgreSQL and Kafka (`docker compose up -d postgres kafka kafka-init` in
`incident-service\`). Stop the compose `investigation-worker` container first, or both will join
the same consumer group and share the partitions.

```powershell
alembic upgrade head                     # create/upgrade the worker schema
uvicorn app.main:app --port 8001
Invoke-RestMethod http://127.0.0.1:8001/health
```

## Test

```powershell
python -m pytest -v                  # everything (integration tests need Docker Desktop)
python -m pytest -v -m "not integration"   # fast unit tests only
```

Integration tests start their own Kafka (`apache/kafka:4.1.0`) and PostgreSQL containers and are
skipped when Docker is not running.

## Configuration (environment variables or .env)

| Variable | Default |
|---|---|
| `KAFKA_BOOTSTRAP_SERVERS` | `localhost:9092` |
| `KAFKA_TOPIC` | `incident-events` |
| `KAFKA_GROUP_ID` | `investigation-worker` |
| `KAFKA_DLQ_TOPIC` | `incident-events.DLQ` |
| `KAFKA_MAX_POLL_INTERVAL_MS` | `300000` |
| `CONSUMER_ENABLED` | `true` |
| `DATABASE_URL` | none (required) |
| `RETRY_MAX_ATTEMPTS` | `5` |
| `RETRY_BASE_DELAY_SECONDS` | `0.5` |
| `RETRY_MAX_DELAY_SECONDS` | `10` |
| `LOG_LEVEL` | `INFO` |

## Docker

The worker is part of `incident-service/compose.yaml` (port 8001 on the host, 8000 in the
container). The container runs `alembic upgrade head` before starting uvicorn.

```powershell
cd ..\incident-service
docker compose up -d --build
docker compose logs -f investigation-worker
```
