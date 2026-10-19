"""Semantic search over worker.chunks (pgvector, cosine distance, always scoped to one tenant).

    python -m app.search "payment API timing out" --tenant acme [--k 5] [--type runbook] [--service payment-service]
    python -m app.search "..." --tenant acme --no-query-instruction     # compare without the BGE query prefix
"""

import argparse
import asyncio
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


def to_pgvector(vec: list[float]) -> str:
    # pgvector accepts a vector literal like "[0.1,0.2,...]"
    return "[" + ",".join(f"{x:.6f}" for x in vec) + "]"


# Columns both searches return, so their results can be fused (RRF) and merged by chunk_id.
_RESULT_COLUMNS = "id AS chunk_id, tenant_id, source_id, chunk_index, source_type, service, ts, content"


def _where(
    *,
    source_types: list[str] | None,
    service: str | None,
    time_from: datetime | None,
    time_to: datetime | None,
) -> str:
    """WHERE clause shared by vector and keyword search. tenant_id is ALWAYS the first filter."""
    filters = ["tenant_id = :tenant"]  # tenant isolation
    if source_types is not None:
        filters.append("source_type = ANY(:source_types)")
    if service is not None:
        filters.append("service = :service")
    # Half-open window [time_from, time_to). Rows without ts (runbooks) never match a time filter.
    if time_from is not None:
        filters.append("ts >= :time_from")
    if time_to is not None:
        filters.append("ts < :time_to")
    return " AND ".join(filters)


def _params(
    tenant_id: str,
    k: int,
    source_types: list[str] | None,
    service: str | None,
    time_from: datetime | None,
    time_to: datetime | None,
) -> dict:
    params: dict = {"tenant": tenant_id, "k": k}
    if source_types is not None:
        params["source_types"] = list(source_types)
    optional = {"service": service, "time_from": time_from, "time_to": time_to}
    params.update({name: value for name, value in optional.items() if value is not None})
    return params


def build_search_sql(
    *,
    source_types: list[str] | None = None,
    service: str | None = None,
    time_from: datetime | None = None,
    time_to: datetime | None = None,
):
    """The vector search query. tenant_id is always in the WHERE clause; the other filters are optional extras."""
    where = _where(source_types=source_types, service=service, time_from=time_from, time_to=time_to)
    return text(f"""
        SELECT {_RESULT_COLUMNS},
               embedding <=> CAST(:q AS vector) AS distance   -- cosine distance
        FROM worker.chunks
        WHERE {where}
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
    time_from: datetime | None = None,      # only chunks with ts >= time_from
    time_to: datetime | None = None,        # only chunks with ts < time_to
) -> list[dict]:
    sql = build_search_sql(source_types=source_types, service=service, time_from=time_from, time_to=time_to)
    params = _params(tenant_id, k, source_types, service, time_from, time_to)
    params["q"] = to_pgvector(query_vector)

    async with engine.begin() as conn:  # a transaction, so SET LOCAL applies only here
        # keep scanning HNSW until enough rows pass the tenant filter (pgvector >= 0.8)
        await conn.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))
        rows = await conn.execute(sql, params)
        return [dict(r._mapping) for r in rows]


def build_keyword_sql(
    *,
    source_types: list[str] | None = None,
    service: str | None = None,
    time_from: datetime | None = None,
    time_to: datetime | None = None,
):
    """Full-text query on the generated content_tsv column (GIN index, migration 0003).

    websearch_to_tsquery parses Google-like syntax and never raises on user input: plain words are
    ANDed, "or" gives OR, "-word" excludes, "quoted phrase" matches a phrase. Same 'english' config as
    the column, so the query is stemmed the same way as the documents.
    """
    where = _where(source_types=source_types, service=service, time_from=time_from, time_to=time_to)
    return text(f"""
        SELECT {_RESULT_COLUMNS},
               ts_rank(content_tsv, query) AS rank
        FROM worker.chunks, websearch_to_tsquery('english', :q) AS query
        WHERE {where}
          AND content_tsv @@ query
        ORDER BY rank DESC, id                                  -- id: deterministic order for equal ranks
        LIMIT :k
    """)


async def keyword_search(
    engine: AsyncEngine,
    *,
    tenant_id: str,
    query: str,                              # websearch syntax, e.g. 'HikariPool or "connection pool"'
    k: int = 5,
    source_types: list[str] | None = None,
    service: str | None = None,
    time_from: datetime | None = None,
    time_to: datetime | None = None,
) -> list[dict]:
    """Same result keys as search_chunks, with "rank" (ts_rank, higher = better) instead of "distance"."""
    sql = build_keyword_sql(source_types=source_types, service=service, time_from=time_from, time_to=time_to)
    params = _params(tenant_id, k, source_types, service, time_from, time_to)
    params["q"] = query
    async with engine.connect() as conn:
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
