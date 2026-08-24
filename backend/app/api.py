"""HTTP API endpoints."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .config import get_settings
from .db import request_session
from .models import Chart, ChartEntry, Download, YouTubeResult
from .schemas import (
    ChartDetailOut,
    ChartEntryOut,
    ChartOut,
    DownloadOut,
    DownloadRequestIn,
    DownloadsSummary,
    RefreshResult,
    SongOut,
    YouTubeResultOut,
)
from .services.downloader import DownloadManager, DownloadRequest
from .services.youtube import (
    YouTubeError,
    YouTubeNotConfigured,
    YouTubeQuotaExceeded,
)
from .services.youtube_service import YouTubeSearchService, youtube_search_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


def get_download_manager(request: Request) -> DownloadManager:
    state = getattr(request.app.state, "fm4_state", None)
    if state is None:
        raise HTTPException(status_code=503, detail="Download manager not initialized")
    return state.download_manager


def get_youtube_service():
    return youtube_search_service()


def _chart_query():
    return (
        select(Chart)
        .options(selectinload(Chart.entries))
        .order_by(Chart.chart_date.desc().nullslast(), Chart.discovered_at.desc())
    )


def _load_entry(session: Session, entry_id: int) -> ChartEntry:
    entry = session.get(ChartEntry, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Song not found")
    return entry


def _latest_download(session: Session, entry_id: int) -> Download | None:
    return session.scalars(
        select(Download)
        .where(Download.entry_id == entry_id)
        .order_by(Download.created_at.desc())
    ).first()


def _entry_status(session: Session, entry: ChartEntry) -> tuple[str | None, float, bool]:
    """Return (download_status, progress, file_exists) for a chart entry."""
    download = _latest_download(session, entry.id)
    if download is None:
        return None, 0.0, False
    exists = bool(download.output_path) and Path(download.output_path).is_file()
    return download.status, download.progress / 100.0, exists


def _entry_out(session: Session, entry: ChartEntry) -> ChartEntryOut:
    status, progress, exists = _entry_status(session, entry)
    return ChartEntryOut(
        id=entry.id,
        rank=entry.rank,
        artist=entry.artist,
        title=entry.title,
        previous_rank=entry.previous_rank,
        weeks_in_chart=entry.weeks_in_chart,
        movement=entry.movement,
        download_status=status,
        download_progress=progress,
        file_exists=exists,
    )


def _youtube_out(result: YouTubeResult) -> YouTubeResultOut:
    return YouTubeResultOut(
        id=result.id,
        rank=result.rank,
        video_id=result.video_id,
        video_title=result.video_title,
        channel=result.channel,
        channel_id=result.channel_id,
        thumbnail_url=result.thumbnail_url,
        duration_seconds=result.duration_seconds,
        video_url=result.video_url,
        published_at=result.published_at,
        query=result.query,
        search_timestamp=result.search_timestamp,
        download_status=None,
    )


# -- charts --------------------------------------------------------


@router.get("/charts", response_model=list[ChartOut])
def list_charts(
    session: Session = Depends(request_session),
    limit: int = Query(200, ge=1, le=1000),
):
    charts = session.scalars(_chart_query().limit(limit)).all()
    result = []
    for chart in charts:
        total = len(chart.entries)
        completed = sum(
            1
            for e in chart.entries
            if _entry_status(session, e)[0] == Download.STATUS_COMPLETED
        )
        result.append(
            ChartOut(
                id=chart.id,
                title=chart.title,
                chart_date=chart.chart_date,
                source_url=chart.source_url,
                discovered_at=chart.discovered_at,
                entry_count=total,
                downloads_completed=completed,
                downloads_total=total,
            )
        )
    return result


@router.get("/charts/{chart_id}", response_model=ChartDetailOut)
def get_chart(
    chart_id: int,
    session: Session = Depends(request_session),
):
    chart = session.get(Chart, chart_id, options=[selectinload(Chart.entries)])
    if chart is None:
        raise HTTPException(status_code=404, detail="Chart not found")
    entries = [_entry_out(session, e) for e in sorted(chart.entries, key=lambda e: e.rank)]
    completed = sum(1 for e in entries if e.download_status == Download.STATUS_COMPLETED)
    return ChartDetailOut(
        id=chart.id,
        title=chart.title,
        chart_date=chart.chart_date,
        source_url=chart.source_url,
        discovered_at=chart.discovered_at,
        entry_count=len(entries),
        downloads_completed=completed,
        downloads_total=len(entries),
        entries=entries,
    )


@router.post("/charts/refresh", response_model=RefreshResult)
async def refresh_charts_endpoint():
    from .tasks import refresh_once

    settings = get_settings()
    try:
        return await refresh_once(settings)
    except Exception as exc:
        logger.exception("Manual chart refresh failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc


# -- songs ---------------------------------------------------------


@router.get("/songs/{entry_id}", response_model=SongOut)
def get_song(
    entry_id: int,
    session: Session = Depends(request_session),
):
    entry = _load_entry(session, entry_id)
    chart = session.get(Chart, entry.chart_id)
    return SongOut(
        id=entry.id,
        rank=entry.rank,
        artist=entry.artist,
        title=entry.title,
        previous_rank=entry.previous_rank,
        weeks_in_chart=entry.weeks_in_chart,
        movement=entry.movement,
        chart_id=entry.chart_id,
        chart_title=chart.title if chart else "",
        chart_date=chart.chart_date if chart else None,
    )


@router.get("/songs/{entry_id}/youtube", response_model=list[YouTubeResultOut])
def get_song_youtube(
    entry_id: int,
    session: Session = Depends(request_session),
):
    _load_entry(session, entry_id)
    results = session.scalars(
        select(YouTubeResult)
        .where(YouTubeResult.entry_id == entry_id)
        .order_by(YouTubeResult.rank)
    ).all()
    return [_youtube_out(r) for r in results]


@router.post("/songs/{entry_id}/youtube/search", response_model=list[YouTubeResultOut])
async def search_song_youtube(
    entry_id: int,
    refresh: bool = Query(False),
    session: Session = Depends(request_session),
    service: YouTubeSearchService = Depends(get_youtube_service),
):
    entry = _load_entry(session, entry_id)
    try:
        results = await service.get_or_search(session, entry, refresh=refresh)
    except (YouTubeNotConfigured, YouTubeQuotaExceeded, YouTubeError) as exc:
        logger.error("YouTube search failed for entry %d: %s", entry_id, exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return [_youtube_out(r) for r in results]


@router.post("/songs/{entry_id}/download", response_model=DownloadOut)
async def download_song(
    entry_id: int,
    payload: DownloadRequestIn,
    session: Session = Depends(request_session),
    manager: DownloadManager = Depends(get_download_manager),
):
    entry = _load_entry(session, entry_id)
    result = session.get(YouTubeResult, payload.youtube_result_id)
    if result is None or result.entry_id != entry_id:
        raise HTTPException(status_code=404, detail="YouTube result not found")

    manager_settings = get_settings()
    async with manager.enqueue_lock:
        # Reject duplicate concurrent or completed downloads of the same song.
        # Runs under the manager's enqueue lock so a parallel request cannot
        # slip a duplicate in between check and queue.
        active = session.scalars(
            select(Download).where(
                Download.entry_id == entry_id,
                Download.status.in_(
                    [Download.STATUS_QUEUED, Download.STATUS_DOWNLOADING]
                ),
            )
        ).first()
        if active is not None:
            raise HTTPException(
                status_code=409,
                detail=f"Download already in progress (id={active.id})",
            )
        completed = session.scalars(
            select(Download).where(
                Download.entry_id == entry_id,
                Download.status == Download.STATUS_COMPLETED,
            )
        ).first()
        if completed is not None and completed.output_path and Path(completed.output_path).is_file():
            return DownloadOut.model_validate(completed)

        request = DownloadRequest(
            entry_id=entry_id,
            video_id=result.video_id,
            video_url=result.video_url,
            video_title=result.video_title,
            result_id=result.id,
            output_dir=Path(manager_settings.resolved_download_dir),
            artist=entry.artist,
            title=entry.title,
        )
        download = await manager.enqueue(request)
    return DownloadOut.model_validate(download)


# -- downloads -----------------------------------------------------


@router.get("/downloads", response_model=list[DownloadOut])
def list_downloads(
    session: Session = Depends(request_session),
    limit: int = Query(200, ge=1, le=1000),
):
    rows = session.scalars(
        select(Download).order_by(Download.created_at.desc()).limit(limit)
    ).all()
    return [DownloadOut.model_validate(r) for r in rows]


@router.get("/downloads/{download_id}", response_model=DownloadOut)
def get_download(
    download_id: int,
    session: Session = Depends(request_session),
):
    row = session.get(Download, download_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Download not found")
    return DownloadOut.model_validate(row)


@router.get("/downloads-summary", response_model=DownloadsSummary)
def downloads_summary(session: Session = Depends(request_session)):
    rows = session.scalars(select(Download)).all()
    summary = DownloadsSummary(
        total=len(rows), queued=0, downloading=0, completed=0, failed=0
    )
    for row in rows:
        if row.status == Download.STATUS_QUEUED:
            summary.queued += 1
        elif row.status == Download.STATUS_DOWNLOADING:
            summary.downloading += 1
        elif row.status == Download.STATUS_COMPLETED:
            summary.completed += 1
        elif row.status == Download.STATUS_FAILED:
            summary.failed += 1
    return summary