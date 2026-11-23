"""Hash-chained audit log and analytics aggregates

Revision ID: 0011
Revises: 0010
"""
from alembic import op  # noqa: F401
from sqlfile import run_sql_file

revision = "0011"
down_revision = '0010'
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("11_audit_analytics.sql")


def downgrade() -> None:
    raise NotImplementedError("Forward-only migration: restore from backup or write a compensating revision.")
