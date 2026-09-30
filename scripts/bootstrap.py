#!/usr/bin/env python3
"""
Automated Initialization & Bootstrap Routine for ISRO SIH26170.
1. Waits for PostgreSQL database readiness.
2. Applies Alembic schema migrations to head.
3. Checks if component readings exist; seeds 10 lots / 1,000 components if empty.
4. Generates initial Module A/B screening predictions and triage verdicts if empty.
5. Launches FastAPI Uvicorn server on port 8000.
"""

import os
import subprocess
import sys
import time

from sqlalchemy import create_engine, text

# Add workspace root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.app.core.config import settings


def wait_for_postgres(max_retries: int = 30, delay_sec: int = 2) -> None:
    """Blocks until PostgreSQL is reachable and accepts queries."""
    print(f"[*] Connecting to PostgreSQL at {settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}...", flush=True)
    engine = create_engine(settings.sync_database_url, connect_args={"connect_timeout": 5})

    for attempt in range(1, max_retries + 1):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            print("[+] PostgreSQL database is ready!", flush=True)
            return
        except Exception as exc:
            print(f"[!] PostgreSQL not ready yet (attempt {attempt}/{max_retries}): {exc}", flush=True)
            time.sleep(delay_sec)

    print("[FATAL] Could not connect to PostgreSQL after multiple attempts.", flush=True)
    sys.exit(1)


def run_alembic_migrations() -> None:
    """Executes database schema migrations up to head."""
    print("[*] Running Alembic schema migrations (upgrade head)...", flush=True)
    res = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"])
    if res.returncode != 0:
        print("[FATAL] Alembic migration failed.", flush=True)
        sys.exit(res.returncode)
    print("[+] Database schema up to date.", flush=True)


def check_and_seed_database() -> None:
    """Seeds synthetic burn-in components and baseline readings if empty."""
    engine = create_engine(settings.sync_database_url)
    with engine.connect() as conn:
        comp_count = conn.execute(text("SELECT COUNT(*) FROM components")).scalar() or 0
        pred_count = conn.execute(text("SELECT COUNT(*) FROM model_predictions")).scalar() or 0

    print(f"[*] Current database state: {comp_count} components, {pred_count} model predictions.", flush=True)

    if comp_count == 0:
        print("[*] Database is empty. Seeding 10 lots with 1,000 components and 4,000 readings...", flush=True)
        res = subprocess.run([
            sys.executable,
            "data_engine/seed_db.py",
            "--lots", "10",
            "--components", "100",
            "--seed", "42",
        ])
        if res.returncode != 0:
            print("[FATAL] Database seeding failed.", flush=True)
            sys.exit(res.returncode)
        print("[+] Seed completed successfully.", flush=True)

    from backend.app.services.screening_service import artifact_path

    missing_artifact = not artifact_path().exists()
    if missing_artifact:
        print(f"[*] No trained model artifact at {artifact_path()}; screening will (re)train it.", flush=True)
    if pred_count == 0 or comp_count == 0 or missing_artifact:
        print("[*] Running Module A and Module B screening inference pipeline...", flush=True)
        res = subprocess.run([sys.executable, "ml_engine/run_screening.py"])
        if res.returncode != 0:
            print("[FATAL] Model screening pipeline failed.", flush=True)
            sys.exit(res.returncode)
        print("[+] Initial predictions and triage verdicts populated.", flush=True)


def start_api_server() -> None:
    """Starts the FastAPI production server using Uvicorn."""
    print("[*] Starting Uvicorn FastAPI server on 0.0.0.0:8000...", flush=True)
    import uvicorn
    uvicorn.run("backend.app.main:app", host="0.0.0.0", port=8000, reload=False)


def main() -> None:
    wait_for_postgres()
    run_alembic_migrations()
    check_and_seed_database()

    # If --no-server is passed, exit cleanly after initialization
    if "--no-server" in sys.argv:
        print("[+] Bootstrap initialization completed without starting server.", flush=True)
        return

    start_api_server()


if __name__ == "__main__":
    main()
