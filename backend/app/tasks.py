"""Background tasks: chart refresh and download reconciliation."""

from __future__ import annotations

import asyncio
import logging

from .config import Settings
from .db import session_scope
from .models import AppState
from .services.fm4_source import FM4Source
from .services.importer import import_chart

logger = logging.getLogger(__name__)

REFRESH_LOCK_KEY = "chart_refresh_in_progress"
FETCH_CONCURRENCY = 4


def reset_refresh_lock() -> None:
    """Clear a stale in-progress marker left behind by an unclean shutdown."""
    with session_scope() as session:
        row = session.get(AppState, REFRESH_LOCK_KEY)
        if row is not None and row.value == "running":
            row.value = "done"
            logger.warning("Cleared stale chart-refresh lock from previous run")


def _set_state(key: str, value: str) -> None:
    with session_scope() as session:
        row = session.get(AppState, key)
        if row is None:
            session.add(AppState(key=key, value=value))
        else:
            row.value = value


def _get_state(key: str) -> str | None:
    with session_scope() as session:
        row = session.get(AppState, key)
        return row.value if row else None


async def refresh_charts(source: FM4Source) -> dict:
    """Discover and import charts not yet in the database.

    A database-backed lock prevents duplicate concurrent runs. Chart pages
    are fetched (and parsed) concurrently; imports are written sequentially
    to keep SQLite write contention low. Individual failures are logged and
    do not abort the whole run.
    """
    if _get_state(REFRESH_LOCK_KEY) == "running":
        logger.warning("Chart refresh already in progress; skipping")
        return {"discovered": 0, "imported": 0, "skipped": 0, "errors": 0}

    _set_state(REFRESH_LOCK_KEY, "running")
    imported = skipped = errors = 0
    try:
        links = await source.discover()
        discovered = len(links)

        semaphore = asyncio.Semaphore(FETCH_CONCURRENCY)

        async def fetch_one(url: str):
            async with semaphore:
                try:
                    return await source.fetch_chart(url)
                except Exception:
                    logger.exception("Failed to fetch chart %s", url)
                    return None

        charts = await asyncio.gather(*(fetch_one(link.url) for link in links))

        for chart in charts:
            if chart is None:
                errors += 1
                continue
            with session_scope() as session:
                result = import_chart(session, chart)
            if result is not None:
                imported += 1
            else:
                skipped += 1
        logger.info(
            "Chart refresh complete: %d discovered, %d imported, %d skipped, %d errors",
            discovered, imported, skipped, errors,
        )
        return {
            "discovered": discovered,
            "imported": imported,
            "skipped": skipped,
            "errors": errors,
        }
    finally:
        _set_state(REFRESH_LOCK_KEY, "done")


async def refresh_once(settings: Settings) -> dict:
    """Create a temporary FM4 source and run one refresh pass."""
    source = FM4Source(
        tag_url=settings.fm4_tag_url,
        timeout=settings.fm4_request_timeout,
        max_charts=settings.fm4_max_charts_per_run,
    )
    try:
        return await refresh_charts(source)
    finally:
        await source.aclose()


class Scheduler:
    """Background loop that periodically refreshes the charts."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.interval = settings.poll_interval_seconds
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="chart-scheduler")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run(self) -> None:
        if self.interval <= 0:
            logger.info("Chart scheduler disabled (FM4_POLL_INTERVAL=0)")
            await asyncio.Event().wait()  # park forever
        logger.info(
            "Chart scheduler started (interval %ss)",
            self.interval,
        )
        # Run once immediately at startup, then sleep between runs.
        while True:
            try:
                await refresh_once(self.settings)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Chart refresh run failed")
            await asyncio.sleep(self.interval)