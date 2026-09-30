#!/usr/bin/env python3
"""
Runs the backend (FastAPI on :8000) and the frontend (Vite on :8080) together for local development.

    python scripts/dev.py            # or: make dev

Prerequisites: PostgreSQL reachable per .env (e.g. `docker compose up -d burnin_postgres`), the
database seeded and screened (`make seed`), and `npm ci` run once in frontend/.
The frontend reads VITE_API_URL (default http://localhost:8000/api/v1); the backend allows the
origins in CORS_ORIGINS (default includes localhost:8080).
"""

import os
import subprocess
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
NPM = "npm.cmd" if os.name == "nt" else "npm"


def main() -> int:
    procs = [
        subprocess.Popen([sys.executable, "-m", "uvicorn", "backend.app.main:app", "--port", "8000", "--reload"], cwd=ROOT),
        subprocess.Popen([NPM, "run", "dev", "--", "--port", "8080", "--strictPort"], cwd=os.path.join(ROOT, "frontend")),
    ]
    print("backend:  http://localhost:8000/docs\nfrontend: http://localhost:8080  (Ctrl+C stops both)", flush=True)
    try:
        while all(p.poll() is None for p in procs):
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        for p in procs:
            if p.poll() is None:
                p.terminate()
        for p in procs:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
    return max(p.returncode or 0 for p in procs)


if __name__ == "__main__":
    sys.exit(main())
