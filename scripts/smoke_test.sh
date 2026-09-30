#!/usr/bin/env bash
# Smoke test against the running docker compose stack (see scripts/smoke_test.py for the checks).
# Usage: scripts/smoke_test.sh [API_URL]    (default http://localhost:8000; includes the restart check)
set -euo pipefail
cd "$(dirname "$0")/.."
PY=$(command -v python3 || command -v python)
exec "$PY" scripts/smoke_test.py --api "${1:-http://localhost:8000}" --restart
