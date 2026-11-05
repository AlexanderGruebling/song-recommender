"""Tests for the FM4 scraper and importer."""

from __future__ import annotations

import pytest

from backend.app.services.fm4_source import (
    ChartParseError,
    parse_chart_page,
    parse_german_date,
)
from backend.app.services.importer import import_chart, normalize_song_key
from backend.app.models import Chart, ChartEntry

from conftest import load_fixture

REAL_PAGE = "fm4_chart_real.html"
REAL_URL = "https://fm4.orf.at/story/fm4charts-25-7-2026-100"


def test_parse_real_chart():
    chart = parse_chart_page(load_fixture(REAL_PAGE), REAL_URL)
    assert chart.source_url == REAL_URL
    assert chart.chart_date == "2026-07-25"
    assert len(chart.entries) == 40
    # First entry should be rank 1 with artist/title.
    first = chart.entries[0]
    assert first.rank == 1
    assert first.artist == "FARCE"
    assert first.title == "Deeply Strange People"
    assert first.movement == "same"
    assert first.previous_rank == "1"
    assert first.weeks_in_chart == "4"
    # Entries are sorted by rank.
    assert [e.rank for e in chart.entries] == list(range(1, 41))


def test_parse_handles_html_entities_and_quotes():
    chart = parse_chart_page(load_fixture(REAL_PAGE), REAL_URL)
    titles = {e.title for e in chart.entries}
    assert "bhs&lilien (checkt ihr wegen brasilien und so)" in titles
    artists = {e.artist for e in chart.entries}
    assert "Barry Can't Swim" in artists


def test_parse_handles_movement_classes():
    chart = parse_chart_page(load_fixture(REAL_PAGE), REAL_URL)
    movements = {e.movement for e in chart.entries}
    assert "up" in movements
    assert "down" in movements
    assert "same" in movements


def test_parse_missing_table_raises():
    with pytest.raises(ChartParseError):
        parse_chart_page("<html><body>no chart here</body></html>", "http://x")


def test_parse_empty_table_raises():
    html = "<table class='charts'><tbody><tr><td>1</td></tr></tbody></table>"
    with pytest.raises(ChartParseError):
        parse_chart_page(html, "http://x")


def test_parse_incomplete_chart_rejected():
    """A chart with fewer than 30 entries is treated as incomplete."""
    rows = "".join(
        f"<tr><td>{i}</td><td></td><td>Artist {i}</td><td>Song {i}</td></tr>"
        for i in range(1, 10)
    )
    html = (
        "<table class='charts'><tbody>"
        + rows
        + "</tbody></table>"
    )
    with pytest.raises(ChartParseError):
        parse_chart_page(html, "http://x")


def test_parse_german_dates():
    assert parse_german_date("25. Juli 2026") == "2026-07-25"
    assert parse_german_date("1. Jänner 2026") == "2026-01-01"
    assert parse_german_date("1. August 2026") == "2026-08-01"
    assert parse_german_date("kein datum hier") is None


def test_import_chart_and_deduplicate(session):
    chart = parse_chart_page(load_fixture(REAL_PAGE), REAL_URL)
    imported = import_chart(session, chart)
    assert imported is not None
    assert len(imported.entries) == 40
    session.commit()

    # Importing the same source URL again must be a no-op.
    again = import_chart(session, chart)
    assert again is None

    charts = session.query(Chart).all()
    assert len(charts) == 1
    entries = session.query(ChartEntry).all()
    assert len(entries) == 40


def test_normalize_song_key():
    assert normalize_song_key("FARCE", "Deeply Strange People") == normalize_song_key(
        "farce", "deeply strange people"
    )
    assert normalize_song_key("KÄSSY", "T-Shirt") == normalize_song_key(
        "kässy", "t-shirt"
    )

# -- discovery and refresh --------------------------------------------

import httpx  # noqa: E402

from backend.app.services.chart_source import ChartSource, DiscoveredChart  # noqa: E402
from backend.app.services.fm4_source import FM4DiscoveryError, FM4Source  # noqa: E402
from backend.app.tasks import refresh_charts  # noqa: E402

TAG_URL = "https://fm4.orf.at/tag/Musik/FM4%20Charts"


def _source(handler) -> FM4Source:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return FM4Source(tag_url=TAG_URL, max_charts=50, client=client)


async def test_discover_keeps_only_canonical_chart_links():
    # The real chart page links to other charts, plus non-chart stories.
    page = load_fixture(REAL_PAGE)
    source = _source(lambda request: httpx.Response(200, text=page))
    try:
        urls = [c.url for c in await source.discover()]
    finally:
        await source.aclose()

    assert len(urls) == len(set(urls))
    assert all(u.startswith("https://fm4.orf.at/story/") for u in urls)
    # Non-chart stories are dropped.
    assert not any("frequenzen" in u or "gewinnspiel" in u for u in urls)
    # Absolute links with a headline slug collapse to the plain story URL.
    assert "https://fm4.orf.at/story/charts-18-7-2026-100" in urls
    assert not any(u.count("/") > 4 for u in urls)
    # Case variants of the slug are accepted.
    assert "https://fm4.orf.at/story/Charts-20260711-100" in urls


async def test_discover_canonicalizes_duplicate_links():
    page = """
      <a href="/story/fm4charts-8-8-2026-100">relative</a>
      <a href="https://fm4.orf.at/story/fm4charts-8-8-2026-100/farce-ist-die-1">absolute</a>
      <a href="/story/fm4charts-8-8-2026-100?ref=tag">query</a>
      <a href="/story/frequenzen-streams100">not a chart</a>
      <a href="https://example.com/story/charts-1-1-2026-100">other site</a>
    """
    source = _source(lambda request: httpx.Response(200, text=page))
    try:
        urls = [c.url for c in await source.discover()]
    finally:
        await source.aclose()
    assert urls == ["https://fm4.orf.at/story/fm4charts-8-8-2026-100"]


async def test_discover_raises_when_tag_page_fails():
    source = _source(lambda request: httpx.Response(503))
    try:
        with pytest.raises(FM4DiscoveryError):
            await source.discover()
    finally:
        await source.aclose()


class FakeSource(ChartSource):
    def __init__(self, links, pages):
        self.links = links
        self.pages = pages
        self.fetched: list[str] = []

    async def discover(self):
        return [DiscoveredChart(url=u) for u in self.links]

    async def fetch_chart(self, url):
        self.fetched.append(url)
        return self.pages[url]()


async def test_refresh_skips_known_and_non_chart_stories(session):
    known_url = "https://fm4.orf.at/story/known"
    new_url = "https://fm4.orf.at/story/new"
    feature_url = "https://fm4.orf.at/story/charts-brandnew"
    broken_url = "https://fm4.orf.at/story/broken"
    import_chart(session, parse_chart_page(load_fixture(REAL_PAGE), known_url))
    session.commit()

    def not_a_chart():
        raise ChartParseError("no table.charts found")

    source = FakeSource(
        [known_url, new_url, feature_url, broken_url],
        {
            new_url: lambda: parse_chart_page(load_fixture(REAL_PAGE), new_url),
            feature_url: not_a_chart,
            broken_url: lambda: None,  # fetch failed
        },
    )
    result = await refresh_charts(source)

    assert known_url not in source.fetched
    assert result == {"discovered": 4, "imported": 1, "skipped": 2, "errors": 1}


async def test_refresh_propagates_discovery_failure():
    class Failing(FakeSource):
        async def discover(self):
            raise FM4DiscoveryError("down")

    with pytest.raises(FM4DiscoveryError):
        await refresh_charts(Failing([], {}))
