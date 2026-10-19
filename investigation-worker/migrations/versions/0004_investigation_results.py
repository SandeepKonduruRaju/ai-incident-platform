"""Store the LLM investigation outcome on worker.investigations.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-19

status: PENDING -> RUNNING -> COMPLETED | FAILED (a CHECK constraint; existing PENDING rows stay valid).
result / evidence: JSONB, because the result shape is owned by app/schemas.py and evolves with the
prompt version; we read it whole, never query inside it (yet).
run_count: incremented by every claim. It is the fencing token (like JPA's @Version): a save only
succeeds for the run that holds the latest claim, so a stale run can never overwrite a newer one.
attempts: LLM output attempts of the latest run (1 = first answer valid, 2 = needed a repair).
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

SCHEMA = "worker"
TABLE = "investigations"
STATUSES = ("PENDING", "RUNNING", "COMPLETED", "FAILED")

_COLUMNS = [
    # The incident as received (title, description, service, createdAt): app.rerun needs it to run
    # an investigation again without the original Kafka event. NULL for rows created before 0004.
    sa.Column("incident", postgresql.JSONB(), nullable=True),
    sa.Column("result", postgresql.JSONB(), nullable=True),
    sa.Column("evidence", postgresql.JSONB(), nullable=True),
    sa.Column("failure_reason", sa.Text(), nullable=True),
    sa.Column("prompt_version", sa.Text(), nullable=True),
    sa.Column("model", sa.Text(), nullable=True),
    sa.Column("input_tokens", sa.Integer(), nullable=True),
    sa.Column("output_tokens", sa.Integer(), nullable=True),
    sa.Column("llm_latency_ms", sa.Integer(), nullable=True),
    sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("run_count", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
]


def upgrade() -> None:
    for column in _COLUMNS:
        op.add_column(TABLE, column, schema=SCHEMA)
    op.create_check_constraint(
        "ck_investigations_status",
        TABLE,
        "status IN (" + ", ".join(f"'{status}'" for status in STATUSES) + ")",
        schema=SCHEMA,
    )
    # "Re-run everything FAILED / PENDING" (app.rerun) filters on status.
    op.create_index("ix_investigations_status", TABLE, ["status"], schema=SCHEMA)


def downgrade() -> None:
    op.drop_index("ix_investigations_status", table_name=TABLE, schema=SCHEMA)
    op.drop_constraint("ck_investigations_status", TABLE, schema=SCHEMA, type_="check")
    for column in reversed(_COLUMNS):
        op.drop_column(TABLE, column.name, schema=SCHEMA)
