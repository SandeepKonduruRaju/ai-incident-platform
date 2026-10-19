"""Hybrid retrieval: from an incident to a small, diverse, labelled set of evidence chunks.

    incident -> build_queries (one spec per evidence type)
             -> per spec: vector search + keyword search (same tenant and filters), fused with RRF
             -> merge, keep the best retrieve_k candidates
             -> cross-encoder rerank against the incident text
             -> per-type caps, final_k items, labelled C1..Cn (the LLM cites these labels in 2.6)

    python -m app.retrieval --tenant acme --scenario db_pool_exhausted
    python -m app.retrieval --tenant globex --incident-id 93e32dbf-1bc0-5416-ba67-624bedbffda4

Tenant isolation: every search filters on tenant_id, and the candidates are checked again before
reranking (defence in depth: a future search bug must fail loudly, not leak another tenant's data).
"""

import argparse
import asyncio
import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncEngine

from app.embedding import BGE_QUERY_INSTRUCTION, Embedder, embed_query
from app.events import IncidentCreatedPayload
from app.fusion import rrf_fuse
from app.query_builder import DEFAULT_WINDOW_AFTER, DEFAULT_WINDOW_BEFORE, QuerySpec, build_queries, incident_text
from app.rerank import Reranker, rerank_async
from app.search import keyword_search, search_chunks
from app.selection import DEFAULT_SOURCE_CAPS, apply_source_caps, validate_k

EVAL_INCIDENTS_PATH = Path(__file__).resolve().parent.parent / "data" / "synthetic" / "eval_incidents.json"


class TenantIsolationError(RuntimeError):
    """A search returned a chunk of another tenant. Must never happen; never caught and ignored."""


@dataclass(frozen=True)
class EvidenceItem:
    label: str                 # "C1".."Cn" after selection; "" before
    chunk_id: UUID
    tenant_id: str
    source_type: str
    source_id: str
    service: str | None
    ts: datetime | None
    content: str
    rrf_score: float
    rerank_score: float


def label_map(items: list[EvidenceItem]) -> dict[str, UUID]:
    """{"C1": chunk_id, ...}: lets 2.6 check that every citation in the LLM answer is real."""
    return {item.label: item.chunk_id for item in items}


async def _search_spec(
    engine: AsyncEngine, tenant_id: str, spec: QuerySpec, vector: list[float], k: int
) -> tuple[list[dict], list[dict]]:
    filters = {
        "tenant_id": tenant_id,
        "k": k,
        "source_types": [spec.source_type],
        "service": spec.service,
        "time_from": spec.time_from,
        "time_to": spec.time_to,
    }
    vector_task = search_chunks(engine, query_vector=vector, **filters)
    if not spec.keyword_query:  # e.g. a title of only 1-2 letter words: nothing to match on
        return await vector_task, []
    return await asyncio.gather(vector_task, keyword_search(engine, query=spec.keyword_query, **filters))


def _fuse(results: list[tuple[list[dict], list[dict]]], tenant_id: str) -> tuple[dict[UUID, dict], dict[UUID, float]]:
    """RRF per spec, then merge across specs by chunk_id (keeping the best score)."""
    rows: dict[UUID, dict] = {}
    rrf: dict[UUID, float] = {}
    for vector_rows, keyword_rows in results:
        for row in (*vector_rows, *keyword_rows):
            if row["tenant_id"] != tenant_id:
                raise TenantIsolationError(f"chunk {row['chunk_id']} belongs to another tenant")
            rows[row["chunk_id"]] = row
        fused = rrf_fuse([[row["chunk_id"] for row in vector_rows], [row["chunk_id"] for row in keyword_rows]])
        for chunk_id, score in fused:
            rrf[chunk_id] = max(score, rrf.get(chunk_id, 0.0))
    return rows, rrf


async def retrieve_evidence(
    engine: AsyncEngine,
    embedder: Embedder,
    reranker: Reranker,
    *,
    tenant_id: str,
    incident: IncidentCreatedPayload,
    retrieve_k: int = 20,
    final_k: int = 6,
    caps: Mapping[str, int] = DEFAULT_SOURCE_CAPS,
    window_before: timedelta = DEFAULT_WINDOW_BEFORE,
    window_after: timedelta = DEFAULT_WINDOW_AFTER,
    query_instruction: str = BGE_QUERY_INSTRUCTION,
) -> list[EvidenceItem]:
    validate_k(retrieve_k=retrieve_k, final_k=final_k)
    specs = build_queries(incident, window_before=window_before, window_after=window_after)

    # All specs share the incident text today; embed each distinct text once.
    vectors = {text: await embed_query(embedder, text, query_instruction) for text in {s.text for s in specs}}
    results = await asyncio.gather(
        *(_search_spec(engine, tenant_id, spec, vectors[spec.text], retrieve_k) for spec in specs)
    )
    rows, rrf = _fuse(list(results), tenant_id)

    candidates = sorted(rrf, key=lambda chunk_id: (-rrf[chunk_id], str(chunk_id)))[:retrieve_k]
    scores = await rerank_async(reranker, incident_text(incident), [rows[chunk_id]["content"] for chunk_id in candidates])
    scored = [
        EvidenceItem(
            label="",
            chunk_id=chunk_id,
            tenant_id=rows[chunk_id]["tenant_id"],
            source_type=rows[chunk_id]["source_type"],
            source_id=rows[chunk_id]["source_id"],
            service=rows[chunk_id]["service"],
            ts=rows[chunk_id]["ts"],
            content=rows[chunk_id]["content"],
            rrf_score=rrf[chunk_id],
            rerank_score=score,
        )
        for chunk_id, score in zip(candidates, scores, strict=True)
    ]
    selected = apply_source_caps(scored, caps, final_k)
    return [replace(item, label=f"C{number}") for number, item in enumerate(selected, start=1)]


# ---------------------------------------------------------------- CLI


def load_eval_incident(tenant: str, *, incident_id: str | None = None, scenario: str | None = None) -> IncidentCreatedPayload:
    """An incident from data/synthetic/eval_incidents.json, only if it belongs to `tenant`."""
    entries = json.loads(EVAL_INCIDENTS_PATH.read_text(encoding="utf-8"))
    for entry in entries:
        if entry["tenantId"] != tenant:
            continue
        if entry["incident"]["incidentId"] == incident_id or entry["scenario"] == scenario:
            return IncidentCreatedPayload.model_validate(entry["incident"])
    raise SystemExit(f"no eval incident {incident_id or scenario!r} for tenant {tenant!r}")


async def _run(tenant: str, incident: IncidentCreatedPayload, retrieve_k: int, final_k: int) -> None:
    from app.config import get_settings
    from app.db import create_engine
    from app.embedding import FastEmbedEmbedder
    from app.rerank import FastEmbedReranker

    settings = get_settings()
    embedder = FastEmbedEmbedder(settings.embedding_model, settings.embedding_cache_dir)
    reranker = FastEmbedReranker(settings.reranker_model, settings.embedding_cache_dir)
    engine = create_engine(settings.database_url)
    try:
        items = await retrieve_evidence(
            engine,
            embedder,
            reranker,
            tenant_id=tenant,
            incident=incident,
            retrieve_k=retrieve_k,
            final_k=final_k,
            caps=settings.retrieval_source_caps,
            window_before=timedelta(minutes=settings.retrieval_window_before_minutes),
            window_after=timedelta(minutes=settings.retrieval_window_after_minutes),
            query_instruction=settings.embedding_query_instruction,
        )
    finally:
        await engine.dispose()

    print(f"incident: {incident.title} | service={incident.affectedService} | createdAt={incident.createdAt}")
    print(f"{'label':<5} {'rerank':>7} {'rrf':>7}  {'type':<8} {'source_id':<44} content")
    for item in items:
        snippet = item.content[:70].replace("\n", " | ")
        print(f"{item.label:<5} {item.rerank_score:>7.2f} {item.rrf_score:>7.4f}  {item.source_type:<8} {item.source_id:<44} {snippet}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Hybrid retrieval for one evaluation incident.")
    parser.add_argument("--tenant", required=True)
    which = parser.add_mutually_exclusive_group(required=True)
    which.add_argument("--incident-id", help="incidentId from data/synthetic/eval_incidents.json")
    which.add_argument("--scenario", help="e.g. db_pool_exhausted (the tenant's eval incident for it)")
    parser.add_argument("--retrieve-k", type=int, default=20)
    parser.add_argument("--final-k", type=int, default=6)
    args = parser.parse_args(argv)
    try:
        validate_k(retrieve_k=args.retrieve_k, final_k=args.final_k)
    except ValueError as exc:
        parser.error(str(exc))
    incident = load_eval_incident(args.tenant, incident_id=args.incident_id, scenario=args.scenario)
    asyncio.run(_run(args.tenant, incident, args.retrieve_k, args.final_k))


if __name__ == "__main__":
    main()
