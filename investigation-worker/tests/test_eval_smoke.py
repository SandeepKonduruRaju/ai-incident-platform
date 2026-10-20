"""CI smoke test of the whole evaluation pipeline: 3 cases, FakeLLM investigator and judge, no database,
no network. Retrieval is replaced by a static retriever over the synthetic chunks (the real retriever is
covered by the retrieval integration tests).

    .\\.venv\\Scripts\\python.exe -m pytest -m eval_smoke -q
"""

from pathlib import Path

import pytest

from app.chunking import chunk_dataset
from app.eval_investigation import EvalCase, EvalContext, EvalOptions, load_cases, matches_expected, run_eval, write_reports
from app.eval_judge import JUDGE_PROMPT_VERSION, FakeJudgeLLM
from app.events import IncidentCreatedPayload
from app.graph import GraphDeps
from app.ingest import load_dataset
from app.llm import FakeLLM
from app.llm_cache import Budget, CachingLLM
from app.retrieval import EvidenceItem

pytestmark = pytest.mark.eval_smoke


def static_retriever(cases: list[EvalCase]):
    """Up to 4 golden chunks for scenario cases, one unrelated runbook chunk for no-evidence cases."""
    chunks = chunk_dataset(**load_dataset())
    by_incident = {c.incident.incidentId: c for c in cases}

    async def retrieve(tenant_id: str, incident: IncidentCreatedPayload) -> list[EvidenceItem]:
        case = by_incident[incident.incidentId]
        own = [c for c in chunks if c.tenant_id == tenant_id]
        if case.expected_source_ids:
            picked = [c for c in own if matches_expected(c.source_id, case.expected_source_ids)][:4]
        else:
            picked = [c for c in own if c.source_type == "runbook" and "rotat" in c.source_id.lower()][:1]
        return [
            EvidenceItem(label=f"C{n}", chunk_id=c.id, tenant_id=c.tenant_id, source_type=c.source_type,
                         source_id=c.source_id, service=c.service, ts=c.ts, content=c.content,
                         rrf_score=0.0, rerank_score=0.0)
            for n, c in enumerate(picked, start=1)
        ]

    return retrieve


def smoke_cases() -> list[EvalCase]:
    return [load_cases(types=[t])[0] for t in ("standard", "no_evidence", "injection")]


async def test_eval_pipeline_produces_reports_on_three_cases(tmp_path: Path):
    from app.eval_investigation import DiscardingStore

    cases = smoke_cases()
    budget = Budget(max_usd=0.25, price_in_per_m=0.10, price_out_per_m=0.50, max_output_tokens=4096)
    llm = CachingLLM(FakeLLM(), "fake-llm", "v1", tmp_path / "cache", budget)
    judge = CachingLLM(FakeJudgeLLM(), "fake-judge", JUDGE_PROMPT_VERSION, tmp_path / "cache", budget)
    deps = GraphDeps(retrieve=static_retriever(cases), llm=llm, store=DiscardingStore())
    options = EvalOptions(provider="fake", model="fake-llm", judge_model="fake-judge", consistency_cases=1, consistency_runs=1)

    run = await run_eval(cases, EvalContext(deps=deps, judge=judge, options=options))
    json_path, md_path = write_reports(run, tmp_path / "reports")

    assert run["stopped_early"] is None and run["skipped_cases"] == []
    rows = {r["case_type"]: r for r in run["cases"]}
    assert all(r["status"] == "COMPLETED" and r["schema_valid"] and r["citation_valid"] for r in run["cases"])
    assert rows["standard"]["evidence_hit"] and rows["standard"]["faithfulness"] == 1.0
    assert rows["injection"]["evidence"][1]["source_id"].startswith("INJECTED-")
    assert rows["no_evidence"]["insufficient_correct"] is False  # FakeLLM always claims a root cause
    assert set(run["summary"]) == {"overall", "standard", "no_evidence", "injection"}
    assert len(run["consistency"]) == 1
    markdown = md_path.read_text(encoding="utf-8")
    for section in ("## Summary", "## Per case", "## Failures", "## Consistency", "## Cost and latency", "## Limitations"):
        assert section in markdown
    assert "FakeLLM run" in markdown and json_path.exists()


async def test_eval_stops_cleanly_when_the_budget_is_too_small(tmp_path: Path):
    from app.eval_investigation import DiscardingStore

    cases = smoke_cases()
    budget = Budget(max_usd=0.0, price_in_per_m=0.10, price_out_per_m=0.50, max_output_tokens=4096)
    llm = CachingLLM(FakeLLM(), "fake-llm", "v1", None, budget)
    judge = CachingLLM(FakeJudgeLLM(), "fake-judge", JUDGE_PROMPT_VERSION, None, budget)
    deps = GraphDeps(retrieve=static_retriever(cases), llm=llm, store=DiscardingStore())
    options = EvalOptions(provider="fake", model="fake-llm", judge_model="fake-judge")

    run = await run_eval(cases, EvalContext(deps=deps, judge=judge, options=options))
    _, md_path = write_reports(run, tmp_path)

    assert run["stopped_early"].startswith("stopping: the next call could exceed the budget")
    assert run["skipped_cases"] == [c.case_id for c in cases] and budget.calls == 0
    assert "Stopped early" in md_path.read_text(encoding="utf-8")
