from __future__ import annotations

import time
from typing import Any

import requests

from config import get_settings
from utils.delay import backoff_delay, polite_delay
from utils.logger import get_logger
from utils.session import refresh_headers, request_get

logger = get_logger(__name__)


class DetailFetchError(Exception):

    def __init__(
        self,
        slug: str,
        category: str,
        attempts: int,
        last_status: int = 0,
        message: str = "",
    ) -> None:
        self.slug        = slug
        self.category    = category
        self.attempts    = attempts
        self.last_status = last_status
        super().__init__(
            message or (
                f"Failed to fetch {category}/{slug} after {attempts} attempts "
                f"(last HTTP status: {last_status})"
            )
        )


def fetch_detail(
    category: str,
    slug: str,
    max_retries: int | None = None,
) -> dict[str, Any]:

    cfg         = get_settings()
    retries     = max_retries if max_retries is not None else cfg.max_retries
    url         = cfg.api_detail_url(category, slug)
    last_status = 0
    t_start     = time.monotonic()

    for attempt in range(1, retries + 2):
        refresh_headers(category=category, slug=slug)

        try:
            response = request_get(url=url)
        except requests.exceptions.Timeout as exc:
            last_status = 0
            logger.warning(
                "Timeout fetching %s/%s (attempt %d/%d): %s",
                category, slug, attempt, retries + 1, exc,
            )
            if attempt <= retries:
                backoff_delay(attempt)
            continue

        except requests.exceptions.ConnectionError as exc:
            last_status = 0
            logger.warning(
                "Connection error fetching %s/%s (attempt %d/%d): %s",
                category, slug, attempt, retries + 1, exc,
            )
            if attempt <= retries:
                backoff_delay(attempt)
            continue

        except requests.exceptions.RequestException as exc:
            last_status = 0
            logger.warning(
                "Request exception fetching %s/%s (attempt %d/%d): %s",
                category, slug, attempt, retries + 1, exc,
            )
            if attempt <= retries:
                backoff_delay(attempt)
            continue

        last_status = response.status_code

        if response.status_code == 429:
            retry_after = _parse_retry_after(response)
            logger.warning(
                "Rate limited (429) fetching %s/%s (attempt %d/%d) — retry after %.0fs",
                category, slug, attempt, retries + 1, retry_after,
            )
            if attempt <= retries:
                polite_delay(min_seconds=retry_after, max_seconds=retry_after + 10)
            continue

        if response.status_code in cfg.retry_on_statuses:
            logger.warning(
                "Retryable HTTP %d fetching %s/%s (attempt %d/%d)",
                response.status_code, category, slug, attempt, retries + 1,
            )
            if attempt <= retries:
                backoff_delay(attempt)
            continue

        if response.status_code == 404:
            logger.warning(
                "404 Not Found: %s/%s — skipping permanently.",
                category, slug,
            )
            raise DetailFetchError(
                slug=slug,
                category=category,
                attempts=attempt,
                last_status=404,
                message=f"404 Not Found: {url}",
            )

        if response.status_code != 200:
            logger.warning(
                "Unexpected HTTP %d for %s/%s — raising.",
                response.status_code, category, slug,
            )
            raise DetailFetchError(
                slug=slug,
                category=category,
                attempts=attempt,
                last_status=response.status_code,
            )

        try:
            data: dict[str, Any] = response.json()
        except Exception as exc:
            logger.warning(
                "JSON decode error for %s/%s (attempt %d/%d): %s | body: %s",
                category, slug, attempt, retries + 1,
                exc, response.text[:200],
            )
            if attempt <= retries:
                backoff_delay(attempt)
            continue

        elapsed = time.monotonic() - t_start
        logger.debug(
            "Fetched %s/%s in %.2fs (attempt %d)",
            category, slug, elapsed, attempt,
        )
        return data

    elapsed = time.monotonic() - t_start
    logger.error(
        "Exhausted %d retries for %s/%s after %.2fs (last status %d)",
        retries + 1, category, slug, elapsed, last_status,
    )
    raise DetailFetchError(
        slug=slug,
        category=category,
        attempts=retries + 1,
        last_status=last_status,
    )


def _parse_retry_after(response: requests.Response) -> float:
    header = response.headers.get("Retry-After", "")
    try:
        return max(1.0, float(header))
    except (ValueError, TypeError):
        return 30.0
