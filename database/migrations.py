from __future__ import annotations

import sqlite3

from utils.logger import get_logger

logger = get_logger(__name__)

CURRENT_VERSION: int = 3

_DDL_SCHEMA_VERSION = """
CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER NOT NULL,
    applied_at  TEXT    NOT NULL
);
"""

_DDL_INSTITUTION_SLUGS = """
CREATE TABLE IF NOT EXISTS institution_slugs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    slug        TEXT    NOT NULL,
    category    TEXT    NOT NULL CHECK(category IN ('college', 'school')),
    source_url  TEXT    NOT NULL,
    status      TEXT    NOT NULL DEFAULT 'pending'
                        CHECK(status IN ('pending', 'completed', 'failed')),
    retry_count INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL,
    UNIQUE(slug, category)
);
"""

_DDL_INSTITUTION_DETAILS = """
CREATE TABLE IF NOT EXISTS institution_details (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    slug         TEXT    NOT NULL,
    category     TEXT    NOT NULL CHECK(category IN ('college', 'school')),
    title        TEXT,
    established  TEXT,
    full_address TEXT,
    type         TEXT,
    phone        TEXT,
    email        TEXT,
    affiliations TEXT,
    source_url   TEXT    NOT NULL DEFAULT '',
    scraped_at   TEXT    NOT NULL,
    UNIQUE(slug, category)
);
"""

_DDL_CRAWL_STATUS = """
CREATE TABLE IF NOT EXISTS crawl_status (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT    NOT NULL,
    phase           TEXT    NOT NULL,
    total_slugs     INTEGER NOT NULL DEFAULT 0,
    completed       INTEGER NOT NULL DEFAULT 0,
    failed          INTEGER NOT NULL DEFAULT 0,
    retried         INTEGER NOT NULL DEFAULT 0,
    started_at      TEXT    NOT NULL,
    finished_at     TEXT,
    elapsed_seconds REAL    NOT NULL DEFAULT 0.0,
    avg_speed_rps   REAL    NOT NULL DEFAULT 0.0
);
"""

_DDL_INDEXES: list[str] = [
    "CREATE INDEX IF NOT EXISTS idx_slugs_status   ON institution_slugs (status);",
    "CREATE INDEX IF NOT EXISTS idx_slugs_category ON institution_slugs (category);",
    "CREATE INDEX IF NOT EXISTS idx_slugs_slug     ON institution_slugs (slug);",
    "CREATE INDEX IF NOT EXISTS idx_details_slug   ON institution_details (slug);",
    "CREATE INDEX IF NOT EXISTS idx_details_cat    ON institution_details (category);",
    "CREATE INDEX IF NOT EXISTS idx_crawl_run_id   ON crawl_status (run_id);",
]

_PRAGMAS: list[str] = [
    "PRAGMA journal_mode=WAL;",
    "PRAGMA synchronous=NORMAL;",
    "PRAGMA foreign_keys=ON;",
    "PRAGMA temp_store=MEMORY;",
    "PRAGMA mmap_size=268435456;",
    "PRAGMA cache_size=-32000;",
    "PRAGMA busy_timeout=30000;",
]

_MIGRATIONS: list[tuple[int, str, list[str]]] = [
    (
        1,
        "Initial schema: institution_slugs, institution_details, crawl_status",
        [
            _DDL_INSTITUTION_SLUGS,
            _DDL_INSTITUTION_DETAILS,
            _DDL_CRAWL_STATUS,
            *_DDL_INDEXES,
        ],
    ),
    (
        2,
        "Add source_url default and scraped_at to institution_details if missing",
        [
            "ALTER TABLE institution_details ADD COLUMN source_url TEXT NOT NULL DEFAULT '';",
            "ALTER TABLE institution_details ADD COLUMN scraped_at TEXT NOT NULL DEFAULT '';",
            "ALTER TABLE institution_slugs ADD COLUMN retry_count INTEGER NOT NULL DEFAULT 0;",
            "ALTER TABLE crawl_status ADD COLUMN retried INTEGER NOT NULL DEFAULT 0;",
            "ALTER TABLE crawl_status ADD COLUMN avg_speed_rps REAL NOT NULL DEFAULT 0.0;",
            "ALTER TABLE institution_details ADD COLUMN title TEXT;",
            "ALTER TABLE institution_details ADD COLUMN established TEXT;",
            "ALTER TABLE institution_details ADD COLUMN full_address TEXT;",
            "ALTER TABLE institution_details ADD COLUMN type TEXT;",
            "ALTER TABLE institution_details ADD COLUMN phone TEXT;",
            "ALTER TABLE institution_details ADD COLUMN email TEXT;",
            "ALTER TABLE institution_details ADD COLUMN affiliations TEXT;",
            "ALTER TABLE institution_details ADD COLUMN category TEXT NOT NULL DEFAULT 'college';",
        ],
    ),
    (
        3,
        "Add retry_count index and status check on slugs",
        [
            "CREATE INDEX IF NOT EXISTS idx_slugs_retry ON institution_slugs (retry_count);",
            "PRAGMA integrity_check;",
            "CREATE INDEX IF NOT EXISTS idx_details_scraped ON institution_details (scraped_at);",
            "CREATE INDEX IF NOT EXISTS idx_crawl_phase ON crawl_status (phase);",
        ],
    ),
]


def run_migrations(conn: sqlite3.Connection) -> None:
    _apply_pragmas(conn)
    _ensure_version_table(conn)

    applied_version = _get_applied_version(conn)
    logger.debug("Current schema version: %d", applied_version)

    pending = [m for m in _MIGRATIONS if m[0] > applied_version]

    if not pending:
        logger.debug("Schema is up-to-date (version %d).", applied_version)
        return

    for version, description, statements in pending:
        logger.info("Applying migration v%d: %s", version, description)
        _apply_migration(conn, version, statements)
        logger.info("Migration v%d applied successfully.", version)

    logger.info(
        "All migrations applied — schema is now at version %d.",
        CURRENT_VERSION,
    )


def get_table_info(conn: sqlite3.Connection) -> dict[str, int]:
    tables = ("institution_slugs", "institution_details", "crawl_status")
    result: dict[str, int] = {}
    cursor = conn.cursor()
    for table in tables:
        try:
            cursor.execute(f"SELECT COUNT(*) FROM {table};")
            result[table] = cursor.fetchone()[0]
        except sqlite3.OperationalError:
            result[table] = -1
    return result


def _apply_pragmas(conn: sqlite3.Connection) -> None:
    cursor = conn.cursor()
    for pragma in _PRAGMAS:
        cursor.execute(pragma)
        logger.debug("Pragma applied: %s", pragma.strip())
    conn.commit()


def _ensure_version_table(conn: sqlite3.Connection) -> None:
    conn.execute(_DDL_SCHEMA_VERSION)
    conn.commit()


def _get_applied_version(conn: sqlite3.Connection) -> int:
    cursor = conn.cursor()
    cursor.execute("SELECT MAX(version) FROM schema_version;")
    row = cursor.fetchone()
    if row and row[0] is not None:
        return int(row[0])
    return 0


def _apply_migration(
    conn: sqlite3.Connection,
    version: int,
    statements: list[str],
) -> None:
    from datetime import datetime, timezone
    applied_at = datetime.now(timezone.utc).isoformat()

    try:
        with conn:
            for stmt in statements:
                try:
                    conn.execute(stmt)
                except sqlite3.OperationalError as e:
                    if "duplicate column name" in str(e).lower():
                        logger.debug("Column already exists (skipped): %s", str(e))
                    else:
                        raise
            conn.execute(
                "INSERT INTO schema_version (version, applied_at) VALUES (?, ?);",
                (version, applied_at),
            )
    except sqlite3.DatabaseError as exc:
        logger.error("Migration v%d failed: %s", version, exc)
        raise
