"""Demo tenant "demo": eight realistic incidents and the evidence that makes them investigable (dev-only, for demos).

Same document format as app.synthetic (runbooks, logs, metrics, past incidents), ingested by app.ingest.ingest_dataset
through the normal chunking and embedding. Written by hand rather than generated: a demo needs believable text, and two
scenarios are shaped on purpose:

    db_pool_deploy     strong, consistent evidence (deploy log, pool metric, runbook, matching past incident):
                       the investigation should name the cause with confidence and cite it.
    checkout_latency   almost nothing relevant (healthy checkout-api logs, a flat metric): it should ABSTAIN
                       (no root cause, low confidence) instead of inventing one.

Timestamps are ANCHORED to the moment the seed runs: retrieval only considers logs and metrics of the incident's own
service from 2 h before to 30 min after it was reported (app.query_builder), and the seed reports the incidents right
after ingesting. Every scenario uses its own service, so one incident's log search never sees another's lines.
Runbooks and past incidents are timeless (no window), as in the synthetic data.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

TENANT = "demo"


@dataclass(frozen=True)
class DemoIncident:
    scenario: str
    title: str
    description: str
    severity: str  # CRITICAL | HIGH | MEDIUM | LOW
    service: str
    status: str  # set after creation with PATCH .../status (new incidents start OPEN)


DEMO_INCIDENTS: tuple[DemoIncident, ...] = (
    DemoIncident(
        "db_pool_deploy",
        "Payment requests failing after configuration deploy",
        "Since the payment-service configuration deploy about 30 minutes ago, around a third of payment requests fail "
        "with 500 errors after hanging for several seconds. Database CPU looks normal.",
        "CRITICAL",
        "payment-service",
        "INVESTIGATING",
    ),
    DemoIncident(
        "checkout_latency",
        "Checkout feels slow for some customers",
        "A few customers told support that the checkout page felt slow this morning. We have no error reports and "
        "could not reproduce it ourselves.",
        "MEDIUM",
        "checkout-api",
        "OPEN",
    ),
    DemoIncident(
        "kafka_rebalance_lag",
        "Order events backing up in orders-consumer",
        "Order confirmation emails and stock updates are delayed. The orders-consumer lag keeps growing even though "
        "all pods are running.",
        "HIGH",
        "orders-consumer",
        "MITIGATED",
    ),
    DemoIncident(
        "tls_cert_expiry",
        "Sign-in failing: auth-gateway cannot reach the identity service",
        "All sign-ins fail with a generic error. auth-gateway reports secure connection errors when calling the "
        "internal identity API. Nothing was deployed today.",
        "CRITICAL",
        "auth-gateway",
        "RESOLVED",
    ),
    DemoIncident(
        "oom_memory_leak",
        "inventory-service pods restarting since the 2.14 release",
        "Since inventory-service 2.14.0 went out, pods restart every few hours and stock lookups get slower before "
        "each restart.",
        "HIGH",
        "inventory-service",
        "INVESTIGATING",
    ),
    DemoIncident(
        "redis_cache_stampede",
        "Product pages slow while database load spikes",
        "Product pages take several seconds to load and the catalog database is close to its CPU limit. The cache "
        "hit rate dropped sharply at the same time.",
        "MEDIUM",
        "catalog-service",
        "MITIGATED",
    ),
    DemoIncident(
        "gateway_timeouts",
        "Card payments timing out at the payment provider",
        "Card payments intermittently fail with timeouts. Our own services look healthy; the failures are on calls "
        "to the external card processor.",
        "HIGH",
        "psp-connector",
        "OPEN",
    ),
    DemoIncident(
        "disk_full_logs",
        "notification-service log volume full, some emails delayed",
        "notification-service reports write errors and a few emails are going out late. The log volume of its pods "
        "appears to be full.",
        "LOW",
        "notification-service",
        "RESOLVED",
    ),
)

# ---------------------------------------------------------------- scenario logs and metrics
# (minutes before the anchor, level, message). The anchor is "now" when the seed runs; incidents are reported
# right after, so these lines fall in each incident's 2-hour retrieval window.

_LOGS: dict[str, tuple[str, list[tuple[int, str, str]]]] = {
    "db_pool_deploy": ("payment-service", [
        (38, "INFO", "ArgoCD sync of payment-service config revision 7f3c2a1: ConfigMap payment-service-config changed "
                     "(spring.datasource.hikari.maximum-pool-size: 40 -> 10)"),
        (37, "INFO", "Rolling restart of payment-service: 6/6 pods restarted with config revision 7f3c2a1"),
        (36, "INFO", "HikariPool-1 - Starting... maximumPoolSize=10, minimumIdle=10, connectionTimeout=3000ms"),
        (31, "WARN", "HikariPool-1 - Connection is not available, request timed out after 3000ms "
                     "(total=10, active=10, idle=0, waiting=37)"),
        (30, "ERROR", "POST /api/v1/payments failed: could not obtain JDBC connection for payments-db within 3000ms "
                      "trace=4be1c09a77d2e310"),
        (27, "WARN", "HikariPool-1 - Connection is not available, request timed out after 3000ms "
                     "(total=10, active=10, idle=0, waiting=58)"),
        (24, "ERROR", "Circuit breaker 'payments-db' OPEN after 50 consecutive connection timeouts"),
        (21, "WARN", "Tomcat thread pool saturated: 180 requests queued, all workers waiting on a database connection"),
        (15, "ERROR", "POST /api/v1/payments failed: could not obtain JDBC connection for payments-db within 3000ms "
                      "trace=91c0d4e2aa6b0f57"),
    ]),
    "checkout_latency": ("checkout-api", [
        (95, "INFO", "GET /api/v1/cart 200 in 41ms"),
        (80, "INFO", "POST /api/v1/checkout 201 in 212ms"),
        (66, "INFO", "Health check OK"),
        (52, "INFO", "POST /api/v1/checkout 201 in 198ms"),
        (37, "INFO", "GET /api/v1/cart 200 in 38ms"),
        (21, "INFO", "Scheduled job 'abandoned-cart-reminders' completed in 4s"),
        (9, "INFO", "POST /api/v1/checkout 201 in 205ms"),
    ]),
    "kafka_rebalance_lag": ("orders-consumer", [
        (44, "INFO", "HPA scaled orders-consumer from 3 to 6 replicas (CPU 82%)"),
        (43, "INFO", "[Consumer groupId=orders-consumer] Revoking previously assigned partitions [order-events-0..11]"),
        (43, "INFO", "[Consumer groupId=orders-consumer] (Re-)joining group: rebalance in progress"),
        (39, "WARN", "[Consumer groupId=orders-consumer] consumer poll timeout has expired: the time between "
                     "subsequent calls to poll() was longer than max.poll.interval.ms=300000; leaving the group"),
        (38, "ERROR", "CommitFailedException: Commit cannot be completed since the group has already rebalanced and "
                      "assigned the partitions to another member"),
        (31, "WARN", "[Consumer groupId=orders-consumer] Rebalance triggered again: member left the group "
                     "(5th rebalance in 14 minutes)"),
        (22, "WARN", "Batch of 500 order events took 341s to process (slow stock-update call per event)"),
        (12, "ERROR", "CommitFailedException: group rebalanced during commit of order-events-7 offset 1849203"),
    ]),
    "tls_cert_expiry": ("auth-gateway", [
        (41, "WARN", "TLS certificate identity-api-tls for identity-api.internal.demo expires in 0 days"),
        (34, "ERROR", "javax.net.ssl.SSLHandshakeException: PKIX path validation failed: certificate for "
                      "identity-api.internal.demo expired 1 minute ago (notAfter reached)"),
        (33, "ERROR", "POST https://identity-api.internal.demo/oauth/token failed: certificate has expired"),
        (30, "WARN", "cert-manager: Certificate identity-api-tls not ready: issuing failed, "
                     "ClusterIssuer internal-ca secret 'internal-ca-key' not found"),
        (25, "ERROR", "Login failed for 412 users in the last 5 minutes: upstream identity-api TLS error"),
        (16, "ERROR", "javax.net.ssl.SSLHandshakeException: certificate expired (peer identity-api.internal.demo)"),
    ]),
    "oom_memory_leak": ("inventory-service", [
        (110, "INFO", "Deployed inventory-service v2.14.0 (new: in-memory reservation cache)"),
        (70, "WARN", "Pod inventory-service-7d9f8c6b5-x2k4p memory at 88% of its 1024Mi limit"),
        (62, "WARN", "GC overhead high: 34% of time spent in GC over the last 5 minutes (heap 1024Mi)"),
        (58, "ERROR", "java.lang.OutOfMemoryError: Java heap space in ReservationCache.put"),
        (57, "ERROR", "Container inventory-service-7d9f8c6b5-x2k4p OOMKilled (exit code 137), restart #3"),
        (31, "WARN", "Cache 'reservations' holds 2,400k entries; no maximum size configured"),
        (14, "ERROR", "Container inventory-service-7d9f8c6b5-q8m1z OOMKilled (exit code 137), restart #2"),
    ]),
    "redis_cache_stampede": ("catalog-service", [
        (36, "WARN", "Redis INFO: used_memory reached maxmemory 2gb; evicted_keys increased by 184k in 60s "
                     "(policy allkeys-lru)"),
        (35, "WARN", "Cache miss storm: product:* hit ratio 0.94 -> 0.31 within one minute"),
        (34, "WARN", "1,200 concurrent requests rebuilding the same cache key product:sku-88213 (no request coalescing)"),
        (30, "ERROR", "catalog-db: query SELECT * FROM products WHERE sku = ? took 4800ms (CPU 96%)"),
        (24, "WARN", "Redis evicted_keys still rising: 2.1M keys evicted in 12 minutes"),
        (11, "ERROR", "GET /api/v1/products/sku-88213 timed out after 5000ms"),
    ]),
    "gateway_timeouts": ("psp-connector", [
        (47, "WARN", "Call to PayFlow POST /v2/authorizations took 9800ms (timeout 10000ms) trace=0c71d2a4"),
        (42, "ERROR", "TimeoutException calling PayFlow POST /v2/authorizations after 10000ms"),
        (39, "WARN", "PayFlow status page: 'Elevated latency for card authorizations in EU region' (investigating)"),
        (33, "ERROR", "Circuit breaker 'payflow' OPEN: failure rate 41% over the last 100 calls"),
        (28, "WARN", "Retry 3/3 for PayFlow authorization of order 5531892"),
        (18, "INFO", "psp-connector CPU 22%, memory 410Mi of 1024Mi, database latency normal"),
    ]),
    "disk_full_logs": ("notification-service", [
        (88, "WARN", "Disk usage on /var/log/app at 91%"),
        (61, "WARN", "logrotate: error running postrotate script for /var/log/app/*.log (exit 1); "
                     "rotation skipped"),
        (40, "WARN", "Disk usage on /var/log/app at 99%"),
        (36, "ERROR", "java.io.IOException: No space left on device writing /var/log/app/notification.log"),
        (35, "ERROR", "Email job 'order-confirmation' failed to write its audit record: No space left on device; "
                      "retrying in 60s"),
        (20, "WARN", "Email queue depth 1,940 (normally under 50)"),
    ]),
}

# Background lines for several services (healthy traffic), so log searches never return only signal.
_NOISE: list[tuple[int, str, str, str]] = [
    (100, "payment-service", "INFO", "GET /api/v1/payments/methods 200 in 18ms"),
    (90, "orders-consumer", "INFO", "Processed 500 messages from order-events in 2.1s"),
    (85, "auth-gateway", "INFO", "Token refresh succeeded for client web-app"),
    (75, "catalog-service", "INFO", "Cache warmup for category 'outdoor' completed in 3s"),
    (64, "checkout-api", "INFO", "Feature flag 'one-click-checkout' evaluated for 1,204 users"),
    (55, "psp-connector", "INFO", "PayFlow webhook received: authorization.captured"),
    (48, "notification-service", "INFO", "Sent 312 emails in the last 10 minutes"),
    (26, "inventory-service", "INFO", "GET /api/v1/stock/sku-10442 200 in 12ms"),
]

_METRICS: dict[str, tuple[str, int, str]] = {
    "db_pool_deploy": ("payment-service", 35,
        "payment-service: db.pool.max dropped from 40 to 10 at the config deploy 38 minutes ago; db.pool.active has "
        "been pinned at 10/10 since, db.pool.pending 0 -> 60; before the deploy the busiest hour peaked at 22 active "
        "connections. p99 latency 140ms -> 3100ms, HTTP 5xx 0.1% -> 31%. payments-db CPU 35% (normal)."),
    "checkout_latency": ("checkout-api", 30,
        "checkout-api: p50 latency 190ms and p99 410ms over the last 2 hours, both within the usual range; error rate "
        "0.05%; traffic normal for a weekday morning."),
    "kafka_rebalance_lag": ("orders-consumer", 30,
        "orders-consumer: consumer group lag on order-events rose from under 100 to 48k messages after the scale-out "
        "from 3 to 6 replicas 44 minutes ago; 5 rebalances in 14 minutes; processing time per 500-message batch up "
        "to 341s against max.poll.interval.ms of 300s."),
    "tls_cert_expiry": ("auth-gateway", 33,
        "auth-gateway: successful logins dropped from 99.8% to 0.4% at one exact minute 34 minutes ago; TLS "
        "handshake errors to identity-api 2.3k/min; certificate-expiry gauge for identity-api.internal.demo at 0 "
        "days; no deploys in the last 24 hours."),
    "oom_memory_leak": ("inventory-service", 20,
        "inventory-service: container memory grows linearly by about 210Mi per hour since v2.14.0 was deployed, "
        "reaching the 1024Mi limit; OOMKilled restarts every 3 to 4 hours; GC time 2% -> 34%; traffic flat."),
    "redis_cache_stampede": ("catalog-service", 30,
        "catalog-service: Redis memory at maxmemory (2gb) with 2.1M evictions in 12 minutes; cache hit ratio 0.94 "
        "-> 0.31; catalog-db CPU 38% -> 96% and query p99 4.8s at the same moment; product page p99 5.2s."),
    "gateway_timeouts": ("psp-connector", 30,
        "psp-connector: p99 latency of PayFlow authorizations 600ms -> 9.8s, timeouts 41% of calls; psp-connector "
        "CPU, memory and database metrics normal; other providers unaffected."),
    "disk_full_logs": ("notification-service", 30,
        "notification-service: /var/log/app volume usage 62% -> 100% over 3 days (log rotation stopped 61 minutes "
        "ago failed again); write errors 140/min; email queue depth 1,940."),
}

# ---------------------------------------------------------------- runbooks and past incidents (timeless)

_RUNBOOKS: list[tuple[str, str | None, str, str]] = [
    ("db_pool", "payment-service", "Database connection pool exhausted (payment-service)", """# Runbook: database connection pool exhausted

Owner: #payments-oncall | Database: payments-db

## Symptoms
- "Connection is not available, request timed out" from HikariPool; requests hang for the connection timeout, then fail.
- db.pool.active flat at the maximum while db.pool.pending grows; database CPU normal.

## Diagnosis
1. Compare db.pool.max now with last week: a smaller pool after a config change is the most common cause.
2. Check the ArgoCD history of payment-service-config for changes to spring.datasource.hikari.maximum-pool-size.
3. If the size did not change, look for long transactions in pg_stat_activity (idle in transaction, lock waits).

## Mitigation
- Revert the config change in ArgoCD (or set maximum-pool-size back to 40) and restart pods one at a time.
- Shed load on write endpoints until the pool recovers.

## Prevention
- Review pool-size changes against peak usage (payment-service peaks at about 22 active connections).
- Alert when pool usage stays above 80% for 5 minutes.
"""),
    ("kafka_lag", "orders-consumer", "Kafka consumer lag and rebalance storms (orders-consumer)",
     """# Runbook: Kafka consumer lag after rebalances

Owner: #orders-oncall | Topic: order-events (12 partitions)

## Symptoms
- Lag grows while all consumers are running; repeated "rebalance in progress" and CommitFailedException.
- "poll timeout has expired ... max.poll.interval.ms" in consumer logs.

## Diagnosis
1. Count rebalances in the last 30 minutes; more than 2 means members keep leaving the group.
2. Compare batch processing time with max.poll.interval.ms: a batch that takes longer makes the member leave.
3. Check for a recent scale-out: new members trigger rebalances, slow batches turn them into a storm.

## Mitigation
- Lower max.poll.records (500 -> 100) so a batch finishes well inside max.poll.interval.ms.
- Pause autoscaling of orders-consumer until the lag is drained.

## Prevention
- Cooperative sticky assignor; keep batch time under half of max.poll.interval.ms.
"""),
    ("tls_internal", "auth-gateway", "Expired certificate on an internal API", """# Runbook: expired internal TLS certificate

Owner: #platform-oncall | Issuer: cert-manager ClusterIssuer internal-ca

## Symptoms
- All calls to one internal API fail at once with "certificate expired"; no deploy before it.

## Diagnosis
1. `kubectl describe certificate <name> -n <namespace>`: why did renewal fail?
2. Check the ClusterIssuer and its CA secret; a missing or rotated secret blocks every renewal.

## Mitigation
- Restore the CA secret, then `cmctl renew <certificate>` and restart the API's pods.

## Prevention
- Alert at 21 and 7 days before expiry; alert on Certificate resources that are not Ready.
"""),
    ("memory_leak", "inventory-service", "Memory leak and OOMKilled pods", """# Runbook: memory leak / OOMKilled pods

Owner: #inventory-oncall

## Symptoms
- Memory climbs in a straight line until pods are OOMKilled (exit code 137); GC time rises first.

## Diagnosis
1. Plot memory per pod since the last deploy: a constant slope that starts with a release points at that release.
2. Look for new in-memory caches or collections without a maximum size.

## Mitigation
- Roll back to the previous version; a rolling restart only buys a few hours.

## Prevention
- Every cache gets a maximum size and an expiry; alert on memory slope.
"""),
    ("cache_stampede", "catalog-service", "Redis evictions and cache stampede (catalog-service)",
     """# Runbook: cache stampede after Redis evictions

Owner: #catalog-oncall | Redis: catalog-cache (maxmemory 2gb, allkeys-lru)

## Symptoms
- Hit ratio collapses, many requests rebuild the same keys at once, database CPU spikes.

## Diagnosis
1. Redis INFO: used_memory at maxmemory and evicted_keys rising means the cache is too small for the working set.
2. Check whether hot keys are rebuilt by many requests at once (no request coalescing / locking).

## Mitigation
- Raise maxmemory (2gb -> 4gb) and enable request coalescing for product keys.

## Prevention
- Alert on evicted_keys rate; jittered TTLs; single-flight cache loading.
"""),
    ("psp_timeouts", "psp-connector", "Payment provider (PayFlow) timeouts", """# Runbook: card processor timeouts

Owner: #payments-oncall | Provider: PayFlow

## Symptoms
- Timeouts only on calls to PayFlow while our own services are healthy.

## Diagnosis
1. Check the PayFlow status page and compare their incident time with our first timeout.
2. Confirm other providers and internal dependencies are unaffected.

## Mitigation
- Route new card payments to the fallback provider; keep retries at most 1 with jitter.

## Prevention
- Per-provider timeouts and circuit breakers; automatic fallback routing.
"""),
    ("disk_full", "notification-service", "Disk full on a log volume", """# Runbook: log volume full

Owner: #messaging-oncall

## Symptoms
- "No space left on device" when writing logs or files; jobs retry and queues grow.

## Diagnosis
1. `df -h /var/log/app` in the pod; check whether logrotate ran (its errors are in the pod's own log).

## Mitigation
- Delete rotated archives older than 2 days, fix the postrotate script and run logrotate by hand.

## Prevention
- Ship logs to stdout instead of files; alert at 80% volume usage.
"""),
    ("onboarding", None, "Onboarding a new service to the cluster", """# Runbook: onboarding a new service

Owner: #platform-oncall

## Checklist
- Namespace, resource requests and limits, readiness and liveness probes.
- Dashboards and alerts from the standard template.
"""),
]

_PAST_INCIDENTS: list[tuple[str, str, int, str, str, str]] = [
    ("db_pool_deploy", "payment-service", 210, "Payment failures after a pool-size change",
     "A configuration refactor lowered the HikariPool maximum size from 40 to 8; peak traffic needs about 22 "
     "connections, so requests waited for connections and timed out.",
     "Restored maximum-pool-size to 40 and added a review rule for pool-size changes."),
    ("kafka_rebalance_lag", "orders-consumer", 160, "orders-consumer lag after scaling out",
     "Scaling out triggered rebalances; batches of 500 events took longer than max.poll.interval.ms, so members "
     "kept leaving the group and the lag grew.",
     "Lowered max.poll.records to 100 and switched to the cooperative sticky assignor."),
    ("tls_cert_expiry", "auth-gateway", 330, "Internal API certificate expired",
     "cert-manager could not renew the certificate because the internal CA secret had been removed during a "
     "namespace clean-up.",
     "Restored the CA secret, renewed the certificate and added a not-Ready certificate alert."),
    ("oom_memory_leak", "inventory-service", 95, "inventory-service OOMKilled after a release",
     "A new in-memory cache had no maximum size and grew until the pods ran out of memory.",
     "Rolled back, then re-released with maximumSize and expireAfterWrite on the cache."),
    ("redis_cache_stampede", "catalog-service", 120, "Catalog slowdown during a sale",
     "Redis reached maxmemory, evicted hot product keys and thousands of requests rebuilt them at once.",
     "Doubled maxmemory and added single-flight loading for product keys."),
    ("gateway_timeouts", "psp-connector", 60, "Card authorizations timing out",
     "PayFlow had a regional latency incident; our retries without jitter added load.",
     "Failed over to the fallback provider and reduced retries to one."),
    ("disk_full_logs", "notification-service", 400, "Log volume full on notification-service",
     "The logrotate postrotate script failed after a base image update, so logs were never rotated.",
     "Fixed the script and moved application logs to stdout."),
    ("noise", "search-service", 250, "Search index rebuild delayed",
     "The nightly index rebuild job ran out of disk on its build node and restarted from the beginning.",
     "Moved the build to a larger node and made the job resume from its last checkpoint."),
]


def _iso(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


def build_dataset(anchor: datetime) -> dict[str, list[dict]]:
    """{runbooks, logs, metrics, incidents} for tenant "demo", log and metric times relative to `anchor` (aware UTC)."""
    logs: list[dict] = []
    for scenario, (service, lines) in _LOGS.items():
        for index, (minutes, level, message) in enumerate(lines, start=1):
            logs.append({
                "source_id": f"LOG-{TENANT}-{scenario}-{index:03d}",
                "tenant_id": TENANT,
                "source_type": "log",
                "service": service,
                "ts": _iso(anchor - timedelta(minutes=minutes)),
                "level": level,
                "message": message,
            })
    for index, (minutes, service, level, message) in enumerate(_NOISE, start=1):
        logs.append({
            "source_id": f"LOG-{TENANT}-noise-{index:04d}",
            "tenant_id": TENANT,
            "source_type": "log",
            "service": service,
            "ts": _iso(anchor - timedelta(minutes=minutes)),
            "level": level,
            "message": message,
        })

    metrics = [
        {
            "source_id": f"MET-{TENANT}-{scenario}",
            "tenant_id": TENANT,
            "source_type": "metric",
            "service": service,
            "ts": _iso(anchor - timedelta(minutes=minutes)),
            "summary": summary,
        }
        for scenario, (service, minutes, summary) in _METRICS.items()
    ]
    runbooks = [
        {
            "source_id": f"RB-{TENANT}-{name}",
            "tenant_id": TENANT,
            "source_type": "runbook",
            "service": service,
            "title": title,
            "content": content,
        }
        for name, service, title, content in _RUNBOOKS
    ]
    incidents = [
        {
            "source_id": f"INC-{TENANT}-{scenario}-1",
            "tenant_id": TENANT,
            "source_type": "incident",
            "service": service,
            "ts": _iso(anchor - timedelta(days=days)),
            "title": title,
            "root_cause": root_cause,
            "fix": fix,
        }
        for scenario, service, days, title, root_cause, fix in _PAST_INCIDENTS
    ]
    return {"runbooks": runbooks, "logs": logs, "metrics": metrics, "incidents": incidents}
