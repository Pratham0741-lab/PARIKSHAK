#!/usr/bin/env bash
# Judge rehearsal on a CLEAN stack: docker compose down -v && up --build, then scripts/judge_rehearsal.py.
# Usage: scripts/judge_rehearsal.sh [--reuse]   (--reuse: skip the reset and use the running stack)
# Exit code is non-zero if any step fails.
set -euo pipefail
cd "$(dirname "$0")/.."
if [ "${1:-}" != "--reuse" ]; then
  docker compose down -v
  docker compose up --build -d --wait
fi
PY=$(command -v python3 || command -v python)
exec "$PY" scripts/judge_rehearsal.py --api "${API_URL:-http://localhost:8000}"
