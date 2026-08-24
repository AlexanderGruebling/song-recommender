"""FM4 Top 40 chart discovery and parsing.

Discovery: the FM4 "FM4 Charts" tag page links to the most recent chart
articles. Each article (e.g. ``/story/fm4charts-8-8-2026-100``) contains a
``table.charts`` with the complete Top 40: rank, movement, artist, title,
previous-week position and weeks in chart. The chart date is shown in a
``div.date`` element using German/Austrian month names.

HTML parsing is CPU-bound (BeautifulSoup over full article pages) and runs
in a worker thread so it never blocks the event loop.
"""

from __future__ import annotations

import asyncio
import html
import logging
import re

import httpx
from bs4 import BeautifulSoup

from .chart_source import ChartData, ChartEntryData, ChartSource, DiscoveredChart

logger = logging.getLogger(__name__)

GERMAN_MONTHS = {
    "jänner": 1, "januar": 1, "februar": 2, "märz": 3, "maerz": 3, "april": 4,
    "mai": 5, "juni": 6, "juli": 7, "august": 8, "september": 9,
    "oktober": 10, "november": 11, "dezember": 12,
}

# Movements are encoded in the CSS class of the second column.
MOVEMENT_PATTERNS = [
    ("new", re.compile(r"\bnew\b", re.I)),
    ("up", re.compile(r"\bup\b", re.I)),
    ("down", re.compile(r"\bdown\b", re.I)),
    ("same", re.compile(r"\bsame\b", re.I)),
]


class FM4Source(ChartSource):
    def __init__(
        self,
        tag_url: str,
        timeout: float = 20.0,
        max_charts: int = 16,
        client: httpx.AsyncClient | None = None,
    ):
        self.tag_url = tag_url
        self.timeout = timeout
        self.max_charts = max_charts
        self._client = client

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                follow_redirects=True,
                headers={"User-Agent": "fm4-top40-downloader/1.0"},
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def discover(self) -> list[DiscoveredChart]:
        try:
            response = await self.client.get(self.tag_url)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.error("FM4 tag page request failed: %s", exc)
            return []

        soup = await asyncio.to_thread(BeautifulSoup, response.text, "html.parser")
        results: list[DiscoveredChart] = []
        for anchor in soup.find_all("a", href=True):
            href = anchor["href"]
            if not href.startswith("/story/"):
                continue
            url = self._absolute(href)
            title = anchor.get_text(" ", strip=True) or None
            results.append(DiscoveredChart(url=url, title=title))
        # Deduplicate while preserving order.
        seen: set[str] = set()
        unique: list[DiscoveredChart] = []
        for item in results:
            if item.url not in seen:
                seen.add(item.url)
                unique.append(item)
        logger.info("FM4 tag page yielded %s story links", len(unique))
        return unique[: self.max_charts]

    async def fetch_chart(self, url: str) -> ChartData | None:
        try:
            response = await self.client.get(url)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.error("FM4 chart fetch failed for %s: %s", url, exc)
            return None

        try:
            return await asyncio.to_thread(parse_chart_page, response.text, url)
        except ChartParseError as exc:
            logger.warning("FM4 chart parse failed for %s: %s", url, exc)
            return None

    def _absolute(self, href: str) -> str:
        if href.startswith("http"):
            return href
        base = self.tag_url.split("/tag/")[0]
        return base + href if href.startswith("/") else f"{base}/{href}"


class ChartParseError(Exception):
    pass


def _text(el) -> str:
    if el is None:
        return ""
    return html.unescape(el.get_text(" ", strip=True))


def parse_chart_page(page_html: str, source_url: str) -> ChartData:
    """Parse an FM4 chart article into a ChartData object."""
    soup = BeautifulSoup(page_html, "html.parser")

    table = soup.find("table", class_="charts")
    if table is None:
        raise ChartParseError("no table.charts found")

    rows = table.find("tbody").find_all("tr") if table.find("tbody") else table.find_all("tr")
    entries: list[ChartEntryData] = []
    for tr in rows:
        cells = tr.find_all("td")
        if len(cells) < 4:
            continue
        rank_text = _text(cells[0])
        try:
            rank = int(rank_text)
        except ValueError:
            continue
        artist = _text(cells[2])
        title = _text(cells[3])
        if not artist or not title:
            continue
        movement = None
        for name, pattern in MOVEMENT_PATTERNS:
            if pattern.search(cells[1].get("class", [""])[0] or ""):
                movement = name
                break
        previous_rank = _text(cells[4]) if len(cells) > 4 else None
        weeks = _text(cells[5]) if len(cells) > 5 else None
        entries.append(
            ChartEntryData(
                rank=rank,
                artist=artist,
                title=title,
                previous_rank=previous_rank or None,
                weeks_in_chart=weeks or None,
                movement=movement,
            )
        )

    if not entries:
        raise ChartParseError("table.charts contains no valid rows")

    title = _extract_title(soup) or "FM4 Top 40"
    chart_date = _extract_date(soup)

    # Guard against obviously incomplete imports.
    if len(entries) < 30:
        raise ChartParseError(
            f"only {len(entries)} entries parsed, refusing incomplete chart"
        )

    return ChartData(
        source_url=source_url,
        title=title,
        chart_date=chart_date,
        entries=sorted(entries, key=lambda e: e.rank),
    )


def _extract_title(soup: BeautifulSoup) -> str | None:
    h1 = soup.find("h1")
    if h1:
        text = _text(h1)
        if text:
            return text
    og = soup.find("meta", property="og:title")
    if og and og.get("content"):
        return og["content"].strip()
    return None


def _extract_date(soup: BeautifulSoup) -> str | None:
    date_div = soup.find("div", class_="date")
    if date_div:
        text = _text(date_div)
        iso = parse_german_date(text)
        if iso:
            return iso
    # Fall back to og:url slugs like .../fm4charts-8-8-2026-100
    og = soup.find("meta", property="og:url")
    if og and og.get("content"):
        m = re.search(r"(\d{1,2})-(\d{1,2})-(\d{4})(?:-|$)", og["content"])
        if m:
            day, month, year = m.groups()
            return f"{year}-{int(month):02d}-{int(day):02d}"
    return None


def parse_german_date(text: str) -> str | None:
    """Parse ``25. Juli 2026`` (and other German variants) into YYYY-MM-DD."""
    m = re.search(r"(\d{1,2})\.?\s+([A-Za-zäöüÄÖÜ]+)\s+(\d{4})", text)
    if not m:
        return None
    day = int(m.group(1))
    month = GERMAN_MONTHS.get(m.group(2).lower())
    if month is None:
        return None
    return f"{int(m.group(3)):04d}-{month:02d}-{day:02d}"