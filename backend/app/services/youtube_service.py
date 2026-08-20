"""YouTube search orchestration: caching, search, ranking and persistence."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ChartEntry, Download, YouTubeResult
from ..config import settings
from .search_ranking import build_search_query, filter_and_rank
from .youtube import YouTubeClient, YouTubeNotConfigured

logger = logging.getLogger(__name__)


class YouTubeSearchService:
    def __init__(
        self,
        client: YouTubeClient,
        max_results: int = 10,
        candidates: int = 3,
    ):
        self.client = client
        self.max_results = max_results
        self.candidates = candidates

    def cached_results(self, session: Session, entry_id: int) -> list[YouTubeResult]:
        return list(
            session.scalars(
                select(YouTubeResult)
                .where(YouTubeResult.entry_id == entry_id)
                .order_by(YouTubeResult.rank)
            )
        )

    def find_cached_for_song(self, session: Session, entry: ChartEntry) -> list[YouTubeResult]:
        """Reuse search results cached for another entry of the same song."""
        return list(
            session.scalars(
                select(YouTubeResult)
                .join(ChartEntry, YouTubeResult.entry_id == ChartEntry.id)
                .where(
                    ChartEntry.song_key == entry.song_key,
                    ChartEntry.id != entry.id,
                    YouTubeResult.query == build_search_query(entry.artist, entry.title),
                )
                .order_by(YouTubeResult.rank)
            )
        )

    async def get_or_search(self, session: Session, entry: ChartEntry, refresh: bool = False):
        """Return ranked candidates for an entry, searching only if needed."""
        if not refresh:
            cached = self.cached_results(session, entry.id)
            if cached:
                return cached
            reused = self.find_cached_for_song(session, entry)
            if reused:
                logger.info(
                    "Reusing YouTube cache for '%s - %s' (entry %d)",
                    entry.artist, entry.title, entry.id,
                )
                for result in reused:
                    session.add(
                        YouTubeResult(
                            entry_id=entry.id,
                            query=result.query,
                            video_id=result.video_id,
                            video_title=result.video_title,
                            channel=result.channel,
                            channel_id=result.channel_id,
                            thumbnail_url=result.thumbnail_url,
                            duration_seconds=result.duration_seconds,
                            video_url=result.video_url,
                            published_at=result.published_at,
                            rank=result.rank,
                        )
                    )
                session.flush()
                return self.cached_results(session, entry.id)

        # Fresh search required.
        if not self.client.configured:
            raise YouTubeNotConfigured()
        query = build_search_query(entry.artist, entry.title)
        logger.info("Searching YouTube for '%s' (entry %d)", query, entry.id)
        try:
            async with httpx.AsyncClient(timeout=15.0) as http:
                results = await self.client.search(query, self.max_results, http)
                durations = await self.client.video_durations(
                    [r["video_id"] for r in results], http
                )
        except Exception as exc:
            logger.error("YouTube search failed for %s: %s", query, exc)
            raise

        for result in results:
            result["duration_seconds"] = durations.get(result["video_id"])
            result["url"] = f"https://www.youtube.com/watch?v={result['video_id']}"

        ranked = filter_and_rank(results, entry.artist, entry.title, self.candidates)

        # Remove any previous results for this entry so a refresh replaces them.
        session.query(YouTubeResult).filter(YouTubeResult.entry_id == entry.id).delete()
        now = datetime.now(timezone.utc)
        for position, result in enumerate(ranked, start=1):
            session.add(
                YouTubeResult(
                    entry_id=entry.id,
                    query=query,
                    video_id=result["video_id"],
                    video_title=result["title"],
                    channel=result["channel"],
                    channel_id=result.get("channel_id"),
                    thumbnail_url=result.get("thumbnail_url"),
                    duration_seconds=result.get("duration_seconds"),
                    video_url=result["url"],
                    published_at=result.get("published_at"),
                    search_timestamp=now,
                    rank=position,
                )
            )
        session.flush()
        return self.cached_results(session, entry.id)

    def has_completed_download(self, session: Session, entry: ChartEntry) -> bool:
        return (
            session.scalar(
                select(Download).where(
                    Download.entry_id == entry.id,
                    Download.status == Download.STATUS_COMPLETED,
                )
            )
            is not None
        )


def youtube_search_service() -> YouTubeSearchService:
    return YouTubeSearchService(
        client=YouTubeClient(settings.youtube_api_key),
        max_results=settings.youtube_max_results,
        candidates=settings.youtube_candidates,
    )