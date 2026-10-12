# Milestone 1 study guide

How to use this: study one section at a time, in order. For each one, open the files listed, read
the code with the explanation next to it, then answer the questions out loud **without looking**.
Every section ends with a model interview answer. Say it in your own words, don't memorise it.

Run the tests for a section with `.\mvnw.cmd test -Dtest=ClassName` (from `incident-service\`).

---

## 1. REST API basics and the request flow

**Files:** `controller/IncidentController.java`, `dto/*.java`

**What happens on `POST /api/v1/incidents`:**
1. Spring Security checks the JWT (section 7). No valid token: 401, the controller never runs.
2. Spring MVC routes the request to `createIncident(...)` by path + HTTP method.
3. `@RequestBody` turns JSON into a `CreateIncidentRequest` record (Jackson).
4. `@Valid` checks the annotations on that record. If they fail: 400 (section 3).
5. The controller calls the service, gets an `Incident` entity, maps it to an `IncidentResponse`.
6. `@ResponseStatus(HttpStatus.CREATED)` makes it a 201.

**Key decisions:**
- **DTOs separate from the entity.** The API contract (`IncidentResponse`) can change independently
  of the table, and internal fields like `version` and `tenantId` are never exposed.
- **PATCH, not PUT, for status.** PUT means "replace the whole resource"; we change one field.
- **Status codes:** 201 for create (something new exists), 200 for reads/updates, 404 for missing.

**Questions:** What is the difference between 400 and 404? Why return 201 rather than 200 on create?
Why is the constructor (dependency injection) not part of the request flow?

> **Interview answer:** "Requests go through the security filter chain first, then the controller,
> which only handles HTTP concerns: binding and validating DTOs, calling the service, choosing status
> codes. DTOs keep the API contract decoupled from the persistence model."

---

## 2. JPA entity and repository

**Files:** `model/Incident.java`, `repository/IncidentRepository.java`

- `@Entity` + `@Table("incidents")`: class = table, **object = row**, field = column.
- `@Id UUID id`: primary key, generated in Java (`UUID.randomUUID()`) before saving.
- `@Enumerated(EnumType.STRING)`: stores `"HIGH"`, not `2`. `ORDINAL` breaks silently if the enum is
  reordered.
- **`protected` no-arg constructor:** JPA creates an empty object, then fills fields by reflection.
  `protected` (not `public`) stops our code creating half-empty incidents; not `private`, because
  Hibernate's proxy subclasses must call it.
- **`equals`/`hashCode` on `id`:** safe because the id exists before the first save.
- `IncidentRepository extends JpaRepository<Incident, UUID>`: `save`, `findById`, `findAll`,
  `count`, paging... for free. Spring Data **generates the implementation at startup** (a proxy over
  `SimpleJpaRepository` + `EntityManager`). Methods like `findByIdAndTenantId` are **derived queries**:
  Spring Data builds the SQL from the method name.

**Questions:** Why does JPA need a no-arg constructor? Who implements `IncidentRepository`? What
would go wrong with `EnumType.ORDINAL`?

> **Interview answer:** "The entity maps one class to one table. I keep a protected no-arg
> constructor for Hibernate and one public constructor that creates a complete, valid incident.
> The repository is just an interface; Spring Data generates the implementation, including queries
> derived from method names."

---

## 3. Validation

**Files:** `dto/CreateIncidentRequest.java`, `dto/UpdateIncidentStatusRequest.java`,
`IncidentControllerValidationTest.java`

- Annotations **declare** rules: `@NotBlank` (rejects null, `""` and `"   "`), `@NotNull` (any type,
  e.g. enums), `@Size(max = …)` (matches the column length, so a too-long value is a 400, not a DB error).
- `@Valid` on the `@RequestBody` **triggers** them, inside Spring MVC, before the method runs.
- The DB constraints (`NOT NULL`) are the last line of defence, not the validation layer.

**Questions:** What happens if you remove `@Valid` but keep the annotations? Why `@NotNull` and not
`@NotBlank` for `severity`? Why must invalid input be a 400 and not a 500?

> **Interview answer:** "I validate at the boundary with Bean Validation on the request DTOs and
> `@Valid`. Bad client input becomes a 400 before it reaches the service or the database; database
> constraints stay as a safety net."

---

## 4. Service layer, transactions, dirty checking, optimistic locking

**Files:** `service/IncidentService.java`, `model/Incident.java` (`changeStatus`, `@Version`),
`IncidentServiceTest.java`

- **Constructor injection** of `IncidentRepository`: dependencies are explicit and `final`, and the
  class is testable with `new IncidentService(mockRepository)`.
- **Why the in-memory map was removed:** lost on restart, not shared between instances, mixed storage
  with business logic, hard to test.
- **`updateStatus` is `@Transactional`:** load the incident → `incident.changeStatus(newStatus)` →
  at commit Hibernate compares the entity with its snapshot (**dirty checking**) and runs the
  `UPDATE`. No `save()` call needed.
- **`changeStatus()` instead of a setter:** the entity guards its own rules (status not null; future
  rules like "can't reopen RESOLVED" go here).
- **`@Version`** (optimistic locking): every update runs
  `UPDATE … SET version = version + 1 WHERE id = ? AND version = ?`. If someone else updated first,
  0 rows match → `ObjectOptimisticLockingFailureException` → **409 Conflict**. Bonus: with a non-null
  pre-assigned id, Spring Data would think a new entity is existing and run a `SELECT` before
  `INSERT`; a null `version` tells it "this is new".
- **Optimistic vs pessimistic locking:** optimistic = no DB locks, detect conflicts at write time
  (good when conflicts are rare); pessimistic = `SELECT … FOR UPDATE`, blocks others (good when
  conflicts are frequent).

**Questions:** Why is there no `save()` in `updateStatus`? What does a 409 mean to the client? When
would you choose pessimistic locking?

> **Interview answer:** "The status update loads the entity inside a transaction and changes it
> through a domain method; dirty checking persists it on commit. `@Version` gives optimistic locking,
> so two concurrent updates can't silently overwrite each other: the loser gets a 409 and retries."

---

## 5. Database configuration, Flyway, H2 vs PostgreSQL

**Files:** `src/main/resources/application.properties`, `db/migration/V1__…sql`, `V2__…sql`,
`src/test/resources/application.properties`

- **Secrets from env vars:** `DB_PASSWORD`, `JWT_SECRET` have no defaults, so the app fails fast
  rather than starting with a guessable credential. Nothing secret is committed.
- **Flyway owns the schema:** versioned SQL files run once, in order, recorded in
  `flyway_schema_history`. Hibernate uses `ddl-auto=validate`: it checks the tables match the
  entities and never changes them. `update`/`create` are fine for prototypes but can't do safe data
  migrations, can't be reviewed, and can drop data.
- **V2 is a safe migration on existing data:** add `tenant_id` with a default (existing rows become
  `default`), then drop the default so new rows must set it.
- **`open-in-view=false`:** no lazy-loading DB access during JSON rendering; transactions end in the
  service.
- **H2 vs PostgreSQL:** fast H2 (PostgreSQL mode) for most tests, zero setup, and it still runs the
  real migrations. Risk: H2 is not PostgreSQL (dialect drift, no `jsonb`/pgvector). Covered by
  Testcontainers (section 6).
- **Lesson learned:** with no datasource URL, tests passed (Spring Boot auto-configured H2 from the
  test classpath) while the real app failed to start. Green tests didn't prove the app could boot.

**Questions:** Why not `ddl-auto=update`? What happens if you edit V1 after it was applied? (Flyway's
checksum fails: you always add a new migration instead.) Why does the app refuse to start without
`DB_PASSWORD`?

> **Interview answer:** "Schema changes are versioned Flyway migrations, reviewed like code, and
> Hibernate only validates. Credentials come from the environment and the app fails fast without them."

---

## 6. Testing strategy

**Files:** all of `src/test/java/...`

| Type | Tool | Speed | What it proves |
|---|---|---|---|
| Unit | JUnit + Mockito (`IncidentServiceTest`) | ms | logic, with the repository mocked |
| Web slice | `@WebMvcTest` + `@MockitoBean` + MockMvc | ~s | routing, JSON, status codes, validation, security rules |
| Full context | `@SpringBootTest` + H2 | ~s | wiring, real token validation, migrations |
| Integration | `@SpringBootTest` + Testcontainers PostgreSQL | ~10s | real persistence, locking, tenant isolation |

- **Why the first controller tests were not enough:** they called controller methods as plain Java,
  so `@ResponseStatus(201)`, `@Valid` and JSON were never exercised. MockMvc sends a real request
  through Spring MVC.
- **`@ServiceConnection`** points the app's DataSource at the container automatically.
- `@Testcontainers(disabledWithoutDocker = true)`: skipped, not failed, without Docker.
- `TestJwt` uses `jwt()` from spring-security-test to fake an authenticated user in web tests;
  `JwtAuthenticationTest` uses **real signed tokens** to test validation itself.

**Questions:** What does `@WebMvcTest` load and not load? Why mock the service in controller tests?
What does Testcontainers catch that H2 can't?

> **Interview answer:** "A test pyramid: fast unit tests for logic, web-slice tests for the HTTP
> contract, and a few Testcontainers integration tests on the real database for persistence,
> locking and tenant isolation."

---

## 7. Error handling

**Files:** `exception/GlobalExceptionHandler.java`, `IncidentErrorHandlingTest.java`

- `@RestControllerAdvice` = one place that turns exceptions into HTTP responses, for all controllers.
- Extends `ResponseEntityExceptionHandler`, so Spring MVC's own errors (malformed JSON, wrong types,
  unsupported media type) also become Problem Details.
- **RFC 9457 Problem Details** (`application/problem+json`): standard fields `type`, `title`,
  `status`, `detail`, `instance`; we add `errors` with field messages for validation.
- The controller throws `IncidentNotFoundException`; the advice maps it to 404. Controllers stay clean.
- **500s never leak internals:** the full exception is logged server-side; the client gets a
  generic message (stack traces/SQL in responses help attackers).

**Questions:** Why a global handler instead of try/catch in each controller? What belongs in a 500
response body, and what doesn't?

> **Interview answer:** "All errors go through one `@RestControllerAdvice` and come out as RFC 9457
> Problem Details, so clients handle one format. Expected errors map to precise status codes;
> unexpected ones are logged with full detail but returned as a generic 500."

---

## 8. Authentication with JWT

**Files:** `security/SecurityConfig.java`, `security/JwtProperties.java`,
`security/DevTokenController.java`, `JwtAuthenticationTest.java`

- **Resource server:** the service doesn't handle passwords or logins; it trusts tokens issued by an
  identity provider and **verifies** them on every request: signature (HS256 with `JWT_SECRET`),
  expiry, issuer, and that a `tenant_id` claim is present.
- **401 vs 403:** 401 = "who are you?" (no/invalid token); 403 = "I know who you are, but no".
- **Stateless, CSRF disabled:** no server session; the token is sent in a header, not a cookie, so
  CSRF (which abuses cookies the browser sends automatically) doesn't apply.
- **HS256 vs RS256:** HS256 = one shared secret signs and verifies (simple, fine when one party
  issues and verifies). RS256 = the IdP signs with a private key, services verify with the public key
  (JWKS). Better with an external IdP and many services: no shared secret to leak. Switching is a
  config change (`issuer-uri`/`jwk-set-uri`).
- **Dev token endpoint:** only exists under the `dev` profile (tested: 404 otherwise). Production
  would use Cognito/Keycloak/Auth0.
- **Limitation to know:** JWTs can't be revoked before expiry. Mitigate with short lifetimes and
  refresh tokens.

**Questions:** What exactly is checked when a token arrives? Why is the JWT secret's length
enforced? How would you move to an external identity provider?

> **Interview answer:** "The service is an OAuth2 resource server. Every request needs a bearer JWT,
> which is validated for signature, expiry, issuer and required claims; the app is stateless.
> Locally a dev-only endpoint issues tokens; in production an IdP would, with RS256 and JWKS."

---

## 9. Multi-tenancy (tenant isolation)

**Files:** `security/TenantResolver.java`, `service/IncidentService.java`,
`repository/IncidentRepository.java`, `V2__add_tenant_id_to_incidents.sql`,
`IncidentApiIntegrationTest.shouldIsolateIncidentsBetweenTenants`

- Model: **shared database, shared schema, `tenant_id` column** (the most common SaaS model).
  Alternatives: schema-per-tenant or database-per-tenant: stronger isolation, but harder to
  operate and migrate.
- The tenant comes **only from the verified JWT**, never from the body/URL, so a client can't
  claim someone else's tenant.
- Every repository call is tenant-scoped (`findByIdAndTenantId`, `findAllByTenantId…`).
- **Another tenant's incident → 404, not 403**, so attackers can't probe which ids exist.
- Two layers: a token without `tenant_id` fails validation (401); if one ever reached the
  controller, `TenantResolver` returns 403.
- Index `(tenant_id, created_at DESC)` keeps per-tenant listing fast.
- **Further hardening (not built):** PostgreSQL Row-Level Security, or a Hibernate tenant filter,
  so a forgotten `tenantId` in a new query can't leak data.

**Questions:** Why 404 instead of 403 across tenants? What's the risk of the shared-schema model,
and how would you reduce it? Why not let clients send `tenantId` in the body?

> **Interview answer:** "Shared schema with a tenant_id column. The tenant comes from a verified
> token claim, every query is scoped by it, and cross-tenant access returns 404 so existence isn't
> leaked. I'd add PostgreSQL row-level security as defence in depth."

---

## 10. RBAC (role-based access control)

**Files:** `security/Role.java`, `security/SecurityConfig.java`, `RoleBasedAccessTest.java`

- The `roles` claim (e.g. `["VIEWER"]`) maps to authorities `ROLE_VIEWER` via
  `JwtAuthenticationConverter`; `hasAnyRole("VIEWER", …)` checks `ROLE_VIEWER`.
- Rules are **centralised** in `SecurityConfig` (URL + HTTP method), easy to audit in one place.
  Alternative: `@PreAuthorize` on methods. That's better when rules depend on data ("only the
  incident owner may…").
- VIEWER reads; RESPONDER and ADMIN also create/change status. ADMIN is reserved for future admin-only
  operations.
- Wrong role → 403, and the service is never called (tests verify this).

**Questions:** Authentication vs authorization? URL rules vs `@PreAuthorize`: when would you use
each? Where do roles come from in production?

> **Interview answer:** "Roles come from a JWT claim and map to Spring authorities. Access rules are
> declared centrally per endpoint and method; a forbidden call is a 403 before any business code
> runs. For data-dependent rules I'd use method security."

---

## 11. Pagination

**Files:** `controller/IncidentController.listIncidents`, `dto/PageResponse.java`,
`repository/IncidentRepository.findAllByTenantId`, `service/IncidentService.findAll`

- `GET /api/v1/incidents?page=0&size=20` returns `{ items, page, size, totalElements, totalPages }`.
- **Why:** without it, one request loads every row: slow responses, high memory, and an easy
  denial-of-service. `size` is capped at 100; `@Min`/`@Max` on the `@RequestParam`s are checked by
  Spring MVC's method validation, so bad values are a 400 before the service runs.
- **`Pageable`** makes Spring Data add `ORDER BY … LIMIT … OFFSET …`; returning `Page` also runs a
  `COUNT(*)` for the totals.
- **Stable order:** sort by `createdAt DESC`, then `id`. Without a unique tie-breaker, rows with the
  same timestamp can appear on two pages or on none.
- **Own `PageResponse` record:** Spring's `Page` JSON is an internal structure that can change
  between versions; the API contract should be ours.
- **Offset vs cursor (keyset) pagination:** offset is simple and allows "jump to page 7", but deep
  pages get slower (the DB still walks the skipped rows) and inserts shift results between requests.
  Cursor pagination (`WHERE (created_at, id) < (:lastCreatedAt, :lastId) LIMIT 20`) is fast at any
  depth and stable, but only supports next/previous. Feeds and large tables use cursors.
- The `(tenant_id, created_at DESC)` index from V2 serves exactly this query.

**Questions:** Why cap the page size? Why the `id` tie-breaker? When would you switch to cursor
pagination?

> **Interview answer:** "The list endpoint is offset-paginated with a capped page size, a stable
> sort with a unique tie-breaker, and an index matching the query. For very large or fast-changing
> data I'd move to keyset pagination."

---

## 12. Request IDs in logs (observability basics)

**Files:** `observability/RequestIdFilter.java`, `application.properties` (`logging.pattern.level`),
`GlobalExceptionHandler.handleUnexpected`, `RequestIdFilterTest.java`

- A servlet filter (`OncePerRequestFilter`) runs **first** (`@Order(HIGHEST_PRECEDENCE)`, before
  Spring Security, so even a 401 carries the id).
- It reuses the caller's `X-Request-Id` if it matches `[A-Za-z0-9._-]{1,64}`, otherwise generates a
  UUID. **Why validate:** a header containing a newline could write fake lines into the logs (log
  injection).
- **MDC (Mapped Diagnostic Context):** a per-thread map the logger reads; `%X{requestId}` in the
  log pattern prints it on every line of that request. The `finally { MDC.remove(...) }` matters:
  server threads are reused, so a leftover id would mislabel the next request's logs.
- The id goes back in the response header and in 500 bodies, so a user can report it.
- **Where this leads:** with several services you propagate the id (or a W3C `traceparent`) on
  outgoing calls and Kafka messages; tools like OpenTelemetry/Micrometer Tracing do this
  automatically as distributed tracing (M4).
- **Async caveat:** MDC is thread-local; work handed to another thread (`@Async`, executors) must
  copy it explicitly.

**Questions:** What is MDC and why must it be cleared? Why accept an incoming id at all? How does
this differ from distributed tracing?

> **Interview answer:** "Each request gets a correlation id in a filter that runs before security.
> It's stored in the logging MDC so every log line carries it, returned to the client, and
> included in 500 responses, so a support ticket maps straight to the logs. Incoming ids are
> validated to prevent log injection."

---

## Mock "tell me about the project" (60 seconds)

"It's a multi-tenant incident management backend in Spring Boot and PostgreSQL, the foundation of an
AI incident-investigation platform. Requests carry a JWT; the service validates it as an OAuth2
resource server, takes the tenant from the token and enforces role-based access. Data goes through
a JPA repository into PostgreSQL, with the schema managed by Flyway migrations. Concurrent updates
are handled with optimistic locking, errors are standard RFC 9457 Problem Details, and the
test suite goes from Mockito unit tests to Testcontainers integration tests on a real PostgreSQL,
including a test that proves one tenant can't see another's data. Next I'm adding Kafka-based
async processing and a RAG pipeline for investigation."
