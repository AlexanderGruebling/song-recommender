"""Application configuration.

All settings are read from environment variables (optionally from a `.env`
file in the working directory). Secret values are never exposed through the
API or logged.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Server ---
    host: str = "0.0.0.0"
    port: int = 8000

    # --- Data ---
    data_dir: Path = Path("./data")
    database_url: str | None = None

    # --- FM4 ---
    fm4_poll_interval: str = "6h"
    fm4_tag_url: str = "https://fm4.orf.at/tag/Musik/FM4%20Charts"
    fm4_request_timeout: float = 20.0
    fm4_max_charts_per_run: int = 16

    # --- YouTube ---
    youtube_api_key: str | None = None
    youtube_max_results: int = 10
    youtube_candidates: int = 3

    # --- Downloads ---
    download_directory: Path = Path("./music")
    ytdlp_path: str = "yt-dlp"
    ytdlp_format: str = "bestaudio/best"
    ytdlp_extract_audio: bool = True
    ytdlp_audio_format: str = "mp3"
    ytdlp_audio_quality: str = "0"
    download_concurrency: int = 1
    # Maximum wall-clock time for a single yt-dlp run ("30m", "1h", seconds;
    # 0 disables). Prevents one hung download from blocking the queue.
    download_timeout: str = "30m"

    # --- Logging ---
    log_level: str = "INFO"

    # --- Internal (derived) ---
    timezone: str = "Europe/Vienna"

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{(self.data_dir / 'fm4top40.db').resolve()}"

    @property
    def resolved_download_dir(self) -> Path:
        self.download_directory.mkdir(parents=True, exist_ok=True)
        return self.download_directory.resolve()

    @property
    def poll_interval_seconds(self) -> int:
        return parse_interval(self.fm4_poll_interval)

    @property
    def download_timeout_seconds(self) -> int:
        return parse_interval(self.download_timeout)


def parse_interval(value: str) -> int:
    """Parse a duration string such as ``6h``, ``30m`` or ``86400`` into seconds."""
    value = value.strip().lower()
    if not value:
        return 0
    try:
        return int(value)
    except ValueError:
        pass
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    num = ""
    for ch in value:
        if ch.isdigit() or ch == ".":
            num += ch
        elif ch in units:
            try:
                return int(float(num) * units[ch])
            except ValueError:
                break
    raise ValueError(f"cannot parse interval: {value!r}")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()