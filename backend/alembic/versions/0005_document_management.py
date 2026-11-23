"""Collections, documents, versions, metadata, access, pages, ingestion

Revision ID: 0005
Revises: 0004
"""
from alembic import op  # noqa: F401
from sqlfile import run_sql_file

revision = "0005"
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("05_document_management.sql")


def downgrade() -> None:
    raise NotImplementedError("Forward-only migration: restore from backup or write a compensating revision.")
