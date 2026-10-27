"""Load the synthetic evidence, chunk it, embed it and upsert it into worker.chunks.

    python -m app.ingest                  # both tenants
    python -m app.ingest --tenant acme

Idempotent: chunk ids are deterministic (see app.chunking), and the insert is an upsert
(INSERT ... ON CONFLICT (id) DO UPDATE of content, embedding and ts), so running it again updates the same rows
instead of adding new ones (ts too: the demo seed re-anchors its evidence to the time it runs).
Known gap: a chunk that disappears from the source (e.g. a removed runbook section) is not deleted.
"""

import argparse
import asyncio
import json
import time
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.chunking import Chunk, chunk_dataset
from app.embedding import Embedder, embed_async

DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "synthetic"
TENANTS = ("acme", "globex")
BATCH_SIZE = 64

# The vector arrives as text ('[0.1,0.2,...]') and is cast in SQL, so we need no pgvector Python package.
UPSERT = text(
    """
    INSERT INTO worker.chunks (id, tenant_id, source_type, service, source_id, chunk_index, ts, content, embedding)
    VALUES (:id, :tenant_id, :source_type, :service, :source_id, :chunk_index, :ts, :content,
            CAST(:embedding AS vector))
    ON CONFLICT (id) DO UPDATE
        SET content = EXCLUDED.content,
            embedding = EXCLUDED.embedding,
            ts = EXCLUDED.ts
    """
)


def load_dataset(data_dir: Path = DEFAULT_DATA_DIR, tenant: str = "all") -> dict[str, list[dict]]:
    """{runbooks, logs, metrics, incidents: [...]} from the JSON files, optionally for one tenant only."""
    dataset = {}
    for kind in ("runbooks", "logs", "metrics", "incidents"):
        docs = json.loads((data_dir / f"{kind}.json").read_text(encoding="utf-8"))
        dataset[kind] = [doc for doc in docs if tenant == "all" or doc["tenant_id"] == tenant]
    return dataset


def to_vector_literal(vector: Sequence[float]) -> str:
    return "[" + ",".join(str(float(v)) for v in vector) + "]"


async def upsert_chunks(
    engine: AsyncEngine, embedder: Embedder, chunks: list[Chunk], batch_size: int = BATCH_SIZE
) -> Counter[tuple[str, str]]:
    """Embed and upsert in batches; returns the number of chunks per (tenant_id, source_type).

    Batches: the model embeds a list faster than one text at a time, and executemany sends one round
    trip per batch. One transaction per batch: a failure loses at most one batch, and a re-run fixes it.
    """
    counts: Counter[tuple[str, str]] = Counter()
    for start in range(0, len(chunks), batch_size):
        batch = chunks[start : start + batch_size]
        vectors = await embed_async(embedder, [chunk.content for chunk in batch])
        rows = [
            {
                "id": chunk.id,
                "tenant_id": chunk.tenant_id,
                "source_type": chunk.source_type,
                "service": chunk.service,
                "source_id": chunk.source_id,
                "chunk_index": chunk.chunk_index,
                "ts": chunk.ts,
                "content": chunk.content,
                "embedding": to_vector_literal(vector),
            }
            for chunk, vector in zip(batch, vectors, strict=True)
        ]
        async with engine.begin() as conn:
            await conn.execute(UPSERT, rows)  # a list of dicts -> executemany
        counts.update((chunk.tenant_id, chunk.source_type) for chunk in batch)
    return counts


async def ingest(
    engine: AsyncEngine, embedder: Embedder, data_dir: Path = DEFAULT_DATA_DIR, tenant: str = "all"
) -> Counter[tuple[str, str]]:
    return await ingest_dataset(engine, embedder, load_dataset(data_dir, tenant))


async def ingest_dataset(engine: AsyncEngine, embedder: Embedder, dataset: dict[str, list[dict]]) -> Counter[tuple[str, str]]:
    """Chunk, embed and upsert an in-memory dataset ({runbooks, logs, metrics, incidents}), e.g. app.demo_data."""
    return await upsert_chunks(engine, embedder, chunk_dataset(**dataset))


async def _run(tenant: str, data_dir: Path) -> None:
    from app.config import get_settings
    from app.db import create_engine
    from app.embedding import FastEmbedEmbedder

    settings = get_settings()
    started = time.perf_counter()
    embedder = FastEmbedEmbedder(settings.embedding_model, settings.embedding_cache_dir)
    model_loaded = time.perf_counter()

    engine = create_engine(settings.database_url)
    try:
        counts = await ingest(engine, embedder, data_dir, tenant)
    finally:
        await engine.dispose()
    finished = time.perf_counter()

    print(f"{'tenant':<8} {'source_type':<10} {'chunks':>6}")
    for (tenant_id, source_type), count in sorted(counts.items()):
        print(f"{tenant_id:<8} {source_type:<10} {count:>6}")
    print(f"total: {sum(counts.values())} chunks (model {settings.embedding_model}, dim {embedder.dim})")
    print(
        f"elapsed: {finished - started:.1f}s "
        f"(model load {model_loaded - started:.1f}s, embed + upsert {finished - model_loaded:.1f}s)"
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Chunk, embed and upsert the synthetic evidence into worker.chunks.")
    parser.add_argument("--tenant", choices=(*TENANTS, "all"), default="all")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    args = parser.parse_args(argv)
    asyncio.run(_run(args.tenant, args.data_dir))


if __name__ == "__main__":
    main()
