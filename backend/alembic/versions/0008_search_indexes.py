"""Full-text, trigram, GIN and HNSW indexes

Revision ID: 0008
Revises: 0007
"""
from alembic import op  # noqa: F401
from sqlfile import run_sql_file

revision = "0008"
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("08_search_indexes.sql")


def downgrade() -> None:
    raise NotImplementedError("Forward-only migration: restore from backup or write a compensating revision.")
