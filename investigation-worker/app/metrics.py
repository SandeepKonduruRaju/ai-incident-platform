"""Prometheus metrics of the worker (section 3.4), served on their own port (METRICS_PORT, default 9464).

prometheus_client, not the OpenTelemetry metrics SDK: Prometheus pulls, so a plain /metrics endpoint
is all we need (no exporter pipeline, no push interval), and the Java service is scraped the same way.
OpenTelemetry is used for traces only (app.tracing).

Labels are LOW-CARDINALITY only: status, model, prompt version, node, kind, direction, partition.
Never incident / investigation / tenant / request ids (one time series per id would overload Prometheus)
and never prompt, evidence or log text. tests/test_metrics.py guards this.
"""

import logging
import threading

from prometheus_client import Counter, Gauge, Histogram, start_http_server

log = logging.getLogger(__name__)

_SECONDS = (0.05, 0.1, 0.25, 0.5, 1, 2, 3, 5, 8, 13, 20, 30, 45, 60, 90, 120)

INVESTIGATIONS = Counter(
    "investigations", "Investigations finished, by outcome", ["status", "model", "prompt_version"]
)
INVESTIGATION_DURATION = Histogram(
    "investigation_duration_seconds", "Wall-clock time of one investigation run", ["status"], buckets=_SECONDS
)
GRAPH_NODE_DURATION = Histogram(
    "graph_node_duration_seconds", "Time spent in one LangGraph node", ["node"], buckets=_SECONDS
)
LLM_REQUEST_DURATION = Histogram(
    "llm_request_duration_seconds", "One LLM API call (successful responses)", ["model"], buckets=_SECONDS
)
LLM_TOKENS = Counter("llm_tokens", "LLM tokens used", ["model", "direction"])
LLM_COST = Counter("llm_cost_usd", "Estimated LLM cost in USD (configured prices per million tokens)", ["model"])
LLM_ERRORS = Counter(
    "llm_errors", "LLM failures: rate_limit | timeout | server | config | invalid_output | rejected", ["model", "kind"]
)
REPAIR_ATTEMPTS = Counter("repair_attempts", "Repair prompts sent after an invalid LLM answer")
INSUFFICIENT_EVIDENCE = Counter("insufficient_evidence", "Investigations finished without evidence (no LLM call)")
KAFKA_CONSUMER_LAG = Gauge("kafka_consumer_lag", "Messages behind the end of the partition", ["partition"])
DLQ_MESSAGES = Counter("dlq_messages", "Messages sent to the dead-letter topic", ["reason"])
STALE_INVESTIGATIONS_REAPED = Counter(
    "stale_investigations_reaped", "RUNNING investigations marked FAILED because their run stopped making progress"
)
RETRIEVAL_DURATION = Histogram("retrieval_duration_seconds", "Hybrid retrieval for one incident", buckets=_SECONDS)
RETRIEVED_CHUNKS = Histogram(
    "retrieved_chunks", "Evidence items handed to the LLM", buckets=(0, 1, 2, 3, 4, 5, 6, 8, 10, 15, 20)
)

_server_lock = threading.Lock()
_server = None


def start_metrics_server(port: int) -> None:
    """Serves /metrics on its own port (not the API port). Idempotent; port 0 = disabled."""
    global _server
    if port <= 0:
        return
    with _server_lock:
        if _server is None:
            _server, _thread = start_http_server(port)
            log.info("metrics on :%d/metrics", port)


def stop_metrics_server() -> None:
    global _server
    with _server_lock:
        if _server is not None:
            _server.shutdown()
            _server.server_close()
            _server = None


def record_llm_usage(model: str, input_tokens: int, output_tokens: int, cost_usd: float, seconds: float) -> None:
    LLM_REQUEST_DURATION.labels(model).observe(seconds)
    LLM_TOKENS.labels(model, "input").inc(input_tokens)
    LLM_TOKENS.labels(model, "output").inc(output_tokens)
    LLM_COST.labels(model).inc(cost_usd)


LLM_ERROR_KINDS = ("rate_limit", "timeout", "server", "config", "invalid_output", "rejected")
DLQ_REASONS = ("permanent", "transient")
OUTCOMES = ("COMPLETED", "FAILED")


def initialize_series(model: str, prompt_version: str) -> None:
    """Creates the known label combinations at 0. A labelled counter otherwise appears only at its first
    increment, starting at 1, and increase()/rate() over it stay 0: the first DLQ message or auth error
    would never fire its alert."""
    for kind in LLM_ERROR_KINDS:
        LLM_ERRORS.labels(model, kind)
    for reason in DLQ_REASONS:
        DLQ_MESSAGES.labels(reason)
    for outcome in OUTCOMES:
        INVESTIGATIONS.labels(outcome, model, prompt_version)
    INVESTIGATIONS.labels("COMPLETED", "none", prompt_version)  # insufficient evidence: no LLM call
