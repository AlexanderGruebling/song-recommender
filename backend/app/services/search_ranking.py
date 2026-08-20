"""Deterministic ranking/filtering of YouTube search results.

Scoring is intentionally simple and rule-based (not an ML model) so it stays
predictable and easy to improve. Candidates are ranked by how well the video
corresponds to the requested artist + title.
"""

from __future__ import annotations

import logging
import re
import unicodedata

logger = logging.getLogger(__name__)

# Tokens that indicate the video is not the plain studio recording.
NEGATIVE_TOKENS = (
    "live", "lyric", "lyrics", "karaoke", "cover", "remix", "mashup",
    "tribute", "reaction", "react", "making of", "behind the scenes",
    "official visualizer", "unplugged", "acoustic", "interview", "trailer",
    "teaser", "instrumental", "full album", "tracklist", "preview",
)
# Tokens that indicate an official video.
POSITIVE_TOKENS = ("official video", "official audio", "official music video", "audio")
# Channel-name markers for topic/official channels.
TOPIC_MARKERS = (" - topic", " topic")
VEVO_MARKER = "vevo"


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def build_search_query(artist: str, title: str) -> str:
    """Construct a YouTube search query for a song."""
    artist = artist.strip()
    title = title.strip()
    # Strip the trailing parenthetical used by FM4 for some songs, e.g.
    # "bhs&lilien (checkt ihr wegen brasilien und so)". It can hurt search.
    title_query = re.sub(r"\s*\(.*?\)\s*$", "", title).strip() or title
    return f"{artist} {title_query}"


def score_result(result: dict, artist: str, title: str) -> float:
    """Score a raw YouTube result. Higher is better."""
    video_title = normalize(result.get("title", ""))
    channel = normalize(result.get("channel", ""))
    artist_n = normalize(artist)
    title_n = normalize(title)

    if not video_title:
        return 0.0

    score = 0.0

    # Exact-ish title match: the normalized video title contains the song title.
    if title_n and title_n in video_title:
        score += 100.0
    # Every significant token of the title present in the video title.
    title_tokens = [t for t in title_n.split() if len(t) > 2]
    if title_tokens:
        present = sum(1 for t in title_tokens if t in video_title)
        score += 30.0 * (present / len(title_tokens))

    # Artist mention in the video title or the channel name.
    artist_tokens = [t for t in artist_n.split() if len(t) > 2]
    if artist_n in video_title:
        score += 30.0
    elif artist_tokens:
        present = sum(1 for t in artist_tokens if t in video_title)
        score += 15.0 * (present / len(artist_tokens))

    if artist_n in channel:
        score += 40.0
    elif artist_tokens:
        present = sum(1 for t in artist_tokens if t in channel)
        score += 20.0 * (present / len(artist_tokens))

    # Official markers.
    if any(token in video_title for token in POSITIVE_TOKENS):
        score += 25.0
    if VEVO_MARKER in channel:
        score += 20.0
    if any(marker in channel for marker in TOPIC_MARKERS):
        score += 15.0

    # Penalties for non-studio versions.
    for token in NEGATIVE_TOKENS:
        if token in video_title:
            score -= 15.0

    return score


def filter_and_rank(
    results: list[dict],
    artist: str,
    title: str,
    candidates: int = 3,
) -> list[dict]:
    """Filter out clearly unrelated videos and return the best candidates."""
    title_n = normalize(title)
    if not title_n:
        return []

    scored: list[tuple[float, dict]] = []
    for result in results:
        video_title = normalize(result.get("title", ""))
        if not video_title:
            continue
        # Reject videos whose title shares no meaningful token with the song.
        title_tokens = {t for t in title_n.split() if len(t) > 2}
        if title_tokens and not any(t in video_title for t in title_tokens):
            continue
        score = score_result(result, artist, title)
        if score > 0:
            scored.append((score, result))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    ranked = [r for _, r in scored[:candidates]]
    logger.debug(
        "Ranking %d results for '%s - %s' -> %d candidates",
        len(results),
        artist,
        title,
        len(ranked),
    )
    return ranked