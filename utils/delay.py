from __future__ import annotations

import random
import time
from contextlib import contextmanager
from typing import Generator

from config import get_settings
from utils.logger import get_logger

logger = get_logger(__name__)


def polite_delay(
    min_seconds: float | None = None,
    max_seconds: float | None = None,
) -> float:
    cfg = get_settings()
    lo = min_seconds if min_seconds is not None else cfg.delay_min
    hi = max_seconds if max_seconds is not None else cfg.delay_max

    if lo > hi:
        lo, hi = hi, lo

    duration = random.uniform(lo, hi)
    logger.debug("Polite delay: %.2f s (window %.1f–%.1f s)", duration, lo, hi)
    time.sleep(duration)
    return duration


def backoff_delay(attempt: int) -> float:
    cfg = get_settings()
    base = cfg.retry_backoff_base ** attempt
    capped = min(base, cfg.retry_backoff_max)
    jittered = capped * random.uniform(0.5, 1.5)
    jittered = max(jittered, 1.0)

    logger.debug(
        "Backoff delay: %.2f s (attempt=%d, base=%.1f)",
        jittered, attempt, base,
    )
    time.sleep(jittered)
    return jittered


@contextmanager
def timed_block(min_duration: float) -> Generator[None, None, None]:
    start = time.monotonic()
    try:
        yield
    finally:
        elapsed = time.monotonic() - start
        remainder = min_duration - elapsed
        if remainder > 0:
            logger.debug(
                "timed_block: sleeping %.2f s more (target=%.1f s, elapsed=%.2f s)",
                remainder, min_duration, elapsed,
            )
            time.sleep(remainder)


def seconds_to_human(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, secs = divmod(int(seconds), 60)
    if minutes < 60:
        return f"{minutes}m {secs:02d}s"
    hours, mins = divmod(minutes, 60)
    return f"{hours}h {mins:02d}m {secs:02d}s"
