"""Alembic environment: always connects as the migration role (rag_migration).

API and worker processes never receive these credentials (extension 2.3).
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # sqlfile helper

from alembic import context
from sqlalchemy import create_engine, pool

from app.core.config import get_settings

config = context.config


def run_migrations_online() -> None:
    engine = create_engine(get_settings().dsn("migration"), poolclass=pool.NullPool, future=True)
    with engine.connect() as connection:
        context.configure(connection=connection, transaction_per_migration=True,
                          version_table_schema="public")
        with context.begin_transaction():
            context.run_migrations()


def run_migrations_offline() -> None:
    context.configure(url=get_settings().dsn("migration"), literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
