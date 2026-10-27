"""Allow status SUPERSEDED on worker.investigations.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-27

SUPERSEDED: the event's request was replaced by a newer one for the same incident (a retry made while the original
event waited in a Kafka backlog), so it was never run and made no LLM call (see app/request_check.py). Terminal.
Downgrade: such rows become FAILED (with their reason kept), which 0004's CHECK allows.
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

SCHEMA = "worker"
TABLE = "investigations"
CONSTRAINT = "ck_investigations_status"
OLD_STATUSES = ("PENDING", "RUNNING", "COMPLETED", "FAILED")
NEW_STATUSES = (*OLD_STATUSES, "SUPERSEDED")


def _check(statuses: tuple[str, ...]) -> str:
    return "status IN (" + ", ".join(f"'{status}'" for status in statuses) + ")"


def upgrade() -> None:
    op.drop_constraint(CONSTRAINT, TABLE, schema=SCHEMA, type_="check")
    op.create_check_constraint(CONSTRAINT, TABLE, _check(NEW_STATUSES), schema=SCHEMA)


def downgrade() -> None:
    op.execute(f"UPDATE {SCHEMA}.{TABLE} SET status = 'FAILED' WHERE status = 'SUPERSEDED'")
    op.drop_constraint(CONSTRAINT, TABLE, schema=SCHEMA, type_="check")
    op.create_check_constraint(CONSTRAINT, TABLE, _check(OLD_STATUSES), schema=SCHEMA)
