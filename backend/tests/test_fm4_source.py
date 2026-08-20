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