"""Tests run against an isolated database and artifact location (see tests/conftest.py)."""

import tempfile
from pathlib import Path

from backend.app.core.config import settings
from backend.app.core.database import async_engine, engine
from backend.app.services.screening_service import artifact_path
from tests.conftest import TEST_DB


def test_all_connections_point_at_the_test_database():
    assert settings.sync_database_url.endswith("/" + TEST_DB)
    assert engine.url.database == TEST_DB
    assert async_engine.url.database == TEST_DB


def test_model_artifact_is_written_outside_the_repository():
    p = artifact_path()
    assert Path(tempfile.gettempdir()).resolve() in p.resolve().parents
    assert p.exists()  # written by the session's screening run
