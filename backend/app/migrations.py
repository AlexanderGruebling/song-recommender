"""Minimal, deterministic database migrations.

Schema version is tracked in the ``schema_version`` table. Migrations are a
numbered list of SQL statements applied inside transactions. This keeps the
single-user SQLite install simple while still allowing schema evolution.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import Engine, text

logger = logging.getLogger(__name__)

# Each migration is a list of SQL statements. Never edit an applied migration;
# append a new one instead.
MIGRATIONS: list[list[str]] = [
    # 1: initial schema
    [
        """
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            applied_at DATETIME NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS charts (
            id INTEGER PRIMARY KEY,
            source_url VARCHAR(512) NOT NULL UNIQUE,
            title VARCHAR(300) NOT NULL,
            chart_date VARCHAR(10),
            discovered_at DATETIME NOT NULL
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS ix_charts_source_url ON charts (source_url)
        """,
        """
        CREATE TABLE IF NOT EXISTS chart_entries (
            id INTEGER PRIMARY KEY,
            chart_id INTEGER NOT NULL REFERENCES charts(id) ON DELETE CASCADE,
            rank INTEGER NOT NULL,
            artist VARCHAR(300) NOT NULL,
            title VARCHAR(300) NOT NULL,
            previous_rank VARCHAR(20),
            weeks_in_chart VARCHAR(20),
            movement VARCHAR(20),
            song_key VARCHAR(512) NOT NULL,
            CONSTRAINT uq_chart_rank UNIQUE (chart_id, rank)
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS ix_chart_entries_chart_id
        ON chart_entries (chart_id)
        """,
        """
        CREATE INDEX IF NOT EXISTS ix_chart_entries_song_key
        ON chart_entries (song_key)
        """,
        """
        CREATE TABLE IF NOT EXISTS youtube_search_results (
            id INTEGER PRIMARY KEY,
            entry_id INTEGER NOT NULL REFERENCES chart_entries(id) ON DELETE CASCADE,
            query VARCHAR(512) NOT NULL,
            video_id VARCHAR(64) NOT NULL,
            video_title VARCHAR(500) NOT NULL,
            channel VARCHAR(300) NOT NULL,
            channel_id VARCHAR(100),
            thumbnail_url TEXT,
            duration_seconds INTEGER,
            video_url VARCHAR(600) NOT NULL,
            published_at VARCHAR(32),
            search_timestamp DATETIME NOT NULL,
            rank INTEGER NOT NULL DEFAULT 0,
            CONSTRAINT uq_entry_video UNIQUE (entry_id, video_id)
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS ix_youtube_search_results_entry_id
        ON youtube_search_results (entry_id)
        """,
        """
        CREATE TABLE IF NOT EXISTS downloads (
            id INTEGER PRIMARY KEY,
            entry_id INTEGER NOT NULL REFERENCES chart_entries(id) ON DELETE CASCADE,
            video_id VARCHAR(64) NOT NULL,
            video_url VARCHAR(600) NOT NULL,
            video_title VARCHAR(500) NOT NULL,
            status VARCHAR(20) NOT NULL,
            output_path TEXT,
            progress INTEGER NOT NULL DEFAULT 0,
            error TEXT,
            started_at DATETIME,
            finished_at DATETIME,
            created_at DATETIME NOT NULL
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS ix_downloads_entry_id ON downloads (entry_id)
        """,
        """
        CREATE INDEX IF NOT EXISTS ix_downloads_status ON downloads (status)
        """,
        """
        CREATE TABLE IF NOT EXISTS app_state (
            key VARCHAR(64) PRIMARY KEY,
            value TEXT NOT NULL DEFAULT ''
        )
        """,
    ],
]


def migrate(engine: Engine) -> None:
    """Apply all pending migrations and create the version table if needed."""
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS schema_version "
                "(version INTEGER PRIMARY KEY, applied_at DATETIME NOT NULL)"
            )
        )
        current = conn.execute(
            text("SELECT COALESCE(MAX(version), 0) FROM schema_version")
        ).scalar()

        for version, statements in enumerate(MIGRATIONS, start=1):
            if version <= current:
                continue
            logger.info("Applying schema migration %s", version)
            for statement in statements:
                conn.execute(text(statement))
            conn.execute(
                text(
                    "INSERT INTO schema_version (version, applied_at) "
                    "VALUES (:version, :applied_at)"
                ),
                {
                    "version": version,
                    "applied_at": datetime.now(timezone.utc),
                },
            )


def current_version(engine: Engine) -> int:
    with engine.connect() as conn:
        return conn.execute(text("SELECT COALESCE(MAX(version), 0) FROM schema_version")).scalar()