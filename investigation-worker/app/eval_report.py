"""Markdown rendering of an evaluation run (app.eval_investigation). Pure: dict in, text out."""

from collections.abc import Sequence
from typing import Any

SUMMARY_COLUMNS = (
    ("n", "n", "int"),
    ("root_cause_accuracy", "root cause ✓", "pct"),
    ("root_cause_yes_or_partial", "✓ or partial", "pct"),
    ("faithfulness", "faithful", "pct"),
    ("citation_validity", "citations valid", "pct"),
    ("citation_coverage", "cited findings", "pct"),
    ("evidence_hit", "evidence hit", "pct"),
    ("injection_resisted", "injection resisted", "pct"),
    ("insufficient_correct", "abstained correctly", "pct"),
    ("schema_valid", "schema valid", "pct"),
    ("attempts_mean", "attempts", "num"),
    ("cost_per_investigation_usd", "$/investigation", "usd"),
    ("latency_p50_ms", "p50", "ms"),
    ("latency_p95_ms", "p95", "ms"),
)


def fmt(value: Any, kind: str) -> str:
    if value is None:
        return "–"
    return {
        "int": lambda v: str(int(v)),
        "pct": lambda v: f"{v * 100:.0f}%",
        "num": lambda v: f"{v:.2f}",
        "usd": lambda v: f"${v:.5f}",
        "ms": lambda v: f"{v / 1000:.1f} s",
    }[kind](value)


def table(header: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join(lines)


def render_summary_table(run: dict[str, Any]) -> str:
    rows = [
        [f"**{name}**" if name == "overall" else name, *(fmt(group[key], kind) for key, _, kind in SUMMARY_COLUMNS)]
        for name, group in run["summary"].items()
    ]
    return table(["cases", *(label for _, label, _ in SUMMARY_COLUMNS)], rows)


def _check(value: bool | None) -> str:
    return "–" if value is None else ("✓" if value else "✗")


def _case_row(r: dict[str, Any]) -> list[str]:
    faithful = f"{r['findings_supported']}/{r['findings_total']}" if r["findings_supported"] is not None else "–"
    special = _check(r["injection_resisted"]) if r["case_type"] == "injection" else _check(r["insufficient_correct"])
    return [
        r["case_id"], r["status"] or "–", r["root_cause_verdict"] or "–", faithful, _check(r["citation_valid"]),
        _check(r["evidence_hit"]), special, str(r["attempts"]), f"{r['input_tokens']}/{r['output_tokens']}",
        fmt(r["cost_usd"], "usd"), fmt(r["latency_ms"], "ms"),
    ]


def render_cases(rows: Sequence[dict[str, Any]]) -> str:
    header = ["case", "status", "root cause", "faithful", "citations valid", "evidence hit",
              "injection resisted / abstained", "attempts", "tokens in/out", "cost", "latency"]
    return table(header, [_case_row(r) for r in rows])


def failure_reasons(r: dict[str, Any]) -> list[str]:
    reasons = []
    if r["status"] != "COMPLETED":
        reasons.append(f"investigation {r['status']}: {r['failure_reason']}")
    if r["root_cause_verdict"] in ("no", "partial"):
        reasons.append(f"root cause **{r['root_cause_verdict']}**: {r['judge'].get('root_cause_reason')}")
    if r["judge"].get("judge_error"):
        reasons.append(f"judge error: {r['judge']['judge_error']}")
    reasons += [f"unsupported finding #{f['index']}: {f['reason']}" for f in r["judge"]["findings"]
                if f["verdict"] == "unsupported"]
    if r["citation_valid"] is False:
        reasons.append("cites a label that is not in the evidence")
    if r["evidence_hit"] is False:
        reasons.append("retrieval found none of the expected sources")
    if r["insufficient_correct"] is False:
        reasons.append("claimed a root cause although no relevant evidence exists")
    if r["injection_resisted"] is False:
        reasons.append(f"followed the injected instructions: {r['judge'].get('injection_reason')}")
    return reasons


def render_failures(rows: Sequence[dict[str, Any]]) -> str:
    lines = [f"- **{r['case_id']}**: " + "; ".join(reasons) for r in rows if (reasons := failure_reasons(r))]
    return "\n".join(lines) or "None."


def render_consistency(run: dict[str, Any]) -> str:
    items = run["consistency"]
    if not items:
        return "Not run (disabled, or the budget stopped the run first)."
    agree = sum(1 for c in items if c["agree"])
    rows = [[c["case_id"], " → ".join(v or "–" for v in c["verdicts"]), _check(c["agree"])] for c in items]
    runs = len(items[0]["verdicts"])
    return (f"Root-cause verdict identical across {runs} runs in **{agree}/{len(items)}** cases.\n\n"
            + table(["case", "verdicts (first run → re-runs)", "agree"], rows))


def render_cost(run: dict[str, Any]) -> str:
    overall, spend = run["summary"]["overall"], run["spend"]
    rows = [
        ["cost per investigation (mean, from tokens)", fmt(overall["cost_per_investigation_usd"], "usd")],
        ["tokens per investigation (mean in / out)",
         f"{overall['input_tokens_mean']:.0f} / {overall['output_tokens_mean']:.0f}"],
        ["judge cost, all cases (from tokens)", fmt(spend["judge_cost_usd_if_uncached"], "usd")],
        ["actually spent in this run (cache misses only)", fmt(spend["actual_usd"], "usd")],
        ["API calls / cache hits", f"{spend['api_calls']} / {spend['cache_hits']}"],
        ["end-to-end latency p50 / p95 (retrieval + LLM)",
         f"{fmt(overall['latency_p50_ms'], 'ms')} / {fmt(overall['latency_p95_ms'], 'ms')}"],
        ["LLM latency p50 / p95", f"{fmt(overall['llm_latency_p50_ms'], 'ms')} / {fmt(overall['llm_latency_p95_ms'], 'ms')}"],
    ]
    return table(["", "value"], rows)


def render_limitations(run: dict[str, Any]) -> str:
    options = run["options"]
    lines = [
        f"- **Synthetic data, small N** ({options['cases_selected']} cases, 6 scenarios × 2 tenants): every "
        "number here has a wide error bar; one case moves a per-type rate by 8–50 points.",
        "- **Clean scenarios**: each incident has one planted cause with consistent logs, metrics and runbooks; "
        "real incidents are noisier and often multi-causal.",
        "- **LLM-as-judge**: verdicts are themselves model output, not ground truth. Faithfulness is judged "
        "against the cited evidence only (supported ≠ true).",
        "- **Latency** sums retrieval time with the recorded LLM latency (cached responses keep their original "
        "latency); it excludes Kafka and database writes.",
    ]
    if options["judge_model"] == options["model"]:
        lines.insert(2, f"- **Same-model judge** ({options['judge_model']} judges its own output): known to be "
                        "biased towards lenient verdicts; a stronger, different judge model would be more credible.")
    if options["provider"] == "fake":
        lines.insert(0, "- **FakeLLM run**: canned answers and placeholder verdicts. Checks the pipeline, measures nothing.")
    return "\n".join(lines)


def render_markdown(run: dict[str, Any]) -> str:
    options = run["options"]
    skipped = ", ".join(run["skipped_cases"]) or "consistency re-runs"
    stopped = f"\n\n> **Stopped early**: {run['stopped_early']}. Skipped: {skipped}." if run["stopped_early"] else ""
    meta = " · ".join([
        f"Run {run['started_at']}", f"provider `{options['provider']}`", f"model `{options['model']}`",
        f"judge `{options['judge_model']}`", f"prompt `{options['prompt_version']}`", f"{options['cases_selected']} cases",
    ])
    return f"""# Investigation quality evaluation

> Synthetic evaluation set (Claude-generated cases, `data/eval/cases.json`); not real incidents.

{meta}{stopped}

## Summary

{render_summary_table(run) if run['summary'] else 'No case completed.'}

Root cause ✓ = judge says the predicted root cause matches the reference; faithful = share of findings whose cited
evidence supports them; abstained correctly = no-evidence cases answered with root_cause null and confidence low.

## Per case

{render_cases(run['cases'])}

## Failures and weak answers

{render_failures(run['cases'])}

## Consistency

{render_consistency(run)}

## Cost and latency

{render_cost(run) if run['summary'] else '–'}

Prices: ${options['price_in_per_m']:.2f} / ${options['price_out_per_m']:.2f} per million input / output tokens.

## Limitations

{render_limitations(run)}
"""
