"""search_chunks on a real PostgreSQL + pgvector container (skipped without Docker).

FakeEmbedder vectors carry no meaning, but the same text always gives the same vector: searching with
the vector of a stored chunk's content finds that chunk at distance 0. That makes the tests exact.
"""

import random
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.embedding import FakeEmbedder
from app.ingest import ingest, to_vector_literal
from app.search import build_search_sql, search_chunks, to_pgvector

pytestmark = pytest.mark.integration

DIM = 384


@pytest.fixture
async def clean_engine(engine):
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE worker.chunks"))
    yield engine


@pytest.fixture
async def both_tenants(clean_engine):
    await ingest(clean_engine, FakeEmbedder())  # acme + globex
    return clean_engine


async def _globex_contents(engine, count: int) -> list[str]:
    """`count` globex chunk contents spread over all source types, used as queries against acme."""
    async with engine.connect() as conn:
        contents = (
            await conn.execute(
                text(
                    "SELECT content FROM worker.chunks WHERE tenant_id = 'globex' "
                    "ORDER BY source_type, source_id, chunk_index"
                )
            )
        ).scalars().all()
    step = len(contents) // count
    return contents[::step][:count]


# ---------------------------------------------------------------- a) tenant isolation


async def test_results_only_come_from_the_requested_tenant(both_tenants):
    embedder = FakeEmbedder()
    # The worst case: each query IS a globex chunk, so globex rows are the nearest ones overall.
    queries = await _globex_contents(both_tenants, 5)
    assert len(queries) == 5

    for query in queries:
        [vector] = embedder.embed([query])
        for tenant in ("acme", "globex"):
            rows = await search_chunks(both_tenants, tenant_id=tenant, query_vector=vector, k=5)
            assert len(rows) == 5
            assert {row["tenant_id"] for row in rows} == {tenant}


async def test_without_the_tenant_filter_an_acme_query_would_return_globex_rows(both_tenants):
    """Proves the isolation test above can fail: the same query without WHERE tenant_id leaks globex rows."""
    [query] = await _globex_contents(both_tenants, 1)
    [vector] = FakeEmbedder().embed([query])

    unfiltered = text(
        "SELECT tenant_id, embedding <=> CAST(:q AS vector) AS distance FROM worker.chunks "
        "ORDER BY embedding <=> CAST(:q AS vector) LIMIT 5"
    )
    async with both_tenants.connect() as conn:
        rows = (await conn.execute(unfiltered, {"q": to_pgvector(vector)})).all()

    assert rows[0].tenant_id == "globex"
    assert rows[0].distance == pytest.approx(0.0, abs=1e-4)
    filtered = await search_chunks(both_tenants, tenant_id="acme", query_vector=vector, k=5)
    assert "globex" not in {row["tenant_id"] for row in filtered}


# ---------------------------------------------------------------- b) iterative scan


def _vector_near(base: list[float], rng: random.Random, noise: float) -> list[float]:
    return [b + rng.uniform(-noise, noise) for b in base]


async def _insert_raw(engine, tenant: str, vectors: list[list[float]]) -> None:
    rows = [
        {
            "id": uuid.uuid4(),
            "tenant": tenant,
            "source_id": f"RAW-{tenant}-{i:05d}",
            "embedding": to_vector_literal(vector),
        }
        for i, vector in enumerate(vectors)
    ]
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO worker.chunks (id, tenant_id, source_type, source_id, chunk_index, content, embedding) "
                "VALUES (:id, :tenant, 'log', :source_id, 0, 'raw', CAST(:embedding AS vector))"
            ),
            rows,
        )


@pytest.fixture
async def skewed_tenants(clean_engine, database_url):
    """2000 rows for 'big' right next to the query, 8 rows for 'small' far away from it.

    HNSW without iterative scan collects only hnsw.ef_search (default 40) candidates, all from 'big';
    the tenant filter then removes them all.

    After ANALYZE, PostgreSQL knows 'small' has 8 rows and (correctly) prefers the B-tree on tenant_id plus
    an exact sort, which never needs the iterative scan. To test the HNSW path we forbid that plan:
    enable_seqscan=off and enable_sort=off leave the HNSW index scan as the only cheap option.
    Otherwise both tests below would pass for the wrong reason.
    """
    rng = random.Random(7)
    query = [1.0] + [0.0] * (DIM - 1)
    far = [-1.0] + [0.0] * (DIM - 1)
    await _insert_raw(clean_engine, "big", [_vector_near(query, rng, 0.05) for _ in range(2000)])
    await _insert_raw(clean_engine, "small", [_vector_near(far, rng, 0.05) for _ in range(8)])

    async with clean_engine.begin() as conn:
        await conn.execute(text("ANALYZE worker.chunks"))  # real row counts per tenant for the planner

    hnsw_only = create_async_engine(
        database_url, connect_args={"server_settings": {"enable_seqscan": "off", "enable_sort": "off"}}
    )
    yield hnsw_only, query
    await hnsw_only.dispose()


async def test_iterative_scan_fills_k_for_a_small_tenant(skewed_tenants):
    engine, query = skewed_tenants
    rows = await search_chunks(engine, tenant_id="small", query_vector=query, k=5)
    assert len(rows) == 5
    assert {row["tenant_id"] for row in rows} == {"small"}


async def test_without_iterative_scan_the_small_tenant_gets_fewer_than_k(skewed_tenants):
    """The control experiment: same query and data, iterative scan off."""
    engine, query = skewed_tenants
    async with engine.begin() as conn:
        await conn.execute(text("SET LOCAL hnsw.iterative_scan = off"))
        rows = (await conn.execute(build_search_sql(), {"q": to_pgvector(query), "tenant": "small", "k": 5})).all()
    assert len(rows) < 5


# ---------------------------------------------------------------- c) the HNSW index is used


async def _plan(engine, tenant: str, query: list[float]) -> str:
    async with engine.connect() as conn:
        plan_sql = text("EXPLAIN " + str(build_search_sql()))
        lines = (await conn.execute(plan_sql, {"q": to_pgvector(query), "tenant": tenant, "k": 5})).scalars().all()
    return "\n".join(lines)


async def test_search_query_uses_the_hnsw_index_for_a_large_tenant(skewed_tenants, clean_engine):
    """No planner settings forced: with real statistics and 2000 matching rows, PostgreSQL picks HNSW itself."""
    _, query = skewed_tenants
    plan = await _plan(clean_engine, "big", query)
    assert "Index Scan using ix_chunks_embedding_hnsw" in plan, plan


async def test_planner_prefers_the_tenant_btree_for_a_tiny_tenant(skewed_tenants, clean_engine):
    """Documents the trade-off: for 8 rows an exact sort is cheaper than HNSW (and gives exact results)."""
    _, query = skewed_tenants
    plan = await _plan(clean_engine, "small", query)
    assert "ix_chunks_tenant_source_type" in plan, plan
    assert "ix_chunks_embedding_hnsw" not in plan, plan


# ---------------------------------------------------------------- e) optional filters


async def test_source_types_filter(both_tenants):
    [vector] = FakeEmbedder().embed(["database connection pool exhausted"])

    runbooks = await search_chunks(both_tenants, tenant_id="acme", query_vector=vector, k=10, source_types=["runbook"])
    mixed = await search_chunks(
        both_tenants, tenant_id="acme", query_vector=vector, k=20, source_types=["metric", "incident"]
    )

    assert len(runbooks) == 10
    assert {row["source_type"] for row in runbooks} == {"runbook"}
    assert {row["source_type"] for row in mixed} == {"metric", "incident"}
    assert {row["tenant_id"] for row in runbooks + mixed} == {"acme"}


async def test_service_filter(both_tenants):
    [vector] = FakeEmbedder().embed(["anything"])
    rows = await search_chunks(both_tenants, tenant_id="globex", query_vector=vector, k=10, service="checkout-api")
    assert rows
    assert {(row["tenant_id"], row["service"]) for row in rows} == {("globex", "checkout-api")}


async def test_results_are_ordered_by_distance(both_tenants):
    [vector] = FakeEmbedder().embed(["anything"])
    rows = await search_chunks(both_tenants, tenant_id="acme", query_vector=vector, k=20)
    distances = [row["distance"] for row in rows]
    assert distances == sorted(distances)
