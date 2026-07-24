from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Iterator

from config import get_settings
from database.migrations import run_migrations, get_table_info
from database.models import CrawlStatus, InstitutionDetail, SlugRecord, SlugStatus
from utils.logger import get_logger

logger = get_logger(__name__)


class Database:

    def __init__(self, db_path: Path | None = None) -> None:
        cfg = get_settings()
        self._path: Path = db_path or cfg.db_path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._local = threading.local()
        conn = self._open_conn()
        run_migrations(conn)
        self._local.conn = conn
        logger.info("Database opened: %s", self._path)

    def _open_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            str(self._path),
            check_same_thread=False,
            isolation_level=None,
            timeout=get_settings().db_timeout,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA cache_size=-16000;")
        conn.execute("PRAGMA busy_timeout=10000;")
        return conn

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = self._open_conn()
        return self._local.conn

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, *_) -> None:
        self.close()

    def close(self) -> None:
        try:
            conn = self._local.conn if hasattr(self._local, "conn") else None
            if conn:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
                conn.close()
                self._local.conn = None
        except Exception as exc:
            logger.warning("Error closing database: %s", exc)

    def get_table_counts(self) -> dict[str, int]:
        return get_table_info(self._get_conn())

    def bulk_insert_slugs(self, slugs: list[SlugRecord]) -> int:
        if not slugs:
            return 0
        sql = (
            "INSERT OR IGNORE INTO institution_slugs "
            "(slug, category, source_url, status, retry_count, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?);"
        )
        rows = [s.to_db_row() for s in slugs]
        with self._lock:
            conn = self._get_conn()
            with conn:
                cur = conn.cursor()
                cur.executemany(sql, rows)
                inserted = cur.rowcount
        logger.debug("bulk_insert_slugs: %d in, %d new", len(slugs), inserted)
        return inserted

    def get_slug_counts(self) -> dict[str, int]:
        with self._lock:
            cur = self._get_conn().cursor()
            cur.execute("SELECT status, COUNT(*) FROM institution_slugs GROUP BY status;")
            rows = cur.fetchall()
        result = {SlugStatus.PENDING: 0, SlugStatus.COMPLETED: 0, SlugStatus.FAILED: 0}
        for row in rows:
            result[row[0]] = row[1]
        return result

    def get_total_slug_count(self) -> int:
        with self._lock:
            cur = self._get_conn().cursor()
            cur.execute("SELECT COUNT(*) FROM institution_slugs;")
            return cur.fetchone()[0]

    def iter_pending_slugs(self, batch_size: int = 100) -> Iterator[SlugRecord]:
        last_id = 0
        while True:
            with self._lock:
                cur = self._get_conn().cursor()
                cur.execute(
                    "SELECT id, slug, category, source_url, status, retry_count, created_at, updated_at "
                    "FROM institution_slugs WHERE status=? AND id>? ORDER BY id ASC LIMIT ?;",
                    (SlugStatus.PENDING, last_id, batch_size),
                )
                rows = cur.fetchall()
            if not rows:
                break
            for row in rows:
                yield SlugRecord.from_db_row(tuple(row))
                last_id = row[0]

    def get_pending_slug_batch(self, limit: int = 50, max_retries: int | None = None) -> list[SlugRecord]:
        with self._lock:
            cur = self._get_conn().cursor()
            if max_retries is not None:
                cur.execute(
                    "SELECT id, slug, category, source_url, status, retry_count, created_at, updated_at "
                    "FROM institution_slugs WHERE status=? OR (status=? AND retry_count<?) "
                    "ORDER BY id ASC LIMIT ?;",
                    (SlugStatus.PENDING, SlugStatus.FAILED, max_retries, limit),
                )
            else:
                cur.execute(
                    "SELECT id, slug, category, source_url, status, retry_count, created_at, updated_at "
                    "FROM institution_slugs WHERE status=? ORDER BY id ASC LIMIT ?;",
                    (SlugStatus.PENDING, limit),
                )
            return [SlugRecord.from_db_row(tuple(row)) for row in cur.fetchall()]

    def mark_slug_completed(self, slug: str, category: str) -> None:
        with self._lock:
            conn = self._get_conn()
            with conn:
                conn.execute(
                    "UPDATE institution_slugs SET status=?, updated_at=datetime('now') "
                    "WHERE slug=? AND category=?;",
                    (SlugStatus.COMPLETED, slug, category),
                )

    def mark_slug_failed(self, slug: str, category: str) -> None:
        with self._lock:
            conn = self._get_conn()
            with conn:
                conn.execute(
                    "UPDATE institution_slugs SET status=?, retry_count=retry_count+1, "
                    "updated_at=datetime('now') WHERE slug=? AND category=?;",
                    (SlugStatus.FAILED, slug, category),
                )

    def requeue_failed_slugs(self, max_retries: int) -> int:
        with self._lock:
            conn = self._get_conn()
            with conn:
                cur = conn.cursor()
                cur.execute(
                    "UPDATE institution_slugs SET status=?, updated_at=datetime('now') "
                    "WHERE status=? AND retry_count<?;",
                    (SlugStatus.PENDING, SlugStatus.FAILED, max_retries),
                )
                count = cur.rowcount
        logger.info("Requeued %d failed slugs (retry_count < %d)", count, max_retries)
        return count

    def upsert_detail(self, detail: InstitutionDetail) -> None:
        sql = (
            "INSERT OR REPLACE INTO institution_details "
            "(slug, category, title, established, full_address, type, "
            "phone, email, affiliations, source_url, scraped_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);"
        )
        with self._lock:
            conn = self._get_conn()
            with conn:
                conn.execute(sql, detail.to_db_row())
        logger.debug("Upserted detail: %s/%s", detail.category, detail.slug)

    def bulk_upsert_details(self, details: list[InstitutionDetail]) -> int:
        if not details:
            return 0
        sql = (
            "INSERT OR REPLACE INTO institution_details "
            "(slug, category, title, established, full_address, type, "
            "phone, email, affiliations, source_url, scraped_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);"
        )
        rows = [d.to_db_row() for d in details]
        with self._lock:
            conn = self._get_conn()
            with conn:
                cur = conn.cursor()
                cur.executemany(sql, rows)
                count = cur.rowcount
        return count

    def detail_exists(self, slug: str, category: str) -> bool:
        with self._lock:
            cur = self._get_conn().cursor()
            cur.execute(
                "SELECT 1 FROM institution_details WHERE slug=? AND category=? LIMIT 1;",
                (slug, category),
            )
            return cur.fetchone() is not None

    def iter_all_details(self, category: str | None = None, batch_size: int = 500) -> Iterator[InstitutionDetail]:
        select = (
            "SELECT id, slug, category, title, established, full_address, "
            "type, phone, email, affiliations, source_url, scraped_at "
            "FROM institution_details"
        )
        offset = 0
        while True:
            with self._lock:
                cur = self._get_conn().cursor()
                if category:
                    cur.execute(
                        f"{select} WHERE category=? ORDER BY id ASC LIMIT ? OFFSET ?;",
                        (category, batch_size, offset),
                    )
                else:
                    cur.execute(
                        f"{select} ORDER BY id ASC LIMIT ? OFFSET ?;",
                        (batch_size, offset),
                    )
                rows = cur.fetchall()
            if not rows:
                break
            for row in rows:
                yield InstitutionDetail.from_db_row(tuple(row))
            offset += len(rows)
            if len(rows) < batch_size:
                break

    def get_detail_count(self, category: str | None = None) -> int:
        with self._lock:
            cur = self._get_conn().cursor()
            if category:
                cur.execute("SELECT COUNT(*) FROM institution_details WHERE category=?;", (category,))
            else:
                cur.execute("SELECT COUNT(*) FROM institution_details;")
            return cur.fetchone()[0]

    def save_crawl_status(self, status: CrawlStatus) -> None:
        sql = (
            "INSERT INTO crawl_status "
            "(run_id, phase, total_slugs, completed, failed, retried, "
            "started_at, finished_at, elapsed_seconds, avg_speed_rps) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);"
        )
        with self._lock:
            conn = self._get_conn()
            with conn:
                conn.execute(sql, status.to_db_row())

    def get_latest_crawl_status(self) -> list[CrawlStatus]:
        with self._lock:
            cur = self._get_conn().cursor()
            cur.execute("SELECT run_id FROM crawl_status ORDER BY started_at DESC LIMIT 1;")
            row = cur.fetchone()
            if not row:
                return []
            run_id = row[0]
            cur.execute(
                "SELECT run_id, phase, total_slugs, completed, failed, retried, "
                "started_at, finished_at, elapsed_seconds, avg_speed_rps "
                "FROM crawl_status WHERE run_id=? ORDER BY started_at ASC;",
                (run_id,),
            )
            rows = cur.fetchall()
        statuses = []
        for r in rows:
            cs = CrawlStatus(
                run_id=r[0], phase=r[1], total_slugs=r[2], completed=r[3],
                failed=r[4], retried=r[5], started_at=r[6], finished_at=r[7],
                elapsed_seconds=r[8], avg_speed_rps=r[9],
            )
            statuses.append(cs)
        return statuses
