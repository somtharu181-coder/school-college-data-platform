from __future__ import annotations

from pathlib import Path
from typing import Any

from config import get_settings
from database.db import Database
from database.models import InstitutionDetail
from utils.logger import get_logger

logger = get_logger(__name__)


def bulk_save_details(
    details: list[InstitutionDetail],
    db: Database,
) -> int:
    if not details:
        return 0
    count = db.bulk_upsert_details(details)
    logger.debug("bulk_save_details: %d records upserted", count)
    return count


def get_export_frame(
    db: Database,
    category: str | None = None,
) -> "pd.DataFrame":
    import pandas as pd
    from storage.csv_export import EXPORT_COLUMNS

    rows = [
        d.to_export_dict()
        for d in db.iter_all_details(category=category, batch_size=500)
    ]
    if not rows:
        return pd.DataFrame(columns=EXPORT_COLUMNS)
    return pd.DataFrame(rows, columns=EXPORT_COLUMNS)


def vacuum_database(db: Database) -> None:
    logger.info("Running VACUUM on database ...")
    try:
        with db._lock:
            conn = db._get_conn()
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
            conn.execute("VACUUM;")
        logger.info("VACUUM complete.")
    except Exception as exc:
        logger.warning("VACUUM failed: %s", exc)


def get_db_stats(db: Database) -> dict[str, Any]:
    cfg    = get_settings()
    counts = db.get_table_counts()
    slugs  = db.get_slug_counts()

    file_size_mb: float = 0.0
    if cfg.db_path.exists():
        file_size_mb = round(cfg.db_path.stat().st_size / (1024 * 1024), 2)

    return {
        "file_size_mb": file_size_mb,
        "table_counts": counts,
        "slug_counts":  slugs,
        "details": {
            "total":    db.get_detail_count(),
            "colleges": db.get_detail_count("college"),
            "schools":  db.get_detail_count("school"),
        },
    }
