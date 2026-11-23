"""Schemas, security-context helpers, platform and tenant entities

Revision ID: 0003
Revises: 0002
"""
from alembic import op  # noqa: F401
from sqlfile import run_sql_file

revision = "0003"
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("03_platform_tenant.sql")


def downgrade() -> None:
    raise NotImplementedError("Forward-only migration: restore from backup or write a compensating revision.")
