from __future__ import annotations

import time
from typing import Any

from config import get_settings
from database.db import Database
from database.models import InstitutionDetail, SlugRecord
from scraper.api_client import DetailFetchError, fetch_detail
from scraper.cleaner import clean
from scraper.parser import parse
from scraper.validator import validate
from utils.delay import polite_delay
from utils.logger import get_logger

logger = get_logger(__name__)


def scrape_institution(
    slug_record: SlugRecord,
    db: Database,
    skip_existing: bool = True,
    apply_delay: bool = True,
) -> InstitutionDetail:

    cfg      = get_settings()
    category = slug_record.category
    slug     = slug_record.slug
    t_start  = time.monotonic()

    logger.debug("Processing %s/%s", category, slug)

    if skip_existing and db.detail_exists(slug, category):
        logger.debug(
            "Skipping %s/%s — detail already exists in DB.",
            category, slug,
        )
        db.mark_slug_completed(slug, category)
        return InstitutionDetail(
            slug       = slug,
            category   = category,
            source_url = cfg.api_detail_url(category, slug),
        )

    source_url = cfg.api_detail_url(category, slug)

    try:
        raw: dict[str, Any] = fetch_detail(
            category    = category,
            slug        = slug,
            max_retries = cfg.max_retries,
        )
    except DetailFetchError:
        db.mark_slug_failed(slug, category)
        raise

    detail = parse(
        raw        = raw,
        category   = category,
        slug       = slug,
        source_url = source_url,
    )

    clean(detail)

    validation = validate(detail)
    if not validation.is_valid:
        logger.warning(
            "Validation issues for %s/%s: %d warning(s) — %s",
            category, slug,
            validation.warning_count,
            "; ".join(validation.warnings[:5]),
        )

    db.upsert_detail(detail)
    db.mark_slug_completed(slug, category)

    elapsed = time.monotonic() - t_start
    logger.info(
        "Scraped %s/%s in %.2fs | title=%r type=%r phone=%s email=%s valid=%s",
        category, slug, elapsed,
        detail.title, detail.type,
        detail.phone_str or "—",
        detail.email_str or "—",
        validation.is_valid,
    )

    if apply_delay:
        polite_delay()

    return detail
