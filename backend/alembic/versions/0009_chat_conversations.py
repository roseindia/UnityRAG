"""Conversations, messages, sources, feedback, search/retrieval logs

Revision ID: 0009
Revises: 0008
"""
from alembic import op  # noqa: F401
from sqlfile import run_sql_file

revision = "0009"
down_revision = '0008'
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("09_chat_conversations.sql")


def downgrade() -> None:
    raise NotImplementedError("Forward-only migration: restore from backup or write a compensating revision.")
