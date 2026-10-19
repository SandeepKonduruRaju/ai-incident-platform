"""Retrieval quality with the REAL embedding model (pgvector container; skipped without Docker).

For each scenario, a query written like an on-call engineer would describe the symptoms (paraphrased,
not copied from the runbook) must find that scenario's runbook or log window for acme in the top 5,
according to data/synthetic/golden.json. Slower than the other tests: it embeds all acme chunks (~15s).
The hybrid tests at the end also load the real cross-encoder reranker.
"""

import asyncio
import json
import re

import pytest
from sqlalchemy import text

from app.config import Settings
from app.db import create_engine
from app.embedding import embed_query
from app.ingest import DEFAULT_DATA_DIR, ingest
from app.retrieval import load_eval_incident, retrieve_evidence
from app.search import keyword_search, search_chunks

pytestmark = pytest.mark.integration

TENANT = "acme"
K = 5
SYMPTOM_QUERIES = {
    "db_pool_exhausted": "payment API timing out, no JDBC connections available",
    "bad_deploy": "errors started right after the new release went out and new pods keep crashing",
    "memory_leak": "memory usage keeps growing for hours until the pods are OOMKilled and restarted",
    "dns_failure": "the service cannot resolve the hostnames of its dependencies",
    "expired_tls_cert": "clients fail with SSL handshake errors because the certificate is no longer valid",
    "slow_downstream": "requests are very slow because a dependency we call takes seconds to answer",
}
GOLDEN = json.loads((DEFAULT_DATA_DIR / "golden.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def real_embedder():
    from app.embedding import FastEmbedEmbedder

    try:
        return FastEmbedEmbedder()  # default model; downloads once into the fastembed cache if missing
    except Exception as exc:  # e.g. no network and no cached model
        pytest.skip(f"embedding model not available: {exc}")


@pytest.fixture(scope="module")
def acme_ingested(database_url, real_embedder):
    """Ingest acme once for the whole module (embedding is the slow part)."""

    async def run() -> None:
        engine = create_engine(database_url)
        try:
            async with engine.begin() as conn:
                await conn.execute(text("TRUNCATE worker.chunks"))
            await ingest(engine, real_embedder, tenant=TENANT)
        finally:
            await engine.dispose()

    asyncio.run(run())


def _is_relevant(source_id: str, scenario: str) -> bool:
    # Log chunks are windows named LOG-<tenant>-<scenario>-<service>; the golden log ids share that prefix.
    return source_id in GOLDEN[scenario][TENANT]["runbooks"] or source_id.startswith(f"LOG-{TENANT}-{scenario}-")


@pytest.mark.parametrize("scenario", list(SYMPTOM_QUERIES))
async def test_symptom_query_finds_the_scenario_in_the_top_5(scenario, acme_ingested, real_embedder, engine):
    instruction = Settings(database_url="unused").embedding_query_instruction
    vector = await embed_query(real_embedder, SYMPTOM_QUERIES[scenario], instruction)

    rows = await search_chunks(engine, tenant_id=TENANT, query_vector=vector, k=K)

    ranks = [rank for rank, row in enumerate(rows, start=1) if _is_relevant(row["source_id"], scenario)]
    assert ranks, f"{scenario}: no relevant chunk in the top {K}: {[row['source_id'] for row in rows]}"


# ---------------------------------------------------------------- hybrid retrieval (section 2.5)


@pytest.fixture(scope="module")
def real_reranker():
    from app.rerank import FastEmbedReranker

    try:
        return FastEmbedReranker()
    except Exception as exc:
        pytest.skip(f"reranker model not available: {exc}")


def _first_trace_id(scenario: str) -> tuple[str, str]:
    """(trace id, log line source_id) of the first log line of the scenario that carries a trace id."""
    logs = json.loads((DEFAULT_DATA_DIR / "logs.json").read_text(encoding="utf-8"))
    for line in logs:
        match = re.search(r"trace=([0-9a-f]{16})", line["message"])
        if line["source_id"].startswith(f"LOG-{TENANT}-{scenario}-") and match:
            return match.group(1), line["source_id"]
    raise AssertionError(f"no trace id in {scenario} logs")


async def test_keyword_search_finds_an_exact_trace_id_that_vector_search_ranks_low(
    acme_ingested, real_embedder, engine
):
    trace_id, _ = _first_trace_id("db_pool_exhausted")
    expected = f"LOG-{TENANT}-db_pool_exhausted-payment-service"  # the log window holding that line

    keyword_rows = await keyword_search(engine, tenant_id=TENANT, query=trace_id, k=5)
    vector = await embed_query(real_embedder, trace_id, Settings(database_url="unused").embedding_query_instruction)
    vector_rows = await search_chunks(engine, tenant_id=TENANT, query_vector=vector, k=50)
    vector_rank = next(rank for rank, row in enumerate(vector_rows, start=1) if row["source_id"] == expected)

    assert [row["source_id"] for row in keyword_rows] == [expected]  # exactly one chunk has this token
    # A 16-hex-digit id has no meaning for an embedding model: the right chunk is far from the top.
    assert vector_rank > K, f"vector search ranked it {vector_rank}"


async def test_hybrid_pipeline_with_real_models(acme_ingested, real_embedder, real_reranker, engine):
    incident = load_eval_incident(TENANT, scenario="db_pool_exhausted")

    items = await retrieve_evidence(engine, real_embedder, real_reranker, tenant_id=TENANT, incident=incident)

    assert {item.tenant_id for item in items} == {TENANT}
    assert items[0].source_id == "LOG-acme-db_pool_exhausted-payment-service"
    found = {item.source_id for item in items}
    assert {"RB-acme-db_pool_exhausted", "MET-acme-db_pool_exhausted", "INC-acme-db_pool_exhausted-1"} <= found
