"""Tests for search query construction and deterministic ranking."""

from __future__ import annotations

from backend.app.services.search_ranking import (
    build_search_query,
    filter_and_rank,
    normalize,
    score_result,
)


def result(title="", channel="", **extra):
    data = {"video_id": "x", "title": title, "channel": channel, "thumbnail_url": None}
    data.update(extra)
    return data


def test_build_search_query():
    assert build_search_query("Nia Archives", "There Goes Ma Head") == (
        "Nia Archives There Goes Ma Head"
    )
    # Trailing parenthetical removed for search robustness.
    assert build_search_query("Alewya", "Cairo FM") == "Alewya Cairo FM"
    assert build_search_query("Band", "Song (feat. Someone)") == "Band Song"


def test_normalize_ignores_case_and_punctuation():
    assert normalize("KÄSSY  - T-Shirt!") == "kassy t shirt"


def test_score_exact_matches_highest():
    official = result(
        title="Nia Archives - There Goes Ma Head (Official Video)",
        channel="Nia Archives",
    )
    lyric = result(
        title="There Goes Ma Head - Nia Archives (Lyrics)",
        channel="Lyric Videos",
    )
    unrelated = result(title="Random cat compilation", channel="Some Channel")

    assert score_result(official, "Nia Archives", "There Goes Ma Head") > score_result(
        lyric, "Nia Archives", "There Goes Ma Head"
    )
    assert score_result(lyric, "Nia Archives", "There Goes Ma Head") > score_result(
        unrelated, "Nia Archives", "There Goes Ma Head"
    )


def test_score_penalizes_live_and_cover():
    live = result(title="There Goes Ma Head (Live)", channel="Some Channel")
    studio = result(title="There Goes Ma Head", channel="Some Channel")
    assert score_result(studio, "Nia Archives", "There Goes Ma Head") > score_result(
        live, "Nia Archives", "There Goes Ma Head"
    )


def test_filter_and_rank_excludes_unrelated():
    results = [
        result(title="There Goes Ma Head (Official Video)", channel="Nia Archives"),
        result(title="Something completely different", channel="Random"),
        result(title="There Goes Ma Head - Cover", channel="CoverBand"),
    ]
    ranked = filter_and_rank(results, "Nia Archives", "There Goes Ma Head", candidates=3)
    titles = [r["title"] for r in ranked]
    assert "Something completely different" not in titles
    assert len(ranked) <= 3


def test_filter_and_rank_returns_requested_count():
    # All candidates match the song title "One"; they differ by channel.
    results = [
        result(title=f"{artist} One", channel=artist)
        for artist in ["A", "B", "C", "D"]
    ]
    ranked = filter_and_rank(results, "A", "One", candidates=2)
    assert len(ranked) == 2
    assert ranked[0]["title"] == "A One"


def test_filter_and_rank_empty_when_no_match():
    ranked = filter_and_rank([], "A", "One")
    assert ranked == []