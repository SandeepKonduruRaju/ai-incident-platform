# investigation-worker

The half of the platform that does the investigating. It reads `IncidentCreated` events from Kafka (topic
`incident-events`, written by incident-service's outbox relay), finds the evidence for each incident, asks Claude what
went wrong, checks the answer and stores it in its own `worker` schema in PostgreSQL. incident-service reads the
results back through a small internal API.

For each event, it:

1. **Skips duplicates and stale requests.** Idempotency is keyed on `eventId`, and `run_count` fencing stops a slow,
   older run from overwriting a newer one. It also checks whether a retry has replaced the request in the meantime
   ([ADR 0002](../docs/adr/0002-superseded-request-check.md)).
2. **Retrieves evidence** with hybrid search. pgvector (meaning) and PostgreSQL full-text (exact identifiers) are merged
   with Reciprocal Rank Fusion, reranked by a cross-encoder, and capped per evidence type so a single noisy log doesn't
   crowd out the runbook.
3. **Investigates** in a small LangGraph workflow (retrieve → analyse → validate → repair), using structured outputs
   from Claude Haiku 5.5. A citation to evidence it was never shown gets one repair attempt, and then the run fails
   rather than storing it ([ADR 0005](../docs/adr/0005-abstain-over-hallucinate.md)).
4. **Fails safely.** Transient errors are retried with backoff and jitter. Poison messages go to
   `incident-events.DLQ`, and offsets are committed only once a message is fully handled. If a crash leaves a run stuck in
   RUNNING, a reaper marks it FAILED with a reason, so nobody watches a spinner forever.

By default the LLM is a fake with canned answers (`LLM_PROVIDER=fake`), so the tests and local runs cost nothing. Set
`LLM_PROVIDER=anthropic` and `ANTHROPIC_API_KEY` to use real Claude.

## Code map

| File | What it does |
|---|---|
| `app/main.py` | FastAPI app: starts the consumer and the reaper; `GET /livez`, `GET /health` |
| `app/consumer.py` | Consume loop, parsing, retries, DLQ, commits, rebalance listener |
| `app/processing.py` | Per-event logic: open or find the investigation, superseded check, claim, run |
| `app/request_check.py` | Is this event still the incident's latest investigation request? |
| `app/investigations.py` | Repository for `worker.investigations` (create, claim, save, with `run_count` fencing) |
| `app/reaper.py` | Marks runs stuck in RUNNING after a crash as FAILED (fenced by `run_count`) |
| `app/graph.py` | The LangGraph investigation workflow |
| `app/llm.py`, `app/prompt.py`, `app/schemas.py` | LLM clients (fake and Anthropic), the prompt, and the result model |
| `app/retrieval.py`, `app/search.py`, `app/fusion.py`, `app/rerank.py`, `app/selection.py` | Hybrid retrieval |
| `app/chunking.py`, `app/embedding.py`, `app/ingest.py` | Chunk, embed and upsert evidence into `worker.chunks` |
| `app/internal_api.py` | `GET /internal/v1/investigations` for incident-service (requires `X-Internal-Token`) |
| `app/metrics.py`, `app/tracing.py`, `app/llm_observed.py` | Prometheus metrics and OpenTelemetry tracing |
| `app/synthetic.py`, `app/demo_data.py`, `app/seed_demo.py` | Synthetic evidence, plus the dev-only demo tenant |
| `app/eval_retrieval.py`, `app/eval_investigation.py`, `app/eval_judge.py` | Evaluations ([docs/evaluation.md](../docs/evaluation.md)) |
| `app/errors.py`, `app/retry.py` | Transient vs permanent errors, backoff with full jitter |
| `migrations/` | Alembic migrations 0001–0005 (the worker's Flyway) |

## Handy commands

```powershell
python -m app.ingest                                              # load the synthetic evidence (idempotent)
python -m app.investigate --tenant acme --scenario db_pool_exhausted   # one investigation, printed
python -m app.eval_retrieval                                      # vector-only vs hybrid retrieval
python -m app.eval_investigation --provider fake                  # eval pipeline without API cost
python -m app.rerun --status PENDING                              # re-run investigations left PENDING
```

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
$env:INTERNAL_API_TOKEN = "dev-only-internal-token-change-me"   # the worker refuses to start without one
uvicorn app.main:app --port 8001
Invoke-RestMethod http://127.0.0.1:8001/health
```

## Test

```powershell
python -m pytest -q                        # everything (integration tests need Docker Desktop)
python -m pytest -q -m "not integration"   # fast unit tests only
python -m pytest -m eval_smoke -q          # eval pipeline smoke test, no Docker
ruff check .                               # what CI runs
```

Integration tests start their own Kafka and PostgreSQL (pgvector) containers, and they're skipped when Docker isn't
running. The tests always use the fake LLM. The few live-LLM tests run only when `LLM_PROVIDER=anthropic` is set in
your shell, because they cost money.

## Configuration (environment variables or .env)

The most useful ones. The full list, with comments, is in [app/config.py](app/config.py).

| Variable | Default |
|---|---|
| `DATABASE_URL` | none (required; or `DB_HOST`, `DB_NAME`, `DB_USERNAME`, `DB_PASSWORD`) |
| `INTERNAL_API_TOKEN` | none (required to start the API) |
| `LLM_PROVIDER` | `fake` (`anthropic` for real Claude, which needs `ANTHROPIC_API_KEY`) |
| `LLM_MODEL` | `claude-haiku-5-5` |
| `KAFKA_BOOTSTRAP_SERVERS` | `localhost:9092` |
| `KAFKA_TOPIC` / `KAFKA_DLQ_TOPIC` | `incident-events` / `incident-events.DLQ` |
| `KAFKA_GROUP_ID` | `investigation-worker` |
| `CONSUMER_ENABLED` | `true` |
| `RETRY_MAX_ATTEMPTS` | `5` |
| `RETRIEVAL_WINDOW_BEFORE_MINUTES` / `..._AFTER_MINUTES` | `120` / `30` (log and metric search window around the incident) |
| `METRICS_PORT` | `9464` |
| `TRACING_EXPORT_ENABLED` | `false` |
| `LOG_LEVEL` | `INFO` |

## Docker

The worker is part of `incident-service/compose.yaml` (port 8001 on the host, 8000 in the
container). The container runs `alembic upgrade head` before starting uvicorn.

```powershell
cd ..\incident-service
docker compose up -d --build
docker compose logs -f investigation-worker
```
