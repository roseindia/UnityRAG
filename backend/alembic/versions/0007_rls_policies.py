"""RLS policies and grants for groups 03-06

Revision ID: 0007
Revises: 0006
"""
from alembic import op  # noqa: F401
from sqlfile import run_sql_file

revision = "0007"
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("07_rls_policies.sql")


def downgrade() -> None:
    raise NotImplementedError("Forward-only migration: restore from backup or write a compensating revision.")
