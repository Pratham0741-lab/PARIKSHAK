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
        print(f"[*] Database is empty. Seeding {settings.DEFAULT_NUM_LOTS} lots x {settings.DEFAULT_COMPONENTS_PER_LOT} parts "
              f"({settings.DEFAULT_GENERATOR} generator, seed {settings.SYNTHETIC_RANDOM_SEED})...", flush=True)
        res = subprocess.run([
            sys.executable,
            "data_engine/seed_db.py",
            "--lots", str(settings.DEFAULT_NUM_LOTS),
            "--components", str(settings.DEFAULT_COMPONENTS_PER_LOT),
            "--seed", str(settings.SYNTHETIC_RANDOM_SEED),
            "--generator", settings.DEFAULT_GENERATOR,
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


def ensure_judge_model() -> None:
    """Train the judge-mode model from examples/judge/train.csv if none is active (fresh volume)."""
    from pathlib import Path

    from backend.app.api.v1.judge import judge_dir, models_dir, pretrained_for
    from backend.app.core.config import settings
    from data_engine.tabular import read_table
    from evaluation.cost import CostConfig
    from ml_engine import judge

    latest = models_dir() / "latest.pkl"
    if latest.exists():
        jm = judge.JudgeModel.load_active(models_dir())  # verifies checksum + self-test; raises with a clear reason
        b = jm.info["bundle"]
        print(f"[+] Loaded model bundle {b['bundle_id']} ({latest}): trained on {b['source_file']}, "
              f"{b['n_parts']} parts, {b['n_lots']} lots" + (f"; version mismatch: {b['version_mismatch']}" if b["version_mismatch"] else ""), flush=True)
        return
    src = Path(__file__).resolve().parent.parent / "examples" / "judge" / "train.csv"
    if not src.exists():
        print(f"[!] No judge model and no {src}; judge mode needs a /judge/train upload.", flush=True)
        return
    print(f"[*] Training the judge-mode model from {src.name}...", flush=True)
    table = read_table(src.read_bytes().decode("utf-8"))  # bytes: the stored hash must equal sha256(file)
    jm, oof, _ = judge.train(table, src.name, CostConfig.from_settings(), pretrained=pretrained_for(table.params),
                             max_flag_rate=settings.JUDGE_MAX_FLAG_RATE)
    saved = jm.save(models_dir())
    print(f"[+] Saved model bundle {saved} (+ latest.pkl)", flush=True)
    judge_dir().mkdir(parents=True, exist_ok=True)
    oof.to_csv(judge_dir() / "train_oof_predictions.csv", index=False)
    print(f"[+] Judge model trained on {src.name}: {jm.info['n_parts']} parts, {jm.info['n_lots']} lots; "
          f"path: {jm.info['path']}", flush=True)
    for line in jm.info["banner"]:
        print(f"    guard: {line}", flush=True)


def start_api_server() -> None:
    """Starts the FastAPI production server using Uvicorn."""
    print("[*] Starting Uvicorn FastAPI server on 0.0.0.0:8000...", flush=True)
    import uvicorn
    uvicorn.run("backend.app.main:app", host="0.0.0.0", port=8000, reload=False)


def main() -> None:
    wait_for_postgres()
    run_alembic_migrations()
    check_and_seed_database()
    ensure_judge_model()

    # If --no-server is passed, exit cleanly after initialization
    if "--no-server" in sys.argv:
        print("[+] Bootstrap initialization completed without starting server.", flush=True)
        return

    start_api_server()


if __name__ == "__main__":
    main()
