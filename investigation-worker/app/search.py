"""Semantic search over worker.chunks (pgvector, cosine distance, always scoped to one tenant).

    python -m app.search "payment API timing out" --tenant acme [--k 5] [--type runbook] [--service payment-service]
    python -m app.search "..." --tenant acme --no-query-instruction     # compare without the BGE query prefix
"""

import argparse
import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


def to_pgvector(vec: list[float]) -> str:
    # pgvector accepts a vector literal like "[0.1,0.2,...]"
    return "[" + ",".join(f"{x:.6f}" for x in vec) + "]"


def build_search_sql(*, source_types: list[str] | None = None, service: str | None = None):
    """The search query. tenant_id is always in the WHERE clause; the other filters are optional extras."""
    filters = ["tenant_id = :tenant"]  # tenant isolation
    if source_types is not None:
        filters.append("source_type = ANY(:source_types)")
    if service is not None:
        filters.append("service = :service")
    return text(f"""
        SELECT tenant_id, source_id, chunk_index, source_type, service, content,
               embedding <=> CAST(:q AS vector) AS distance   -- cosine distance
        FROM worker.chunks
        WHERE {" AND ".join(filters)}
        ORDER BY embedding <=> CAST(:q AS vector)               -- nearest first (uses HNSW)
        LIMIT :k
    """)


async def search_chunks(
    engine: AsyncEngine,
    *,                          # keyword-only: callers must name every argument
    tenant_id: str,             # REQUIRED, no default → impossible to forget
    query_vector: list[float],
    k: int = 5,
    source_types: list[str] | None = None,  # e.g. ["runbook"]; None = all types
    service: str | None = None,             # e.g. "payment-service"; None = all services
) -> list[dict]:
    sql = build_search_sql(source_types=source_types, service=service)
    params = {"q": to_pgvector(query_vector), "tenant": tenant_id, "k": k}
    if source_types is not None:
        params["source_types"] = list(source_types)
    if service is not None:
        params["service"] = service

    async with engine.begin() as conn:  # a transaction, so SET LOCAL applies only here
        # keep scanning HNSW until enough rows pass the tenant filter (pgvector >= 0.8)
        await conn.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))
        rows = await conn.execute(sql, params)
        return [dict(r._mapping) for r in rows]


async def _run(
    query: str, tenant: str, k: int, source_types: list[str] | None, service: str | None, use_instruction: bool
) -> None:
    from app.config import get_settings
    from app.db import create_engine
    from app.embedding import FastEmbedEmbedder, embed_query

    settings = get_settings()
    embedder = FastEmbedEmbedder(settings.embedding_model, settings.embedding_cache_dir)  # SAME model as the ingest
    instruction = settings.embedding_query_instruction if use_instruction else ""
    query_vector = await embed_query(embedder, query, instruction)

    engine = create_engine(settings.database_url)
    try:
        rows = await search_chunks(
            engine, tenant_id=tenant, query_vector=query_vector, k=k, source_types=source_types, service=service
        )
    finally:
        await engine.dispose()

    for r in rows:
        snippet = r["content"][:80].replace("\n", " | ")
        print(f"{r['distance']:.3f}  {r['source_type']:8} {r['source_id']:44} {snippet}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Semantic search over worker.chunks for one tenant.")
    parser.add_argument("query")
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument(
        "--type", dest="source_types", action="append", choices=("runbook", "log", "metric", "incident"),
        help="filter by source type; repeat for several",
    )
    parser.add_argument("--service")
    parser.add_argument(
        "--no-query-instruction", dest="use_instruction", action="store_false",
        help="embed the raw query, without EMBEDDING_QUERY_INSTRUCTION (to compare)",
    )
    args = parser.parse_args(argv)
    if args.k < 1:
        parser.error("--k must be at least 1")
    asyncio.run(_run(args.query, args.tenant, args.k, args.source_types, args.service, args.use_instruction))


if __name__ == "__main__":
    main()
