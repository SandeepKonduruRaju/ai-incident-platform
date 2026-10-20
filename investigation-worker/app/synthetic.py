"""Deterministic synthetic evidence (logs, metric summaries, runbooks, past incidents) for two tenants.

Used later to test retrieval: for each scenario and tenant, golden.json lists the source_ids a good
search should find. Noise (normal INFO logs, unrelated warnings, runbooks and incidents) makes the
search work for it.

    python -m app.synthetic                 # writes data/synthetic/*.json with the default seed
    python -m app.synthetic --seed 7 --out C:\\tmp\\synthetic

Same seed -> byte-identical files. Each (tenant, scenario) gets its own random generator, seeded
with a string (hashed with SHA-512, so it does not depend on PYTHONHASHSEED): adding a scenario
does not change the data of the others.
"""

import argparse
import json
import random
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

DEFAULT_SEED = 42
DEFAULT_OUT = Path(__file__).resolve().parent.parent / "data" / "synthetic"

TENANTS = ("acme", "globex")
SERVICES = ("payment-service", "checkout-api", "auth-service", "inventory-service")
SCENARIOS = (
    "db_pool_exhausted",
    "bad_deploy",
    "memory_leak",
    "dns_failure",
    "expired_tls_cert",
    "slow_downstream",
)
EVIDENCE_TYPES = ("logs", "metrics", "runbooks", "incidents")

# All synthetic events happen in September 2026; past incidents before that.
BASE_TIME = datetime(2026, 9, 1, tzinfo=UTC)

# Per-tenant details, so the same scenario looks different for acme and globex
# (different affected service, database, versions, hosts, thresholds, team channel).
TENANT_PROFILES = {
    "acme": {
        "region": "eu-west-1",
        "cluster": "acme-prod-eu",
        "namespace": "payments",
        "database": "orders-db",
        "pool_max": 20,
        "oncall": "#acme-oncall",
        "deploy_tool": "ArgoCD",
        "domain": "api.acme.example",
        "cert_name": "acme-api-tls",
        "dns_host": "payments.internal.acme",
        "resolver": "10.20.0.2",
        "downstream": "fraud-check",
        "heap_mb": 1024,
        "affected": {
            "db_pool_exhausted": "payment-service",
            "bad_deploy": "checkout-api",
            "memory_leak": "inventory-service",
            "dns_failure": "auth-service",
            "expired_tls_cert": "checkout-api",
            "slow_downstream": "payment-service",
        },
    },
    "globex": {
        "region": "us-east-2",
        "cluster": "globex-k8s-a",
        "namespace": "prod",
        "database": "ledger-db",
        "pool_max": 50,
        "oncall": "#globex-sre",
        "deploy_tool": "Spinnaker",
        "domain": "pay.globex.example",
        "cert_name": "globex-pay-cert",
        "dns_host": "ledger.svc.globex.local",
        "resolver": "172.16.0.10",
        "downstream": "tax-service",
        "heap_mb": 2048,
        "affected": {
            "db_pool_exhausted": "inventory-service",
            "bad_deploy": "payment-service",
            "memory_leak": "checkout-api",
            "dns_failure": "payment-service",
            "expired_tls_cert": "auth-service",
            "slow_downstream": "checkout-api",
        },
    },
}

# ---------------------------------------------------------------- scenario templates
# Placeholders come from the tenant profile plus per-scenario and per-line random values.

SCENARIO_TEMPLATES = {
    "db_pool_exhausted": {
        "logs": [
            ("WARN", "HikariPool-1 - Connection is not available, request timed out after {ms}ms "
                     "(total={pool_max}, active={pool_max}, idle=0, waiting={count})"),
            ("ERROR", "POST /api/v1/payments failed: could not obtain JDBC connection for {database} "
                      "within {ms}ms trace={trace}"),
            ("WARN", "Slow query on {database}: UPDATE ledger_entries took {ms}ms (waiting for row lock)"),
            ("ERROR", "Circuit breaker '{database}' OPEN after {count} consecutive connection timeouts"),
            ("WARN", "Tomcat thread pool saturated: {count} requests queued, all workers waiting on DB"),
        ],
        "metric": "{service} on {cluster} ({region}): db.pool.active pinned at {pool_max}/{pool_max} for 27 "
                  "minutes from {start}; db.pool.pending rose from 0 to {count}; p99 latency 180ms -> {ms}ms; "
                  "HTTP 5xx rate 0.1% -> {pct}%. Application CPU normal (~40%), {database} CPU normal.",
        "runbook_title": "Database connection pool exhausted ({service})",
        "runbook": """# Runbook: {service} database connection pool exhausted

Owner: {oncall} | Cluster: {cluster} ({region}) | Database: {database}

## Symptoms
- Logs: "Connection is not available, request timed out" from HikariPool; JDBC timeouts on requests.
- Metric db.pool.active flat at the maximum ({pool_max}) while db.pool.pending keeps growing.
- 5xx errors rise, but CPU on the service and on {database} looks normal.

## Diagnosis
1. Count sessions on {database}: `SELECT state, count(*) FROM pg_stat_activity GROUP BY state;`
2. Look for long-running or idle-in-transaction sessions and lock waits in `pg_locks`.
3. Check recent changes that hold connections longer (missing transaction boundaries, N+1 queries).

## Mitigation
- Terminate idle-in-transaction sessions older than 5 minutes.
- Temporarily raise maximumPoolSize from {pool_max} to {pool_raise}, restarting pods one at a time.
- Shed load: enable the rate limit on write endpoints.

## Prevention
- Set statement_timeout and idle_in_transaction_session_timeout.
- Alert when pool usage stays above 80% for 5 minutes.
""",
        "incidents": [
            {"title": "{service} 5xx spike: connection pool exhausted on {database}",
             "root_cause": "A reporting job kept transactions open for minutes and used all {pool_max} "
                           "pool connections.",
             "fix": "Killed the long transactions, moved the report to a read replica and set "
                    "idle_in_transaction_session_timeout=60s."},
            {"title": "Payment failures during peak: {database} pool saturation",
             "root_cause": "Traffic tripled and a connection leak on an error path kept connections "
                           "checked out; pool size {pool_max} was too small.",
             "fix": "Fixed the leak in the error handler, raised the pool size and added a pool-usage alert."},
        ],
    },
    "bad_deploy": {
        "logs": [
            ("WARN", "{deploy_tool} rollout of {service} {version}: readiness probe failing on {count} pods"),
            ("ERROR", "NullPointerException in PricingEngine.applyDiscount (build {version}) trace={trace}"),
            ("ERROR", "POST /api/v1/checkout returned 500 on pod {pod} running {version}"),
            ("WARN", "Feature flag 'new-pricing-engine' defaulted to ON in {version}"),
            ("ERROR", "Pod {pod} in CrashLoopBackOff, restarted {count} times since deploy {version}"),
        ],
        "metric": "{service}: error rate jumped from 0.2% to {pct}% within 2 minutes of the {version} rollout "
                  "at {start} ({deploy_tool}); errors only on pods running {version}; pods still on "
                  "{prev_version} stay at 0.2%; latency and traffic unchanged.",
        "runbook_title": "Bad deployment and rollback ({service})",
        "runbook": """# Runbook: rolling back a bad {service} deployment

Owner: {oncall} | Deploy tool: {deploy_tool} | Namespace: {namespace}

## Symptoms
- Error rate rises within minutes of a rollout; new pods fail readiness or crash-loop.
- Errors are concentrated on pods with the new version label.

## Diagnosis
1. Compare error rate by `version` label: old pods healthy, new pods failing means the release.
2. Check {deploy_tool} history for the last rollout and the diff (code, config, feature flags).
3. Read the first stack trace after the deploy; a new exception type points at the change.

## Mitigation
- Roll back to the last good version: `kubectl rollout undo deployment/{service} -n {namespace}`
  (or "Rollback" in {deploy_tool}).
- If a feature flag caused it, switch the flag off instead of rolling back.

## Prevention
- Canary 5% of traffic for 15 minutes with automatic rollback on error-rate increase.
- Validate configuration at startup and fail the readiness probe on bad config.
""",
        "incidents": [
            {"title": "{service} {version} release caused 500s",
             "root_cause": "A null discount code was not handled in the new pricing engine path.",
             "fix": "Rolled back to {prev_version}, added a null check and a contract test."},
            {"title": "Misconfigured {service} deploy pointed at staging",
             "root_cause": "The {deploy_tool} pipeline set PRICING_URL to the staging endpoint.",
             "fix": "Rolled back, added startup config validation and a pipeline check."},
        ],
    },
    "memory_leak": {
        "logs": [
            ("WARN", "GC overhead high: {pct}% of time spent in GC over the last 5 minutes (heap {heap_mb}Mi)"),
            ("ERROR", "java.lang.OutOfMemoryError: Java heap space in ProductCacheLoader trace={trace}"),
            ("WARN", "Pod {pod} memory at {pct}% of its {heap_mb}Mi limit"),
            ("ERROR", "Container {pod} OOMKilled (exit code 137), restart #{count}"),
            ("WARN", "Cache 'product-details' holds {count}k entries; eviction disabled"),
        ],
        "metric": "{service}: container memory grows linearly by about {growth}Mi/hour since the deploy on "
                  "{start}, reaching the {heap_mb}Mi limit; OOMKilled restarts every ~{hours} hours; "
                  "GC time 2% -> {pct}%; traffic flat.",
        "runbook_title": "Memory leak and OOMKilled pods ({service})",
        "runbook": """# Runbook: {service} memory leak / OOMKilled

Owner: {oncall} | Memory limit: {heap_mb}Mi | Cluster: {cluster}

## Symptoms
- Memory climbs steadily (a straight line, not spikes) until pods are OOMKilled (exit code 137).
- GC time rises before each restart; latency gets worse as the heap fills.

## Diagnosis
1. Plot memory per pod since the last deploy: a constant slope means a leak.
2. Take a heap dump before the kill: `jcmd <pid> GC.heap_dump /tmp/heap.hprof`.
3. Check in-memory caches and listener registries for missing size limits.

## Mitigation
- Rolling restart to buy time; temporarily raise the limit above {heap_mb}Mi.
- Roll back if the leak started with a deploy.

## Prevention
- Bound every cache (maximumSize plus expiry).
- Alert on memory slope, not only on absolute usage.
""",
        "incidents": [
            {"title": "{service} repeatedly OOMKilled",
             "root_cause": "Unbounded in-memory product cache: eviction was disabled in configuration.",
             "fix": "Enabled maximumSize=50000 with expireAfterWrite and raised the limit temporarily."},
            {"title": "Gradual memory growth in {service}",
             "root_cause": "Event listeners were registered on every request and never removed.",
             "fix": "Fixed listener deregistration and added a heap-slope alert."},
        ],
    },
    "dns_failure": {
        "logs": [
            ("ERROR", "java.net.UnknownHostException: {dns_host}: Temporary failure in name resolution"),
            ("WARN", "DNS lookup for {dns_host} via {resolver} timed out after {ms}ms"),
            ("ERROR", "Upstream call failed: could not resolve {dns_host} (attempt {count}) trace={trace}"),
            ("WARN", "CoreDNS: i/o timeout reading from upstream {resolver}:53"),
            ("ERROR", "Readiness check dependency '{dns_host}' DOWN: name resolution failed"),
        ],
        "metric": "{service}: outbound request failures at {pct}% with UnknownHostException from {start} for "
                  "18 minutes; CoreDNS p99 latency 2ms -> {ms}ms and SERVFAIL responses rising; CPU and "
                  "memory of {service} normal.",
        "runbook_title": "DNS resolution failures ({service})",
        "runbook": """# Runbook: DNS resolution failures in {cluster}

Owner: {oncall} | Upstream resolver: {resolver}

## Symptoms
- UnknownHostException / "Temporary failure in name resolution" for internal names like {dns_host}.
- Many services fail at once while their own CPU and memory look normal.

## Diagnosis
1. From an affected pod: `kubectl exec -n {namespace} <pod> -- nslookup {dns_host}`.
2. Check CoreDNS pods: restarts, OOM, and logs for upstream timeouts to {resolver}.
3. Check the pod's resolv.conf (ndots, search domains): high ndots multiplies lookups.

## Mitigation
- Scale CoreDNS up and restart unhealthy CoreDNS pods.
- Fail over to the secondary resolver if {resolver} is down.

## Prevention
- Run NodeLocal DNSCache; use fully qualified names for internal calls.
- Alert on CoreDNS SERVFAIL rate and latency.
""",
        "incidents": [
            {"title": "{service} could not reach dependencies: DNS outage in {cluster}",
             "root_cause": "CoreDNS pods ran out of memory after a cluster scale-up; upstream {resolver} "
                           "was overloaded.",
             "fix": "Scaled CoreDNS to 4 replicas with more memory and enabled NodeLocal DNSCache."},
            {"title": "Intermittent UnknownHostException in {service}",
             "root_cause": "The default ndots:5 caused five lookups per request and saturated DNS.",
             "fix": "Set ndots:2 and switched to fully qualified service names."},
        ],
    },
    "expired_tls_cert": {
        "logs": [
            ("ERROR", "javax.net.ssl.SSLHandshakeException: PKIX path validation failed: certificate "
                      "expired on {expiry} for {domain}"),
            ("WARN", "TLS certificate {cert_name} for {domain} expires in 0 days"),
            ("ERROR", "Client handshake failed: remote error: tls: expired certificate (peer {domain})"),
            ("ERROR", "Webhook delivery to https://{domain}/callbacks failed: certificate has expired"),
            ("WARN", "cert-manager: Certificate {cert_name} not ready: ACME challenge failed"),
        ],
        "metric": "{service}: HTTPS success rate dropped from 99.9% to {low}% exactly at {start} (the "
                  "certificate notAfter time); TLS handshake errors {count}k/min; traffic and latency normal "
                  "before the drop; certificate-expiry gauge for {domain} reached 0 days.",
        "runbook_title": "Expired TLS certificate ({domain})",
        "runbook": """# Runbook: expired TLS certificate for {domain}

Owner: {oncall} | Certificate: {cert_name} (cert-manager)

## Symptoms
- Sudden, total failure of HTTPS calls at one exact time; SSLHandshakeException "certificate expired".
- No deploy or traffic change before the failure.

## Diagnosis
1. Check the dates: `openssl s_client -connect {domain}:443 -servername {domain} | openssl x509 -noout -dates`.
2. `kubectl describe certificate {cert_name} -n {namespace}`: why did renewal fail (ACME challenge, credentials)?
3. Make sure the full chain (intermediate certificate) is served.

## Mitigation
- Force renewal: `cmctl renew {cert_name} -n {namespace}`, then restart the ingress or pods to load the new secret.
- If renewal is blocked, install a manually issued certificate as a stopgap.

## Prevention
- Alert at 21 and 7 days before expiry; test renewal in staging.
""",
        "incidents": [
            {"title": "Outage: TLS certificate for {domain} expired",
             "root_cause": "cert-manager renewal failed silently after the DNS01 credentials were rotated.",
             "fix": "Renewed manually, fixed the credentials and added an expiry alert at 14 days."},
            {"title": "Partner webhooks failing on {domain}",
             "root_cause": "The intermediate certificate was missing from the chain after a manual renewal.",
             "fix": "Deployed the full chain and added a chain-validation check in CI."},
        ],
    },
    "slow_downstream": {
        "logs": [
            ("WARN", "Call to {downstream} took {ms}ms (timeout 2000ms) trace={trace}"),
            ("ERROR", "TimeoutException calling {downstream} POST /v1/check after 2000ms"),
            ("WARN", "Retry {count}/3 for {downstream} request"),
            ("WARN", "Bulkhead '{downstream}' full: {count} concurrent calls rejected"),
            ("ERROR", "Circuit breaker '{downstream}' OPEN: failure rate {pct}% over the last 100 calls"),
        ],
        "metric": "{service}: p99 latency 220ms -> {ms}ms from {start}; {downstream} p99 latency 80ms -> "
                  "1900ms over the same window; {service} CPU and database metrics normal; retries to "
                  "{downstream} 3x higher; error rate {pct}% (timeouts).",
        "runbook_title": "Slow downstream dependency ({downstream})",
        "runbook": """# Runbook: {service} slowed down by {downstream}

Owner: {oncall} | Dependency: {downstream}

## Symptoms
- {service} latency rises while its own CPU, memory and database look normal.
- Timeouts and retries towards {downstream}; circuit breaker opening.

## Diagnosis
1. Compare {service} latency with {downstream} latency on the same graph: same shape means the dependency.
2. Check for a retry storm: retries without jitter multiply load on a slow dependency.
3. Ask the {downstream} owners about deploys or database changes.

## Mitigation
- Lower the timeout and the number of retries; serve the fallback response.
- Open the circuit breaker manually if {downstream} stays slow.

## Prevention
- Per-dependency timeouts, jittered backoff, bulkheads and circuit breakers.
""",
        "incidents": [
            {"title": "{service} latency spike caused by {downstream}",
             "root_cause": "{downstream} lost a database index during a migration; its p99 rose to 2s.",
             "fix": "The {downstream} team restored the index; we cut the timeout to 800ms with a fallback."},
            {"title": "Retry storm against {downstream}",
             "root_cause": "Three retries without jitter multiplied load during a {downstream} slowdown.",
             "fix": "Added jittered exponential backoff and a circuit breaker."},
        ],
    },
}

# ---------------------------------------------------------------- evaluation incidents
# One "current" incident per tenant and scenario, shaped like incident-service's IncidentCreatedPayload:
# what an on-call engineer would type when opening the incident. Written from the symptoms, in other
# words than the runbooks, so retrieval has to match meaning, not copy-pasted text.

EVAL_INCIDENT_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://github.com/SandeepKonduruRaju/ai-incident-platform/eval-incidents")
# The incident is opened 10 minutes after the scenario starts (its logs span start .. start + 40 min).
EVAL_INCIDENT_DELAY = timedelta(minutes=10)

EVAL_INCIDENT_TEMPLATES = {
    "db_pool_exhausted": {
        "title": "{service} requests timing out, 5xx rising",
        "description": "Since {start} many {service} requests hang for seconds and then fail. The errors mention "
                       "timeouts while talking to {database}. CPU on the service and on the database looks normal.",
    },
    "bad_deploy": {
        "title": "{service} error rate up after today's release",
        "description": "Shortly after {service} {version} was rolled out with {deploy_tool}, users started getting "
                       "server errors and some of the new pods keep restarting.",
    },
    "memory_leak": {
        "title": "{service} pods restarting every few hours",
        "description": "{service} pods are killed and restarted regularly. Before each restart the service gets "
                       "slower and its memory usage climbs steadily.",
    },
    "dns_failure": {
        "title": "{service} cannot reach its dependencies",
        "description": "Since {start} outbound calls from {service} fail with host lookup errors, although the "
                       "dependencies themselves report healthy.",
    },
    "expired_tls_cert": {
        "title": "HTTPS failures on {domain}",
        "description": "Clients calling {domain} ({service}) suddenly get secure connection errors since {start}. "
                       "Nothing was deployed.",
    },
    "slow_downstream": {
        "title": "{service} very slow, many timeouts",
        "description": "{service} p99 latency is many times higher than usual while its own CPU and database look "
                       "fine. Calls to another service are timing out and being retried.",
    },
}

# ---------------------------------------------------------------- noise templates

NOISE_INFO = [
    "GET /api/v1/{resource} 200 in {small_ms}ms",
    "Health check OK",
    "Processed {count} messages from queue {queue}",
    "Scheduled job '{job}' completed in {seconds}s",
    "Cache hit ratio {ratio}",
    "User login succeeded (method=password)",
    "Connected to {database} (pool size {pool_max})",
    "Configuration reloaded from config-server",
    "Feature flag 'dark-mode' evaluated for {count} users",
    "POST /api/v1/{resource} 201 in {small_ms}ms",
]
NOISE_WARN = [
    "Deprecated configuration key 'server.compression' is used",
    "Slow client: upload took {seconds}s from 203.0.113.{octet}",
    "Rate limit reached for API key ending {hex4}",
    "Retrying S3 upload of report-{count}.csv after HTTP 503",
    "Clock skew of {small_ms}ms detected against NTP",
    "Disk usage on /var/log at {disk}%",
]
NOISE_METRICS = [
    "{service}: CPU steady between {low_cpu}% and {high_cpu}% all week; no anomalies.",
    "{service}: weekly traffic pattern normal; peak {count}k requests/min at 12:00 UTC.",
    "{service}: memory stable at {mem}Mi of {heap_mb}Mi limit; GC time under 2%.",
    "{service}: Kafka consumer lag below 50 messages; no rebalances.",
]
NOISE_RUNBOOKS = {
    "rotate_api_keys": ("Rotating partner API keys", """# Runbook: rotating partner API keys

Owner: {oncall}

## When
- Every 90 days, or immediately if a key may have leaked.

## Steps
1. Create the new key in the secrets manager ({region}).
2. Deploy services with both keys accepted for 24 hours.
3. Revoke the old key and confirm no traffic uses it.
"""),
    "onboard_new_service": ("Onboarding a new service to {cluster}", """# Runbook: onboarding a new service

Owner: {oncall}

## Checklist
- Namespace, resource requests and limits, readiness and liveness probes.
- Dashboards and alerts from the standard template.

## Go-live
- Load test at 2x expected traffic before enabling it for customers.
"""),
    "scale_out_for_campaign": ("Scaling out before a marketing campaign", """# Runbook: scaling out before a campaign

Owner: {oncall}

## Before
- Raise HPA minimum replicas for checkout-api and payment-service one day before.
- Pre-warm caches and confirm database headroom.

## After
- Return HPA settings to normal and review the cost report.
"""),
}
NOISE_INCIDENTS = [
    {"title": "Marketing email batch delayed",
     "service": "auth-service",
     "root_cause": "The email provider throttled our account after a sudden volume increase.",
     "fix": "Spread the batch over 4 hours and requested a higher quota."},
    {"title": "Analytics dashboard showed stale data",
     "service": "inventory-service",
     "root_cause": "The nightly export job failed on a schema change in the warehouse.",
     "fix": "Updated the export query and added a freshness check on the dashboard."},
]

RESOURCES = ("orders", "carts", "products", "sessions", "invoices")
QUEUES = ("order-events", "email-jobs", "stock-updates")
JOBS = ("nightly-report", "cache-warmup", "token-cleanup")

NOISE_LOGS_PER_TENANT = 180
NOISE_WARN_SHARE = 0.15
EXTRA_SIGNAL_LOGS = 3  # repeats of random signal templates, with different numbers


# ---------------------------------------------------------------- generation


def _hex(rng: random.Random, length: int) -> str:
    return "".join(rng.choice("0123456789abcdef") for _ in range(length))


def _iso(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


def _line_values(rng: random.Random) -> dict:
    """Fresh numbers for every log line, so repeated templates still differ."""
    return {
        "ms": rng.randint(900, 30000),
        "pct": rng.randint(12, 97),
        "count": rng.randint(3, 60),
        "trace": _hex(rng, 16),
        "small_ms": rng.randint(4, 180),
        "seconds": rng.randint(1, 90),
        "ratio": f"0.{rng.randint(80, 99)}",
        "octet": rng.randint(2, 250),
        "hex4": _hex(rng, 4),
        "disk": rng.randint(70, 84),
        "resource": rng.choice(RESOURCES),
        "queue": rng.choice(QUEUES),
        "job": rng.choice(JOBS),
    }


def _scenario_items(seed: int, tenant: str, scenario: str) -> dict[str, list[dict]]:
    rng = random.Random(f"{seed}-{tenant}-{scenario}")
    profile = TENANT_PROFILES[tenant]
    template = SCENARIO_TEMPLATES[scenario]
    service = profile["affected"][scenario]
    start = BASE_TIME + timedelta(days=rng.randint(1, 27), hours=rng.randint(0, 23), minutes=rng.randint(0, 59))
    major, minor = rng.randint(2, 7), rng.randint(0, 9)
    context = {
        **{k: v for k, v in profile.items() if k != "affected"},
        "service": service,
        "start": start.strftime("%Y-%m-%d %H:%M UTC"),
        "version": f"v{major}.{minor}.{rng.randint(1, 9)}",
        "prev_version": f"v{major}.{minor}.0",
        "pod": f"{service}-{_hex(rng, 9)}-{_hex(rng, 5)}",
        "pool_raise": profile["pool_max"] + profile["pool_max"] // 2,
        "growth": rng.randint(40, 160),
        "hours": rng.randint(3, 9),
        "low": rng.randint(1, 15),
        "expiry": (start - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M UTC"),
    }

    def render(text: str, extra: dict | None = None) -> str:
        return text.format_map({**context, **_line_values(rng), **(extra or {})})

    # Every template once, plus a few repeats, spread over a 40-minute window.
    log_templates = list(template["logs"]) + [rng.choice(template["logs"]) for _ in range(EXTRA_SIGNAL_LOGS)]
    offsets = sorted(rng.randint(0, 40 * 60) for _ in log_templates)
    logs = [
        {
            "source_id": f"LOG-{tenant}-{scenario}-{index:03d}",
            "tenant_id": tenant,
            "source_type": "log",
            "service": service,
            "ts": _iso(start + timedelta(seconds=offset)),
            "level": level,
            "message": render(message),
        }
        for index, ((level, message), offset) in enumerate(zip(log_templates, offsets, strict=True), start=1)
    ]
    metrics = [
        {
            "source_id": f"MET-{tenant}-{scenario}",
            "tenant_id": tenant,
            "source_type": "metric",
            "service": service,
            "ts": _iso(start),
            "summary": render(template["metric"]),
        }
    ]
    runbooks = [
        {
            "source_id": f"RB-{tenant}-{scenario}",
            "tenant_id": tenant,
            "source_type": "runbook",
            "service": service,
            "title": render(template["runbook_title"]),
            "content": render(template["runbook"]),
        }
    ]
    incidents = [
        {
            "source_id": f"INC-{tenant}-{scenario}-{number}",
            "tenant_id": tenant,
            "source_type": "incident",
            "service": service,
            "ts": _iso(BASE_TIME - timedelta(days=rng.randint(20, 400))),
            "title": render(incident["title"]),
            "root_cause": render(incident["root_cause"]),
            "fix": render(incident["fix"]),
        }
        for number, incident in enumerate(template["incidents"][: rng.choice((1, 2))], start=1)
    ]
    # Built from the context only (no rng draws), so adding it did not change any other generated value.
    eval_incident = {
        "tenantId": tenant,
        "scenario": scenario,
        "incident": {
            "incidentId": str(uuid.uuid5(EVAL_INCIDENT_NAMESPACE, f"{tenant}:{scenario}")),
            "title": EVAL_INCIDENT_TEMPLATES[scenario]["title"].format_map(context),
            "description": EVAL_INCIDENT_TEMPLATES[scenario]["description"].format_map(context),
            "severity": "HIGH",
            "status": "OPEN",
            "affectedService": service,
            "createdAt": _iso(start + EVAL_INCIDENT_DELAY),
        },
    }
    return {
        "logs": logs,
        "metrics": metrics,
        "runbooks": runbooks,
        "incidents": incidents,
        "eval_incident": eval_incident,
    }


def _noise_items(seed: int, tenant: str) -> dict[str, list[dict]]:
    rng = random.Random(f"{seed}-{tenant}-noise")
    profile = TENANT_PROFILES[tenant]
    base = {k: v for k, v in profile.items() if k != "affected"}

    logs = []
    for index in range(1, NOISE_LOGS_PER_TENANT + 1):
        warn = rng.random() < NOISE_WARN_SHARE
        message = rng.choice(NOISE_WARN if warn else NOISE_INFO)
        moment = BASE_TIME + timedelta(seconds=rng.randint(0, 30 * 24 * 3600))
        logs.append({
            "source_id": f"LOG-{tenant}-noise-{index:04d}",
            "tenant_id": tenant,
            "source_type": "log",
            "service": rng.choice(SERVICES),
            "ts": _iso(moment),
            "level": "WARN" if warn else "INFO",
            "message": message.format_map({**base, **_line_values(rng)}),
        })

    metrics = []
    for index, service in enumerate(SERVICES, start=1):
        values = {
            **base,
            "service": service,
            "count": rng.randint(2, 40),
            "low_cpu": rng.randint(20, 35),
            "high_cpu": rng.randint(36, 55),
            "mem": rng.randint(300, profile["heap_mb"] // 2),
        }
        metrics.append({
            "source_id": f"MET-{tenant}-noise-{index:02d}",
            "tenant_id": tenant,
            "source_type": "metric",
            "service": service,
            "ts": _iso(BASE_TIME + timedelta(days=rng.randint(0, 29))),
            "summary": rng.choice(NOISE_METRICS).format_map(values),
        })

    runbooks = [
        {
            "source_id": f"RB-{tenant}-{name}",
            "tenant_id": tenant,
            "source_type": "runbook",
            "service": None,
            "title": title.format_map(base),
            "content": content.format_map(base),
        }
        for name, (title, content) in NOISE_RUNBOOKS.items()
    ]

    incidents = [
        {
            "source_id": f"INC-{tenant}-noise-{number}",
            "tenant_id": tenant,
            "source_type": "incident",
            "service": incident["service"],
            "ts": _iso(BASE_TIME - timedelta(days=rng.randint(20, 400))),
            "title": incident["title"],
            "root_cause": incident["root_cause"],
            "fix": incident["fix"],
        }
        for number, incident in enumerate(NOISE_INCIDENTS, start=1)
    ]
    return {"logs": logs, "metrics": metrics, "runbooks": runbooks, "incidents": incidents}


def generate(seed: int = DEFAULT_SEED) -> dict:
    """Build the whole dataset in memory: {logs, metrics, runbooks, incidents, eval_incidents: [...], golden: {...}}."""
    dataset: dict = {kind: [] for kind in EVIDENCE_TYPES}
    golden: dict = {scenario: {} for scenario in SCENARIOS}
    eval_incidents: list[dict] = []

    for tenant in TENANTS:
        for scenario in SCENARIOS:
            items = _scenario_items(seed, tenant, scenario)
            for kind in EVIDENCE_TYPES:
                dataset[kind].extend(items[kind])
            golden[scenario][tenant] = {kind: [item["source_id"] for item in items[kind]] for kind in EVIDENCE_TYPES}
            eval_incidents.append(items["eval_incident"])
        noise = _noise_items(seed, tenant)
        for kind in EVIDENCE_TYPES:
            dataset[kind].extend(noise[kind])

    # Stable order: by tenant, then time (if any), then id. Signal and noise end up interleaved.
    for kind in EVIDENCE_TYPES:
        dataset[kind].sort(key=lambda item: (item["tenant_id"], item.get("ts") or "", item["source_id"]))
    dataset["golden"] = golden
    dataset["eval_incidents"] = eval_incidents
    return dataset


def write(dataset: dict, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name in (*EVIDENCE_TYPES, "golden", "eval_incidents"):
        path = out_dir / f"{name}.json"
        # newline="\n": identical bytes on Windows and Linux.
        path.write_text(json.dumps(dataset[name], indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        written.append(path)
    return written


def counts(dataset: dict) -> dict[str, dict[str, int]]:
    return {
        kind: {tenant: sum(1 for item in dataset[kind] if item["tenant_id"] == tenant) for tenant in TENANTS}
        for kind in EVIDENCE_TYPES
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Generate deterministic synthetic incident evidence.")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    dataset = generate(args.seed)
    for path in write(dataset, args.out):
        print(f"wrote {path}")
    print(f"{'type':<10}" + "".join(f"{tenant:>8}" for tenant in TENANTS))
    for kind, per_tenant in counts(dataset).items():
        print(f"{kind:<10}" + "".join(f"{per_tenant[tenant]:>8}" for tenant in TENANTS))


if __name__ == "__main__":
    main()
