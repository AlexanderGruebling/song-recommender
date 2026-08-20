"""Tests for the YouTube client and search caching."""

from __future__ import annotations

import pytest

from backend.app.models import ChartEntry, Chart, YouTubeResult
from backend.app.services.youtube import (
    YouTubeClient,
    YouTubeNotConfigured,
    iso8601_duration_to_seconds,
)
from backend.app.services.youtube_service import YouTubeSearchService


class FakeYouTubeClient(YouTubeClient):
    """In-memory stand-in that returns canned results without HTTP."""

    def __init__(self, results, durations=None, configured=True):
        super().__init__("fake-key" if configured else None)
        self.results = results
        self.durations = durations or {}
        self.search_calls = 0

    async def search(self, query, max_results=10, client=None):
        self.search_calls += 1
        return [dict(r) for r in self.results]

    async def video_durations(self, video_ids, client=None):
        return {v: self.durations.get(v) for v in video_ids}


def _entry(session, artist="Nia Archives", title="There Goes Ma Head", url=None):
    chart = Chart(
        source_url=url or f"http://example.test/{artist}/{title}",
        title="Test",
        chart_date="2026-08-15",
    )
    entry = ChartEntry(
        rank=1, artist=artist, title=title,
        song_key=f"{artist.lower()}|{title.lower()}",
    )
    chart.entries.append(entry)
    session.add(chart)
    session.flush()
    return entry


def test_iso8601_duration():
    assert iso8601_duration_to_seconds("PT3M45S") == 225
    assert iso8601_duration_to_seconds("PT1H2M3S") == 3723
    assert iso8601_duration_to_seconds("PT45S") == 45
    assert iso8601_duration_to_seconds(None) is None
    assert iso8601_duration_to_seconds("garbage") is None


def test_client_requires_key():
    client = YouTubeClient(None)
    with pytest.raises(YouTubeNotConfigured):
        client._require_key()


async def test_search_caches_results(session):
    results = [
        {"video_id": "v1", "title": "Nia Archives - There Goes Ma Head (Official)",
         "channel": "Nia Archives", "channel_id": "c1", "published_at": "2026-01-01",
         "thumbnail_url": "https://img/y1"},
        {"video_id": "v2", "title": "There Goes Ma Head (Lyrics)",
         "channel": "Lyrics", "channel_id": "c2", "published_at": "2026-01-02",
         "thumbnail_url": "https://img/y2"},
    ]
    fake = FakeYouTubeClient(results, durations={"v1": 225, "v2": 226})
    service = YouTubeSearchService(fake, max_results=10, candidates=3)
    entry = _entry(session)

    first = await service.get_or_search(session, entry)
    assert len(first) == 2
    assert fake.search_calls == 1

    # Second call must reuse the cache without a new API call.
    again = await service.get_or_search(session, entry)
    assert len(again) == 2
    assert fake.search_calls == 1
    # Duration was attached from the videos.list call.
    assert any(r.duration_seconds == 225 for r in again)


async def test_refresh_force_new_search(session):
    fake = FakeYouTubeClient(
        [{"video_id": "old", "title": "old", "channel": "x",
          "channel_id": None, "published_at": None, "thumbnail_url": None}],
        configured=True,
    )
    service = YouTubeSearchService(fake, candidates=3)
    entry = _entry(session, artist="A", title="One")
    await service.get_or_search(session, entry)
    assert fake.search_calls == 1

    fake.results = [{"video_id": "new", "title": "A One (New Version)", "channel": "x",
                     "channel_id": None, "published_at": None, "thumbnail_url": None}]
    refreshed = await service.get_or_search(session, entry, refresh=True)
    assert fake.search_calls == 2
    assert [r.video_id for r in refreshed] == ["new"]


async def test_cache_reused_across_entries_with_same_song(session):
    fake = FakeYouTubeClient(
        [{"video_id": "v1", "title": "A One", "channel": "A",
          "channel_id": None, "published_at": None, "thumbnail_url": None}],
        configured=True,
    )
    service = YouTubeSearchService(fake, candidates=3)
    first = _entry(session, artist="A", title="One", url="http://example.test/chart1")
    await service.get_or_search(session, first)
    assert fake.search_calls == 1

    # Same song in a different chart: cache is reused, no new API call.
    second = _entry(session, artist="A", title="One", url="http://example.test/chart2")
    second.rank = 5
    cached = await service.get_or_search(session, second)
    assert fake.search_calls == 1
    assert len(cached) == 1
    assert session.query(YouTubeResult).filter(YouTubeResult.entry_id == second.id).count() == 1


async def test_search_without_key_raises(session):
    fake = FakeYouTubeClient([], configured=False)
    service = YouTubeSearchService(fake, candidates=3)
    entry = _entry(session)
    with pytest.raises(YouTubeNotConfigured):
        await service.get_or_search(session, entry)