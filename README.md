# AI Incident Investigation Platform

[![CI](https://github.com/SandeepKonduruRaju/ai-incident-platform/actions/workflows/ci.yml/badge.svg)](https://github.com/SandeepKonduruRaju/ai-incident-platform/actions/workflows/ci.yml)

When something breaks in production, most of the first half hour goes on digging: what was deployed, what the logs
say, whether this has happened before. I built this project to find out how much of that digging an LLM can do
*reliably*, and just as importantly, how to make it say "I don't know" when the evidence isn't there.

Here's how it works. You report an incident. A Java API stores it, together with an investigation request, in one
transaction (a transactional outbox that feeds Kafka). A Python worker picks up the request, pulls that tenant's logs,
metrics, runbooks and past incidents with hybrid search, and asks Claude for a root cause, the contributing factors and
the steps to fix it. Every finding has to cite its evidence, and the citations are checked before anything is saved.
When the evidence is thin, you get an honest low-confidence answer instead of a confident guess. In the React UI, the
report sits next to its evidence: click a citation and both the sentence and its source light up.

The data is synthetic, since I don't have a real company's incidents to play with. The engineering around it, though
(multi-tenancy, retries, idempotency, observability, load testing), is built the way I'd want it in a real system.

## 60-second demo

It's 2 a.m. and someone reports "Payment requests failing after configuration deploy". A few seconds later the
investigation names the cause, a config change that dropped the connection pool from 40 to 10, with high confidence.
Every sentence points at the deploy log, the pool metric, the runbook or a matching past incident. A vaguer report,
"Checkout feels slow for some customers", gets "Low confidence — not enough evidence to confirm a cause", which is
exactly what it should say.

| | |
|---|---|
| ![Incident list](docs/screenshots/list-1440-light.png) | ![Confident investigation, citation selected](docs/screenshots/investigation-confident-1440-light.png) |
| ![Abstaining investigation](docs/screenshots/investigation-abstained-1440-light.png) | ![Report an incident](docs/screenshots/report-form-1440-light.png) |

These are real runs against Claude Haiku 5.5 on the demo tenant. To take them yourself, seed the tenant with
`python -m app.seed_demo` ([Demo data](#demo-data)), then run `npm run screenshots:demo` in `frontend/`. The script
only reads, and it also captures dark-mode and phone (390 px) versions.

## Architecture

```mermaid
flowchart LR
    B[Browser<br/>React UI] -->|same origin| N[ui: nginx<br/>static + /api proxy]
    N --> API[incident-service<br/>Spring Boot 4 · Java 17]
    API -->|one transaction| DB[(PostgreSQL 18 + pgvector<br/>incidents + outbox)]
    API <-->|cache, rate limits<br/>fail open| RD[(Redis 8)]
    DB -->|OutboxRelay| K[[Kafka<br/>incident-events]]
    K --> W[investigation-worker<br/>FastAPI · aiokafka]
    K -. poison / permanent errors .-> DLQ[[incident-events.DLQ]]
    W -->|superseded check| DB
    W --> R[Hybrid retrieval<br/>pgvector HNSW + tsvector<br/>RRF → cross-encoder rerank]
    R --> G[LangGraph<br/>retrieve → analyse → validate → repair]
    G -->|structured outputs| C[Claude Haiku 5.5]
    G --> WDB[(worker schema<br/>investigations, chunks)]
    API -->|GET internal API<br/>X-Internal-Token| W
```

Flows, data ownership and failure behaviour: [docs/architecture.md](docs/architecture.md). Decisions with their
alternatives: [docs/adr/](docs/adr/).

## Tech stack

**incident-service**: Java 17 · Spring Boot 4.1 (Web MVC, Data JPA, Security OAuth2 resource server,
Kafka) · Flyway · JUnit 5, MockMvc, Testcontainers.
**investigation-worker**: Python 3.13 · FastAPI · aiokafka · SQLAlchemy async + asyncpg · Alembic ·
pgvector · fastembed (bge-small embeddings, MiniLM cross-encoder, ONNX on CPU) · LangGraph · Anthropic
SDK · pytest + Testcontainers.
**frontend**: React 19 · TypeScript · Vite · CSS Modules · Vitest + Testing Library · Playwright · nginx
(non-root).
**Infrastructure**: PostgreSQL 18 + pgvector, Redis 8 (cache + rate limit), Kafka 4.1 (KRaft), Docker (multi-stage, non-root images on
ghcr.io), Docker Compose, GitHub Actions (tests, ruff, Trivy image scan).

## Key design decisions

Most of the effort went into the unglamorous parts: making sure no investigation is lost, duplicated or overwritten,
and that one tenant can never see another's data.

| Decision | Why |
|---|---|
| **Transactional outbox** | The incident and its event are committed together; a relay publishes to Kafka, so no event is lost and none is sent for a rolled-back write. |
| **Idempotent consumer** | At-least-once delivery + dedup on `eventId` → effectively-once processing. |
| **Retries + DLQ** | Transient errors back off with jitter; poison or permanent failures go to a dead-letter topic, and the offset is committed only after success or dead-lettering. |
| **Status-aware idempotency, `run_count` fencing** | A redelivered event re-runs only stale or unfinished investigations; every claim and save checks `run_count`, so a slow old run can never overwrite a newer one. |
| **Hybrid search + RRF** | Vector search finds meaning, full-text finds exact identifiers (`HikariPool`, `v4.1.2`); Reciprocal Rank Fusion merges them and a cross-encoder reranks the result. Per-type caps keep the evidence diverse. |
| **Structured outputs** | One Pydantic model generates the JSON schema sent to Claude and validates the answer; unknown citation labels trigger a single repair attempt. |
| **Tenant isolation** | The tenant comes only from the verified JWT and is in every query, including vector search and the worker's internal API; another tenant's incident is indistinguishable from a missing one (404). |
| **Prompt-injection defence** | Evidence is delimited and sanitised, and the prompt treats it as data; tested with injected log lines. |

For the decisions that took real thought, the ADRs record what I chose, what I rejected, and what it costs:

| ADR | Decision |
|---|---|
| [0001](docs/adr/0001-transactional-outbox.md) | Transactional outbox for investigation requests |
| [0002](docs/adr/0002-superseded-request-check.md) | Worker skips superseded requests by reading `outbox_events` (accepted coupling) |
| [0003](docs/adr/0003-fail-open-redis-circuit-breaker.md) | Redis is optional: fail open behind a circuit breaker |
| [0004](docs/adr/0004-cache-only-terminal-investigations.md) | Cache only COMPLETED/FAILED investigations |
| [0005](docs/adr/0005-abstain-over-hallucinate.md) | Abstain rather than guess; validate every citation |
| [0006](docs/adr/0006-not-started-and-retry.md) | NOT_STARTED status and retry through the outbox |
| [0007](docs/adr/0007-same-origin-no-cors.md) | Same origin for UI and API (no CORS) |

## Results

All the numbers below come from real runs, not targets.

**Tests** (all with the fake LLM, so they cost nothing; integration tests use Testcontainers):

| Suite | Tests |
|---|---|
| incident-service (`mvnw clean verify`) | 106 (unit, MockMvc slices, H2 and PostgreSQL/Redis/Kafka Testcontainers) |
| investigation-worker (`pytest`) | 314 passed, 3 skipped (the live-LLM tests, opt-in) |
| frontend (Vitest) | 68 |
| frontend (Playwright e2e, against the running stack) | 1 smoke test: login → report → Completed → select a citation |

**Load test** (k6 against the compose stack on one 8-vCPU laptop shared by every container and the load generator;
full report and caveats in [docs/load-test.md](docs/load-test.md)):

| Scenario | p95 | Errors | Result |
|---|---|---|---|
| End to end, 30 incidents/min (POST → Completed: median 1.1 s, p95 2.7 s) | 257 ms | 0 % | ✅ 150/150 investigations completed |
| Investigation reads, 20 req/s, cache **on** (hit ratio 0.98) | 44 ms | 0 % | ✅ |
| Investigation reads, 20 req/s, cache **off** | 1,042 ms | 0.1 % | ❌ |
| API mix, 10 → 100 VUs | 4,089 ms | 17.1 % | ❌ first bottleneck: the CPU-bound worker slows the synchronous read path |
| Spike, 10 → 200 VUs in 10 s | 1,491 ms | 3.2 % | ❌ API back to normal within 30 s; backlog drained in ~18 min |

Yes, three rows fail, and I've left them in on purpose: finding where it breaks was the point of the exercise. The
first bottleneck is the synchronous read from the API to the worker (fixing it is the first item in
[What I'd do next](#what-id-do-next)). The load test also caught a real bug: when Redis went down, the fail-open
logic sent every request straight to the worker at once. A circuit breaker fixed it
([ADR 0003](docs/adr/0003-fail-open-redis-circuit-breaker.md)).

## Evaluation (synthetic data)

28 Claude-generated cases (standard, paraphrased, no evidence, prompt injection) run end to end through the
production graph. Claude Haiku 5.5 does the investigating and an LLM judge scores the answers. Take these numbers
with a pinch of salt: the cases are small and clean, and the judge is the same model.

| | root cause correct | faithful findings | citations valid | injection resisted | abstained when no evidence | cost / investigation | latency p50 / p95 |
|---|---|---|---|---|---|---|---|
| overall (n=28) | **89%** (100% incl. partial) | **94%** | 100% | 2/2 | 2/2 | **$0.00067** | 7.3 s / 10.9 s |

Full report, per-case results and caveats (small N, same-model judge): [docs/evaluation.md](docs/evaluation.md).

## Quickstart (Windows PowerShell)

Prerequisites: Docker Desktop, Java 17, Python 3.13.

```powershell
# 1. The whole stack: PostgreSQL 5433, Kafka 9092, worker 8001, API 8080 (+ loads the synthetic evidence).
#    Local-only dev defaults; see incident-service/.env.example.
cd incident-service
$env:LLM_PROVIDER = "fake"            # canned answers, no API key, no cost ("anthropic" for real Claude)
docker compose up -d --build
docker compose ps                     # wait until incident-service is "healthy" (~40 s)

# Optional: run the API from source instead (docker compose stop incident-service first)
#   $env:DB_URL = "jdbc:postgresql://localhost:5433/incident_platform"; $env:DB_PASSWORD = "localpass"
#   $env:JWT_SECRET = "<32+ chars>"; $env:SPRING_PROFILES_ACTIVE = "dev"
#   $env:INTERNAL_API_TOKEN = "dev-only-internal-token-change-me"; .\mvnw.cmd spring-boot:run

# 2. Token, incident, investigation.
$token = (Invoke-RestMethod -Method Post http://localhost:8080/api/v1/dev/token -ContentType "application/json" `
  -Body '{"subject":"alice","tenantId":"acme","roles":["RESPONDER"]}').accessToken
$h = @{ Authorization = "Bearer $token" }
$incident = Invoke-RestMethod -Method Post http://localhost:8080/api/v1/incidents -Headers $h -ContentType "application/json" `
  -Body '{"title":"inventory-service pods restarting","description":"memory climbs before each restart","severity":"HIGH","affectedService":"inventory-service"}'
Invoke-RestMethod "http://localhost:8080/api/v1/incidents/$($incident.id)/investigation" -Headers $h   # repeat until COMPLETED
```

Tests:

```powershell
cd incident-service;      .\mvnw.cmd test                                   # Docker needed for integration tests
cd ..\investigation-worker; .\.venv\Scripts\python.exe -m pytest -q          # integration tests start containers
.\.venv\Scripts\python.exe -m pytest -m eval_smoke -q                        # eval pipeline, FakeLLM, ~20 s
```

### Demo data

A dev-only seed fills tenant `demo` with eight realistic incidents and the evidence that makes them investigable
([investigation-worker/app/demo_data.py](investigation-worker/app/demo_data.py)): a DB connection pool exhausted
after a config deploy (strong evidence, should be confident), checkout latency with almost no evidence (should
abstain), Kafka consumer lag after a rebalance, an expired internal TLS certificate, OOMKilled pods from a memory
leak, Redis evictions causing a cache stampede, payment-provider timeouts and a full log volume. Mixed severities and
statuses (set through `PATCH /api/v1/incidents/{id}/status`).

```powershell
cd investigation-worker
$env:DATABASE_URL = "postgresql+asyncpg://incident_app:localpass@localhost:5433/incident_platform"
.\.venv\Scripts\python.exe -m app.seed_demo --dry-run   # what it would do; writes nothing
.\.venv\Scripts\python.exe -m app.seed_demo             # ingest evidence, report the incidents (API on :8080)
```

It is not a migration and never runs on its own. It ingests the evidence first, with log and metric timestamps
anchored to the moment it runs (retrieval only looks 2 h back from an incident), then reports each incident through
the public API with a dev token. It is idempotent (titles that already exist in `demo` are skipped, and each request
carries a fixed `Idempotency-Key`) and prints ids and titles, never the token. Each reported incident starts a real
investigation: with `LLM_PROVIDER=anthropic` that costs about $0.0007 each.

## Observability

Metrics, traces and alerts run in an optional compose profile, so the default stack stays light.

```powershell
cd incident-service
$env:LLM_PROVIDER = "fake"; $env:TRACING_EXPORT_ENABLED = "true"   # send spans to the collector
docker compose --profile observability up -d --build
```

| What | URL | Notes |
|---|---|---|
| Grafana | http://localhost:3000 | `admin` / `$env:GRAFANA_ADMIN_PASSWORD` (dev-only default in compose.yaml); dashboard "AI Incident Platform" |
| Prometheus | http://localhost:9090 | targets, PromQL, firing alerts at `/alerts` |
| Jaeger | http://localhost:16686 | traces of both services |
| Metrics endpoints | `incident-service:8081/actuator/prometheus`, `investigation-worker:9464/metrics` | inside the Docker network only, never published on the host |

- **One trace per incident, end to end.** The POST's W3C `traceparent` is stored with the outbox row,
  the relay continues it in the Kafka record headers, and the worker's consume span is its child:
  HTTP request → outbox publish → `incident-events process` → investigation → graph nodes → `llm.generate`
  and SQL spans. The Java → worker read API is traced too. Every log line in both services has `traceId=`.
  Spans carry ids, counts, model, tokens and timings, never prompt, evidence or answer text.
- **Dashboard** (`observability/grafana/dashboards/`):
  - API rate, errors and p95 latency by route.
  - Pipeline: outbox backlog and publishes, Kafka consumer lag, DLQ messages.
  - Investigations: rate by status, p50/p95 duration, SLO stat, per-node p95.
  - LLM: p95 latency, tokens/min, cost/hour, errors by kind, repair and insufficient-evidence rates, retrieval.
- **Alerts** (`observability/prometheus/rules/`):

  | Alert | Fires when |
  |---|---|
  | `KafkaConsumerLagGrowing` | Consumer lag has kept growing for 10 minutes |
  | `DeadLetterMessages` | Any message has been dead-lettered |
  | `InvestigationFailureRateHigh` | More than 10% of investigations FAILED over 15 minutes |
  | `InvestigationLatencyP95High` | p95 investigation time is above 60 s for 10 minutes |
  | `LLMConfigError` | Any LLM authentication or configuration error |
  | `LLMCostPerHourHigh` | LLM spend in the last hour exceeds `$env:LLM_COST_ALERT_USD_PER_HOUR` (default $1) |
  | `ScrapeTargetDown` | Prometheus can't scrape a service |

- **SLO:** 95% of investigations finish in under 30 s over 7 days. The SLI comes from the
  `investigation_duration_seconds` histogram, with recording rules
  `sli:investigation_latency_under_30s:ratio_rate{5m,1h,7d}`. `InvestigationLatencySLOBreached` fires when
  the 7-day ratio drops below 0.95.

## Kubernetes (local, kind)

The same stack on a 3-node [kind](https://kind.sigs.k8s.io/) cluster (1 control plane + 2 workers), with Kustomize
manifests in `k8s/` (`base` + `overlays/local`).

**Prerequisites:** Docker Desktop (about 10 GB of memory), `kind` (`winget install --id Kubernetes.kind -e`) and
`kubectl` (bundled with Docker Desktop; `kubectl -k` provides Kustomize). Stop the compose stack first.

```powershell
.\scripts\k8s-up.ps1     # cluster + ingress-nginx + metrics-server, build/load images (:<git sha>), secrets, apply, wait
.\scripts\k8s-down.ps1   # deletes the kind cluster (and everything in it)
```

Then use the API through the ingress at http://localhost/api/... (same calls as the quickstart above, on port 80).

| Manifest | What it runs |
|---|---|
| `postgres.yaml` | PostgreSQL 18 + pgvector StatefulSet (2 Gi PVC), `pg_isready` probes |
| `kafka.yaml` | Kafka 4.1 KRaft single broker StatefulSet (2 Gi PVC), advertised as `kafka:9092` |
| `kafka-topics-job.yaml` | Job: creates `incident-events` and its DLQ (3 partitions), idempotent |
| `investigation-worker.yaml` | 3 replicas (one per partition), migrations in an initContainer, `/livez` liveness, `/health` readiness |
| `worker-ingest-job.yaml` | Job: loads the synthetic evidence (idempotent upserts) |
| `incident-service.yaml` | 2 replicas, rolling update with `maxUnavailable: 0`, actuator probes, PodDisruptionBudget, HPA (CPU 70%, 2–5) |
| `ingress.yaml` | `/api` → incident-service only (the worker API, actuator, Postgres and Kafka stay internal) |
| `network-policies.yaml` | Worker API only from incident-service; Postgres/Kafka only from labelled clients; API only from ingress-nginx |

- **Security:**
  - Every pod runs as non-root with no privilege escalation, all capabilities dropped and a seccomp profile. The
    namespace enforces the Pod Security "restricted" standard.
  - All root filesystems are read-only; `/tmp` and the Kafka config directory are emptyDir volumes.
  - Secrets come from `scripts/k8s-secrets.ps1` (built from the `.env` files) and are never committed.
    `k8s/secrets.example.yaml` shows the key names.
- **Local-only caveats:**
  - Postgres and Kafka run as single replicas without backups, TLS or authentication.
  - ingress-nginx (now retired upstream) is used for local routing only.
  - metrics-server skips kubelet certificate checks (kind's kubelet certificates are self-signed).
  - Images are loaded into kind directly, without a registry.
- **On AWS this maps to:**

  | Local (kind) | AWS |
  |---|---|
  | kind cluster | EKS |
  | Postgres StatefulSet | RDS / Aurora PostgreSQL with pgvector |
  | Kafka StatefulSet | Amazon MSK |
  | ingress-nginx | AWS Load Balancer Controller (ALB) or Gateway API |
  | Script-made Secrets | AWS Secrets Manager via External Secrets |
  | `kind load` images | ECR images pushed by CI (`ghcr.io` today) |

  The app Deployments, probes, PDB, HPA and NetworkPolicies carry over unchanged in a new overlay.
- **CI:** the "Kubernetes manifests" job renders the overlay and validates it with kubeconform (strict, Kubernetes 1.37
  schemas), with no cluster and no secrets.

## Continuous Deployment (GitOps)

Deployments are **pulled**, not pushed. CI never touches the cluster; Argo CD runs inside it and keeps it equal to
`k8s/overlays/gitops` on `main`.

```mermaid
flowchart LR
    Dev[git push / merge to main] --> CI[GitHub Actions CI<br/>tests, lint, image build + Trivy]
    CI -->|push :full-sha| GHCR[(GHCR<br/>incident-service, investigation-worker)]
    CI -->|opens PR: bump newTag<br/>in k8s/overlays/gitops| PR[deploy gitops PR]
    PR -->|review + merge = deploy| Main[(main branch)]
    Argo[Argo CD in the cluster] -->|watches| Main
    Argo -->|sync waves: data, Jobs, apps| K8s[kind / EKS cluster]
    K8s -->|pull images| GHCR
```

1. **Images:** on every push to `main` that changes app code, CI builds, scans and pushes both images to GHCR,
   tagged with the full commit SHA.
2. **Bump PR:** the `gitops-bump` job opens (or updates) one PR, on branch `gitops/image-bump`, that changes
   `k8s/overlays/gitops/kustomization.yaml` (via `scripts/gitops-bump.py`). Main is never pushed to directly.
   - The two app image tags always move to the new commit.
   - The ingest Job's image tag and its `synthetic-data-sha256` annotation move only when
     `investigation-worker/data/synthetic` changed. A release therefore doesn't re-run the slow ingest; new data
     does.
3. **Deploy:** merging that PR is the deployment. Argo CD (automated sync, prune, selfHeal) applies it in sync
   waves:
   1. Postgres and Kafka;
   2. the topics Job;
   3. the ingest Job, which runs migrations;
   4. the two Deployments;
   5. Ingress, HPA and PDB.
4. **Drift:** a manual `kubectl edit` is reverted by selfHeal. incident-service's replica count is excluded,
   because the HPA owns it.
5. **Rollback:** `git revert` the merge commit of the bad bump PR (via a PR). Argo CD syncs the previous SHA back.
   Nothing needs to be rebuilt: ECR/GHCR still hold the old images.

**Install locally:** `.\scripts\argocd-up.ps1`. It creates the cluster (`k8s-up.ps1 -SkipApps`: add-ons, namespace,
secrets), installs Argo CD v3.5.6 and applies `k8s/argocd/`. Then:
- **UI:** `kubectl -n argocd port-forward svc/argocd-server 8443:443`, open https://localhost:8443, user `admin`.
- **Password:** the script prints the command that reads it from `argocd-initial-admin-secret`.

Don't also run `k8s-up.ps1` without `-SkipApps` on the same cluster: both would manage the same resources.

**Secrets are not in git.** `scripts/k8s-secrets.ps1` creates them before Argo CD syncs, and the AppProject forbids
Secret resources from the repo. It's a pragmatic local trade-off: a new cluster needs the script once, and secret
rotation is outside GitOps. Production uses Sealed Secrets (encrypted in git) or External Secrets (synced from AWS
Secrets Manager).

**On EKS:**
- The same Application and overlay pattern, with an `overlays/eks` directory.
- Argo CD is installed in the EKS cluster.
- Images come from ECR instead of GHCR (the bump job targets ECR).
- Secrets come from External Secrets Operator reading Secrets Manager.
- An ALB Ingress replaces ingress-nginx.

## AWS (Terraform)

`infra/` describes an AWS deployment as code:
- **Compute and data:** ECS Fargate, RDS PostgreSQL + pgvector, a single-broker Kafka task, a public ALB → API only.
- **Secrets and access:** Secrets Manager, and GitHub OIDC roles trusted only for `main`.
- **Cost guard:** a $5 budget.

CI checks it without AWS credentials (fmt, validate, tflint, trivy). Deploy and destroy are manual, disabled-by-default
workflows. See [infra/README.md](infra/README.md) for the architecture, estimated costs (≈ $4/day while running) and
the bootstrap → deploy → destroy-the-same-day steps.

## Frontend

A React + TypeScript UI in [frontend/](frontend/), designed as an annotated case file for an on-call engineer:
- **Incidents:** the whole row is a link; severity as a coloured edge plus a word; status with a small indicator;
  relative times with the full date as a tooltip; search and severity/status filters; an empty state.
- **Report an incident:** client-side validation with the API's rules (400 field errors and the 429 message inline),
  service suggestions from existing incidents, an `Idempotency-Key` per report and a 15 s timeout that says the
  incident may have been saved and that reporting again is safe.
- **Investigation:** polls `GET .../investigation` honouring `Retry-After` until it is final. The report (serif) sits
  next to a sticky evidence rail; citations are numbered marks `[1] [2]`, and selecting one highlights the cited
  sentence and its evidence with a marker colour. On phones the evidence opens in a focus-trapped bottom sheet (the
  page behind it is `inert`). Confidence is written out; NOT_STARTED and FAILED offer a Retry button.
- **Everywhere:** light/dark/system theme, self-hosted fonts, visible focus, WCAG AA contrast (checked), reduced motion
  respected, per-page titles, errors with the API's message and the request id.

| Decision | Choice and why |
|---|---|
| Token storage | In memory (React state) only, never localStorage: an XSS bug cannot read a persisted token later. Cost: a refresh signs you out. A real deployment would use an identity provider with an HttpOnly cookie or a BFF. |
| Serving | nginx (non-root, pinned) serves the build and proxies `/api` to incident-service: one origin, so **no CORS** in containers. The Vite dev server proxies `/api` the same way. In Kubernetes the Ingress routes `/` to the UI and `/api` to incident-service on the same host. |
| CORS | Off by default (`CORS_ALLOWED_ORIGINS` empty: every cross-origin request is refused). Only for a UI on another origin in development, e.g. `$env:CORS_ALLOWED_ORIGINS = "http://localhost:5173"`. |
| API types | Hand-written from the Java DTOs ([frontend/src/api/types.ts](frontend/src/api/types.ts)): the API is small, and springdoc would add a dependency and a public spec endpoint to a Boot 4 service for little gain. |
| Styling | CSS Modules (built into Vite) and one tokens file (`src/styles/tokens.css`) for colours, type and spacing: scoped class names, light/dark, no UI kit. |
| Routing | A 60-line History-API router for four routes instead of a routing library. |

```powershell
# Development (hot reload) against the API on :8080
cd frontend; npm ci; npm run dev                      # http://localhost:5173 (proxies /api)
npm run lint; npm run typecheck; npm test; npm run build

# In compose: the stack now includes the UI
cd incident-service; $env:LLM_PROVIDER = "fake"; docker compose up -d --build
# -> http://localhost:3001  (sign in as any user/tenant; RESPONDER can create incidents)

# E2E smoke test against the running compose stack (login -> create -> COMPLETED)
cd frontend; npx playwright install chromium; npm run e2e
```

## API

| Method | Path | Roles |
|---|---|---|
| POST | `/api/v1/incidents` | RESPONDER, ADMIN; per-tenant rate limit (429 + `Retry-After`). Optional `Idempotency-Key` (1-255 visible ASCII characters, per tenant): 201 the first time; the same key and body again → **200** with the original incident and `Idempotent-Replayed: true` (nothing new created or enqueued); the same key with a different body → 422 |
| GET | `/api/v1/incidents`, `/api/v1/incidents/{id}` | VIEWER, RESPONDER, ADMIN |
| PATCH | `/api/v1/incidents/{id}/status` | RESPONDER, ADMIN |
| GET | `/api/v1/incidents/{id}/investigation` | VIEWER, RESPONDER, ADMIN (PENDING/RUNNING carry `Retry-After`; worker down → 503; `NOT_STARTED` when no run exists and none is on its way) |
| POST | `/api/v1/incidents/{id}/investigation/retry` | RESPONDER, ADMIN; only from `NOT_STARTED` or `FAILED` (409 otherwise); 202 + a new event through the outbox; its own per-tenant rate limit |
| POST | `/api/v1/dev/token` | public, `dev` profile only |

Errors are RFC 9457 Problem Details; every response carries an `X-Request-Id` that is propagated to the
worker's logs.

## Known limitations

Things I know are weak, so you don't have to find them:

- **Synthetic data only**: the evaluation set is small and clean (one planted cause per incident), so the
  headline numbers carry wide error bars.
- **Reads couple to the worker**: the investigation endpoint calls the worker synchronously (503 when it is
  down); an `InvestigationCompleted` event with a read model would remove that coupling.
- **Shared-secret service auth**: one static `X-Internal-Token`; no mTLS or per-service identity yet.
- **Time-windowed evidence**: logs and metrics are searched around `createdAt`; an incident filed long
  after its symptoms gets only runbooks and past incidents.
- **Dev-only sign-in in the UI**: the frontend uses the `dev` token endpoint; there is no identity provider yet.
- **Worker reads incident-service's outbox**: the superseded-request check queries `public.outbox_events` directly
  (an accepted coupling, [ADR 0002](docs/adr/0002-superseded-request-check.md)).
- **Citations are checked for existence, not support**: 6% of findings in the evaluation cite evidence that does not
  fully support them ([ADR 0005](docs/adr/0005-abstain-over-hallucinate.md)).
- **Outbox grows forever**: published rows are never deleted.

## What I'd do next

None of this is built yet:

- **Event-driven read model.** The worker publishes `InvestigationCompleted`/`Failed`; incident-service stores the
  result in its own table. Reads stop calling the worker synchronously (the load test's first bottleneck), the cache
  becomes optional, and the superseded check could move to incident-service.
- **Outbox retention.** A scheduled job deletes rows published more than N days ago (in batches, using the
  `published_at` index), so the table and its indexes stay small.
- **Relay publishing outside the database transaction.** Today the relay holds the rows' locks while it waits for
  Kafka. Claim a batch (mark it in flight with a lease), commit, publish, then mark it published; or use change data
  capture (Debezium) on the outbox table.
- **Citation-supports-claim validation.** A second, cheap pass that checks each finding against the text of the
  evidence it cites, and drops or flags unsupported findings before saving, closing the 6% gap above.

## Repository layout

```
incident-service/       Spring Boot API, Flyway migrations, outbox relay, compose.yaml (whole stack)
frontend/               React + TypeScript UI (Vite), nginx image, Vitest + Playwright tests
  scripts/              read-only demo screenshot script
loadtest/               k6 scenarios (milestone 4), results in docs/load-test.md
investigation-worker/   Kafka consumer, ingestion, retrieval, LangGraph investigation, internal API, eval
  app/seed_demo.py      dev-only demo seed (tenant "demo")
  data/synthetic/       generated logs, metrics, runbooks, past incidents (+ golden labels)
  data/eval/            evaluation cases
docs/                   architecture, ADRs, evaluation and load-test reports, screenshots, study guide
```

## Roadmap

I built this in four milestones, each adding a layer on top of the last:

- **M1** Secure REST backend: JWT, RBAC, tenant isolation, Flyway, Testcontainers ✅
- **M2** AI investigation: outbox, Kafka, idempotency, DLQ, hybrid RAG, LangGraph + Claude, evaluation ✅
- **M3** Deployed app: CI/CD, Docker images, AWS, Terraform, Kubernetes, UI ✅
- **M4** Production quality: caching, rate limits, observability, load testing, reliability (NOT_STARTED + retry,
  superseded requests, idempotent create), UI redesign, docs ✅
