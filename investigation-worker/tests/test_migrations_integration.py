"""Migrations 0002 and 0003 on a real PostgreSQL + pgvector container (skipped without Docker)."""

import asyncio
import uuid

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.db import create_engine
from tests.conftest import PROJECT_ROOT

pytestmark = pytest.mark.integration


async def test_migrations_are_at_head(engine):
    async with engine.connect() as conn:
        version = (await conn.execute(text("SELECT version_num FROM worker.alembic_version"))).scalar_one()
    assert version == "0004"


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


async def test_content_tsv_is_generated_from_content_with_a_gin_index(engine):
    vector_384 = "[" + ",".join(["0.1"] * 384) + "]"
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO worker.chunks (id, tenant_id, source_type, source_id, chunk_index, content, embedding) "
                "VALUES (:id, 'acme', 'log', 'TSV-test', 0, 'HikariPool connections timing out', CAST(:e AS vector))"
            ),
            {"id": uuid.uuid4(), "e": vector_384},
        )
        tsv = (
            await conn.execute(text("SELECT content_tsv::text FROM worker.chunks WHERE source_id = 'TSV-test'"))
        ).scalar_one()
        index = (
            await conn.execute(
                text("SELECT indexdef FROM pg_indexes WHERE schemaname = 'worker' AND indexname = 'ix_chunks_content_tsv'")
            )
        ).scalar_one()
        generated = (
            await conn.execute(
                text(
                    "SELECT is_generated FROM information_schema.columns "
                    "WHERE table_schema = 'worker' AND table_name = 'chunks' AND column_name = 'content_tsv'"
                )
            )
        ).scalar_one()
        await conn.execute(text("DELETE FROM worker.chunks WHERE source_id = 'TSV-test'"))

    # Lower-cased and stemmed by the 'english' config ("connections" -> "connect", "timing" -> "time").
    assert "'hikaripool'" in tsv and "'connect'" in tsv and "'time'" in tsv
    assert "USING gin (content_tsv)" in index
    assert generated == "ALWAYS"


async def test_migration_0003_downgrade_and_upgrade_again(database_url):
    """The new revision is reversible and re-applies cleanly (IF EXISTS / IF NOT EXISTS)."""
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    config.attributes["database_url"] = database_url
    config.attributes["configure_logging"] = False

    # Alembic's env.py calls asyncio.run(), which cannot run inside this test's event loop: use a thread.
    await asyncio.to_thread(command.downgrade, config, "0002")
    await asyncio.to_thread(command.upgrade, config, "head")

    engine = create_engine(database_url)
    try:
        async with engine.connect() as conn:
            version = (await conn.execute(text("SELECT version_num FROM worker.alembic_version"))).scalar_one()
            has_column = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM information_schema.columns "
                        "WHERE table_schema = 'worker' AND table_name = 'chunks' AND column_name = 'content_tsv'"
                    )
                )
            ).scalar_one()
    finally:
        await engine.dispose()
    assert (version, has_column) == ("0004", 1)  # back at head, with 0003's column re-created
