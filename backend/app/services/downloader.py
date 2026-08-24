"""Asynchronous yt-dlp download manager.

Downloads run in the background as subprocesses (never through a shell). A
single worker consumes a queue so at most ``DOWNLOAD_CONCURRENCY`` processes
run at once. Progress is parsed from yt-dlp's ``--newline --progress`` output
and persisted to the database.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from ..config import Settings
from ..db import session_scope
from ..models import Download
from .filenames import output_template, sanitize_component

logger = logging.getLogger(__name__)

PROGRESS_RE = re.compile(r"\[download\]\s+(\d+(?:\.\d+)?)%")


@dataclass
class DownloadRequest:
    entry_id: int
    video_id: str
    video_url: str
    video_title: str
    result_id: int
    output_dir: Path
    artist: str
    title: str


@dataclass
class DownloadStats:
    total: int = 0
    queued: int = 0
    downloading: int = 0
    completed: int = 0
    failed: int = 0


class DownloadManager:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.queue: asyncio.Queue[DownloadRequest] = asyncio.Queue()
        self._workers: list[asyncio.Task] = []
        # Serializes duplicate-check + enqueue so concurrent requests cannot
        # both queue a download for the same entry.
        self.enqueue_lock = asyncio.Lock()
        self._active: dict[int, asyncio.Task] = {}  # entry_id -> task

    # -- lifecycle -------------------------------------------------

    def start(self) -> None:
        self._workers = [
            asyncio.create_task(self._worker(), name=f"download-worker-{i}")
            for i in range(max(1, self.settings.download_concurrency))
        ]

    async def stop(self) -> None:
        for worker in self._workers:
            worker.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers = []

    async def reconcile_interrupted(self) -> None:
        """Mark queued/downloading rows from a previous run as failed."""
        with session_scope() as session:
            rows = session.scalars(
                select(Download).where(
                    Download.status.in_(
                        [Download.STATUS_QUEUED, Download.STATUS_DOWNLOADING]
                    )
                )
            ).all()
            for row in rows:
                row.status = Download.STATUS_FAILED
                row.error = "Interrupted by application restart"
                row.finished_at = datetime.now(timezone.utc)
                logger.info(
                    "Reconciled interrupted download %d (entry %d) -> failed",
                    row.id, row.entry_id,
                )

    # -- public API -------------------------------------------------

    async def enqueue(self, request: DownloadRequest) -> Download:
        """Create a queued download row and schedule it. Returns the row."""
        with session_scope() as session:
            download = Download(
                entry_id=request.entry_id,
                video_id=request.video_id,
                video_url=request.video_url,
                video_title=request.video_title,
                status=Download.STATUS_QUEUED,
            )
            session.add(download)
            session.flush()
            download_id = download.id
        await self.queue.put(request)
        logger.info(
            "Queued download %d for entry %d (%s)",
            download_id, request.entry_id, request.video_title,
        )
        return self.get_download(download_id)

    async def _worker(self) -> None:
        while True:
            request = await self.queue.get()
            try:
                await self._process(request)
            except Exception:
                logger.exception("Unexpected download failure for entry %d", request.entry_id)
            finally:
                self.queue.task_done()

    async def _process(self, request: DownloadRequest) -> None:
        # Refresh status -> downloading.
        download_id = self._mark(request.entry_id, Download.STATUS_DOWNLOADING)
        if download_id is None:
            logger.warning("No queued download row for entry %d; skipping", request.entry_id)
            return

        command = self._build_command(request)
        logger.info(
            "Starting yt-dlp for entry %d (download %d): %s",
            request.entry_id, download_id, request.video_url,
        )

        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        assert process.stdout is not None
        progress = 0
        recent_lines: deque[str] = deque(maxlen=5)
        try:
            async for line in process.stdout:
                text = line.decode("utf-8", errors="replace").strip()
                if not text:
                    continue
                match = PROGRESS_RE.search(text)
                if match:
                    percent = float(match.group(1))
                    self._update_progress(download_id, percent)
                elif "destination:" not in text:
                    recent_lines.append(text[:300])
                if "destination:" in text or text.startswith("[download]"):
                    logger.debug("yt-dlp: %s", text[:200])
            returncode = await process.wait()
        except asyncio.CancelledError:
            process.kill()
            await process.wait()
            self._fail(download_id, "Download cancelled")
            raise

        if returncode == 0:
            output = self._locate_output(request)
            self._complete(download_id, output)
        else:
            error = f"yt-dlp exited with code {returncode}"
            if recent_lines:
                error += ": " + " | ".join(recent_lines)
            self._fail(download_id, error)

    # -- status updates ---------------------------------------------

    def _mark(self, entry_id: int, status: str) -> int | None:
        with session_scope() as session:
            row = session.scalars(
                select(Download)
                .where(
                    Download.entry_id == entry_id,
                    Download.status.in_([Download.STATUS_QUEUED, Download.STATUS_DOWNLOADING]),
                )
                .order_by(Download.created_at.desc())
            ).first()
            if row is None:
                return None
            row.status = status
            row.started_at = datetime.now(timezone.utc)
            return row.id

    def _update_progress(self, download_id: int, percent: float) -> None:
        with session_scope() as session:
            row = session.get(Download, download_id)
            if row:
                row.progress = int(percent * 100)

    def _complete(self, download_id: int, output_path: str | None) -> None:
        with session_scope() as session:
            row = session.get(Download, download_id)
            if row:
                row.status = Download.STATUS_COMPLETED
                row.progress = 10000
                row.output_path = output_path
                row.error = None
                row.finished_at = datetime.now(timezone.utc)
        logger.info("Download %d completed -> %s", download_id, output_path)

    def _fail(self, download_id: int, error: str) -> None:
        with session_scope() as session:
            row = session.get(Download, download_id)
            if row:
                row.status = Download.STATUS_FAILED
                row.error = error
                row.finished_at = datetime.now(timezone.utc)
        logger.error("Download %d failed: %s", download_id, error)

    # -- helpers ----------------------------------------------------

    def _build_command(self, request: DownloadRequest) -> list[str]:
        template = output_template(
            str(request.output_dir), request.artist, request.title
        )
        command = [
            self.settings.ytdlp_path,
            "--no-playlist",
            "--newline",
            "--progress",
            "--no-overwrites",
            "-f", self.settings.ytdlp_format,
            "-o", template,
        ]
        if self.settings.ytdlp_extract_audio:
            command += [
                "-x",
                "--audio-format", self.settings.ytdlp_audio_format,
                "--audio-quality", self.settings.ytdlp_audio_quality,
            ]
        command.append(request.video_url)
        return command

    def _locate_output(self, request: DownloadRequest) -> str | None:
        """Find the file yt-dlp produced for this request."""
        artist_part = sanitize_component(request.artist) or "unknown-artist"
        title_part = sanitize_component(request.title) or "unknown-title"
        stem = f"{artist_part} - {title_part}"
        directory = Path(request.output_dir)
        if directory.is_dir():
            for path in sorted(directory.iterdir()):
                if path.stem == stem and path.is_file():
                    return str(path.resolve())
        return None

    def get_download(self, download_id: int) -> Download | None:
        with session_scope() as session:
            row = session.get(Download, download_id)
            if row is None:
                return None
            session.expunge(row)
            return row

    def list_downloads(self, limit: int = 100) -> list[Download]:
        with session_scope() as session:
            rows = session.scalars(
                select(Download).order_by(Download.created_at.desc()).limit(limit)
            ).all()
            for row in rows:
                session.expunge(row)
            return list(rows)

    def stats(self) -> DownloadStats:
        with session_scope() as session:
            rows = session.scalars(select(Download)).all()
        stats = DownloadStats(total=len(rows))
        for row in rows:
            if row.status == Download.STATUS_QUEUED:
                stats.queued += 1
            elif row.status == Download.STATUS_DOWNLOADING:
                stats.downloading += 1
            elif row.status == Download.STATUS_COMPLETED:
                stats.completed += 1
            elif row.status == Download.STATUS_FAILED:
                stats.failed += 1
        return stats