"""Helper: run one of the versioned SQL files in database/migrations/.

The file is sent through the raw psycopg connection *without* parameters so
that literal '%' characters (format() patterns in PL/pgSQL) are not treated
as bind placeholders.  It runs inside Alembic's per-migration transaction.
"""
from __future__ import annotations

from pathlib import Path

from alembic import op

SQL_DIR = Path(__file__).resolve().parents[2] / "database" / "migrations"


def run_sql_file(name: str) -> None:
    sql = (SQL_DIR / name).read_text(encoding="utf-8")
    op.get_bind().connection.driver_connection.execute(sql)
