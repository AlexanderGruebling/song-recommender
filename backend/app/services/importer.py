"""Import discovered charts into the database, deduplicating by source URL."""

from __future__ import annotations

import logging
import unicodedata
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Chart, ChartEntry
from .chart_source import ChartData

logger = logging.getLogger(__name__)


def normalize_song_key(artist: str, title: str) -> str:
    """Produce a stable, case/diacritic-insensitive identity for a song."""
    def clean(value: str) -> str:
        value = unicodedata.normalize("NFKD", value)
        value = "".join(c for c in value if not unicodedata.combining(c))
        value = value.lower()
        value = re.sub(r"[^a-z0-9]+", " ", value)
        return " ".join(value.split())

    return f"{clean(artist)}|{clean(title)}"


def import_chart(session: Session, chart: ChartData) -> Chart | None:
    """Insert a chart if its source URL is not already known.

    Returns the persisted Chart, or ``None`` when the chart is a duplicate.
    """
    existing = session.scalar(
        select(Chart).where(Chart.source_url == chart.source_url)
    )
    if existing is not None:
        logger.info("Skipping already-imported chart %s", chart.source_url)
        return None

    model = Chart(
        source_url=chart.source_url,
        title=chart.title,
        chart_date=chart.chart_date,
    )
    for entry in chart.entries:
        model.entries.append(
            ChartEntry(
                rank=entry.rank,
                artist=entry.artist,
                title=entry.title,
                previous_rank=entry.previous_rank,
                weeks_in_chart=entry.weeks_in_chart,
                movement=entry.movement,
                song_key=normalize_song_key(entry.artist, entry.title),
            )
        )
    session.add(model)
    session.flush()
    logger.info(
        "Imported chart %s (%s) with %d entries",
        chart.source_url,
        chart.chart_date or "no date",
        len(model.entries),
    )
    return model