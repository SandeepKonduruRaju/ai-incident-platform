"""The worker's own tables, in its own "worker" schema (incident-service owns "public").

SQLAlchemy Core (tables + SQL expressions), not the ORM: closer to JdbcTemplate than to JPA.
The schema itself is created by the Alembic migrations in migrations/ (Alembic ~ Flyway).
"""

from sqlalchemy import Column, DateTime, Index, Integer, MetaData, String, Table, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

SCHEMA = "worker"

metadata = MetaData(schema=SCHEMA)

# One row per event we have handled: the idempotency record (eventId is the primary key).
processed_events = Table(
    "processed_events",
    metadata,
    Column("event_id", Uuid, primary_key=True),
    Column("event_type", String(100), nullable=False),
    Column("processed_at", DateTime(timezone=True), nullable=False),
)

investigations = Table(
    "investigations",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("incident_id", Uuid, nullable=False),
    Column("tenant_id", String(64), nullable=False),
    Column("status", String(20), nullable=False),  # PENDING | RUNNING | COMPLETED | FAILED (0004) | SUPERSEDED (0005)
    Column("request_id", String(255)),
    Column("created_at", DateTime(timezone=True), nullable=False),
    # --- migration 0004: the investigation input and outcome ---
    Column("incident", JSONB),
    Column("result", JSONB),
    Column("evidence", JSONB),
    Column("failure_reason", Text),
    Column("prompt_version", Text),
    Column("model", Text),
    Column("input_tokens", Integer),
    Column("output_tokens", Integer),
    Column("llm_latency_ms", Integer),
    Column("attempts", Integer, nullable=False, server_default="0"),
    Column("run_count", Integer, nullable=False, server_default="0"),
    Column("started_at", DateTime(timezone=True)),
    Column("completed_at", DateTime(timezone=True)),
    Index("ix_investigations_tenant_incident", "tenant_id", "incident_id"),
)


def create_engine(database_url: str) -> AsyncEngine:
    # pool_pre_ping: check a pooled connection is alive before using it (survives DB restarts).
    # timeout / command_timeout: fail fast instead of hanging, so the error is classified as transient.
    return create_async_engine(
        database_url,
        pool_pre_ping=True,
        connect_args={"timeout": 5, "command_timeout": 10},
    )
