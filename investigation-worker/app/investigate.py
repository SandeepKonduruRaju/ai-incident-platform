"""Run the investigation graph for one evaluation incident and print the result.

    python -m app.investigate --tenant acme --scenario db_pool_exhausted                 # LLM_PROVIDER from settings
    python -m app.investigate --tenant globex --scenario db_pool_exhausted --provider anthropic

Creates a new investigation row each run (request_id "cli-investigate"), so the run is stored exactly
like one triggered by Kafka. Needs the compose PostgreSQL with ingested data.
"""

import argparse
import asyncio
import json
import sys
from typing import Any

from app.config import Settings, get_settings
from app.errors import LLMConfigError
from app.events import IncidentCreatedPayload
from app.graph import run_investigation
from app.investigations import InvestigationRef, claim, create_pending, release


def report(state: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    """The result plus each citation label resolved to the evidence it points at."""
    sources = {item.label: f"{item.source_id} ({item.source_type})" for item in state.get("evidence", [])}
    return {
        "status": row["status"],
        "result": row["result"],
        "citations": sources,
        "failure_reason": row["failure_reason"],
        "model": row["model"],
        "prompt_version": row["prompt_version"],
        "attempts": row["attempts"],
        "input_tokens": row["input_tokens"],
        "output_tokens": row["output_tokens"],
        "llm_latency_ms": row["llm_latency_ms"],
    }


async def _run(settings: Settings, tenant: str, incident: IncidentCreatedPayload) -> int:
    from app.db import create_engine
    from app.investigations import get
    from app.investigator import build_deps, build_retriever, load_models
    from app.llm import build_llm

    try:
        llm = build_llm(settings)
    except LLMConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    engine = create_engine(settings.database_url)
    try:
        embedder, reranker = await load_models(settings)
        deps = build_deps(settings, engine, llm, build_retriever(engine, embedder, reranker, settings))
        ref: InvestigationRef | None = await claim(
            engine, await create_pending(engine, tenant_id=tenant, incident=incident, request_id="cli-investigate")
        )
        assert ref is not None  # a row we just created cannot be claimed by anyone else
        try:
            state = await run_investigation(deps, ref, incident, time_budget_seconds=settings.investigation_time_budget_seconds)
        except LLMConfigError as exc:
            await release(engine, ref)
            print(f"error: {exc} (investigation {ref.id} left PENDING)", file=sys.stderr)
            return 2
        row = await get(engine, ref.id)
    finally:
        await engine.dispose()

    print(f"investigation {ref.id}  provider={settings.llm_provider}  incident: {incident.title}")
    print(json.dumps(report(state, row), indent=2, ensure_ascii=False, default=str))
    return 0


def main(argv: list[str] | None = None) -> None:
    from app.logging_context import configure_logging
    from app.retrieval import load_eval_incident

    parser = argparse.ArgumentParser(description="Investigate one evaluation incident with the LangGraph pipeline.")
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--scenario", required=True, help="e.g. db_pool_exhausted (see data/synthetic/eval_incidents.json)")
    parser.add_argument("--provider", choices=("fake", "anthropic"), help="overrides LLM_PROVIDER")
    parser.add_argument("--log-level", default="WARNING")
    args = parser.parse_args(argv)

    configure_logging(args.log_level)
    settings = get_settings()
    if args.provider:
        settings = settings.model_copy(update={"llm_provider": args.provider})
    incident = load_eval_incident(args.tenant, scenario=args.scenario)
    raise SystemExit(asyncio.run(_run(settings, args.tenant, incident)))


if __name__ == "__main__":
    main()
