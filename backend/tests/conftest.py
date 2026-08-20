"""Shared pytest fixtures.

The app uses a global engine/session; for tests we point the engine at a
temporary SQLite database before importing the application modules.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# Point the app at a throwaway database before anything imports it.
_tmpdir = Path(tempfile.mkdtemp(prefix="fm4test-"))
os.environ["DATA_DIR"] = str(_tmpdir)
os.environ["DOWNLOAD_DIRECTORY"] = str(_tmpdir / "music")
os.environ["YOUTUBE_API_KEY"] = ""
os.environ["FM4_POLL_INTERVAL"] = "0"

from backend.app.db import get_engine, init_db  # noqa: E402
from backend.app.db import get_session  # noqa: E402
from sqlalchemy import text


@pytest.fixture(autouse=True)
def fresh_db():
    init_db()
    yield
    with get_engine().begin() as conn:
        for statement in (
            "DELETE FROM youtube_search_results",
            "DELETE FROM downloads",
            "DELETE FROM chart_entries",
            "DELETE FROM charts",
        ):
            conn.execute(text(statement))


@pytest.fixture
def session(fresh_db):
    """A session that is always rolled back/closed after the test, so it never
    holds a write lock that would block the fresh_db cleanup."""
    session = get_session()
    yield session
    session.close()


def load_fixture(name: str) -> str:
    path = Path(__file__).parent / "fixtures" / name
    return path.read_text(encoding="utf-8")