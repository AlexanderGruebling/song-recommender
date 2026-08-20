"""Tests for filename generation and sanitization."""

from __future__ import annotations

from backend.app.services.filenames import (
    build_filename,
    output_template,
    sanitize_component,
)


def test_sanitize_component_removes_problematic_chars():
    assert sanitize_component('Weird/Name:*?"<>|') == "WeirdName"
    assert sanitize_component("  spaced  out  ") == "spaced out"


def test_build_filename():
    assert build_filename("Nia Archives", "There Goes Ma Head", "mp3") == (
        "Nia Archives - There Goes Ma Head.mp3"
    )
    assert build_filename("Band/with/slashes", "Song: Title", "m4a") == (
        "Bandwithslashes - Song Title.m4a"
    )


def test_build_filename_falls_back_to_unknown():
    assert build_filename("", "", "mp3") == "unknown-artist - unknown-title.mp3"


def test_output_template_leaves_extension_to_ytdlp():
    template = output_template("/music", "Nia Archives", "There Goes Ma Head")
    assert template == "/music/Nia Archives - There Goes Ma Head.%(ext)s"


def test_output_template_sanitizes():
    template = output_template("/music", "A/B", 'C:"D"')
    basename = template.rsplit("/", 1)[-1]
    assert ":" not in basename
    assert "/" not in basename