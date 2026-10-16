"""Create processed_events and investigations in the worker schema.

Revision ID: 0001
Revises:
Create Date: 2026-10-16
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

SCHEMA = "worker"


def upgrade() -> None:
    # Idempotency record: one row per eventId we have handled.
    op.create_table(
        "processed_events",
        sa.Column("event_id", sa.Uuid(), primary_key=True),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
        schema=SCHEMA,
    )
    op.create_table(
        "investigations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("incident_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("request_id", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_investigations_tenant_incident", "investigations", ["tenant_id", "incident_id"], schema=SCHEMA
    )


def downgrade() -> None:
    op.drop_index("ix_investigations_tenant_incident", table_name="investigations", schema=SCHEMA)
    op.drop_table("investigations", schema=SCHEMA)
    op.drop_table("processed_events", schema=SCHEMA)
