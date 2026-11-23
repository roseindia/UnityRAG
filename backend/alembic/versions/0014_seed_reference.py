"""Reference seed data

Revision ID: 0014
Revises: 0013
"""
from alembic import op  # noqa: F401
from sqlfile import run_sql_file

revision = "0014"
down_revision = '0013'
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("14_seed_reference.sql")


def downgrade() -> None:
    raise NotImplementedError("Forward-only migration: restore from backup or write a compensating revision.")
