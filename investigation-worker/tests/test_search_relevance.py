"""Retrieval quality with the REAL embedding model (pgvector container; skipped without Docker).

For each scenario, a query written like an on-call engineer would describe the symptoms (paraphrased,
not copied from the runbook) must find that scenario's runbook or log window for acme in the top 5,
according to data/synthetic/golden.json. Slower than the other tests: it embeds all acme chunks (~15s).
"""

import asyncio
import json

import pytest
from sqlalchemy import text

from app.config import Settings
from app.db import create_engine
from app.embedding import embed_query
from app.ingest import DEFAULT_DATA_DIR, ingest
from app.search import search_chunks

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
