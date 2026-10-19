"""The whole LangGraph workflow with FakeLLM, a fake retriever and an in-memory store (no Docker, no network)."""

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest

from app.errors import LLMConfigError, PermanentLLMError, TransientLLMError
from app.events import IncidentCreatedPayload
from app.graph import GraphDeps, build_graph, run_investigation
from app.investigations import InvestigationRef
from app.llm import FakeLLM, LLMResponse
from app.retrieval import EvidenceItem

REF = InvestigationRef(id=uuid.uuid4(), tenant_id="acme", status="RUNNING", run_count=1)
INCIDENT = IncidentCreatedPayload(
    incidentId=uuid.uuid4(),
    title="payment-service timing out",
    description="Requests hang, then fail.",
    severity="HIGH",
    status="OPEN",
    affectedService="payment-service",
    createdAt=datetime(2026, 9, 24, 22, 30, tzinfo=UTC),
)


def _item(label: str, source_type: str = "log", content: str = "HikariPool timeout") -> EvidenceItem:
    return EvidenceItem(
        label=label, chunk_id=uuid.uuid4(), tenant_id="acme", source_type=source_type,
        source_id=f"SRC-{label}", service="payment-service", ts=None, content=content,
        rrf_score=0.03, rerank_score=1.0,
    )


EVIDENCE = [_item("C1"), _item("C2", "runbook", "Runbook: kill idle sessions")]

VALID = json.dumps(
    {
        "root_cause": {"text": "Connection pool exhausted [C1]", "citations": ["C1"]},
        "contributing_factors": [],
        "remediation": [{"text": "Kill idle sessions [C2]", "citations": ["C2"]}],
        "confidence": "medium",
        "summary": "Pool exhaustion [C1].",
    }
)
UNKNOWN_CITATION = VALID.replace('["C2"]', '["C9"]')


@dataclass
class MemoryStore:
    saves: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    async def save_completed(self, ref: InvestigationRef, **values: Any) -> bool:
        self.saves.append(("COMPLETED", values))
        return True

    async def save_failed(self, ref: InvestigationRef, **values: Any) -> bool:
        self.saves.append(("FAILED", values))
        return True


def _deps(llm: FakeLLM, evidence=EVIDENCE, **overrides) -> tuple[GraphDeps, MemoryStore, list[float]]:
    store, sleeps = MemoryStore(), []

    async def retrieve(tenant_id: str, incident: IncidentCreatedPayload) -> list[EvidenceItem]:
        assert tenant_id == "acme"
        return list(evidence)

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    deps = GraphDeps(retrieve=retrieve, llm=llm, store=store, sleep=fake_sleep, **overrides)
    return deps, store, sleeps


async def _run(deps: GraphDeps, budget: float = 60.0):
    return await run_investigation(deps, REF, INCIDENT, time_budget_seconds=budget)


async def test_happy_path_completes_with_result_evidence_and_usage():
    llm = FakeLLM([VALID])
    deps, store, _ = _deps(llm)

    state = await _run(deps)

    assert state["outcome"] == "COMPLETED"
    [(status, saved)] = store.saves
    assert status == "COMPLETED"
    assert saved["result"]["root_cause"]["citations"] == ["C1"]
    assert [e["label"] for e in saved["evidence"]] == ["C1", "C2"]
    assert saved["evidence"][0]["source_id"] == "SRC-C1"
    assert saved["attempts"] == 1
    assert saved["prompt_version"] == "v1"
    assert saved["usage"].model == "fake-llm" and saved["usage"].input_tokens > 0
    assert len(llm.calls) == 1
    assert "<evidence>" in llm.calls[0]["user"] and llm.calls[0]["schema"]["additionalProperties"] is False


async def test_invalid_then_valid_uses_repair_and_completes_with_two_attempts():
    llm = FakeLLM([UNKNOWN_CITATION, VALID])
    deps, store, _ = _deps(llm)

    state = await _run(deps)

    assert state["outcome"] == "COMPLETED"
    [(status, saved)] = store.saves
    assert (status, saved["attempts"]) == ("COMPLETED", 2)
    repair_prompt = llm.calls[1]["user"]
    assert "<previous_answer>" in repair_prompt and "C9" in repair_prompt  # the error is fed back
    assert saved["usage"].output_tokens == sum(len(t) // 4 for t in (UNKNOWN_CITATION, VALID))


async def test_invalid_twice_fails_but_still_stores_the_evidence():
    llm = FakeLLM(["not json", UNKNOWN_CITATION, VALID])  # the third answer must never be requested
    deps, store, _ = _deps(llm)

    state = await _run(deps)

    assert state["outcome"] == "FAILED"
    [(status, saved)] = store.saves
    assert status == "FAILED"
    assert saved["reason"].startswith("invalid LLM output after 2 attempts") and "C9" in saved["reason"]
    assert [e["label"] for e in saved["evidence"]] == ["C1", "C2"]
    assert len(llm.calls) == 2


async def test_max_tokens_answer_goes_to_repair():
    truncated = LLMResponse(VALID[:40], 100, 4096, 10, "m", "max_tokens")
    llm = FakeLLM([truncated, VALID])
    deps, store, _ = _deps(llm)

    await _run(deps)

    assert store.saves[0][0] == "COMPLETED"
    assert "max_tokens" in llm.calls[1]["user"]


async def test_no_evidence_completes_as_insufficient_without_calling_the_llm():
    llm = FakeLLM([VALID])
    deps, store, _ = _deps(llm, evidence=[])

    state = await _run(deps)

    assert state["outcome"] == "COMPLETED"
    [(status, saved)] = store.saves
    assert status == "COMPLETED"
    assert saved["result"]["root_cause"] is None
    assert (saved["result"]["confidence"], saved["result"]["summary"]) == ("low", "insufficient evidence")
    assert saved["evidence"] == [] and saved["attempts"] == 0
    assert llm.calls == []


async def test_transient_error_is_retried_then_succeeds():
    llm = FakeLLM([TransientLLMError("529 overloaded"), TransientLLMError("429", retry_after=2.5), VALID])
    deps, store, sleeps = _deps(llm, llm_max_retries=3, retry_base_delay_seconds=0.1, retry_max_delay_seconds=1.0)

    state = await _run(deps)

    assert state["outcome"] == "COMPLETED"
    assert len(llm.calls) == 3
    assert len(sleeps) == 2 and 0 <= sleeps[0] <= 0.1 and sleeps[1] == 2.5  # backoff, then retry-after
    assert store.saves[0][1]["attempts"] == 1  # retries of ONE output are not extra output attempts


async def test_transient_errors_exhausting_retries_fail_the_investigation():
    llm = FakeLLM([TransientLLMError("503")] * 3)
    deps, store, _ = _deps(llm, llm_max_retries=3)

    await _run(deps)

    [(status, saved)] = store.saves
    assert status == "FAILED" and "LLM unavailable after 3 tries" in saved["reason"]
    assert saved["evidence"]


async def test_permanent_llm_error_fails_without_retry():
    llm = FakeLLM([PermanentLLMError("400 invalid_request_error")])
    deps, store, sleeps = _deps(llm)

    await _run(deps)

    assert store.saves[0][0] == "FAILED" and "rejected" in store.saves[0][1]["reason"]
    assert len(llm.calls) == 1 and sleeps == []


async def test_time_budget_exceeded_fails():
    class SlowLLM(FakeLLM):
        async def generate(self, system, user, schema):
            await asyncio.sleep(5)
            return await super().generate(system, user, schema)

    deps, store, _ = _deps(SlowLLM([VALID]))

    state = await _run(deps, budget=0.05)

    assert state["outcome"] == "FAILED"
    assert store.saves[0][1]["reason"] == "time budget exceeded"


async def test_llm_config_error_propagates_and_nothing_is_saved():
    deps, store, _ = _deps(FakeLLM([LLMConfigError("bad key")]))

    with pytest.raises(LLMConfigError):
        await _run(deps)
    assert store.saves == []


async def test_graph_compiles_once_and_is_reusable():
    deps, store, _ = _deps(FakeLLM([VALID, VALID]))
    graph = build_graph(deps)

    for _ in range(2):
        await run_investigation(deps, REF, INCIDENT, time_budget_seconds=60, graph=graph)

    assert [status for status, _ in store.saves] == ["COMPLETED", "COMPLETED"]
