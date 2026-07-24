from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

from database.db import Database
from database.models import InstitutionDetail, SlugRecord
from scraper.api_client import DetailFetchError
from scraper.institution_scraper import scrape_institution
from utils.logger import get_logger
from utils.session import close_session

logger = get_logger(__name__)


@dataclass
class WorkerResult:

    slug:        str
    category:    str
    success:     bool                      = False
    detail:      InstitutionDetail | None  = None
    error:       Exception | None          = None
    elapsed:     float                     = 0.0
    thread_name: str                       = ""
    attempt:     int                       = 1

    @property
    def is_retryable(self) -> bool:
        if self.success:
            return False
        if isinstance(self.error, DetailFetchError):
            return self.error.last_status != 404
        return True

    def __repr__(self) -> str:
        status = "OK" if self.success else f"FAIL({type(self.error).__name__})"
        return (
            f"WorkerResult({self.category}/{self.slug} "
            f"{status} {self.elapsed:.2f}s)"
        )


def run_worker(
    slug_record: SlugRecord,
    db: Database,
    apply_delay: bool = True,
) -> WorkerResult:

    slug        = slug_record.slug
    category    = slug_record.category
    thread_name = threading.current_thread().name
    t_start     = time.monotonic()

    logger.debug(
        "[%s] Starting %s/%s",
        thread_name, category, slug,
    )

    try:
        detail = scrape_institution(
            slug_record   = slug_record,
            db            = db,
            skip_existing = True,
            apply_delay   = apply_delay,
        )

        elapsed = time.monotonic() - t_start
        logger.debug(
            "[%s] Completed %s/%s in %.2fs",
            thread_name, category, slug, elapsed,
        )

        return WorkerResult(
            slug        = slug,
            category    = category,
            success     = True,
            detail      = detail,
            elapsed     = elapsed,
            thread_name = thread_name,
        )

    except DetailFetchError as exc:
        elapsed = time.monotonic() - t_start
        log_level = "warning" if exc.last_status == 404 else "error"
        getattr(logger, log_level)(
            "[%s] %s/%s fetch failed: %s (status=%d attempts=%d elapsed=%.2fs)",
            thread_name, category, slug,
            type(exc).__name__, exc.last_status, exc.attempts, elapsed,
        )
        return WorkerResult(
            slug        = slug,
            category    = category,
            success     = False,
            error       = exc,
            elapsed     = elapsed,
            thread_name = thread_name,
        )

    except Exception as exc:
        elapsed = time.monotonic() - t_start
        logger.error(
            "[%s] %s/%s unexpected error: %s: %s (elapsed=%.2fs)",
            thread_name, category, slug,
            type(exc).__name__, str(exc)[:200], elapsed,
            exc_info=True,
        )
        return WorkerResult(
            slug        = slug,
            category    = category,
            success     = False,
            error       = exc,
            elapsed     = elapsed,
            thread_name = thread_name,
        )


def worker_thread_cleanup() -> None:
    close_session()
    logger.debug(
        "Thread cleanup complete for: %s",
        threading.current_thread().name,
    )
