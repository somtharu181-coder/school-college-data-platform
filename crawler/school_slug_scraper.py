from __future__ import annotations

from typing import Any

from config import get_settings
from crawler.pagination import get_listing_meta, paginate
from database.models import SlugRecord
from utils.logger import get_logger

logger = get_logger(__name__)

CATEGORY: str = "school"


def scrape_school_slugs(
    start_page: int = 1,
    progress_every: int = 50,
) -> list[SlugRecord]:

    cfg = get_settings()

    try:
        meta = get_listing_meta(CATEGORY)
        total_pages = meta.get("pages", "?")
        total_count = meta.get("count", "?")
        logger.info(
            "School slug scrape: %s institutions across %s pages "
            "(page_size=%s, start_page=%d)",
            total_count, total_pages, meta.get("size", 24), start_page,
        )
    except Exception as exc:
        logger.warning("Could not fetch pre-flight metadata: %s", exc)
        total_pages = "?"
        total_count = "?"

    slugs: list[SlugRecord] = []
    pages_crawled: int = 0

    for page_num, results, pagination_meta in paginate(
        CATEGORY,
        start_page=start_page,
    ):
        page_slugs = _extract_slugs(results, pagination_meta)
        slugs.extend(page_slugs)
        pages_crawled += 1

        if pages_crawled % progress_every == 0:
            total_pages_actual = pagination_meta.get("pages", "?")
            pct = (page_num / total_pages_actual * 100) if isinstance(total_pages_actual, int) else 0
            logger.info(
                "School progress: page %d/%s (%.1f%%) — %d slugs collected",
                page_num, total_pages_actual, pct, len(slugs),
            )

    logger.info(
        "School slug scrape complete — %d pages crawled, %d slugs collected.",
        pages_crawled, len(slugs),
    )
    return slugs


def _extract_slugs(
    results: list[dict[str, Any]],
    pagination_meta: dict[str, Any],
) -> list[SlugRecord]:

    cfg = get_settings()
    source_url = cfg.api_listing_url(CATEGORY)
    records: list[SlugRecord] = []

    for item in results:
        slug = item.get("slug")

        if not slug:
            logger.warning(
                "School result missing slug field: %s",
                str(item)[:120],
            )
            continue

        if not isinstance(slug, str) or not slug.strip():
            logger.warning("Skipping school result with invalid slug: %r", slug)
            continue

        records.append(
            SlugRecord(
                slug       = slug.strip().lower(),
                category   = CATEGORY,
                source_url = source_url,
            )
        )

    return records
