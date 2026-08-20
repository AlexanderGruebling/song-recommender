"""YouTube Data API v3 client.

Uses ``search.list`` (one call, 100 quota units / separate daily bucket) to
find candidate videos, then a single ``videos.list`` call (1 unit, up to 50
ids) to fetch durations. Results are cached in the database so repeated page
views do not consume quota.
"""

from __future__ import annotations

import logging
import re

import httpx

logger = logging.getLogger(__name__)


class YouTubeError(Exception):
    """Base class for YouTube API failures."""


class YouTubeQuotaExceeded(YouTubeError):
    pass


class YouTubeKeyInvalid(YouTubeError):
    pass


class YouTubeNotConfigured(YouTubeError):
    pass


class YouTubeClient:
    BASE = "https://www.googleapis.com/youtube/v3"

    def __init__(self, api_key: str | None, timeout: float = 15.0):
        self.api_key = api_key
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    async def search(
        self,
        query: str,
        max_results: int = 10,
        client: httpx.AsyncClient | None = None,
    ) -> list[dict]:
        """Return raw search results (snippet only)."""
        self._require_key()
        params = {
            "part": "snippet",
            "q": query,
            "type": "video",
            "maxResults": max_results,
            "safeSearch": "none",
            "relevanceLanguage": "en",
            "videoCategoryId": "10",  # Music
        }
        data = await self._get("/search", params, client)
        items = data.get("items", [])
        results = []
        for item in items:
            video_id = (item.get("id") or {}).get("videoId")
            snippet = item.get("snippet") or {}
            if not video_id:
                continue
            results.append(
                {
                    "video_id": video_id,
                    "title": snippet.get("title", ""),
                    "channel": snippet.get("channelTitle", ""),
                    "channel_id": snippet.get("channelId"),
                    "published_at": snippet.get("publishedAt"),
                    "thumbnail_url": self._best_thumbnail(snippet.get("thumbnails")),
                }
            )
        return results

    async def video_durations(
        self,
        video_ids: list[str],
        client: httpx.AsyncClient | None = None,
    ) -> dict[str, int]:
        """Return {video_id: duration_seconds} for up to 50 ids."""
        if not video_ids:
            return {}
        self._require_key()
        params = {
            "part": "contentDetails",
            "id": ",".join(video_ids[:50]),
        }
        data = await self._get("/videos", params, client)
        durations: dict[str, int] = {}
        for item in data.get("items", []):
            content = item.get("contentDetails") or {}
            seconds = iso8601_duration_to_seconds(content.get("duration"))
            if seconds is not None:
                durations[item.get("id")] = seconds
        return durations

    async def _get(
        self,
        path: str,
        params: dict,
        client: httpx.AsyncClient | None,
    ) -> dict:
        if client is None:
            async with httpx.AsyncClient(timeout=self.timeout) as own:
                return await self._get(path, params, own)
        response = await client.get(
            f"{self.BASE}{path}",
            params={**params, "key": self.api_key},
        )
        if response.status_code == 403:
            raise self._error_for(response, "YouTube API returned 403")
        if response.status_code != 200:
            raise YouTubeError(
                f"YouTube API returned HTTP {response.status_code}: "
                f"{response.text[:300]}"
            )
        return response.json()

    def _error_for(self, response: httpx.Response, message: str) -> YouTubeError:
        try:
            errors = response.json().get("error", {}).get("errors", [])
            reason = errors[0].get("reason") if errors else ""
        except ValueError:
            reason = ""
        if reason == "quotaExceeded":
            return YouTubeQuotaExceeded("YouTube daily quota exceeded")
        if reason in ("keyInvalid", "badRequest"):
            return YouTubeKeyInvalid("YouTube API key is invalid or not enabled")
        return YouTubeError(f"{message}: {reason}")

    def _require_key(self) -> None:
        if not self.api_key:
            raise YouTubeNotConfigured("YOUTUBE_API_KEY is not configured")

    @staticmethod
    def _best_thumbnail(thumbnails) -> str | None:
        if not thumbnails:
            return None
        for size in ("maxres", "standard", "high", "medium", "default"):
            entry = thumbnails.get(size)
            if entry and entry.get("url"):
                return entry["url"]
        return None


def iso8601_duration_to_seconds(duration: str | None) -> int | None:
    """Convert an ISO-8601 duration such as ``PT3M45S`` into seconds."""
    if not duration:
        return None
    m = re.match(r"^PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$", duration)
    if not m:
        return None
    hours, minutes, seconds = (int(g) if g else 0 for g in m.groups())
    return hours * 3600 + minutes * 60 + seconds