"""Migration 0002 on a real PostgreSQL + pgvector container (skipped without Docker)."""

import uuid

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration


async def test_migrations_are_at_head(engine):
    async with engine.connect() as conn:
        version = (await conn.execute(text("SELECT version_num FROM worker.alembic_version"))).scalar_one()
    assert version == "0002"


async def test_vector_extension_is_installed(engine):
    async with engine.connect() as conn:
        version = (
            await conn.execute(text("SELECT extversion FROM pg_extension WHERE extname = 'vector'"))
        ).scalar_one_or_none()
    assert version is not None


async def test_chunks_indexes_exist(engine):
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text("SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'worker' AND tablename = 'chunks'")
            )
        ).all()
    indexes = {name: definition for name, definition in rows}

    hnsw = indexes["ix_chunks_embedding_hnsw"]
    assert "USING hnsw" in hnsw
    assert "vector_cosine_ops" in hnsw
    assert "USING btree (tenant_id, source_type)" in indexes["ix_chunks_tenant_source_type"]


async def test_chunks_accepts_a_384_dim_vector_and_rejects_other_sizes(engine):
    vector_384 = "[" + ",".join(["0.1"] * 384) + "]"
    insert = text(
        "INSERT INTO worker.chunks (id, tenant_id, source_type, source_id, chunk_index, content, embedding) "
        "VALUES (:id, 'acme', 'runbook', 'RB-test', 0, 'test', CAST(:embedding AS vector))"
    )
    async with engine.begin() as conn:
        await conn.execute(insert, {"id": uuid.uuid4(), "embedding": vector_384})
        distance = (
            await conn.execute(
                text("SELECT embedding <=> CAST(:q AS vector) FROM worker.chunks WHERE source_id = 'RB-test'"),
                {"q": vector_384},
            )
        ).scalar_one()
        await conn.execute(text("DELETE FROM worker.chunks WHERE source_id = 'RB-test'"))
    assert distance == pytest.approx(0.0, abs=1e-6)  # identical vectors: cosine distance 0

    with pytest.raises(Exception, match="expected 384 dimensions"):
        async with engine.begin() as conn:
            await conn.execute(insert, {"id": uuid.uuid4(), "embedding": "[0.1,0.2,0.3]"})


async def test_source_type_is_restricted(engine):
    vector_384 = "[" + ",".join(["0.1"] * 384) + "]"
    with pytest.raises(Exception, match="check constraint"):
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO worker.chunks (id, tenant_id, source_type, source_id, chunk_index, content, embedding) "
                    "VALUES (:id, 'acme', 'email', 'X', 0, 'x', CAST(:e AS vector))"
                ),
                {"id": uuid.uuid4(), "e": vector_384},
            )
