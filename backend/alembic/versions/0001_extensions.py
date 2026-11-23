"""PostgreSQL extensions (no-op when bootstrap already created them)

Revision ID: 0001
Revises: None
"""
from alembic import op  # noqa: F401

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    missing = [e for e in ("vector", "pg_trgm", "pgcrypto", "citext")
               if not bind.exec_driver_sql("SELECT 1 FROM pg_extension WHERE extname = %s", (e,)).fetchone()]
    if missing:
        raise RuntimeError(f"extensions {missing} missing - run `python -m app.database.bootstrap` as superuser first")


def downgrade() -> None:
    raise NotImplementedError("Forward-only migration: restore from backup or write a compensating revision.")
