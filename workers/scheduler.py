from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import get_settings
from crawler.slug_manager import get_phase1_summary, run_slug_discovery
from database.db import Database
from database.models import CrawlStatus
from utils.delay import seconds_to_human
from utils.logger import get_logger
from workers.queue_manager import run_detail_scraping

logger = get_logger(__name__)


@dataclass
class PipelineOptions:

    skip_phase1:    bool       = False
    skip_phase2:    bool       = False
    force_restart:  bool       = False
    max_workers:    int | None = None
    batch_size:     int        = 50
    progress_every: int        = 100
    apply_delay:    bool       = True


@dataclass
class PipelineResult:

    run_id:        str
    phase1_status: CrawlStatus | None = None
    phase2_status: CrawlStatus | None = None
    total_elapsed: float = 0.0
    summary:       dict[str, Any] | None = None

    @property
    def success(self) -> bool:
        p2 = self.phase2_status
        if p2 is not None:
            return p2.completed > 0
        p1 = self.phase1_status
        if p1 is not None:
            return p1.total_slugs > 0
        return False


def run_pipeline(
    options: PipelineOptions | None = None,
) -> PipelineResult:

    if options is None:
        options = PipelineOptions()

    cfg    = get_settings()
    run_id = _generate_run_id()
    t_run  = time.monotonic()

    logger.info("=" * 70)
    logger.info("Pipeline started — run_id=%r", run_id)
    logger.info(
        "Options: skip_phase1=%s skip_phase2=%s force_restart=%s "
        "workers=%d batch_size=%d",
        options.skip_phase1, options.skip_phase2, options.force_restart,
        options.max_workers or cfg.max_workers, options.batch_size,
    )
    logger.info("=" * 70)

    phase1_status: CrawlStatus | None = None
    phase2_status: CrawlStatus | None = None

    with Database() as db:
        counts = db.get_table_counts()
        logger.info(
            "DB state: slugs=%d details=%d crawl_status=%d",
            counts.get("institution_slugs", 0),
            counts.get("institution_details", 0),
            counts.get("crawl_status", 0),
        )

        if not options.skip_phase1:
            logger.info("--- Phase 1: Slug Discovery ---")
            phase1_status = run_slug_discovery(
                db            = db,
                run_id        = run_id,
                force_restart = options.force_restart,
            )
            summary1 = get_phase1_summary(db)
            logger.info(
                "Phase 1 summary: %s",
                {k: v for k, v in summary1.items() if k != "checkpoint_exists"},
            )
        else:
            logger.info("Phase 1 skipped (skip_phase1=True)")
            total_slugs = db.get_total_slug_count()
            logger.info("Existing slugs in DB: %d", total_slugs)

        if not options.skip_phase2:
            pending = db.get_slug_counts().get("pending", 0)
            if pending == 0:
                logger.info(
                    "No pending slugs — Phase 2 skipped."
                )
            else:
                logger.info(
                    "--- Phase 2: Detail Scraping (%d pending slugs) ---",
                    pending,
                )
                phase2_status = run_detail_scraping(
                    db             = db,
                    run_id         = run_id,
                    max_workers    = options.max_workers,
                    batch_size     = options.batch_size,
                    progress_every = options.progress_every,
                    apply_delay    = options.apply_delay,
                )
        else:
            logger.info("Phase 2 skipped (skip_phase2=True)")

        if phase2_status is not None and phase2_status.completed > 0:
            _run_exports(db, run_id)
        elif options.skip_phase2 is False:
            logger.info("No detail records to export.")

        total_elapsed = time.monotonic() - t_run
        summary       = _build_summary(
            db            = db,
            run_id        = run_id,
            phase1_status = phase1_status,
            phase2_status = phase2_status,
            total_elapsed = total_elapsed,
        )
        _print_summary(summary)
        _save_summary(summary)

    result = PipelineResult(
        run_id        = run_id,
        phase1_status = phase1_status,
        phase2_status = phase2_status,
        total_elapsed = total_elapsed,
        summary       = summary,
    )

    logger.info(
        "Pipeline complete — run_id=%r elapsed=%s success=%s",
        run_id, seconds_to_human(total_elapsed), result.success,
    )
    return result


def _run_exports(db: Database, run_id: str) -> None:
    try:
        from storage.csv_export import export_all
        export_all(db=db, run_id=run_id)
    except Exception as exc:
        logger.error("Export failed: %s", exc, exc_info=True)


def _build_summary(
    db: Database,
    run_id: str,
    phase1_status: CrawlStatus | None,
    phase2_status: CrawlStatus | None,
    total_elapsed: float,
) -> dict[str, Any]:

    cfg          = get_settings()
    slug_counts  = db.get_slug_counts()
    detail_count = db.get_detail_count()

    summary: dict[str, Any] = {
        "run_id":       run_id,
        "total_elapsed": seconds_to_human(total_elapsed),
        "database":     str(cfg.db_path),
        "slugs": {
            "total":     db.get_total_slug_count(),
            "pending":   slug_counts.get("pending",   0),
            "completed": slug_counts.get("completed", 0),
            "failed":    slug_counts.get("failed",    0),
        },
        "details": {
            "total":    detail_count,
            "colleges": db.get_detail_count("college"),
            "schools":  db.get_detail_count("school"),
        },
    }

    if phase1_status:
        summary["phase1"] = phase1_status.to_summary_dict()
    if phase2_status:
        summary["phase2"] = phase2_status.to_summary_dict()

    return summary


def _print_summary(summary: dict[str, Any]) -> None:
    lines = [
        "",
        "=" * 60,
        "  PIPELINE SUMMARY",
        "=" * 60,
        f"  Run ID        : {summary['run_id']}",
        f"  Total Elapsed : {summary['total_elapsed']}",
        f"  Database      : {summary['database']}",
        "",
        "  SLUGS",
        f"    Total       : {summary['slugs']['total']}",
        f"    Completed   : {summary['slugs']['completed']}",
        f"    Pending     : {summary['slugs']['pending']}",
        f"    Failed      : {summary['slugs']['failed']}",
        "",
        "  INSTITUTION DETAILS",
        f"    Total       : {summary['details']['total']}",
        f"    Colleges    : {summary['details']['colleges']}",
        f"    Schools     : {summary['details']['schools']}",
    ]

    if "phase1" in summary:
        p1 = summary["phase1"]
        lines += [
            "",
            "  PHASE 1 (Slug Discovery)",
            f"    Elapsed     : {p1['elapsed']}",
            f"    Speed       : {p1['avg_speed_rps']}",
        ]

    if "phase2" in summary:
        p2 = summary["phase2"]
        lines += [
            "",
            "  PHASE 2 (Detail Scraping)",
            f"    Completed   : {p2['completed']}",
            f"    Failed      : {p2['failed']}",
            f"    Retried     : {p2['retried']}",
            f"    Success Rate: {p2['success_rate']}",
            f"    Elapsed     : {p2['elapsed']}",
            f"    Speed       : {p2['avg_speed_rps']}",
        ]

    lines.append("=" * 60)
    report = "\n".join(lines)
    print(report)
    logger.info(report)


def _save_summary(summary: dict[str, Any]) -> None:
    import json
    cfg  = get_settings()
    path = cfg.output_dir / f"{cfg.summary_filename}_{summary['run_id'][:10]}.json"
    try:
        with path.open("w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
        logger.info("Summary saved: %s", path)
    except OSError as exc:
        logger.warning("Could not save summary JSON: %s", exc)


def _generate_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
