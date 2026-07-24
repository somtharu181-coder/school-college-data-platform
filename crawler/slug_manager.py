from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from config import get_settings
from crawler.pagination import paginate
from database.db import Database
from database.models import CrawlStatus, SlugRecord
from utils.delay import seconds_to_human
from utils.logger import get_logger

logger = get_logger(__name__)

_CHECKPOINT_FILE = "slug_discovery.json"
FLUSH_EVERY      = 10


def run_slug_discovery(
    db: Database,
    run_id: str,
    force_restart: bool = False,
) -> CrawlStatus:

    started    = time.monotonic()
    status     = CrawlStatus(
        run_id     = run_id,
        phase      = "slug_discovery",
        started_at = _iso_now(),
    )
    checkpoint = _load_checkpoint(force_restart=force_restart)

    logger.info(
        "run_slug_discovery: run_id=%r force_restart=%s",
        run_id, force_restart,
    )

    if checkpoint["college_done"] and checkpoint["school_done"]:
        total_in_db = db.get_total_slug_count()
        if total_in_db == 0:
            logger.warning(
                "Checkpoint says discovery is complete but DB has 0 slugs — restarting."
            )
            checkpoint = _default_checkpoint()
            _save_checkpoint(checkpoint)
        else:
            logger.info(
                "Slug discovery already complete — %d slugs in DB.", total_in_db
            )
            counts = db.get_slug_counts()
            status.total_slugs = total_in_db
            status.completed   = counts.get("completed", 0)
            status.failed      = counts.get("failed", 0)
            status.finish(elapsed=time.monotonic() - started)
            db.save_crawl_status(status)
            return status

    total_inserted = 0

    if not checkpoint["college_done"]:
        start_page = max(1, checkpoint.get("college_last_page", 1))
        inserted   = _stream_category(db, "college", start_page, checkpoint)
        total_inserted += inserted
        checkpoint["college_done"] = True
        _save_checkpoint(checkpoint)
        logger.info("College scrape complete — %d new slugs inserted", inserted)
    else:
        logger.info("College slugs already crawled — skipping.")

    if not checkpoint["school_done"]:
        start_page = max(1, checkpoint.get("school_last_page", 1))
        inserted   = _stream_category(db, "school", start_page, checkpoint)
        total_inserted += inserted
        checkpoint["school_done"] = True
        _save_checkpoint(checkpoint)
        logger.info("School scrape complete — %d new slugs inserted", inserted)
    else:
        logger.info("School slugs already crawled — skipping.")

    total_in_db = db.get_total_slug_count()
    elapsed     = time.monotonic() - started
    status.total_slugs = total_in_db
    status.completed   = total_inserted
    status.finish(elapsed=elapsed)

    logger.info(
        "Slug discovery finished — %d total slugs (%d new) in %s at %.3f req/s",
        total_in_db, total_inserted,
        seconds_to_human(elapsed), status.avg_speed_rps,
    )
    db.save_crawl_status(status)
    return status


def _stream_category(
    db: Database,
    category: str,
    start_page: int,
    checkpoint: dict[str, Any],
) -> int:

    cfg           = get_settings()
    source_url    = cfg.api_listing_url(category)
    buffer:  list[SlugRecord] = []
    seen:    dict[tuple[str, str], bool] = {}
    total_inserted = 0
    pages_since_flush = 0
    last_page = start_page

    logger.info(
        "Streaming %r slugs from page %d (flush every %d pages)",
        category, start_page, FLUSH_EVERY,
    )

    for page_num, results, meta in paginate(category, start_page=start_page):
        total_pages = meta.get("pages", "?")

        for item in results:
            slug = item.get("slug")
            if not slug or not isinstance(slug, str):
                continue
            slug = slug.strip().lower()
            key  = (slug, category)
            if key not in seen:
                seen[key] = True
                buffer.append(SlugRecord(
                    slug       = slug,
                    category   = category,
                    source_url = source_url,
                ))

        pages_since_flush += 1
        last_page = page_num

        if pages_since_flush >= FLUSH_EVERY:
            if buffer:
                inserted = db.bulk_insert_slugs(buffer)
                total_inserted += inserted
                logger.info(
                    "[%s] Flushed page %d/%s — %d buffered, %d inserted, %d total",
                    category, page_num, total_pages,
                    len(buffer), inserted, total_inserted,
                )
                buffer.clear()

            checkpoint[f"{category}_last_page"] = page_num
            _save_checkpoint(checkpoint)
            pages_since_flush = 0

    if buffer:
        inserted = db.bulk_insert_slugs(buffer)
        total_inserted += inserted
        logger.info(
            "[%s] Final flush — %d buffered, %d inserted, %d total",
            category, len(buffer), inserted, total_inserted,
        )
        buffer.clear()

    checkpoint[f"{category}_last_page"] = last_page
    _save_checkpoint(checkpoint)
    return total_inserted


def _deduplicate(slugs: list[SlugRecord]) -> list[SlugRecord]:
    seen: dict[tuple[str, str], bool] = {}
    unique: list[SlugRecord] = []
    for record in slugs:
        key = (record.slug, record.category)
        if key not in seen:
            seen[key] = True
            unique.append(record)
    return unique


def _checkpoint_path() -> Path:
    return get_settings().checkpoint_dir / _CHECKPOINT_FILE


def _default_checkpoint() -> dict[str, Any]:
    return {
        "college_last_page": 1,
        "school_last_page":  1,
        "college_done":      False,
        "school_done":       False,
    }


def _load_checkpoint(force_restart: bool = False) -> dict[str, Any]:
    if force_restart:
        logger.info("force_restart=True — ignoring existing checkpoint.")
        return _default_checkpoint()

    path = _checkpoint_path()
    if not path.exists():
        return _default_checkpoint()

    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        logger.info(
            "Checkpoint loaded — college: page=%s done=%s | school: page=%s done=%s",
            data.get("college_last_page"), data.get("college_done"),
            data.get("school_last_page"),  data.get("school_done"),
        )
        checkpoint = _default_checkpoint()
        checkpoint.update(data)
        return checkpoint
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to read checkpoint (%s) — starting fresh.", exc)
        return _default_checkpoint()


def _save_checkpoint(checkpoint: dict[str, Any]) -> None:
    path = _checkpoint_path()
    try:
        with path.open("w", encoding="utf-8") as f:
            json.dump(checkpoint, f, indent=2)
    except OSError as exc:
        logger.warning("Failed to save checkpoint: %s", exc)


def get_phase1_summary(db: Database) -> dict[str, Any]:
    counts = db.get_slug_counts()
    total  = db.get_total_slug_count()
    with db._lock:
        cur = db._get_conn().cursor()
        cur.execute(
            "SELECT category, COUNT(*) FROM institution_slugs GROUP BY category;"
        )
        by_category = dict(cur.fetchall())
    return {
        "total":              total,
        "by_category":        by_category,
        "pending":            counts.get("pending",   0),
        "completed":          counts.get("completed", 0),
        "failed":             counts.get("failed",    0),
        "checkpoint_exists":  _checkpoint_path().exists(),
    }


def _iso_now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
