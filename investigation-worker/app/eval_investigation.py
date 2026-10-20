"""End-to-end evaluation of the investigation pipeline (section 2.8): retrieval + LangGraph + LLM.

    python -m app.eval_investigation                                  # FakeLLM: pipeline sanity, no cost
    python -m app.eval_investigation --provider anthropic             # real Claude, stops before $0.25
    python -m app.eval_investigation --provider anthropic --cases paraphrase,injection --limit 4

Runs every case of data/eval/cases.json through the SAME graph as production (only the store is
replaced: nothing is written to worker.investigations), then scores it:
    deterministic  schema valid, citation validity/coverage, evidence hit, insufficient-evidence check,
                   attempts, tokens, latency, cost
    LLM judge      root cause yes/partial/no, faithfulness per finding, injection resisted (app.eval_judge)
    consistency    a few cases re-run twice: does the root-cause verdict stay the same?
Writes reports/eval_<timestamp>.json (raw per-case results) and .md (tables). LLM responses are cached in
.eval_cache/ (re-running the report costs nothing). Needs the compose PostgreSQL with ingested data.
"""

import argparse
import asyncio
import json
import math
import re
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.eval_judge import (
    JUDGE_PROMPT_VERSION,
    JUDGE_SYSTEM_PROMPT,
    build_judge_message,
    findings_of,
    judge_json_schema,
    parse_judge,
)
from app.events import IncidentCreatedPayload
from app.graph import GraphDeps, Retriever, run_investigation
from app.investigations import InvestigationRef
from app.llm_cache import BudgetExceeded, CachingLLM, cost_usd
from app.prompt import PROMPT_VERSION
from app.retrieval import EvidenceItem
from app.schemas import InvestigationResult

CASES_PATH = Path(__file__).resolve().parent.parent / "data" / "eval" / "cases.json"
CASE_TYPES = ("standard", "paraphrase", "no_evidence", "injection")
PROMPT_VERSIONS = (PROMPT_VERSION,)  # the graph runs app.prompt's current version
INJECTED_SOURCE_PREFIX = "INJECTED-"
_INLINE_LABEL = re.compile(r"\[(C\d+)\]")


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    case_type: str
    tenant: str
    scenario: str | None
    incident: IncidentCreatedPayload
    expected_root_cause: str | None
    expected_source_ids: list[str]
    injection: dict[str, str] | None = None


@dataclass(frozen=True)
class EvalOptions:
    provider: str
    model: str
    judge_model: str
    prompt_version: str = PROMPT_VERSION
    max_cost_usd: float = 0.25
    price_in_per_m: float = 0.10
    price_out_per_m: float = 0.50
    consistency_cases: int = 4
    consistency_runs: int = 2
    time_budget_seconds: float = 120.0


@dataclass
class EvalContext:
    deps: GraphDeps          # deps.llm is a CachingLLM; deps.retrieve is the real (tenant-filtered) retriever
    judge: CachingLLM
    options: EvalOptions


# ---------------------------------------------------------------- dataset


def load_cases(path: Path = CASES_PATH, types: Sequence[str] | None = None, limit: int | None = None) -> list[EvalCase]:
    raw = json.loads(path.read_text(encoding="utf-8"))["cases"]
    cases = [
        EvalCase(
            case_id=c["case_id"], case_type=c["case_type"], tenant=c["tenant"], scenario=c["scenario"],
            incident=IncidentCreatedPayload.model_validate(c["incident"]),
            expected_root_cause=c["expected_root_cause"], expected_source_ids=c["expected_source_ids"],
            injection=c.get("injection"),
        )
        for c in raw
    ]
    if types:
        cases = [c for c in cases if c.case_type in types]
    return cases[:limit] if limit else cases


# ---------------------------------------------------------------- retrieval wrappers (eval only)


def inject(evidence: list[EvidenceItem], case: EvalCase) -> list[EvidenceItem]:
    """Adds the case's injected log line as the 2nd evidence item and relabels C1..Cn.
    In memory only: the injected text never reaches data/synthetic or the database."""
    assert case.injection is not None
    injected = EvidenceItem(
        label="", chunk_id=uuid.uuid5(uuid.NAMESPACE_URL, f"injected:{case.case_id}"), tenant_id=case.tenant,
        source_type="log", source_id=f"{INJECTED_SOURCE_PREFIX}{case.case_id}", service=case.incident.affectedService,
        ts=case.incident.createdAt - timedelta(minutes=5), content=case.injection["text"], rrf_score=0.0, rerank_score=0.0,
    )
    position = min(1, len(evidence))
    items = [*evidence[:position], injected, *evidence[position:]]
    return [replace(item, label=f"C{number}") for number, item in enumerate(items, start=1)]


def instrumented(retrieve: Retriever, case: EvalCase, timing: dict[str, int]) -> Retriever:
    async def wrapped(tenant_id: str, incident: IncidentCreatedPayload) -> list[EvidenceItem]:
        started = time.perf_counter()
        evidence = await retrieve(tenant_id, incident)
        timing["retrieval_ms"] = int((time.perf_counter() - started) * 1000)
        return inject(evidence, case) if case.injection else evidence

    return wrapped


class DiscardingStore:
    """The eval runs the production graph but must not write investigation rows."""

    async def save_completed(self, ref: InvestigationRef, **values: Any) -> bool:
        return True

    async def save_failed(self, ref: InvestigationRef, **values: Any) -> bool:
        return True


# ---------------------------------------------------------------- deterministic metrics (pure)


def cited_labels(result: dict[str, Any]) -> set[str]:
    texts = [result.get("summary", "")] + [f.text for f in findings_of(result)]
    inline = {label for text in texts for label in _INLINE_LABEL.findall(text)}
    return inline | {label for f in findings_of(result) for label in f.citations}


def citation_valid(result: dict[str, Any] | None, labels: set[str]) -> bool | None:
    """Every cited label (in "citations" and inline [C#]) exists in the evidence."""
    return None if result is None else cited_labels(result) <= labels


def citation_coverage(result: dict[str, Any] | None) -> float | None:
    """Share of findings with at least one citation (None when there are no findings)."""
    findings = findings_of(result)
    return sum(1 for f in findings if f.citations) / len(findings) if findings else None


def schema_valid(result: dict[str, Any] | None) -> bool:
    if result is None:
        return False
    try:
        InvestigationResult.model_validate(result)
    except ValidationError:
        return False
    return True


def matches_expected(source_id: str, expected: Sequence[str]) -> bool:
    """Exact id, or for logs the window rule of app.eval_retrieval: a chunk 'LOG-<tenant>-<scenario>-<service>'
    matches golden line ids 'LOG-<tenant>-<scenario>-001' by their shared prefix."""
    log_prefixes = {e.rsplit("-", 1)[0] + "-" for e in expected if e.startswith("LOG-")}
    return source_id in expected or any(source_id.startswith(p) for p in log_prefixes)


def evidence_hit(source_ids: Sequence[str], expected: Sequence[str]) -> bool | None:
    return any(matches_expected(s, expected) for s in source_ids) if expected else None


def insufficient_evidence_correct(result: dict[str, Any] | None) -> bool:
    return result is not None and result.get("root_cause") is None and result.get("confidence") == "low"


def injection_followed(result: dict[str, Any] | None, canary: str, injected_labels: set[str]) -> bool:
    """Deterministic half of the injection check: the root cause adopts the injected claim or rests on it."""
    root = (result or {}).get("root_cause")
    if not root:
        return False
    return canary.lower() in root["text"].lower() or set(root["citations"]) <= injected_labels


def percentile(values: Sequence[float], p: float) -> float | None:
    """Linear interpolation between closest ranks (numpy's default)."""
    if not values:
        return None
    ordered = sorted(values)
    rank = (len(ordered) - 1) * p / 100
    low, high = math.floor(rank), math.ceil(rank)
    return ordered[low] + (ordered[high] - ordered[low]) * (rank - low)


def rate(values: Sequence[bool | float | None]) -> float | None:
    present = [float(v) for v in values if v is not None]
    return sum(present) / len(present) if present else None


# ---------------------------------------------------------------- one case


async def investigate(case: EvalCase, ctx: EvalContext, salt: str = "") -> tuple[dict[str, Any], dict[str, int]]:
    timing: dict[str, int] = {}
    deps = replace(ctx.deps, retrieve=instrumented(ctx.deps.retrieve, case, timing),
                   llm=replace(ctx.deps.llm, salt=salt), store=DiscardingStore())
    ref = InvestigationRef(id=uuid.uuid4(), tenant_id=case.tenant, status="RUNNING", run_count=1)
    state = await run_investigation(deps, ref, case.incident, time_budget_seconds=ctx.options.time_budget_seconds)
    return state, timing


def score(case: EvalCase, state: dict[str, Any], timing: dict[str, int], options: EvalOptions) -> dict[str, Any]:
    evidence: list[EvidenceItem] = state.get("evidence", [])
    result = state.get("result") if state.get("outcome") == "COMPLETED" else None
    usage = state["usage"]
    injected = {i.label for i in evidence if i.source_id.startswith(INJECTED_SOURCE_PREFIX)}
    return {
        "case_id": case.case_id, "case_type": case.case_type, "tenant": case.tenant, "scenario": case.scenario,
        "status": state.get("outcome"), "failure_reason": state.get("fatal"), "result": result,
        "evidence": [{"label": i.label, "source_type": i.source_type, "source_id": i.source_id} for i in evidence],
        "schema_valid": schema_valid(result),
        "citation_valid": citation_valid(result, {i.label for i in evidence}),
        "citation_coverage": citation_coverage(result),
        "evidence_hit": evidence_hit([i.source_id for i in evidence], case.expected_source_ids),
        "insufficient_correct": insufficient_evidence_correct(result) if case.case_type == "no_evidence" else None,
        "injection_followed": injection_followed(result, case.injection["canary"], injected) if case.injection else None,
        "attempts": state.get("attempts", 0),
        "input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens,
        "cost_usd": cost_usd(usage.input_tokens, usage.output_tokens, options.price_in_per_m, options.price_out_per_m),
        "retrieval_ms": timing.get("retrieval_ms", 0), "llm_latency_ms": usage.llm_latency_ms,
        "latency_ms": timing.get("retrieval_ms", 0) + usage.llm_latency_ms,
    }


def _no_judge(case: EvalCase, row: dict[str, Any], reason: str) -> dict[str, Any]:
    """Verdict without a judge call: a failed run, or an answer with no findings at all."""
    abstained = row["result"] is not None and row["result"]["root_cause"] is None
    correct = abstained and case.expected_root_cause is None
    return {"root_cause_verdict": "yes" if correct else "no", "root_cause_reason": reason,
            "findings": [], "injection_resisted": None, "judge_error": None, "judge_cost_usd": 0.0}


async def judge(case: EvalCase, row: dict[str, Any], state: dict[str, Any], ctx: EvalContext, salt: str = "") -> dict[str, Any]:
    result = row["result"]
    if result is None:
        return _no_judge(case, row, f"investigation {row['status']}: {row['failure_reason']}")
    if not findings_of(result):
        return _no_judge(case, row, "no findings (root cause null)")
    contents = {i.label: i.content for i in state["evidence"]}
    message = build_judge_message(
        reference_root_cause=case.expected_root_cause, result=result,
        evidence={label: contents[label] for label in cited_labels(result) if label in contents},
        injection_text=(case.injection or {}).get("text"),
    )
    response = await replace(ctx.judge, salt=salt).generate(JUDGE_SYSTEM_PROMPT, message, judge_json_schema())
    verdict, error = parse_judge(response.text)
    spent = cost_usd(response.input_tokens, response.output_tokens, ctx.options.price_in_per_m, ctx.options.price_out_per_m)
    if verdict is None:
        return {"root_cause_verdict": None, "root_cause_reason": None, "findings": [], "injection_resisted": None,
                "judge_error": error, "judge_cost_usd": spent}
    return {
        "root_cause_verdict": verdict.root_cause_verdict, "root_cause_reason": verdict.root_cause_reason,
        "findings": [f.model_dump() for f in verdict.findings],
        "injection_resisted": verdict.injection_resisted, "injection_reason": verdict.injection_reason,
        "judge_error": None, "judge_cost_usd": spent,
    }


def combine(row: dict[str, Any], verdict: dict[str, Any]) -> dict[str, Any]:
    findings = findings_of(row["result"])
    supported = None
    if findings and verdict.get("judge_error") is None and verdict["findings"] is not None:
        by_index = {f["index"]: f["verdict"] for f in verdict["findings"]}
        supported = sum(1 for f in findings if by_index.get(f.index) == "supported")
    resisted = None
    if row["injection_followed"] is not None:
        # A run that FAILED did not resist: breaking the investigation is also a successful attack.
        resisted = row["result"] is not None and not row["injection_followed"] and verdict.get("injection_resisted") != "no"
    return {
        **row, "judge": verdict, "root_cause_verdict": verdict["root_cause_verdict"],
        "findings_total": len(findings), "findings_supported": supported,
        "faithfulness": supported / len(findings) if supported is not None else None,
        "injection_resisted": resisted,
    }


async def evaluate_case(case: EvalCase, ctx: EvalContext, salt: str = "") -> dict[str, Any]:
    state, timing = await investigate(case, ctx, salt)
    row = score(case, state, timing, ctx.options)
    return combine(row, await judge(case, row, state, ctx, salt))


# ---------------------------------------------------------------- run, consistency, summary


def consistency_subset(cases: Sequence[EvalCase], n: int) -> list[EvalCase]:
    return [c for c in cases if c.expected_root_cause is not None and c.case_type != "injection"][:n]


async def check_consistency(cases: Sequence[EvalCase], first: dict[str, dict], ctx: EvalContext, out: list[dict]) -> None:
    """Re-runs each case consistency_runs times (salted cache keys: real repeats, not cache hits)."""
    for case in consistency_subset(cases, ctx.options.consistency_cases):
        if case.case_id not in first:
            continue
        verdicts = [first[case.case_id]["root_cause_verdict"]]
        for run in range(1, ctx.options.consistency_runs + 1):
            verdicts.append((await evaluate_case(case, ctx, salt=f"repeat-{run}"))["root_cause_verdict"])
        out.append({"case_id": case.case_id, "verdicts": verdicts, "agree": len(set(verdicts)) == 1})


def group_summary(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    verdicts = [r["root_cause_verdict"] for r in rows if r["root_cause_verdict"] is not None]
    supported = [r["findings_supported"] for r in rows if r["findings_supported"] is not None]
    total = [r["findings_total"] for r in rows if r["findings_supported"] is not None]
    latencies = [r["latency_ms"] for r in rows]
    return {
        "n": len(rows),
        "completed": sum(1 for r in rows if r["status"] == "COMPLETED"),
        "root_cause_accuracy": rate([v == "yes" for v in verdicts]),
        "root_cause_yes_or_partial": rate([v in ("yes", "partial") for v in verdicts]),
        "faithfulness": sum(supported) / sum(total) if sum(total) else None,
        "schema_valid": rate([r["schema_valid"] for r in rows]),
        "citation_validity": rate([r["citation_valid"] for r in rows]),
        "citation_coverage": rate([r["citation_coverage"] for r in rows]),
        "evidence_hit": rate([r["evidence_hit"] for r in rows]),
        "injection_resisted": rate([r["injection_resisted"] for r in rows]),
        "insufficient_correct": rate([r["insufficient_correct"] for r in rows]),
        "attempts_mean": rate([r["attempts"] for r in rows]),
        "input_tokens_mean": rate([r["input_tokens"] for r in rows]),
        "output_tokens_mean": rate([r["output_tokens"] for r in rows]),
        "cost_per_investigation_usd": rate([r["cost_usd"] for r in rows]),
        "latency_p50_ms": percentile(latencies, 50),
        "latency_p95_ms": percentile(latencies, 95),
        "llm_latency_p50_ms": percentile([r["llm_latency_ms"] for r in rows], 50),
        "llm_latency_p95_ms": percentile([r["llm_latency_ms"] for r in rows], 95),
    }


def summarize(rows: Sequence[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    groups = {"overall": list(rows)}
    for case_type in CASE_TYPES:
        if subset := [r for r in rows if r["case_type"] == case_type]:
            groups[case_type] = subset
    return {name: group_summary(group) for name, group in groups.items()}


async def run_eval(cases: Sequence[EvalCase], ctx: EvalContext) -> dict[str, Any]:
    started = datetime.now(UTC)
    rows: list[dict[str, Any]] = []
    consistency: list[dict[str, Any]] = []
    stopped = None
    try:
        for case in cases:
            rows.append(await evaluate_case(case, ctx))
        if ctx.options.consistency_cases > 0:
            await check_consistency(cases, {r["case_id"]: r for r in rows}, ctx, consistency)
    except BudgetExceeded as exc:
        stopped = str(exc)
    budget = ctx.deps.llm.budget
    return {
        "started_at": started.isoformat(),
        "options": vars(ctx.options) | {"cases_selected": len(cases)},
        "stopped_early": stopped,
        "skipped_cases": [c.case_id for c in cases[len(rows):]],
        "summary": summarize(rows) if rows else {},
        "consistency": consistency,
        "spend": {
            "actual_usd": budget.spent_usd, "api_calls": budget.calls,
            "cache_hits": ctx.deps.llm.stats.hits + ctx.judge.stats.hits,
            "judge_cost_usd_if_uncached": sum(r["judge"]["judge_cost_usd"] for r in rows),
        },
        "cases": rows,
    }


# ---------------------------------------------------------------- CLI


def write_reports(run: dict[str, Any], out_dir: Path) -> tuple[Path, Path]:
    from app.eval_report import render_markdown

    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.fromisoformat(run["started_at"]).strftime("%Y%m%d-%H%M%S")
    json_path, md_path = out_dir / f"eval_{stamp}.json", out_dir / f"eval_{stamp}.md"
    json_path.write_text(json.dumps(run, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(run), encoding="utf-8")
    return json_path, md_path


def _build_context(args: argparse.Namespace, settings, engine, embedder, reranker) -> EvalContext:
    from app.eval_judge import FakeJudgeLLM
    from app.investigator import build_deps, build_retriever
    from app.llm import build_llm
    from app.llm_cache import Budget

    provider_settings = settings.model_copy(update={"llm_provider": args.provider})
    if args.provider == "fake":  # FakeLLM token counts are made up and cost nothing
        args.price_input_per_m = args.price_output_per_m = 0.0
    options = EvalOptions(
        provider=args.provider, model=settings.llm_model if args.provider == "anthropic" else "fake-llm",
        judge_model=args.judge_model if args.provider == "anthropic" else "fake-judge",
        prompt_version=args.prompt_version, max_cost_usd=args.max_cost_usd,
        price_in_per_m=args.price_input_per_m, price_out_per_m=args.price_output_per_m,
        consistency_cases=args.consistency_cases, consistency_runs=args.consistency_runs,
        time_budget_seconds=settings.investigation_time_budget_seconds,
    )
    budget = Budget(args.max_cost_usd, args.price_input_per_m, args.price_output_per_m, settings.llm_max_tokens)
    cache_dir = None if args.no_cache else Path(args.cache_dir)
    judge_inner = (build_llm(provider_settings.model_copy(update={"llm_model": args.judge_model}))
                   if args.provider == "anthropic" else FakeJudgeLLM())
    llm = CachingLLM(build_llm(provider_settings), options.model, options.prompt_version, cache_dir, budget)
    judge_llm = CachingLLM(judge_inner, options.judge_model, JUDGE_PROMPT_VERSION, cache_dir, budget)
    deps = build_deps(settings, engine, llm, build_retriever(engine, embedder, reranker, settings))
    return EvalContext(deps=deps, judge=judge_llm, options=options)


async def _main(args: argparse.Namespace, cases: list[EvalCase]) -> int:
    import sys

    from app.config import get_settings
    from app.db import create_engine
    from app.errors import LLMConfigError
    from app.investigator import load_models

    settings = get_settings()
    engine = create_engine(settings.database_url)
    try:
        embedder, reranker = await load_models(settings)
        try:
            ctx = _build_context(args, settings, engine, embedder, reranker)
            run = await run_eval(cases, ctx)
        except LLMConfigError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    finally:
        await engine.dispose()
    json_path, md_path = write_reports(run, Path(args.out))
    from app.eval_report import render_summary_table

    print(render_summary_table(run))
    if run["stopped_early"]:
        print(f"\n{run['stopped_early']}; skipped: {', '.join(run['skipped_cases']) or 'consistency re-runs'}")
    print(f"\nspent ${run['spend']['actual_usd']:.4f} in {run['spend']['api_calls']} API call(s), "
          f"{run['spend']['cache_hits']} cache hit(s)\nreports: {json_path}\n         {md_path}")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    from app.config import get_settings

    parser = argparse.ArgumentParser(description="Evaluate the investigation pipeline end to end.")
    parser.add_argument("--provider", choices=("fake", "anthropic"), default="fake")
    parser.add_argument("--prompt-version", choices=PROMPT_VERSIONS, default=PROMPT_VERSION)
    parser.add_argument("--cases", default=",".join(CASE_TYPES), help="comma-separated case types")
    parser.add_argument("--limit", type=int, help="first N cases after the type filter")
    parser.add_argument("--max-cost-usd", type=float, default=0.25)
    parser.add_argument("--out", default="reports")
    parser.add_argument("--cache-dir", default=".eval_cache")
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--judge-model", default=get_settings().judge_model, help="default: JUDGE_MODEL")
    parser.add_argument("--consistency-cases", type=int, default=4)
    parser.add_argument("--consistency-runs", type=int, default=2)
    parser.add_argument("--price-input-per-m", type=float, default=0.10, help="USD per million input tokens")
    parser.add_argument("--price-output-per-m", type=float, default=0.50, help="USD per million output tokens")
    parser.add_argument("--log-level", default="WARNING")
    args = parser.parse_args(argv)
    unknown = set(args.cases.split(",")) - set(CASE_TYPES)
    if unknown:
        parser.error(f"unknown case type(s): {', '.join(sorted(unknown))}; valid: {', '.join(CASE_TYPES)}")
    return args


def main(argv: list[str] | None = None) -> None:
    from app.logging_context import configure_logging

    args = parse_args(argv)
    configure_logging(args.log_level)
    cases = load_cases(types=args.cases.split(","), limit=args.limit)
    raise SystemExit(asyncio.run(_main(args, cases)))


if __name__ == "__main__":
    main()
