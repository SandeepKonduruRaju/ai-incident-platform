"""keyword_search (PostgreSQL full-text search) on a real PostgreSQL + pgvector container (skipped without Docker).

FakeEmbedder is enough here: keyword search does not use the embeddings. The "keyword beats vector on an
exact token" test with the real model lives in test_search_relevance.py.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import text

from app.embedding import FakeEmbedder
from app.ingest import ingest
from app.search import keyword_search

pytestmark = pytest.mark.integration


@pytest.fixture
async def both_tenants(engine):
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE worker.chunks"))
    await ingest(engine, FakeEmbedder())
    return engine


async def test_exact_token_is_found(both_tenants):
    rows = await keyword_search(both_tenants, tenant_id="acme", query="HikariPool", k=5)
    assert rows
    assert all("hikaripool" in row["content"].lower() for row in rows)
    assert rows[0]["source_id"] in {"LOG-acme-db_pool_exhausted-payment-service", "RB-acme-db_pool_exhausted"}


async def test_results_have_the_same_keys_as_vector_search_plus_rank(both_tenants):
    [row] = await keyword_search(both_tenants, tenant_id="acme", query="CrashLoopBackOff", k=1)
    assert set(row) == {
        "chunk_id", "tenant_id", "source_id", "chunk_index", "source_type", "service", "ts", "content", "rank",
    }
    assert row["rank"] > 0


async def test_ranked_by_ts_rank_descending(both_tenants):
    rows = await keyword_search(both_tenants, tenant_id="acme", query="pool or connection or timeout", k=10)
    ranks = [row["rank"] for row in rows]
    assert len(rows) == 10
    assert ranks == sorted(ranks, reverse=True)


async def test_tenant_isolation(both_tenants):
    # "ledger-db" is globex's database name: it appears only in globex chunks.
    assert await keyword_search(both_tenants, tenant_id="acme", query="ledger-db", k=10) == []
    globex = await keyword_search(both_tenants, tenant_id="globex", query="ledger-db", k=10)
    assert globex
    assert {row["tenant_id"] for row in globex} == {"globex"}


async def test_without_the_tenant_filter_the_same_query_would_leak(both_tenants):
    """Control for the isolation test: the raw full-text match finds globex rows for that word."""
    async with both_tenants.connect() as conn:
        tenants = (
            await conn.execute(
                text(
                    "SELECT DISTINCT tenant_id FROM worker.chunks "
                    "WHERE content_tsv @@ websearch_to_tsquery('english', 'ledger-db')"
                )
            )
        ).scalars().all()
    assert tenants == ["globex"]


async def test_source_type_and_service_filters(both_tenants):
    runbooks = await keyword_search(both_tenants, tenant_id="acme", query="pool", k=20, source_types=["runbook"])
    assert runbooks and {row["source_type"] for row in runbooks} == {"runbook"}

    payment = await keyword_search(both_tenants, tenant_id="acme", query="pool", k=20, service="payment-service")
    assert payment and {row["service"] for row in payment} == {"payment-service"}


async def test_time_window_filter(both_tenants):
    # acme's db_pool_exhausted logs and metric happen on 2026-09-24 (see data/synthetic).
    inside = await keyword_search(
        both_tenants,
        tenant_id="acme",
        query="HikariPool",
        k=10,
        source_types=["log"],
        time_from=datetime(2026, 9, 24, tzinfo=UTC),
        time_to=datetime(2026, 9, 25, tzinfo=UTC),
    )
    outside = await keyword_search(
        both_tenants,
        tenant_id="acme",
        query="HikariPool",
        k=10,
        source_types=["log"],
        time_from=datetime(2026, 9, 1, tzinfo=UTC),
        time_to=datetime(2026, 9, 2, tzinfo=UTC),
    )
    assert [row["source_id"] for row in inside] == ["LOG-acme-db_pool_exhausted-payment-service"]
    assert outside == []


async def test_user_input_syntax_never_raises(both_tenants):
    # websearch_to_tsquery accepts any text: unbalanced quotes, operators, stop words only.
    for query in ['"unclosed quote', "-", "the and of", "a & b | !c", ""]:
        await keyword_search(both_tenants, tenant_id="acme", query=query, k=3)
