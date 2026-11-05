"""Asynchronous yt-dlp download manager.

Downloads run in the background as subprocesses (never through a shell). A
single worker consumes a queue so at most ``DOWNLOAD_CONCURRENCY`` processes
run at once. Progress is parsed from yt-dlp's ``--newline --progress`` output
and persisted to the database.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import signal
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select

from ..config import Settings
from ..db import session_scope
from ..models import Download
from .filenames import output_template, sanitize_component

logger = logging.getLogger(__name__)

PROGRESS_RE = re.compile(r"\[download\]\s+(\d+(?:\.\d+)?)%")

# Throttle DB writes to reduce SD-card I/O on Raspberry Pi (Issue #7).
PROGRESS_BATCH_PERCENT = 5
PROGRESS_BATCH_SECONDS = 5.0


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
        download_id = await asyncio.to_thread(self._insert_row, request)
        await self.queue.put(request)
        logger.info(
            "Queued download %d for entry %d (%s)",
            download_id, request.entry_id, request.video_title,
        )
        return await asyncio.to_thread(self.get_download, download_id)

    def _insert_row(self, request: DownloadRequest) -> int:
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
            return download.id

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

        # Own process group, so a kill also reaches ffmpeg spawned by yt-dlp.
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            start_new_session=True,
        )
        assert process.stdout is not None
        last_persisted_percent = -1
        last_persisted_time = time.monotonic()
        recent_lines: deque[str] = deque(maxlen=5)

        async def consume() -> int:
            nonlocal last_persisted_percent, last_persisted_time
            async for line in process.stdout:
                text = line.decode("utf-8", errors="replace").strip()
                if not text:
                    continue
                match = PROGRESS_RE.search(text)
                if match:
                    percent = float(match.group(1))
                    whole = int(percent)
                    now = time.monotonic()
                    is_final = percent >= 99.9
                    should_persist = False
                    if is_final:
                        should_persist = True
                    elif last_persisted_percent == -1:
                        # First progress update always persists.
                        should_persist = True
                    elif whole - last_persisted_percent >= PROGRESS_BATCH_PERCENT:
                        should_persist = True
                    elif (
                        now - last_persisted_time >= PROGRESS_BATCH_SECONDS
                        and whole != last_persisted_percent
                    ):
                        should_persist = True
                    if should_persist:
                        # Avoid duplicate writes for the same whole percent
                        # except for the final update.
                        if whole != last_persisted_percent or is_final:
                            last_persisted_percent = whole
                            last_persisted_time = now
                            self._update_progress(download_id, percent)
                elif "destination:" not in text:
                    recent_lines.append(text[:300])
                if "destination:" in text or text.startswith("[download]"):
                    logger.debug("yt-dlp: %s", text[:200])
            return await process.wait()

        timeout = self.settings.download_timeout_seconds or None
        try:
            returncode = await asyncio.wait_for(consume(), timeout)
        except asyncio.TimeoutError:
            await self._kill(process)
            self._fail(download_id, f"yt-dlp timed out after {timeout}s")
            return
        except asyncio.CancelledError:
            await self._kill(process)
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

    @staticmethod
    async def _kill(process: asyncio.subprocess.Process) -> None:
        """Kill yt-dlp and its children (ffmpeg), then reap the process."""
        if process.returncode is None:
            try:
                if hasattr(os, "killpg"):
                    os.killpg(process.pid, signal.SIGKILL)
                else:  # pragma: no cover - non-POSIX
                    process.kill()
            except ProcessLookupError:
                pass
        await process.wait()

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
            counts = dict(
                session.execute(
                    select(Download.status, func.count()).group_by(Download.status)
                ).all()
            )
        return DownloadStats(
            total=sum(counts.values()),
            queued=counts.get(Download.STATUS_QUEUED, 0),
            downloading=counts.get(Download.STATUS_DOWNLOADING, 0),
            completed=counts.get(Download.STATUS_COMPLETED, 0),
            failed=counts.get(Download.STATUS_FAILED, 0),
        )