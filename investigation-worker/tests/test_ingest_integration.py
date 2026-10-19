"""Ingestion into a real PostgreSQL + pgvector container with FakeEmbedder (skipped without Docker)."""

import pytest
from sqlalchemy import text

from app.embedding import FakeEmbedder
from app.ingest import ingest

pytestmark = pytest.mark.integration


async def _count(engine) -> int:
    async with engine.connect() as conn:
        return (await conn.execute(text("SELECT count(*) FROM worker.chunks"))).scalar_one()


@pytest.fixture
async def clean_engine(engine):
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE worker.chunks"))
    yield engine


async def test_ingest_twice_gives_the_same_rows(clean_engine):
    first = await ingest(clean_engine, FakeEmbedder())
    rows_after_first = await _count(clean_engine)

    second = await ingest(clean_engine, FakeEmbedder())

    assert rows_after_first == sum(first.values()) > 0
    assert await _count(clean_engine) == rows_after_first  # upsert on deterministic ids: no duplicates
    assert second == first


async def test_ingest_one_tenant_only(clean_engine):
    counts = await ingest(clean_engine, FakeEmbedder(), tenant="globex")

    async with clean_engine.connect() as conn:
        tenants = (await conn.execute(text("SELECT DISTINCT tenant_id FROM worker.chunks"))).scalars().all()
    assert tenants == ["globex"]
    assert {tenant for tenant, _ in counts} == {"globex"}


async def test_stored_runbook_chunks_keep_order_title_and_384_dims(clean_engine):
    await ingest(clean_engine, FakeEmbedder(), tenant="acme")

    async with clean_engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT chunk_index, content, vector_dims(embedding) AS dims FROM worker.chunks "
                    "WHERE source_id = 'RB-acme-db_pool_exhausted' ORDER BY chunk_index"
                )
            )
        ).all()
    # Overview (Owner line) + Symptoms, Diagnosis, Mitigation, Prevention
    assert [row.chunk_index for row in rows] == [0, 1, 2, 3, 4]
    assert all(row.content.startswith("Database connection pool exhausted (payment-service) — ") for row in rows)
    assert {row.dims for row in rows} == {384}
