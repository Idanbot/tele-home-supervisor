"""Logging helpers for tele_home_supervisor"""

import json
import logging
import os


class JsonFormatter(logging.Formatter):
    """Custom JSON formatter for structured logging."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "name": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        if hasattr(record, "extra"):
            log_entry.update(record.extra)  # type: ignore
        return json.dumps(log_entry)


def setup_logging() -> None:
    level_name = os.environ.get("LOG_LEVEL", "DEBUG").upper()
    level = getattr(logging, level_name, logging.DEBUG)
    log_format = os.environ.get("LOG_FORMAT", "text").lower()

    root = logging.getLogger()
    if not root.handlers:
        handler = logging.StreamHandler()
        if log_format == "json":
            formatter = JsonFormatter(datefmt="%Y-%m-%dT%H:%M:%SZ")
        else:
            formatter = logging.Formatter(
                fmt="%(asctime)s %(levelname)s %(name)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        handler.setFormatter(formatter)
        root.addHandler(handler)
    root.setLevel(level)

    # Suppress verbose HTTP request logs from telegram/httpx
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)


__all__ = ["setup_logging"]
