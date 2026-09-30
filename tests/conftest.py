"""
Test isolation: every test runs against a dedicated database (default `burn_in_test_db`) that is
dropped, migrated, seeded (seed 42, 10 lots x 100 parts) and screened at the start of the session.
The development database is never written to; `pytest_sessionfinish` fails the run if its
inspector_reviews / audit_events row counts changed. The model artifact goes to a temp directory.

This module must configure the environment BEFORE any backend module binds its settings.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.core import config as _config  # noqa: E402

TEST_DB = os.environ.get("BURNIN_TEST_DB", "burn_in_test_db")
_DEV_SYNC_URL = _config.settings.sync_database_url
_DEV_DB = _DEV_SYNC_URL.rsplit("/", 1)[1]
if _DEV_DB == TEST_DB:
    raise RuntimeError("Refusing to run: the configured database already is the test database name.")
_TEST_SYNC_URL = _DEV_SYNC_URL.rsplit("/", 1)[0] + "/" + TEST_DB
_TEST_ASYNC_URL = _config.settings.async_database_url.rsplit("/", 1)[0] + "/" + TEST_DB
_ARTIFACT_DIR = tempfile.mkdtemp(prefix="burnin_test_artifacts_")

os.environ["DATABASE_URL"] = _TEST_SYNC_URL
os.environ["ASYNC_DATABASE_URL"] = _TEST_ASYNC_URL
os.environ["POSTGRES_DB"] = TEST_DB
os.environ["MODEL_ARTIFACT_PATH"] = str(Path(_ARTIFACT_DIR) / "screening_model.joblib")
_config.get_settings.cache_clear()
_config.settings = _config.get_settings()
assert _config.settings.sync_database_url.endswith("/" + TEST_DB)

import pytest  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

_GUARDED_TABLES = ("inspector_reviews", "audit_events", "components", "model_predictions")


def _dev_counts() -> dict:
    eng = create_engine(_DEV_SYNC_URL)
    out = {}
    try:
        with eng.connect() as c:
            for t in _GUARDED_TABLES:
                try:
                    out[t] = c.execute(text(f"SELECT count(*) FROM {t}")).scalar()
                except Exception:
                    c.rollback()
                    out[t] = None  # table may not exist in an older dev schema
    finally:
        eng.dispose()
    return out


def _recreate_test_database() -> None:
    admin = create_engine(_DEV_SYNC_URL.rsplit("/", 1)[0] + "/postgres", isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB}" WITH (FORCE)'))
        c.execute(text(f'CREATE DATABASE "{TEST_DB}"'))
    admin.dispose()


def pytest_configure(config):
    config._dev_db_counts_before = _dev_counts()


@pytest.fixture(scope="session", autouse=True)
def isolated_test_database():
    """Fresh test DB: migrate to head, seed deterministically, run the out-of-fold screening pipeline."""
    from alembic import command
    from alembic.config import Config

    _recreate_test_database()
    command.upgrade(Config(str(ROOT / "alembic.ini")), "head")

    from data_engine.seed_db import seed_database
    from ml_engine.run_screening import run_pipeline

    seed_database(num_lots=10, components_per_lot=100, random_seed=42)
    run_pipeline(persist=True)
    yield
    from backend.app.core.database import engine

    engine.dispose()


def pytest_sessionfinish(session, exitstatus):
    before = getattr(session.config, "_dev_db_counts_before", None)
    after = _dev_counts()
    if before is not None and before != after:
        session.exitstatus = 1
        print(f"\nDEV DATABASE WAS MODIFIED BY THE TEST RUN: before={before} after={after}")
    else:
        print(f"\nDev database '{_DEV_DB}' untouched by tests: {after}")
