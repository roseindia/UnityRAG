#!/usr/bin/env bash
# Local development setup (Linux / macOS).  Requires Python 3.12+, Docker (or a local PostgreSQL 16 + pgvector and Redis).
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -r backend/requirements-dev.txt
[ -f backend/.env ] || { cp backend/.env.example backend/.env; echo "Created backend/.env - edit secrets before use."; }
echo "Setup complete. Next: scripts/start.sh (Docker) or scripts/migrate.sh then run the API locally."
