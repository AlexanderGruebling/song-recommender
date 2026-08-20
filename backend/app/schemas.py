"""Pydantic response/request schemas.

These are the contract between the frontend and the API. Secrets are never
included.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ChartEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    rank: int
    artist: str
    title: str
    previous_rank: str | None
    weeks_in_chart: str | None
    movement: str | None
    download_status: str | None = None
    download_progress: float = 0.0
    file_exists: bool = False


class ChartOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    chart_date: str | None
    source_url: str
    discovered_at: datetime
    entry_count: int = 0
    downloads_completed: int = 0
    downloads_total: int = 0


class ChartDetailOut(ChartOut):
    entries: list[ChartEntryOut] = []


class YouTubeResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    rank: int
    video_id: str
    video_title: str
    channel: str
    channel_id: str | None
    thumbnail_url: str | None
    duration_seconds: int | None
    video_url: str
    published_at: str | None
    query: str
    search_timestamp: datetime
    download_status: str | None = None


class SongOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    rank: int
    artist: str
    title: str
    previous_rank: str | None
    weeks_in_chart: str | None
    movement: str | None
    chart_id: int
    chart_title: str = ""
    chart_date: str | None = None


class DownloadRequestIn(BaseModel):
    youtube_result_id: int


class DownloadOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    entry_id: int
    video_id: str
    video_url: str
    video_title: str
    status: str
    output_path: str | None
    progress: float
    error: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


class RefreshResult(BaseModel):
    discovered: int
    imported: int
    skipped: int
    errors: int


class DownloadsSummary(BaseModel):
    total: int
    queued: int
    downloading: int
    completed: int
    failed: int