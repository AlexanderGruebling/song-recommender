"""Structured logging setup.

Logs are emitted as JSON-ish key=value lines on stderr so they are easy to
grep and can be parsed by journald. Secrets are never logged.
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone


class KeyValueFormatter(logging.Formatter):
    """Format records as ``ts=... level=... logger=... message key=value``."""

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        parts = [
            f"ts={ts}",
            f"level={record.levelname}",
            f"logger={record.name}",
        ]
        if record.exc_info:
            record.exc_text = self.formatException(record.exc_info)
        message = record.getMessage()
        if message:
            parts.append(message)
        extra = getattr(record, "extra", None)
        if isinstance(extra, dict):
            parts.extend(f"{k}={v}" for k, v in extra.items())
        if record.exc_text:
            parts.append(record.exc_text.replace("\n", " | "))
        return " ".join(parts)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(KeyValueFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)