# AI Incident Investigation Platform

A multi-tenant backend for recording and investigating production incidents. Milestone 1 (this
code) is a secure, tested REST service. Later milestones add AI-assisted investigation
(Kafka, RAG with pgvector, LangGraph agents).

## Architecture (Milestone 1)

```mermaid
flowchart LR
    Client -->|HTTPS + Bearer JWT| SF[Spring Security filter chain<br/>JWT validation, roles]
    SF --> C[IncidentController<br/>@Valid DTOs]
    C --> S[IncidentService<br/>@Transactional, tenant-scoped]
    S --> R[IncidentRepository<br/>Spring Data JPA]
    R --> DB[(PostgreSQL 18<br/>schema by Flyway)]
    C -. errors .-> EH[GlobalExceptionHandler<br/>RFC 9457 Problem Details]
```

- **Controller**: HTTP only. Maps DTOs, reads the caller's tenant from the JWT, returns status codes.
- **Service**: business rules (new incidents start `OPEN`, status changes), always scoped to one tenant.
- **Repository**: Spring Data JPA; queries derived from method names (`findByIdAndTenantId`).
- **Database**: PostgreSQL; the schema is versioned SQL migrations run by Flyway; Hibernate only validates it.

## Tech stack

Java 17 · Spring Boot 4.1 (Web MVC, Data JPA, Validation, Security OAuth2 Resource Server) ·
PostgreSQL 18 · Flyway · JUnit 5, Mockito, MockMvc, Testcontainers · Maven

## API

All endpoints except health require `Authorization: Bearer <JWT>`. The token must contain a
`tenant_id` claim and a `roles` claim.

| Method | Path | Roles | Success | Errors |
|---|---|---|---|---|
| GET | `/api/v1/health` | public | 200 | |
| POST | `/api/v1/incidents` | RESPONDER, ADMIN | 201 | 400, 401, 403 |
| GET | `/api/v1/incidents` | VIEWER, RESPONDER, ADMIN | 200 (newest first) | 401, 403 |
| GET | `/api/v1/incidents/{id}` | VIEWER, RESPONDER, ADMIN | 200 | 400, 401, 403, 404 |
| PATCH | `/api/v1/incidents/{id}/status` | RESPONDER, ADMIN | 200 | 400, 401, 403, 404, 409 |
| POST | `/api/v1/dev/token` | public, **`dev` profile only** | 200 | 400 |

Create request:

```json
{ "title": "Payments failing", "description": "Checkout returns 500",
  "severity": "HIGH", "affectedService": "payment-service" }
```

Severity: `LOW | MEDIUM | HIGH | CRITICAL`. Status: `OPEN | INVESTIGATING | MITIGATED | RESOLVED`.

### Errors

Every error is an [RFC 9457](https://www.rfc-editor.org/rfc/rfc9457) Problem Details body
(`application/problem+json`):

```json
{ "status": 400, "title": "Validation failed", "detail": "One or more fields are invalid.",
  "instance": "/api/v1/incidents",
  "errors": [ { "field": "title", "message": "must not be blank" } ] }
```

| Status | When |
|---|---|
| 400 | Invalid body, malformed JSON, unknown enum value, id that is not a UUID |
| 401 | Missing, expired, wrongly signed or foreign-issuer token, or token without `tenant_id` |
| 403 | Authenticated but the role is not allowed |
| 404 | Incident does not exist **or belongs to another tenant** (existence is not revealed) |
| 409 | Concurrent update detected by optimistic locking (`@Version`) |
| 500 | Unexpected error (logged server-side; no internal details returned) |

## Security model

- **Authentication**: the service is an OAuth2 resource server. It validates HS256-signed JWTs
  (signature, expiry, issuer `incident-platform`). In production an identity provider issues the
  tokens; locally the `dev`-profile-only `/api/v1/dev/token` endpoint does.
- **Tenant isolation**: the tenant comes only from the verified token's `tenant_id` claim. Every
  query filters by it.
- **RBAC**: the `roles` claim maps to `ROLE_*` authorities; rules are centralised in `SecurityConfig`.
- **Secrets**: `DB_PASSWORD` and `JWT_SECRET` come from environment variables, have no defaults, and
  the app refuses to start without them.

## Running locally (Windows PowerShell)

Prerequisites: Java 17, PostgreSQL running on `localhost:5432`, Docker Desktop (for integration tests).

One-time database setup:

```powershell
$psql = "C:\Program Files\PostgreSQL\18\bin\psql.exe"
& $psql -U postgres -c "CREATE ROLE incident_app WITH LOGIN PASSWORD '<choose-a-password>';"
& $psql -U postgres -c "CREATE DATABASE incident_platform OWNER incident_app;"
```

Start the app (Flyway creates/upgrades the schema on startup):

```powershell
cd incident-service
$env:DB_PASSWORD = "<the password above>"
$env:JWT_SECRET  = "<any string of at least 32 characters>"
$env:SPRING_PROFILES_ACTIVE = "dev"   # enables the local token endpoint
.\mvnw.cmd spring-boot:run
```

Get a token and call the API:

```powershell
$token = (Invoke-RestMethod -Method Post http://localhost:8080/api/v1/dev/token `
  -ContentType "application/json" `
  -Body '{"subject":"alice","tenantId":"acme","roles":["RESPONDER"]}').accessToken

Invoke-RestMethod -Method Post http://localhost:8080/api/v1/incidents `
  -Headers @{ Authorization = "Bearer $token" } -ContentType "application/json" `
  -Body '{"title":"Payments failing","severity":"HIGH","affectedService":"payment-service"}'
```

Optional overrides: `DB_URL` (default `jdbc:postgresql://localhost:5432/incident_platform`),
`DB_USERNAME` (default `incident_app`).

## Tests

```powershell
cd incident-service
.\mvnw.cmd test
```

| Layer | Classes | What they prove |
|---|---|---|
| Unit | `IncidentServiceTest` | Business logic with a mocked repository (no Spring, no DB) |
| Web slice | `IncidentControllerTest`, `IncidentControllerValidationTest`, `IncidentErrorHandlingTest`, `RoleBasedAccessTest` | HTTP status codes, JSON, validation, error bodies, role rules (`@WebMvcTest`, mocked service) |
| Security | `JwtAuthenticationTest`, `DevTokenControllerTest` | Real signed tokens: valid / expired / wrong key / wrong issuer / no tenant / roles |
| Integration | `IncidentApiIntegrationTest` | Full stack on real PostgreSQL in Docker (Testcontainers): persistence, optimistic locking, tenant isolation |

Integration tests are skipped automatically when Docker is not running. Other tests use in-memory
H2 in PostgreSQL mode and still run the real Flyway migrations.

## Project structure

```
incident-service/src/main/java/com/sandeep/incidentplatform/
  controller/   IncidentController, HealthController
  dto/          request/response records with validation
  exception/    GlobalExceptionHandler, IncidentNotFoundException
  model/        Incident (JPA entity), IncidentSeverity, IncidentStatus
  repository/   IncidentRepository (Spring Data JPA)
  security/     SecurityConfig, JwtProperties, Role, TenantResolver, DevTokenController
  service/      IncidentService
incident-service/src/main/resources/db/migration/   Flyway SQL migrations (V1, V2)
docs/milestone-1-study-guide.md                      design decisions explained
```

## Roadmap

- **M1 Reliable backend**: CRUD, validation, JPA + PostgreSQL + Flyway, error handling,
  integration tests, JWT auth, tenant isolation, RBAC ✅
- **M2 Investigation**: Kafka, async processing, idempotency, retries/DLQ, Python/FastAPI, RAG,
  pgvector, LangGraph agents, evidence-backed hypotheses, evaluation
- **M3 Deployed app**: React, Docker, CI/CD, AWS, Terraform, Kubernetes
- **M4 Production quality**: caching, observability, performance, reliability
