"""Narrow SECURITY DEFINER authentication functions

Revision ID: 0013
Revises: 0012
"""
from alembic import op  # noqa: F401
from sqlfile import run_sql_file

revision = "0013"
down_revision = '0012'
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("13_security_functions.sql")


def downgrade() -> None:
    raise NotImplementedError("Forward-only migration: restore from backup or write a compensating revision.")
