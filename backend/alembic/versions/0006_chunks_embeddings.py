"""Document chunks, embeddings, ACL propagation

Revision ID: 0006
Revises: 0005
"""
from alembic import op  # noqa: F401
from sqlfile import run_sql_file

revision = "0006"
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("06_chunks_embeddings.sql")


def downgrade() -> None:
    raise NotImplementedError("Forward-only migration: restore from backup or write a compensating revision.")
