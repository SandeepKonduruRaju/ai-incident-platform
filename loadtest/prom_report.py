"""Server-side numbers for one load-test run, from the observability profile's Prometheus (milestone 4).

    python loadtest/prom_report.py --start 2026-10-26T13:00:00Z --end 2026-10-26T13:05:00Z --out loadtest/results/x.prom.json

Prints Kafka lag peak, investigations/min, cache hit ratio, CPU and pool saturation over [start, end], so the
k6 client-side numbers can be matched with what the services saw. Standard library only.
"""

import argparse
import json
import urllib.parse
import urllib.request
from datetime import datetime

QUERIES = {
    "kafka_lag_peak": "max_over_time(sum(kafka_consumer_lag)[{d}s:5s])",
    "investigations_per_min": 'sum(increase(investigations_total{{status=~"COMPLETED|FAILED"}}[{d}s])) * 60 / {d}',
    "investigations_failed": 'sum(increase(investigations_total{{status="FAILED"}}[{d}s]))',
    "investigation_p95_s": "histogram_quantile(0.95, sum by (le) (rate(investigation_duration_seconds_bucket[{d}s])))",
    "cache_hit_ratio": (
        "sum(increase(cache_hits_total[{d}s])) / (sum(increase(cache_hits_total[{d}s])) + sum(increase(cache_misses_total[{d}s])))"
    ),
    "cache_hits": "sum(increase(cache_hits_total[{d}s]))",
    "rate_limited": "sum(increase(rate_limited_total[{d}s]))",
    "redis_errors": "sum(increase(redis_errors_total[{d}s]))",
    "worker_client_errors": "sum(increase(worker_client_errors_total[{d}s]))",
    "api_p95_s_server": (
        "histogram_quantile(0.95, sum by (le) (rate(http_server_requests_seconds_bucket"
        '{{job="incident-service",uri=~"/api/v1/incidents.*"}}[{d}s])))'
    ),
    "incident_service_cpu_peak": 'max_over_time(process_cpu_usage{{job="incident-service"}}[{d}s:5s])',
    "incident_service_tomcat_busy_peak": 'max_over_time(sum(tomcat_threads_busy_threads{{job="incident-service"}})[{d}s:5s])',
    "incident_service_hikari_pending_peak": 'max_over_time(sum(hikaricp_connections_pending{{job="incident-service"}})[{d}s:5s])',
    "worker_cpu_cores_peak": 'max_over_time(rate(process_cpu_seconds_total{{job="investigation-worker"}}[30s])[{d}s:5s])',
}


def _instant(prometheus: str, query: str, at: datetime) -> float | None:
    url = f"{prometheus}/api/v1/query?" + urllib.parse.urlencode({"query": query, "time": at.timestamp()})
    with urllib.request.urlopen(url, timeout=15) as response:  # noqa: S310 (local Prometheus)
        result = json.load(response)["data"]["result"]
    if not result:
        return None
    value = float(result[0]["value"][1])
    return None if value != value else round(value, 4)  # NaN (e.g. 0/0 hit ratio) -> None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--start", required=True, help="ISO-8601 UTC, e.g. 2026-10-26T13:00:00Z")
    parser.add_argument("--end", required=True)
    parser.add_argument("--prometheus", default="http://localhost:9090")
    parser.add_argument("--out", help="also write the numbers as JSON here")
    args = parser.parse_args()

    start = datetime.fromisoformat(args.start.replace("Z", "+00:00"))
    end = datetime.fromisoformat(args.end.replace("Z", "+00:00"))
    window = max(int((end - start).total_seconds()), 60)
    numbers = {name: _instant(args.prometheus, q.format(d=window), end) for name, q in QUERIES.items()}

    for name, value in numbers.items():
        print(f"  {name:<38} {value}")
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump({"start": args.start, "end": args.end, **numbers}, f, indent=2)


if __name__ == "__main__":
    main()
