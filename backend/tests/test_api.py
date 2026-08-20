"""API endpoint tests using an in-process ASGI transport."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backend.app.config import get_settings
from backend.app.db import init_db, session_scope
from backend.app.main import create_app
from backend.app.models import Chart, ChartEntry, Download, YouTubeResult
from backend.app.services.downloader import DownloadManager
from backend.app.tasks import Scheduler


@pytest_asyncio.fixture
async def client(tmp_path):
    settings = get_settings()
    init_db()
    app = create_app()
    # Wire up state without starting the network scheduler or download workers.
    app.state.fm4_state = type("S", (), {})()
    app.state.fm4_state.download_manager = DownloadManager(settings)
    app.state.fm4_state.scheduler = Scheduler(settings)

    # Seed a chart + entry so tests have data.
    with session_scope() as session:
        chart = Chart(source_url="https://fm4.orf.at/story/test-100",
                      title="Test Chart", chart_date="2026-08-15")
        entry = ChartEntry(rank=1, artist="Nia Archives",
                           title="There Goes Ma Head", song_key="nia archives|there goes ma head")
        chart.entries.append(entry)
        session.add(chart)
        session.flush()
        entry_id = entry.id
        session.add(YouTubeResult(
            entry_id=entry.id, query="q", video_id="abc123",
            video_title="Official", channel="Nia Archives", video_url="https://y",
            rank=1,
        ))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        c.entry_id = entry_id
        yield c


async def test_health(client):
    response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_charts_list(client):
    response = await client.get("/api/charts")
    assert response.status_code == 200
    charts = response.json()
    assert len(charts) == 1
    assert charts[0]["entry_count"] == 1


async def test_chart_detail(client):
    response = await client.get("/api/charts/1")
    assert response.status_code == 200
    data = response.json()
    assert len(data["entries"]) == 1
    assert data["entries"][0]["artist"] == "Nia Archives"


async def test_chart_detail_404(client):
    response = await client.get("/api/charts/9999")
    assert response.status_code == 404


async def test_song_and_youtube(client):
    response = await client.get(f"/api/songs/{client.entry_id}")
    assert response.status_code == 200
    song = response.json()
    assert song["artist"] == "Nia Archives"

    response = await client.get(f"/api/songs/{client.entry_id}/youtube")
    assert response.status_code == 200
    candidates = response.json()
    assert len(candidates) == 1
    assert candidates[0]["video_id"] == "abc123"


async def test_song_404(client):
    response = await client.get("/api/songs/9999")
    assert response.status_code == 404


async def test_download_flow(client):
    # The DownloadManager in the fixture is never started, so enqueue only
    # persists the queued row without launching a real download.
    response = await client.post(
        f"/api/songs/{client.entry_id}/download",
        json={"youtube_result_id": 1},
    )
    assert response.status_code == 200
    download = response.json()
    assert download["status"] == Download.STATUS_QUEUED
    assert download["video_id"] == "abc123"


async def test_download_rejects_unknown_result(client):
    response = await client.post(
        f"/api/songs/{client.entry_id}/download",
        json={"youtube_result_id": 9999},
    )
    assert response.status_code == 404


async def test_downloads_endpoints(client):
    response = await client.get("/api/downloads")
    assert response.status_code == 200
    response = await client.get("/api/downloads-summary")
    assert response.status_code == 200
    assert response.json()["total"] == 0


async def test_refresh_endpoint(client, monkeypatch):
    async def fake_refresh(settings):
        return {"discovered": 2, "imported": 1, "skipped": 1, "errors": 0}

    monkeypatch.setattr("backend.app.tasks.refresh_once", fake_refresh)
    response = await client.post("/api/charts/refresh")
    assert response.status_code == 200
    assert response.json() == {"discovered": 2, "imported": 1, "skipped": 1, "errors": 0}