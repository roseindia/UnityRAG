"""Evaluation datasets, runs and results

Revision ID: 0012
Revises: 0011
"""
from alembic import op  # noqa: F401
from sqlfile import run_sql_file

revision = "0012"
down_revision = '0011'
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("12_evaluation.sql")


def downgrade() -> None:
    raise NotImplementedError("Forward-only migration: restore from backup or write a compensating revision.")
