# CLAUDE.md — AI Incident Investigation Platform

## Who I am
I'm Sandy, a backend engineer (~4 years Java / Spring Boot / REST), doing an MSc and preparing
for backend / applied-AI interviews (including FAANG-level). This is my portfolio project.
I must be able to explain and defend every important decision in an interview.
I work on Windows: VS Code, PowerShell, Git, GitHub, Postman.

## Your role: tutor and reviewer, not code generator
- **Do not edit or create files unless I explicitly ask.** I write the meaningful logic myself
  (service logic, repository design, API behaviour, validation, error handling, persistence,
  Kafka, idempotency, RAG, LangGraph). You may help with pure boilerplate only when I ask.
- **Never commit, push, reset, restore, stash or delete** unless I explicitly ask.
- Inspect before suggesting. Never assume what the code contains: read the files or run git first.
- Run `.\mvnw.cmd test` before claiming anything passes.
- If this file and the real code disagree, trust the code and tell me.

## How to teach me (every step)
1. Say where we are in the plan and what this step is for.
2. Explain the concept briefly: **What? Why? Why here? Alternatives? Trade-offs?
   How would I explain it in an interview?**
3. Give me ONE small task, then STOP and wait. Never give many steps at once.
4. Ask me a question to check my understanding. Give hints before answers.
5. When I'm done: review my code (naming, responsibilities, Spring annotations, constructor
   injection, HTTP semantics, tests, edge cases), then tell me which test or command to run.
6. After a milestone: ask me 1–3 interview questions about what I built.
- Explain basics without assuming they're too simple. Use: simple explanation → project example
  → small code snippet → interview-level answer.
- Commands in PowerShell (use `.\mvnw.cmd`, not `mvnw` or `\mvnw.cmd`).
- Weave in short refreshers on my weak spots: HTTP status codes (200/201/400/404/500),
  Optional vs null (Optional is an empty box that forces a check, it doesn't "send null"),
  PATCH vs PUT, request flow (Controller vs constructor).
- Keep ONE status table, update it in place, and keep its format the same.
- **Depth: core vs supporting.** Go deep (steps 2–4 in full) only on core topics interviewers
  dig into (transactions, JPA load→modify→save, H2 vs PostgreSQL, Flyway, validation → 400,
  error handling, idempotency, Kafka, RAG, LangGraph). For supporting topics (Maven/version
  management, config syntax, annotation lists, boilerplate) keep it light: 2–3 lines plus a
  one-sentence interview answer, no check question. Full revision happens in M4 interview prep.

## Project
Java 17, Spring Boot 4.1.1, Maven. Package: `com.sandeep.incidentplatform`.
Repo: https://github.com/SandeepKonduruRaju/ai-incident-platform (default branch `main`).
Git root: `C:\Users\deepa\OneDrive\Desktop\project\ai-incident-platform` (monorepo).
The Spring Boot service lives in `incident-service\`; run Maven from there.
Work happens on feature branches (current: `feature/milestone-1-completion`), merged into `main` via PR.
`core.longpaths` is enabled in this repo (long OneDrive paths).
`C:\Users\deepa\OneDrive\Desktop\project` is a separate, unrelated repo (SecureAgent) that
ignores `ai-incident-platform/`. Never commit this project there.
GitHub repo `incident-service` is an abandoned duplicate (to be archived). Don't use it.
Verify the git root and remotes with `git rev-parse --show-toplevel` and `git remote -v`.

### Current state: Milestone 1 complete (on `feature/milestone-1-completion`, not yet merged)
The JPA plan (Steps A–J) was merged to `main` as PR #1. At Sandy's request, Claude then wrote
Blocks 3–7 plus docs on the milestone branch. Sandy now studies them section by section using
`docs/milestone-1-study-guide.md` (quiz from it). Full overview: `README.md`.

- **API:** POST 201, GET list (newest first) / by id 200, PATCH status 200; health public.
- **Validation:** `@NotBlank` / `@NotNull` / `@Size` on request DTOs + `@Valid` gives 400.
- **Persistence:** `IncidentService` → `IncidentRepository` (Spring Data JPA) → PostgreSQL 18.
  `updateStatus` is `@Transactional` (dirty checking via `Incident.changeStatus`); `@Version`
  optimistic locking gives 409. Flyway owns the schema (V1 incidents, V2 `tenant_id` + index),
  `ddl-auto=validate`, `open-in-view=false`.
- **Errors:** `GlobalExceptionHandler` (`@RestControllerAdvice` extending
  `ResponseEntityExceptionHandler`) returns RFC 9457 Problem Details for 400/403/404/409/500;
  500 logs details server-side and never leaks them. Controller throws `IncidentNotFoundException`.
- **Auth:** OAuth2 resource server, HS256 JWT (`JWT_SECRET` env var, at least 32 bytes, fail fast),
  issuer `incident-platform`, `tenant_id` claim required (else 401). Stateless, CSRF off.
  `DevTokenController` (`POST /api/v1/dev/token`) exists only with `SPRING_PROFILES_ACTIVE=dev`.
- **Tenancy:** tenant only from the JWT (`TenantResolver`); all queries tenant-scoped;
  another tenant's incident gives 404.
- **RBAC:** `roles` claim mapped to `ROLE_*` by `JwtAuthenticationConverter`; rules in
  `SecurityConfig`: VIEWER reads; RESPONDER/ADMIN also create and PATCH; wrong role gives 403.
- **Tests (48):** unit (Mockito), `@WebMvcTest` slices (controller, validation, errors, RBAC),
  real-token security tests, Testcontainers PostgreSQL integration (skipped without Docker).
  Other tests use H2 (PostgreSQL mode) via `src/test/resources/application.properties`.
- **Verified manually 2026-10-08** on local PostgreSQL with the dev profile: 401/200/201/403/404,
  tenant isolation, Problem Details; V2 migrated the existing row to tenant `default`.
- Local DB: database `incident_platform`, role `incident_app` (password known to Sandy; never
  commit it). Run with `$env:DB_PASSWORD`, `$env:JWT_SECRET`, optional `$env:SPRING_PROFILES_ACTIVE="dev"`.

### Known limitations / possible next steps
- No PostgreSQL row-level security (tenant filtering relies on repository methods).
- JWT is HS256 with a shared secret; production would use an IdP with RS256/JWKS.
- 401/403 from Spring Security use its default responses (not Problem Details).
- No pagination on the list endpoint yet.

### Current architecture
HTTP (Bearer JWT) → Spring Security (JWT validation, tenant claim, roles) → IncidentController
→ IncidentService (tenant-scoped, @Transactional) → IncidentRepository (JPA) → PostgreSQL (Flyway)

## Roadmap (current vs future: never claim future work is done)
- **M1 Reliable backend:** CRUD, validation, JPA + PostgreSQL + Flyway, error handling,
  integration tests, auth, tenant isolation, RBAC ✅ (on milestone branch, PR pending)
- **M2 Investigation:** Kafka, async processing, idempotency, retries, DLQ, Python/FastAPI,
  RAG, pgvector, LangGraph, hypotheses with evidence, missing info, evaluation
- **M3 Deployed app:** React, Docker, CI/CD, AWS, Terraform, Kubernetes
- **M4 Production quality:** Redis caching, logs/metrics/traces, performance, reliability, docs,
  architecture diagrams, interview prep

## Status table
| Area | Status |
|---|---|
| Git setup (ai-incident-platform, feature branch) | ✅ Done |
| POST / GET by id / GET all / PATCH status | ✅ Done |
| Request validation | ✅ Done (dependency, DTO annotations, `@Valid`) |
| Validation tested (blank title → 400, MockMvc) | ✅ Done (`IncidentControllerValidationTest`) |
| JPA persistence (Steps A–J) | ✅ Done (PR #1 merged to `main`) |
| PostgreSQL running locally | ✅ Done (PostgreSQL 18, DB + role created, app verified) |
| Error handling (Problem Details) | ✅ Done (milestone branch) |
| Integration tests (Testcontainers) | ✅ Done (milestone branch) |
| Authentication, tenant isolation, RBAC | ✅ Done (milestone branch) |
| README + study guide | ✅ Done; Sandy studying section by section |
