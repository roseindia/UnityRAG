"""Identity and access control

Revision ID: 0004
Revises: 0003
"""
from alembic import op  # noqa: F401
from sqlfile import run_sql_file

revision = "0004"
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("04_identity_access.sql")


def downgrade() -> None:
    raise NotImplementedError("Forward-only migration: restore from backup or write a compensating revision.")
