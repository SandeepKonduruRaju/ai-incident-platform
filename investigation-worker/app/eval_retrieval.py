"""Compare vector-only search with the full hybrid pipeline on every evaluation incident.

    python -m app.eval_retrieval              # table only
    python -m app.eval_retrieval --details    # also print the top-k source_ids of every case

For each (scenario, tenant) in data/synthetic/eval_incidents.json:
    (a) vector-only: the incident text embedded, top-k over all of the tenant's chunks (no other filter)
    (b) hybrid:      retrieve_evidence (vector + keyword per evidence type, RRF, rerank, caps)
A chunk is relevant if golden.json lists its source_id for that scenario and tenant (log windows match
by the "LOG-<tenant>-<scenario>-" prefix). Metrics, per case and averaged:
    hit@k  1 if any relevant chunk is in the top k
    MRR    1 / rank of the first relevant chunk (0 if none)
    rel    number of relevant chunks in the top k
    types  number of distinct evidence types among the relevant chunks (max 4: log, metric, runbook, incident)
Needs the compose PostgreSQL with ingested data (python -m app.ingest).
"""

import argparse
import asyncio
import json
from dataclasses import dataclass
from datetime import timedelta

from app.ingest import DEFAULT_DATA_DIR

GOLDEN_KEYS = {"log": "logs", "metric": "metrics", "runbook": "runbooks", "incident": "incidents"}


@dataclass(frozen=True)
class Metrics:
    hit: int
    reciprocal_rank: float
    relevant: int
    types: int


def is_relevant(source_type: str, source_id: str, golden_case: dict, tenant: str, scenario: str) -> bool:
    if source_type == "log":
        return source_id.startswith(f"LOG-{tenant}-{scenario}-")
    return source_id in golden_case[GOLDEN_KEYS[source_type]]


def score(results: list[tuple[str, str]], golden_case: dict, tenant: str, scenario: str) -> Metrics:
    """results: [(source_type, source_id)] in rank order."""
    flags = [is_relevant(t, s, golden_case, tenant, scenario) for t, s in results]
    first = next((rank for rank, flag in enumerate(flags, start=1) if flag), None)
    return Metrics(
        hit=int(first is not None),
        reciprocal_rank=1 / first if first else 0.0,
        relevant=sum(flags),
        types=len({t for (t, _), flag in zip(results, flags, strict=True) if flag}),
    )


def _row(label: str, a: Metrics, b: Metrics) -> str:
    return (
        f"{label:<30} | {a.hit:>5} {a.reciprocal_rank:>5.2f} {a.relevant:>3} {a.types:>5} "
        f"| {b.hit:>5} {b.reciprocal_rank:>5.2f} {b.relevant:>3} {b.types:>5}"
    )


def _mean(values: list[Metrics]) -> Metrics:
    n = len(values)
    return Metrics(
        hit=sum(m.hit for m in values) / n,
        reciprocal_rank=sum(m.reciprocal_rank for m in values) / n,
        relevant=sum(m.relevant for m in values) / n,
        types=sum(m.types for m in values) / n,
    )


async def _evaluate(k: int, retrieve_k: int, details: bool) -> None:
    from app.config import get_settings
    from app.db import create_engine
    from app.embedding import FastEmbedEmbedder, embed_query
    from app.events import IncidentCreatedPayload
    from app.query_builder import incident_text
    from app.rerank import FastEmbedReranker
    from app.retrieval import retrieve_evidence
    from app.search import search_chunks

    settings = get_settings()
    golden = json.loads((DEFAULT_DATA_DIR / "golden.json").read_text(encoding="utf-8"))
    cases = json.loads((DEFAULT_DATA_DIR / "eval_incidents.json").read_text(encoding="utf-8"))
    embedder = FastEmbedEmbedder(settings.embedding_model, settings.embedding_cache_dir)
    reranker = FastEmbedReranker(settings.reranker_model, settings.embedding_cache_dir)
    engine = create_engine(settings.database_url)

    vector_scores: list[Metrics] = []
    hybrid_scores: list[Metrics] = []
    lines: list[str] = []
    try:
        for case in sorted(cases, key=lambda c: (c["scenario"], c["tenantId"])):
            tenant, scenario = case["tenantId"], case["scenario"]
            incident = IncidentCreatedPayload.model_validate(case["incident"])
            golden_case = golden[scenario][tenant]

            vector = await embed_query(embedder, incident_text(incident), settings.embedding_query_instruction)
            vector_rows = await search_chunks(engine, tenant_id=tenant, query_vector=vector, k=k)
            vector_results = [(r["source_type"], r["source_id"]) for r in vector_rows]

            items = await retrieve_evidence(
                engine,
                embedder,
                reranker,
                tenant_id=tenant,
                incident=incident,
                retrieve_k=retrieve_k,
                final_k=k,
                caps=settings.retrieval_source_caps,
                window_before=timedelta(minutes=settings.retrieval_window_before_minutes),
                window_after=timedelta(minutes=settings.retrieval_window_after_minutes),
                query_instruction=settings.embedding_query_instruction,
            )
            hybrid_results = [(item.source_type, item.source_id) for item in items]

            a = score(vector_results, golden_case, tenant, scenario)
            b = score(hybrid_results, golden_case, tenant, scenario)
            vector_scores.append(a)
            hybrid_scores.append(b)
            lines.append(_row(f"{scenario} / {tenant}", a, b))
            if details:
                for name, results in (("vector", vector_results), ("hybrid", hybrid_results)):
                    marked = [
                        f"{sid}{'*' if is_relevant(t, sid, golden_case, tenant, scenario) else ''}" for t, sid in results
                    ]
                    lines.append(f"    {name}: {', '.join(marked)}")
    finally:
        await engine.dispose()

    header = f"{'k=' + str(k) + ' (* = relevant)':<30} | {'vector-only':^22} | {'hybrid + rerank + caps':^22}"
    columns = f"{'scenario / tenant':<30} | {'hit@k':>5} {'MRR':>5} {'rel':>3} {'types':>5} | {'hit@k':>5} {'MRR':>5} {'rel':>3} {'types':>5}"
    print(header)
    print(columns)
    print("-" * len(columns))
    print("\n".join(lines))
    print("-" * len(columns))
    a, b = _mean(vector_scores), _mean(hybrid_scores)
    print(
        f"{'OVERALL (mean of ' + str(len(cases)) + ')':<30} | {a.hit:>5.2f} {a.reciprocal_rank:>5.2f} {a.relevant:>3.1f} "
        f"{a.types:>5.2f} | {b.hit:>5.2f} {b.reciprocal_rank:>5.2f} {b.relevant:>3.1f} {b.types:>5.2f}"
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Vector-only vs hybrid retrieval on the evaluation incidents.")
    parser.add_argument("--k", type=int, default=6, help="top-k for both (the hybrid pipeline's final_k)")
    parser.add_argument("--retrieve-k", type=int, default=20)
    parser.add_argument("--details", action="store_true")
    args = parser.parse_args(argv)
    asyncio.run(_evaluate(args.k, args.retrieve_k, args.details))


if __name__ == "__main__":
    main()
