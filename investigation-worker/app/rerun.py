"""Re-run stored investigations, e.g. after fixing ANTHROPIC_API_KEY or after an LLM outage.

    python -m app.rerun --status PENDING                       # left PENDING by an LLM config error
    python -m app.rerun --status FAILED --tenant acme --limit 5

Each investigation is claimed with the same fenced conditional UPDATE as the consumer, so a rerun can
never run concurrently with the consumer on the same investigation. An LLM config error stops the
whole rerun (every following call would fail the same way).
"""

import argparse
import asyncio
import sys

from app.config import Settings, get_settings
from app.errors import LLMConfigError
from app.events import IncidentCreatedPayload


async def _run(settings: Settings, status: str, tenant: str | None, limit: int) -> int:
    from app.db import create_engine
    from app.investigations import claim, find_by_status, release
    from app.investigator import build_deps, build_retriever, load_models, make_investigate
    from app.llm import build_llm

    try:
        llm = build_llm(settings)
    except LLMConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    engine = create_engine(settings.database_url)
    counts: dict[str, int] = {}
    try:
        candidates = await find_by_status(engine, status, tenant_id=tenant, limit=limit)
        if not candidates:
            print(f"no {status} investigations" + (f" for tenant {tenant}" if tenant else ""))
            return 0
        embedder, reranker = await load_models(settings)
        investigate = make_investigate(
            build_deps(settings, engine, llm, build_retriever(engine, embedder, reranker, settings)), settings
        )
        for ref, incident_json in candidates:
            if incident_json is None:
                print(f"{ref.id} {ref.tenant_id}: skipped (created before migration 0004, incident not stored)")
                counts["SKIPPED"] = counts.get("SKIPPED", 0) + 1
                continue
            claimed = await claim(engine, ref, allowed=(status,))
            if claimed is None:
                print(f"{ref.id} {ref.tenant_id}: skipped (changed by another run)")
                counts["SKIPPED"] = counts.get("SKIPPED", 0) + 1
                continue
            try:
                outcome = await investigate(claimed, IncidentCreatedPayload.model_validate(incident_json))
            except LLMConfigError as exc:
                await release(engine, claimed)
                print(f"error: {exc}; stopping (investigation {ref.id} left PENDING)", file=sys.stderr)
                return 2
            counts[outcome] = counts.get(outcome, 0) + 1
            print(f"{ref.id} {ref.tenant_id}: {status} -> {outcome}")
    finally:
        await engine.dispose()
    print("summary: " + ", ".join(f"{name}={count}" for name, count in sorted(counts.items())))
    return 0


def main(argv: list[str] | None = None) -> None:
    from app.logging_context import configure_logging

    parser = argparse.ArgumentParser(description="Re-run PENDING or FAILED investigations.")
    parser.add_argument("--status", required=True, choices=("PENDING", "FAILED"))
    parser.add_argument("--tenant")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--provider", choices=("fake", "anthropic"), help="overrides LLM_PROVIDER")
    parser.add_argument("--log-level", default="WARNING")
    args = parser.parse_args(argv)
    if not 1 <= args.limit <= 500:
        parser.error("--limit must be between 1 and 500")

    configure_logging(args.log_level)
    settings = get_settings()
    if args.provider:
        settings = settings.model_copy(update={"llm_provider": args.provider})
    raise SystemExit(asyncio.run(_run(settings, args.status, args.tenant, args.limit)))


if __name__ == "__main__":
    main()
