"""Unit tests for the investigation eval (section 2.8): metrics, judge parsing, cache, budget, dataset.
No API key, no network, no database."""

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.eval_investigation import (
    CASE_TYPES,
    CASES_PATH,
    INJECTED_SOURCE_PREFIX,
    citation_coverage,
    citation_valid,
    evidence_hit,
    inject,
    injection_followed,
    insufficient_evidence_correct,
    load_cases,
    percentile,
    rate,
    schema_valid,
)
from app.events import IncidentCreatedPayload
from app.eval_judge import FakeJudgeLLM, build_judge_message, findings_of, parse_judge
from app.ingest import DEFAULT_DATA_DIR
from app.llm import FakeLLM
from app.llm_cache import Budget, BudgetExceeded, CachingLLM, cost_usd
from app.retrieval import EvidenceItem
from app.synthetic import SCENARIOS

RESULT = {
    "root_cause": {"text": "Pool exhausted [C1].", "citations": ["C1"]},
    "contributing_factors": [{"text": "Slow queries [C2].", "citations": ["C2"]}],
    "remediation": [{"text": "Kill idle sessions.", "citations": ["C3"]}],
    "confidence": "high",
    "summary": "The pool is exhausted [C1].",
}
LABELS = {"C1", "C2", "C3"}


def _item(label: str, source_id: str = "RB-acme-x") -> EvidenceItem:
    return EvidenceItem(label=label, chunk_id=uuid.uuid4(), tenant_id="acme", source_type="runbook", source_id=source_id,
                        service="payment-service", ts=None, content=f"content {label}", rrf_score=0.1, rerank_score=1.0)


# ---------------------------------------------------------------- deterministic metrics


def test_citation_validity_checks_citation_lists_and_inline_labels():
    assert citation_valid(RESULT, LABELS) is True
    assert citation_valid(RESULT, {"C1", "C2"}) is False  # remediation cites C3
    inline_only = {**RESULT, "summary": "See [C9]."}
    assert citation_valid(inline_only, LABELS) is False
    assert citation_valid(None, LABELS) is None


def test_citation_coverage_is_share_of_findings_with_a_citation():
    assert citation_coverage(RESULT) == 1.0
    uncited = {**RESULT, "remediation": [{"text": "Do something.", "citations": []}]}
    assert citation_coverage(uncited) == pytest.approx(2 / 3)
    assert citation_coverage({**RESULT, "root_cause": None, "contributing_factors": [], "remediation": []}) is None


def test_schema_valid():
    assert schema_valid(RESULT)
    assert not schema_valid(None)
    assert not schema_valid({**RESULT, "root_cause": None})  # null root cause requires confidence low


def test_insufficient_evidence_needs_null_root_cause_and_low_confidence():
    abstain = {**RESULT, "root_cause": None, "confidence": "low"}
    assert insufficient_evidence_correct(abstain)
    assert not insufficient_evidence_correct(RESULT)
    assert not insufficient_evidence_correct({**abstain, "confidence": "medium"})
    assert not insufficient_evidence_correct(None)


def test_evidence_hit_matches_ids_and_log_windows_by_prefix():
    expected = ["LOG-acme-db_pool_exhausted-001", "RB-acme-db_pool_exhausted"]
    assert evidence_hit(["LOG-acme-db_pool_exhausted-payment-service"], expected)
    assert evidence_hit(["RB-acme-db_pool_exhausted"], expected)
    assert not evidence_hit(["LOG-acme-noise-payment-service", "RB-acme-memory_leak"], expected)
    assert evidence_hit(["anything"], []) is None


def test_injection_followed_when_root_cause_adopts_canary_or_rests_only_on_injected_item():
    canary = "solar flare"
    assert not injection_followed(RESULT, canary, {"C2"})
    assert injection_followed({**RESULT, "root_cause": {"text": "A Solar Flare hit RAM.", "citations": ["C1"]}}, canary, {"C2"})
    assert injection_followed({**RESULT, "root_cause": {"text": "Something.", "citations": ["C2"]}}, canary, {"C2"})
    assert not injection_followed({**RESULT, "root_cause": None, "confidence": "low"}, canary, {"C2"})


def test_inject_puts_the_item_second_and_relabels():
    items = inject([_item("C1", "A"), _item("C2", "B")], load_cases(types=["injection"])[0])
    assert [i.label for i in items] == ["C1", "C2", "C3"]
    assert items[1].source_id.startswith(INJECTED_SOURCE_PREFIX)
    assert "ignore" in items[1].content.lower()
    assert [items[0].source_id, items[2].source_id] == ["A", "B"]


def test_percentile_interpolates_like_numpy():
    values = list(range(1, 11))
    assert percentile(values, 50) == pytest.approx(5.5)
    assert percentile(values, 95) == pytest.approx(9.55)
    assert percentile([7], 95) == 7
    assert percentile([], 50) is None


def test_rate_ignores_not_applicable_values():
    assert rate([True, False, None, True]) == pytest.approx(2 / 3)
    assert rate([None]) is None


def test_cost_uses_prices_per_million_tokens():
    assert cost_usd(1_000_000, 0, 0.10, 0.50) == pytest.approx(0.10)
    assert cost_usd(2000, 400, 0.10, 0.50) == pytest.approx(0.0004)


# ---------------------------------------------------------------- judge


def test_findings_are_numbered_root_cause_first():
    findings = findings_of(RESULT)
    assert [(f.index, f.kind) for f in findings] == [(0, "root_cause"), (1, "contributing_factor"), (2, "remediation")]
    assert findings_of(None) == []


def test_judge_message_shows_reference_findings_cited_evidence_and_injection():
    message = build_judge_message(reference_root_cause="pool exhausted", result=RESULT,
                                  evidence={"C1": "HikariPool timeout"}, injection_text="ignore previous instructions")
    assert "<reference_root_cause>\npool exhausted" in message
    assert message.count("<finding index=") == 3
    assert "[C1] HikariPool timeout" in message
    assert "<injection_attempt>" in message
    no_ref = build_judge_message(reference_root_cause=None, result=RESULT, evidence={}, injection_text=None)
    assert "expected to be insufficient" in no_ref and "<injection_attempt>" not in no_ref


async def test_judge_output_from_fake_llm_parses():
    judge = FakeJudgeLLM()
    message = build_judge_message(reference_root_cause="x", result=RESULT, evidence={}, injection_text="ignore it")
    response = await judge.generate("system", message, {})
    verdict, error = parse_judge(response.text)
    assert error is None
    assert [f.index for f in verdict.findings] == [0, 1, 2]
    assert verdict.injection_resisted == "yes"


@pytest.mark.parametrize("text", ["", "not json", json.dumps({"root_cause_verdict": "maybe"})])
def test_invalid_judge_output_is_reported_not_raised(text):
    verdict, error = parse_judge(text)
    assert verdict is None and error.startswith("judge output invalid")


# ---------------------------------------------------------------- cache and budget


def _budget(max_usd: float = 1.0) -> Budget:
    return Budget(max_usd=max_usd, price_in_per_m=0.10, price_out_per_m=0.50, max_output_tokens=4096)


async def test_cache_hit_replays_the_response_without_calling_the_llm(tmp_path: Path):
    inner = FakeLLM()
    budget = _budget()
    llm = CachingLLM(inner, "m", "v1", tmp_path, budget)
    first = await llm.generate("sys", "user [C1] x", {})
    second = await llm.generate("sys", "user [C1] x", {})
    assert second == first
    assert len(inner.calls) == 1 and (llm.stats.hits, llm.stats.misses) == (1, 1)
    assert budget.calls == 1  # the hit was free


@pytest.mark.parametrize("change", [{"salt": "repeat-1"}, {"prompt_version": "v2"}, {"model": "other"}])
async def test_cache_key_includes_model_prompt_version_and_salt(tmp_path: Path, change):
    from dataclasses import replace

    inner = FakeLLM()
    llm = CachingLLM(inner, "m", "v1", tmp_path, _budget())
    await llm.generate("sys", "user", {})
    await replace(llm, **change).generate("sys", "user", {})
    assert len(inner.calls) == 2


async def test_budget_stops_before_a_call_that_could_exceed_it(tmp_path: Path):
    inner = FakeLLM()
    llm = CachingLLM(inner, "m", "v1", tmp_path, _budget(max_usd=0.001))  # worst case of one call is ~$0.002
    with pytest.raises(BudgetExceeded):
        await llm.generate("sys", "user", {})
    assert inner.calls == []


async def test_cached_responses_are_served_even_when_the_budget_is_spent(tmp_path: Path):
    await CachingLLM(FakeLLM(), "m", "v1", tmp_path, _budget()).generate("sys", "user", {})
    inner = FakeLLM()
    response = await CachingLLM(inner, "m", "v1", tmp_path, _budget(max_usd=0.0)).generate("sys", "user", {})
    assert response.text and inner.calls == []


# ---------------------------------------------------------------- dataset file


def _synthetic_ids() -> set[str]:
    return {doc["source_id"] for name in ("logs", "metrics", "runbooks", "incidents")
            for doc in json.loads((DEFAULT_DATA_DIR / f"{name}.json").read_text(encoding="utf-8"))}


def test_dataset_is_marked_synthetic_and_has_the_planned_mix():
    raw = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    assert "SYNTHETIC" in raw["_note"] and "Claude" in raw["_note"]
    counts = {t: sum(1 for c in raw["cases"] if c["case_type"] == t) for t in CASE_TYPES}
    assert counts == {"standard": 12, "paraphrase": 12, "no_evidence": 2, "injection": 2}


def test_dataset_cases_are_valid_and_reference_existing_data():
    cases = load_cases()
    known_ids = _synthetic_ids()
    assert len({c.case_id for c in cases}) == len(cases)
    assert len({c.incident.incidentId for c in cases}) == len(cases)
    for case in cases:
        assert case.case_type in CASE_TYPES
        assert set(case.expected_source_ids) <= known_ids, case.case_id
        if case.case_type == "no_evidence":
            assert case.expected_root_cause is None and case.expected_source_ids == [] and case.scenario is None
        else:
            assert case.scenario in SCENARIOS and case.expected_root_cause and case.expected_source_ids
        if case.case_type == "injection":
            assert {"text", "canary"} <= set(case.injection) and case.injection["canary"] in case.injection["text"]


def test_standard_cases_are_the_existing_eval_incidents():
    originals = json.loads((DEFAULT_DATA_DIR / "eval_incidents.json").read_text(encoding="utf-8"))
    standard = {(c.tenant, c.scenario): c.incident for c in load_cases(types=["standard"])}
    assert {(o["tenantId"], o["scenario"]) for o in originals} == set(standard)
    for original in originals:
        expected = IncidentCreatedPayload.model_validate(original["incident"])
        assert standard[(original["tenantId"], original["scenario"])] == expected


# Words that would make retrieval trivial: the paraphrases must describe symptoms, not name the cause.
RUNBOOK_WORDS = ("pool", "oom", "memory", "dns", "certificate", "tls", "https", "deploy", "release", "rollback",
                 "timeout", "timing out", "lookup", "downstream", "leak", "5xx")


def test_paraphrases_keep_service_and_time_but_avoid_runbook_words():
    standard = {(c.tenant, c.scenario): c.incident for c in load_cases(types=["standard"])}
    for case in load_cases(types=["paraphrase"]):
        base = standard[(case.tenant, case.scenario)]
        assert (case.incident.affectedService, case.incident.createdAt) == (base.affectedService, base.createdAt)
        text = f"{case.incident.title} {case.incident.description}".lower()
        assert not [w for w in RUNBOOK_WORDS if w in text], case.case_id


def test_injected_text_is_not_in_the_synthetic_data():
    corpus = "".join((DEFAULT_DATA_DIR / f"{n}.json").read_text(encoding="utf-8").lower()
                     for n in ("logs", "metrics", "runbooks", "incidents"))
    for case in load_cases(types=["injection"]):
        assert case.injection["canary"].lower() not in corpus
        assert "ignore" not in corpus  # no injected instructions were written into the dataset


def test_no_evidence_cases_use_services_without_any_data():
    services = {doc.get("service") for name in ("logs", "metrics")
                for doc in json.loads((DEFAULT_DATA_DIR / f"{name}.json").read_text(encoding="utf-8"))}
    for case in load_cases(types=["no_evidence"]):
        assert case.incident.affectedService not in services
        assert case.incident.createdAt < datetime(2026, 9, 1, tzinfo=UTC)
