from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Final

from config import get_settings


_RESET: Final[str] = "\033[0m"
_COLOURS: Final[dict[int, str]] = {
    logging.DEBUG:    "\033[36m",
    logging.INFO:     "\033[32m",
    logging.WARNING:  "\033[33m",
    logging.ERROR:    "\033[31m",
    logging.CRITICAL: "\033[35m",
}

_MAX_BYTES: Final[int] = 10 * 1024 * 1024
_BACKUP_COUNT: Final[int] = 5

_configured: bool = False


class _ColouredFormatter(logging.Formatter):

    def __init__(self, fmt: str, datefmt: str, use_colour: bool = True) -> None:
        super().__init__(fmt=fmt, datefmt=datefmt)
        self._use_colour = use_colour

    def format(self, record: logging.LogRecord) -> str:
        formatted = super().format(record)
        if not self._use_colour:
            return formatted
        colour = _COLOURS.get(record.levelno, _RESET)
        return f"{colour}{formatted}{_RESET}"


def _configure_root_logger() -> None:
    global _configured
    if _configured:
        return

    cfg = get_settings()
    numeric_level: int = getattr(logging, cfg.log_level.upper(), logging.INFO)

    root = logging.getLogger()
    root.setLevel(numeric_level)

    for noisy in ("urllib3", "charset_normalizer", "selenium"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    fmt = cfg.log_format
    datefmt = cfg.log_date_format

    log_file: Path = cfg.log_dir / "edusanjal_crawler.log"
    file_handler = RotatingFileHandler(
        filename=str(log_file),
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
        delay=False,
    )
    file_handler.setLevel(numeric_level)
    file_handler.setFormatter(logging.Formatter(fmt=fmt, datefmt=datefmt))

    console_handler = logging.StreamHandler(stream=sys.stderr)
    console_handler.setLevel(numeric_level)

    use_colour = hasattr(sys.stderr, "isatty") and sys.stderr.isatty()
    console_handler.setFormatter(
        _ColouredFormatter(fmt=fmt, datefmt=datefmt, use_colour=use_colour)
    )

    root.addHandler(file_handler)
    root.addHandler(console_handler)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    _configure_root_logger()
    return logging.getLogger(name)


def get_progress_logger() -> logging.Logger:
    _configure_root_logger()
    return logging.getLogger("progress")
