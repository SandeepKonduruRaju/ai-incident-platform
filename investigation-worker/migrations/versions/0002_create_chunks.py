"""Enable pgvector and create worker.chunks (evidence text + embedding for retrieval).

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-17

Plain SQL instead of op.create_table: the vector(384) column type comes from the pgvector
extension, and SQLAlchemy only knows it with the extra `pgvector` Python package, which this
plumbing step does not need yet.
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Extensions are per database, not per schema. IF NOT EXISTS: safe if another schema or a
    # previous run already enabled it. Needs a role allowed to create extensions (ours is the owner).
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.execute(
        """
        CREATE TABLE worker.chunks (
            id          UUID        PRIMARY KEY,
            tenant_id   TEXT        NOT NULL,
            source_type TEXT        NOT NULL
                        CHECK (source_type IN ('log', 'metric', 'runbook', 'incident')),
            service     TEXT,
            source_id   TEXT        NOT NULL,   -- e.g. RB-acme-db_pool_exhausted
            chunk_index INT         NOT NULL,   -- position of this chunk inside its source document
            ts          TIMESTAMPTZ,            -- when the evidence happened (logs, metrics, incidents)
            content     TEXT        NOT NULL,
            embedding   vector(384) NOT NULL,   -- 384 dimensions = the size of the planned embedding model
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )

    # HNSW (Hierarchical Navigable Small World): an approximate nearest-neighbour graph index.
    # Without it, "ORDER BY embedding <=> :query LIMIT k" compares the query with EVERY row.
    # vector_cosine_ops makes the index serve the cosine-distance operator <=>; it only helps
    # queries that use that same operator. HNSW vs IVFFlat: better recall/speed trade-off and no
    # training step, so it can be built on an empty table; costs more memory and slower inserts.
    op.execute(
        "CREATE INDEX ix_chunks_embedding_hnsw ON worker.chunks USING hnsw (embedding vector_cosine_ops)"
    )

    # B-tree for the filters every search applies first: one tenant only (tenant isolation) and
    # usually one evidence type ("runbooks for acme"). tenant_id first because it is always present.
    op.execute("CREATE INDEX ix_chunks_tenant_source_type ON worker.chunks (tenant_id, source_type)")


def downgrade() -> None:
    op.execute("DROP TABLE worker.chunks")
    # The extension is left in place: other schemas in this database may use it.
