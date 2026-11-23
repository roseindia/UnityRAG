#!/usr/bin/env bash
# start.sh            -> full stack with Docker Compose
# start.sh --local    -> API + worker + scheduler from the virtualenv (PostgreSQL/Redis must be running)
set -euo pipefail
cd "$(dirname "$0")/.."
if [ "${1:-}" = "--local" ]; then
  . .venv/bin/activate
  cd backend
  celery -A app.workers.celery_app worker -Q ingestion,maintenance --loglevel=INFO --concurrency=2 &
  celery -A app.workers.celery_app beat --loglevel=INFO --schedule /tmp/celerybeat-schedule &
  trap 'kill $(jobs -p)' EXIT
  uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
else
  [ -f backend/.env ] || cp backend/.env.example backend/.env
  docker compose up -d --build
  echo "API: http://localhost:8000/docs  (via Nginx: http://localhost:8080)"
  echo "Create the first platform admin: docker compose exec api python -m app.cli create-platform-admin --email you@example.com"
fi
