"""Tests for download state transitions and failure handling."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from backend.app.config import Settings
from backend.app.db import session_scope
from backend.app.models import Download
from backend.app.services.downloader import DownloadManager, DownloadRequest
from backend.app.services.filenames import output_template


def _settings(tmp_path) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        download_directory=tmp_path / "music",
        ytdlp_path="yt-dlp",
        ytdlp_format="bestaudio/best",
        ytdlp_extract_audio=True,
        ytdlp_audio_format="mp3",
        download_concurrency=1,
    )


def _request(tmp_path, artist="Nia Archives", title="There Goes Ma Head"):
    return DownloadRequest(
        entry_id=7,
        video_id="abc123",
        video_url="https://www.youtube.com/watch?v=abc123",
        video_title="Nia Archives - There Goes Ma Head (Official Video)",
        result_id=1,
        output_dir=tmp_path / "music",
        artist=artist,
        title=title,
    )


async def test_enqueue_creates_queued_row(tmp_path):
    manager = DownloadManager(_settings(tmp_path))
    manager.start()
    try:
        download = await manager.enqueue(_request(tmp_path))
        assert download.status == Download.STATUS_QUEUED
    finally:
        await manager.stop()


async def test_successful_download_transitions_to_completed(tmp_path, monkeypatch):
    manager = DownloadManager(_settings(tmp_path))
    manager.start()
    try:
        (tmp_path / "music").mkdir(parents=True, exist_ok=True)
        # Create the file yt-dlp would produce so _locate_output finds it.
        template = output_template(str(tmp_path / "music"), "Nia Archives",
                                   "There Goes Ma Head")
        target = Path(template.replace("%(ext)s", "mp3"))
        target.write_bytes(b"fake-audio")

        async def fake_exec(*args, **kwargs):
            proc = asyncio.create_subprocess_exec(
                "true", stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            return proc

        monkeypatch.setattr(manager, "_build_command", lambda r: ["true"])
        download = await manager.enqueue(_request(tmp_path))
        # Let the worker finish.
        await asyncio.sleep(0.5)
        row = manager.get_download(download.id)
        assert row.status == Download.STATUS_COMPLETED
        assert row.output_path == str(target.resolve())
    finally:
        await manager.stop()


async def test_failed_download_recorded(tmp_path, monkeypatch):
    manager = DownloadManager(_settings(tmp_path))
    manager.start()
    try:
        async def failing_exec(*args, **kwargs):
            proc = asyncio.create_subprocess_exec(
                "sh", "-c", "echo boom; exit 3",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            return proc

        monkeypatch.setattr(manager, "_build_command", lambda r: ["sh", "-c", "false"])
        download = await manager.enqueue(_request(tmp_path))
        await asyncio.sleep(0.5)
        row = manager.get_download(download.id)
        assert row.status == Download.STATUS_FAILED
        assert row.error and "code" in row.error
    finally:
        await manager.stop()


async def test_restart_reconciliation_marks_stale_rows_failed(tmp_path):
    with session_scope() as session:
        session.add(
            Download(
                entry_id=7,
                video_id="abc",
                video_url="https://y",
                video_title="t",
                status=Download.STATUS_DOWNLOADING,
            )
        )
    manager = DownloadManager(_settings(tmp_path))
    await manager.reconcile_interrupted()
    with session_scope() as session:
        row = session.get(Download, 1)
        assert row.status == Download.STATUS_FAILED
        assert "Interrupted" in row.error


def test_command_uses_no_shell(tmp_path):
    manager = DownloadManager(_settings(tmp_path))
    command = manager._build_command(_request(tmp_path))
    assert command[0] == "yt-dlp"
    assert "--no-overwrites" in command
    assert command[-1] == "https://www.youtube.com/watch?v=abc123"
    # Every argument is a single list element: no shell involved.
    assert any(a.startswith("-o") for a in command) or "-o" in command
    assert "-f" in command

async def test_hung_download_times_out_and_kills_children(tmp_path, monkeypatch):
    """A stuck yt-dlp run fails after DOWNLOAD_TIMEOUT and its children die too."""
    settings = _settings(tmp_path)
    settings.download_timeout = "1"
    manager = DownloadManager(settings)
    pidfile = tmp_path / "child.pid"
    # Stand-in for yt-dlp spawning ffmpeg: a background child that outlives sh.
    monkeypatch.setattr(
        manager, "_build_command",
        lambda r: ["sh", "-c", f"sleep 60 & echo $! > {pidfile}; wait"],
    )
    manager.start()
    try:
        download = await manager.enqueue(_request(tmp_path))
        for _ in range(40):
            await asyncio.sleep(0.1)
            row = manager.get_download(download.id)
            if row.status == Download.STATUS_FAILED:
                break
        assert row.status == Download.STATUS_FAILED
        assert "timed out" in row.error
        child = int(pidfile.read_text())
        await asyncio.sleep(0.1)
        with pytest.raises(ProcessLookupError):
            os.kill(child, 0)
    finally:
        await manager.stop()


def test_timeout_setting_parses_and_can_be_disabled(tmp_path):
    settings = _settings(tmp_path)
    assert settings.download_timeout_seconds == 30 * 60
    settings.download_timeout = "0"
    assert settings.download_timeout_seconds == 0
