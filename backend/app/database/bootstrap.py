"""Cluster bootstrap: roles, database, extensions (superuser, run once per cluster).

    python -m app.database.bootstrap          # uses DB_SUPERUSER_DSN

Afterwards all schema changes run through Alembic as rag_migration
(`alembic upgrade head`), which never has superuser rights.
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

import psycopg
from psycopg import sql

from app.core.config import get_settings

log = logging.getLogger("bootstrap")
SQL_DIR = Path(__file__).resolve().parents[3] / "database" / "migrations"


def render_roles_sql(conn: psycopg.Connection) -> str:
    s = get_settings()
    text_ = (SQL_DIR / "02_roles.sql").read_text(encoding="utf-8")
    values = {
        "RAG_MIGRATION_PASSWORD": s.db_migration_password.get_secret_value(),
        "RAG_APP_PASSWORD": s.db_app_password.get_secret_value(),
        "RAG_WORKER_PASSWORD": s.db_worker_password.get_secret_value(),
        "RAG_READONLY_PASSWORD": s.db_readonly_password.get_secret_value(),
    }
    for key, value in values.items():
        text_ = text_.replace("{{" + key + "}}", sql.Literal(value).as_string(conn))
    return text_


def bootstrap(superuser_dsn: str, *, drop_existing: bool = False) -> None:
    s = get_settings()
    with psycopg.connect(superuser_dsn, autocommit=True) as su:
        su.execute(render_roles_sql(su))
        exists = su.execute("SELECT 1 FROM pg_database WHERE datname = %s", (s.db_name,)).fetchone()
        if exists and drop_existing:
            su.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(s.db_name)))
            exists = None
        if not exists:
            su.execute(sql.SQL("CREATE DATABASE {} OWNER rag_migration ENCODING 'UTF8'").format(sql.Identifier(s.db_name)))
            log.info("created database %s", s.db_name)
    target = psycopg.conninfo.make_conninfo(superuser_dsn, dbname=s.db_name)
    with psycopg.connect(target, autocommit=True) as db:
        db.execute((SQL_DIR / "01_extensions.sql").read_text(encoding="utf-8"))
        db.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(s.db_name)))
        db.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO rag_app, rag_worker, rag_readonly").format(
            sql.Identifier(s.db_name)))
    log.info("bootstrap complete for %s", s.db_name)


def main() -> None:
    logging.basicConfig(level="INFO")
    parser = argparse.ArgumentParser(description="Bootstrap PostgreSQL roles, database and extensions")
    parser.add_argument("--drop-existing", action="store_true", help="drop and recreate the database (dev/test only)")
    args = parser.parse_args()
    s = get_settings()
    if s.db_superuser_dsn is None:
        raise SystemExit("DB_SUPERUSER_DSN must be set for bootstrap")
    if args.drop_existing and s.environment == "production":
        raise SystemExit("--drop-existing is refused in production")
    bootstrap(s.db_superuser_dsn.get_secret_value(), drop_existing=args.drop_existing)


if __name__ == "__main__":
    main()
