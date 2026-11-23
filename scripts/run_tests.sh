#!/usr/bin/env bash
# Runs the full suite against a real PostgreSQL (database rag_pytest is dropped and recreated).
#   TEST_DB_SUPERUSER_DSN="host=localhost user=postgres password=postgres dbname=postgres" scripts/run_tests.sh
set -euo pipefail
cd "$(dirname "$0")/../backend"
python -m pytest tests -q -p no:cacheprovider "$@"
