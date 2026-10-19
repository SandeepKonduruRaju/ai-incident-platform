"""Full-text search on worker.chunks: a generated tsvector column + GIN index (keyword half of hybrid search).

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-19

Why: embeddings match meaning but are weak on exact tokens (error codes, "HikariPool", trace ids,
hostnames). PostgreSQL full-text search matches exactly those, so we combine both (hybrid retrieval).

GENERATED ALWAYS AS (...) STORED: PostgreSQL computes the column from content on every INSERT/UPDATE,
so ingest needs no change and the column can never drift from content. The 'english' config
lower-cases, drops stop words and stems ("timing" -> "time"); queries must use the same config.
IF NOT EXISTS / IF EXISTS: safe to re-run, like 0002's CREATE EXTENSION IF NOT EXISTS.
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Adding a STORED generated column rewrites the table once (fine for our size; on a huge table this
    # would need a maintenance window or a batched backfill of a normal column instead).
    op.execute(
        """
        ALTER TABLE worker.chunks
            ADD COLUMN IF NOT EXISTS content_tsv tsvector
            GENERATED ALWAYS AS (to_tsvector('english', content)) STORED
        """
    )
    # GIN (Generalized Inverted Index): word -> rows containing it, like a book index. Serves the @@ operator.
    op.execute("CREATE INDEX IF NOT EXISTS ix_chunks_content_tsv ON worker.chunks USING gin (content_tsv)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS worker.ix_chunks_content_tsv")
    op.execute("ALTER TABLE worker.chunks DROP COLUMN IF EXISTS content_tsv")
