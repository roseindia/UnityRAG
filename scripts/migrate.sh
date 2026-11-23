#!/usr/bin/env bash
# Bootstrap roles/database/extensions (superuser, idempotent) and apply Alembic migrations as rag_migration.
set -euo pipefail
cd "$(dirname "$0")/../backend"
[ -d ../.venv ] && . ../.venv/bin/activate
python -m app.database.bootstrap
alembic upgrade head
echo "Database is at revision: $(alembic current 2>/dev/null | tail -1)"
