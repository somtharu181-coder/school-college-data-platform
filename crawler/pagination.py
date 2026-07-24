from __future__ import annotations

from typing import Any, Generator

from config import get_settings
from utils.delay import polite_delay
from utils.logger import get_logger
from utils.session import refresh_headers, request_get

logger = get_logger(__name__)

PageResult = tuple[int, list[dict[str, Any]], dict[str, Any]]


def paginate(
    category: str,
    start_page: int = 1,
    delay_min: float | None = None,
    delay_max: float | None = None,
) -> Generator[PageResult, None, None]:

    cfg = get_settings()
    base_url = cfg.api_listing_url(category)

    current_url: str = base_url
    current_params: dict | None = {"page": start_page} if start_page > 1 else None

    page_num: int = start_page
    consecutive_errors: int = 0
    max_consecutive_errors: int = 3

    logger.info(
        "Starting pagination for category=%r from page=%d",
        category, start_page,
    )

    while current_url:
        refresh_headers(category=category)

        try:
            response = request_get(
                url=current_url,
                params=current_params,
            )
        except Exception as exc:
            consecutive_errors += 1
            logger.error(
                "Request exception on page %d (attempt %d): %s",
                page_num, consecutive_errors, exc,
            )
            if consecutive_errors >= max_consecutive_errors:
                logger.critical(
                    "Too many consecutive errors (%d) at page %d — aborting.",
                    consecutive_errors, page_num,
                )
                return
            polite_delay(min_seconds=5.0, max_seconds=10.0)
            continue

        if response.status_code == 429:
            logger.warning(
                "Rate limited (429) on page %d — backing off.", page_num
            )
            polite_delay(min_seconds=30.0, max_seconds=60.0)
            continue

        if response.status_code != 200:
            consecutive_errors += 1
            logger.warning(
                "HTTP %d on page %d (consecutive errors: %d)",
                response.status_code, page_num, consecutive_errors,
            )
            if consecutive_errors >= max_consecutive_errors:
                logger.critical(
                    "Too many consecutive HTTP errors (%d) — aborting.",
                    consecutive_errors,
                )
                return
            polite_delay(min_seconds=5.0, max_seconds=10.0)
            continue

        try:
            data: dict[str, Any] = response.json()
        except Exception as exc:
            consecutive_errors += 1
            logger.error(
                "JSON decode error on page %d: %s | body: %s",
                page_num, exc, response.text[:200],
            )
            if consecutive_errors >= max_consecutive_errors:
                return
            polite_delay(min_seconds=5.0, max_seconds=10.0)
            continue

        pagination_meta = data.get("pagination")
        results         = data.get("results")

        if not isinstance(pagination_meta, dict) or not isinstance(results, list):
            consecutive_errors += 1
            logger.error(
                "Unexpected response structure on page %d: pagination=%s, results=%s",
                page_num,
                type(pagination_meta).__name__,
                type(results).__name__,
            )
            if consecutive_errors >= max_consecutive_errors:
                return

            _next = _build_next_url(base_url, page_num + 1)
            current_url = _next
            current_params = None
            page_num += 1
            continue

        consecutive_errors = 0
        total_pages: int     = pagination_meta.get("pages", 0)
        total_count: int     = pagination_meta.get("count", 0)
        next_url: str | None = pagination_meta.get("next")

        logger.info(
            "[%s] Page %d/%s — %d results (total=%d) next=%s",
            category,
            page_num,
            total_pages,
            len(results),
            total_count,
            next_url if next_url else "END",
        )

        yield page_num, results, pagination_meta

        if not next_url:
            logger.info(
                "Pagination complete for %r — %d pages, %d total items.",
                category, total_pages, total_count,
            )
            break

        current_url    = next_url
        current_params = None
        page_num      += 1

        polite_delay(min_seconds=delay_min, max_seconds=delay_max)


def get_listing_meta(category: str) -> dict[str, Any]:
    cfg = get_settings()
    url = cfg.api_listing_url(category)
    refresh_headers(category=category)

    try:
        response = request_get(url=url, params={"page": 1})
        response.raise_for_status()
        data = response.json()
        meta = data.get("pagination", {})
        logger.debug(
            "Listing meta for %r: count=%s pages=%s",
            category, meta.get("count"), meta.get("pages"),
        )
        return meta
    except Exception as exc:
        raise RuntimeError(
            f"Failed to fetch listing metadata for category={category!r}: {exc}"
        ) from exc


def _build_next_url(base_url: str, page: int) -> str:
    separator = "&" if "?" in base_url else "?"
    return f"{base_url}{separator}page={page}"
