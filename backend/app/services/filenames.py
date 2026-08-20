"""Deterministic, filesystem-safe filename generation."""

from __future__ import annotations

import re


def sanitize_component(value: str) -> str:
    """Sanitize a name component (artist or title) for use in a filename."""
    # Remove characters that are problematic on common filesystems.
    value = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "", value)
    # Collapse whitespace and trim separators.
    value = re.sub(r"\s+", " ", value).strip(" .")
    return value[:120]


def build_filename(artist: str, title: str, extension: str) -> str:
    """Return ``Artist - Title.ext`` with safe characters, never empty."""
    artist_part = sanitize_component(artist) or "unknown-artist"
    title_part = sanitize_component(title) or "unknown-title"
    name = f"{artist_part} - {title_part}"
    return f"{name}.{extension.lstrip('.')}"


def output_template(output_dir: str, artist: str, title: str) -> str:
    """Build a yt-dlp ``-o`` template.

    ``%(ext)s`` is left for yt-dlp to fill so the actual extension matches the
    downloaded format. yt-dlp itself will not overwrite existing files when
    ``--no-overwrites`` is used.
    """
    artist_part = sanitize_component(artist) or "unknown-artist"
    title_part = sanitize_component(title) or "unknown-title"
    return f"{output_dir}/{artist_part} - {title_part}.%(ext)s"