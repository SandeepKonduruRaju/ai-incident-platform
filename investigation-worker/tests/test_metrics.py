"""Prometheus metrics of the worker (section 3.4): incremented on each graph path with FakeLLM, LLM error
kinds, DLQ and lag, the /metrics server, and a guard against high-cardinality labels. No Docker."""

import asyncio
import re
import socket
import urllib.request
from types import SimpleNamespace

import pytest
from aiokafka import TopicPartition
from prometheus_client import REGISTRY

from app.config import Settings
from app.consumer import Failure, IncidentEventConsumer
from app.errors import ErrorCategory, LLMConfigError, TransientLLMError
from app.llm import FakeLLM
from app.llm_observed import ObservedLLM
from app.metrics import start_metrics_server, stop_metrics_server
from tests.test_graph import EVIDENCE, UNKNOWN_CITATION, VALID, _deps, _run

OUR_METRICS = {
    "investigations", "investigation_duration_seconds", "graph_node_duration_seconds", "llm_request_duration_seconds",
    "llm_tokens", "llm_cost_usd", "llm_errors", "repair_attempts", "insufficient_evidence", "kafka_consumer_lag",
    "dlq_messages", "retrieval_duration_seconds", "retrieved_chunks",
}
ALLOWED_LABELS = {"status", "model", "prompt_version", "node", "kind", "direction", "partition", "reason", "le"}
UUID_LIKE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-")


def value(name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


def observed(llm: FakeLLM) -> ObservedLLM:
    return ObservedLLM(inner=llm, model="fake-llm", prompt_version="v1", price_in_per_m=0.10, price_out_per_m=0.50)


async def test_completed_run_counts_outcome_duration_nodes_and_llm_usage():
    before = {
        "done": value("investigations_total", status="COMPLETED", model="fake-llm", prompt_version="v1"),
        "duration": value("investigation_duration_seconds_count", status="COMPLETED"),
        "analyse": value("graph_node_duration_seconds_count", node="analyse"),
        "tokens_in": value("llm_tokens_total", model="fake-llm", direction="input"),
        "cost": value("llm_cost_usd_total", model="fake-llm"),
    }
    deps, _, _ = _deps(observed(FakeLLM([VALID])))

    state = await _run(deps)

    assert state["outcome"] == "COMPLETED"
    assert value("investigations_total", status="COMPLETED", model="fake-llm", prompt_version="v1") == before["done"] + 1
    assert value("investigation_duration_seconds_count", status="COMPLETED") == before["duration"] + 1
    assert value("graph_node_duration_seconds_count", node="analyse") == before["analyse"] + 1
    assert value("llm_tokens_total", model="fake-llm", direction="input") > before["tokens_in"]
    assert value("llm_cost_usd_total", model="fake-llm") > before["cost"]


async def test_invalid_answers_count_repair_invalid_output_and_failed():
    before = (
        value("repair_attempts_total"),
        value("llm_errors_total", model="fake-llm", kind="invalid_output"),
        value("investigations_total", status="FAILED", model="fake-llm", prompt_version="v1"),
    )
    deps, _, _ = _deps(observed(FakeLLM([UNKNOWN_CITATION, UNKNOWN_CITATION])))

    state = await _run(deps)

    assert state["outcome"] == "FAILED"
    assert value("repair_attempts_total") == before[0] + 1
    assert value("llm_errors_total", model="fake-llm", kind="invalid_output") == before[1] + 2
    assert value("investigations_total", status="FAILED", model="fake-llm", prompt_version="v1") == before[2] + 1


async def test_repaired_answer_completes_after_one_repair():
    repairs = value("repair_attempts_total")
    deps, _, _ = _deps(observed(FakeLLM([UNKNOWN_CITATION, VALID])))

    assert (await _run(deps))["outcome"] == "COMPLETED"
    assert value("repair_attempts_total") == repairs + 1


async def test_no_evidence_counts_insufficient_evidence_without_a_model():
    before = (value("insufficient_evidence_total"),
              value("investigations_total", status="COMPLETED", model="none", prompt_version="v1"))
    deps, _, _ = _deps(observed(FakeLLM()), evidence=[])

    await _run(deps)

    assert value("insufficient_evidence_total") == before[0] + 1
    assert value("investigations_total", status="COMPLETED", model="none", prompt_version="v1") == before[1] + 1


@pytest.mark.parametrize(
    ("error", "kind"),
    [(TransientLLMError("429", kind="rate_limit"), "rate_limit"), (TransientLLMError("timeout", kind="timeout"), "timeout"),
     (TransientLLMError("529"), "server"), (LLMConfigError("bad key"), "config")],
)
async def test_llm_errors_are_counted_by_kind(error, kind):
    before = value("llm_errors_total", model="fake-llm", kind=kind)
    with pytest.raises(type(error)):
        await observed(FakeLLM([error])).generate("system", "user", {})
    assert value("llm_errors_total", model="fake-llm", kind=kind) == before + 1


async def test_dead_lettered_message_is_counted_by_reason():
    class Producer:
        async def send_and_wait(self, *args, **kwargs):
            return None

    consumer = IncidentEventConsumer(Settings(database_url="unused"), processor=None)
    record = SimpleNamespace(topic="incident-events", partition=0, offset=7, value=b"{", key=None, headers=[])
    before = value("dlq_messages_total", reason="permanent")

    await consumer._dead_letter(Producer(), record, Failure(ErrorCategory.PERMANENT, ValueError("bad"), 1))

    assert value("dlq_messages_total", reason="permanent") == before + 1


async def test_consumer_lag_is_end_offset_minus_committed_per_partition():
    tp = TopicPartition("incident-events", 2)

    class Kafka:
        def assignment(self):
            return {tp}

        async def end_offsets(self, partitions):
            return {tp: 10}

        async def committed(self, partition):
            return 7

    consumer = IncidentEventConsumer(Settings(database_url="unused"), processor=None)
    task = asyncio.create_task(consumer._report_lag(Kafka()))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert value("kafka_consumer_lag", partition="2") == 3


def test_metrics_endpoint_serves_our_metrics_on_its_own_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    start_metrics_server(port)
    try:
        body = urllib.request.urlopen(f"http://127.0.0.1:{port}/metrics", timeout=5).read().decode()
    finally:
        stop_metrics_server()
    assert "# TYPE investigations_total counter" in body
    assert "llm_cost_usd_total" in body
    assert "ANTHROPIC" not in body and "INTERNAL_API_TOKEN" not in body


async def test_labels_stay_low_cardinality():
    """No ids or free text in labels: one time series per incident would overload Prometheus."""
    deps, _, _ = _deps(observed(FakeLLM([VALID])))
    await _run(deps)  # make sure every graph metric has samples

    families = [f for f in REGISTRY.collect() if f.name in OUR_METRICS]
    assert {f.name for f in families} == OUR_METRICS
    for family in families:
        for sample in family.samples:
            assert set(sample.labels) <= ALLOWED_LABELS, (family.name, sample.labels)
            for label_value in sample.labels.values():
                assert not UUID_LIKE.search(label_value), (family.name, sample.labels)
                assert len(label_value) <= 40, (family.name, sample.labels)
        assert len(family.samples) < 200, family.name
    contents = {item.content for item in EVIDENCE}
    assert not any(v in contents for f in families for s in f.samples for v in s.labels.values())
