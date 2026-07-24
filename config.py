"""
config.py — Central configuration for the EduSanjal data extraction pipeline.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

BASE_DIR: Final[Path] = Path(__file__).parent.resolve()


@dataclass(frozen=True)
class Settings:

    # ── API ───────────────────────────────────────────────────────────────────
    api_base_url: str = "https://api.edusanjal.com.np/v1"
    api_college_path: str = "/college/"
    api_school_path: str = "/school/"

    # ── Categories ────────────────────────────────────────────────────────────
    categories: tuple[str, ...] = ("college", "school")

    # ── Pagination ────────────────────────────────────────────────────────────
    default_page_size: int = 24

    # ── HTTP Session ──────────────────────────────────────────────────────────
    request_timeout: int = 30
    max_retries: int = 5
    retry_backoff_base: float = 2.0
    retry_backoff_max: float = 32.0
    retry_on_statuses: tuple[int, ...] = (429, 500, 502, 503, 504)

    # ── Request Delay ─────────────────────────────────────────────────────────
    delay_min: float = 0.8
    delay_max: float = 2.5

    # ── Concurrency ───────────────────────────────────────────────────────────
    max_workers: int = 8

    # ── Paths ─────────────────────────────────────────────────────────────────
    db_path: Path = BASE_DIR / "output" / "edusanjal.db"
    log_dir: Path = BASE_DIR / "logs"
    output_dir: Path = BASE_DIR / "output"
    checkpoint_dir: Path = BASE_DIR / "checkpoints"

    csv_filename: str = "institutions"
    excel_filename: str = "institutions"
    summary_filename: str = "crawl_summary"

    # ── Logging ───────────────────────────────────────────────────────────────
    log_level: str = "INFO"
    log_format: str = "%(asctime)s | %(levelname)-8s | %(name)-30s | %(message)s"
    log_date_format: str = "%Y-%m-%d %H:%M:%S"

    # ── User-Agent pool ───────────────────────────────────────────────────────
    user_agents: tuple[str, ...] = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36 Edg/123.0.0.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    )

    # ── Accept-Language pool ──────────────────────────────────────────────────
    accept_languages: tuple[str, ...] = (
        "en-US,en;q=0.9",
        "en-GB,en;q=0.9",
        "en;q=0.9",
    )

    # ── Selenium ──────────────────────────────────────────────────────────────
    selenium_headless: bool = True
    selenium_page_load_timeout: int = 30
    selenium_implicit_wait: int = 10

    # ── Database ──────────────────────────────────────────────────────────────
    db_timeout: float = 30.0
    db_wal_mode: bool = True

    # ── Helpers ───────────────────────────────────────────────────────────────

    def api_listing_url(self, category: str) -> str:
        return f"{self.api_base_url}/{category}/"

    def api_detail_url(self, category: str, slug: str) -> str:
        return f"{self.api_base_url}/{category}/{slug}/"

    def ensure_directories(self) -> None:
        for directory in (
            self.db_path.parent,
            self.log_dir,
            self.output_dir,
            self.checkpoint_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)


def _apply_env_overrides(settings: Settings) -> Settings:
    overrides: dict = {}

    mapping = {
        "api_base_url":    ("API_BASE_URL",      str),
        "request_timeout": ("REQUEST_TIMEOUT",   int),
        "max_retries":     ("MAX_RETRIES",        int),
        "delay_min":       ("DELAY_MIN",          float),
        "delay_max":       ("DELAY_MAX",          float),
        "max_workers":     ("MAX_WORKERS",        int),
        "log_level":       ("LOG_LEVEL",          str),
    }

    for attr, (env_key, cast) in mapping.items():
        val = os.environ.get(f"EDUSANJAL_{env_key}")
        if val is not None:
            try:
                overrides[attr] = cast(val)
            except (ValueError, TypeError):
                pass

    db_path_str = os.environ.get("EDUSANJAL_DB_PATH")
    if db_path_str:
        overrides["db_path"] = Path(db_path_str)

    if not overrides:
        return settings

    import dataclasses
    return dataclasses.replace(settings, **overrides)


_settings_instance: Settings | None = None


def get_settings() -> Settings:
    global _settings_instance
    if _settings_instance is None:
        _settings_instance = _apply_env_overrides(Settings())
        _settings_instance.ensure_directories()
    return _settings_instance


settings = get_settings()
