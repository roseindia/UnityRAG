"""Tenant AI/RAG configuration, prompts, guardrail events, model usage

Revision ID: 0010
Revises: 0009
"""
from alembic import op  # noqa: F401
from sqlfile import run_sql_file

revision = "0010"
down_revision = '0009'
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("10_ai_configuration.sql")


def downgrade() -> None:
    raise NotImplementedError("Forward-only migration: restore from backup or write a compensating revision.")
