"""Chart source abstraction.

A chart source knows how to (a) discover recently published chart pages and
(b) parse a chart page into structured data. The FM4 implementation lives in
``app.services.fm4_source``. Adding another radio station later only requires
a new implementation of this interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ChartEntryData:
    rank: int
    artist: str
    title: str
    previous_rank: str | None = None
    weeks_in_chart: str | None = None
    movement: str | None = None


@dataclass
class ChartData:
    source_url: str  # stable identity used for deduplication
    title: str
    chart_date: str | None = None  # ISO date YYYY-MM-DD if available
    entries: list[ChartEntryData] = field(default_factory=list)


@dataclass
class DiscoveredChart:
    url: str
    title: str | None = None


class ChartSource(ABC):
    """Interface for a chart provider."""

    @abstractmethod
    async def discover(self) -> list[DiscoveredChart]:
        """Return recently published chart pages, newest first."""

    @abstractmethod
    async def fetch_chart(self, url: str) -> ChartData | None:
        """Fetch and parse a single chart page.

        Returns None when the page cannot be fetched; raises ChartParseError
        when it is not a usable chart.
        """