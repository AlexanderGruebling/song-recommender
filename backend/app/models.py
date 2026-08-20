"""SQLAlchemy models for the persistent store.

Schema is versioned through the lightweight migration runner in
``app.migrations`` rather than relying on ``create_all`` upgrades.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Chart(Base):
    __tablename__ = "charts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Stable source identifier, e.g. the FM4 story URL.
    source_url: Mapped[str] = mapped_column(String(512), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(300))
    chart_date: Mapped[str | None] = mapped_column(String(10))  # ISO date (YYYY-MM-DD)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    entries: Mapped[list["ChartEntry"]] = relationship(
        back_populates="chart",
        cascade="all, delete-orphan",
        order_by="ChartEntry.rank",
    )


class ChartEntry(Base):
    __tablename__ = "chart_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chart_id: Mapped[int] = mapped_column(
        ForeignKey("charts.id", ondelete="CASCADE"), index=True
    )
    rank: Mapped[int] = mapped_column(Integer)
    artist: Mapped[str] = mapped_column(String(300))
    title: Mapped[str] = mapped_column(String(300))
    # "neu" or a number; stored as text because FM4 uses the literal "neu".
    previous_rank: Mapped[str | None] = mapped_column(String(20))
    weeks_in_chart: Mapped[str | None] = mapped_column(String(20))
    movement: Mapped[str | None] = mapped_column(String(20))  # up / down / same / new
    # Normalized identity used to reuse YouTube caches across charts.
    song_key: Mapped[str] = mapped_column(String(512), index=True)

    chart: Mapped[Chart] = relationship(back_populates="entries")
    youtube_results: Mapped[list["YouTubeResult"]] = relationship(
        back_populates="entry", cascade="all, delete-orphan"
    )
    downloads: Mapped[list["Download"]] = relationship(
        back_populates="entry", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("chart_id", "rank", name="uq_chart_rank"),
    )


class YouTubeResult(Base):
    __tablename__ = "youtube_search_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entry_id: Mapped[int] = mapped_column(
        ForeignKey("chart_entries.id", ondelete="CASCADE"), index=True
    )
    query: Mapped[str] = mapped_column(String(512))
    video_id: Mapped[str] = mapped_column(String(64))
    video_title: Mapped[str] = mapped_column(String(500))
    channel: Mapped[str] = mapped_column(String(300))
    channel_id: Mapped[str | None] = mapped_column(String(100))
    thumbnail_url: Mapped[str | None] = mapped_column(Text)
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    video_url: Mapped[str] = mapped_column(String(600))
    published_at: Mapped[str | None] = mapped_column(String(32))
    search_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    rank: Mapped[int] = mapped_column(Integer, default=0)  # 1-based candidate rank

    entry: Mapped[ChartEntry] = relationship(back_populates="youtube_results")

    __table_args__ = (
        UniqueConstraint("entry_id", "video_id", name="uq_entry_video"),
    )


class Download(Base):
    __tablename__ = "downloads"

    # Stable statuses used by the UI and the downloader.
    STATUS_QUEUED = "queued"
    STATUS_DOWNLOADING = "downloading"
    STATUS_COMPLETED = "completed"
    STATUS_FAILED = "failed"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entry_id: Mapped[int] = mapped_column(
        ForeignKey("chart_entries.id", ondelete="CASCADE"), index=True
    )
    video_id: Mapped[str] = mapped_column(String(64))
    video_url: Mapped[str] = mapped_column(String(600))
    video_title: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), index=True)
    output_path: Mapped[str | None] = mapped_column(Text)
    progress: Mapped[float] = mapped_column(BigInteger, default=0)  # percent*100
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    entry: Mapped[ChartEntry] = relationship(back_populates="downloads")


class AppState(Base):
    __tablename__ = "app_state"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")


class SchemaVersion(Base):
    __tablename__ = "schema_version"

    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)