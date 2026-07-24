from __future__ import annotations

import argparse
import signal
import sys
import threading
import time

from config import get_settings
from utils.logger import get_logger
from workers.scheduler import PipelineOptions, run_pipeline

logger = get_logger(__name__)

_shutdown_event = threading.Event()
_shutdown_requested = False


def _handle_signal(signum, frame):
    global _shutdown_requested
    if _shutdown_requested:
        print("\n\nForced exit. Some data may not be saved.", flush=True)
        sys.exit(1)

    _shutdown_requested = True
    _shutdown_event.set()
    print(
        "\n\n[!] Shutdown signal received — finishing current work unit...",
        flush=True,
    )
    logger.warning("Shutdown signal received — draining current work unit.")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="main.py",
        description="EduSanjal data extraction pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--skip-phase1", dest="skip_phase1", action="store_true",
        help="Skip slug discovery (use slugs already in DB)",
    )
    p.add_argument(
        "--skip-phase2", dest="skip_phase2", action="store_true",
        help="Skip detail scraping (discovery only)",
    )
    p.add_argument(
        "--force-restart", dest="force_restart", action="store_true",
        help="Ignore checkpoints and re-crawl from page 1",
    )
    p.add_argument(
        "--workers", dest="workers", type=int, default=None, metavar="N",
        help="Thread pool size for Phase 2 (default: from config)",
    )
    p.add_argument(
        "--batch-size", dest="batch_size", type=int, default=50, metavar="N",
        help="Sliding window size for Phase 2 work queue (default: 50)",
    )
    p.add_argument(
        "--progress-every", dest="progress_every", type=int, default=100, metavar="N",
        help="Log progress every N completed records (default: 100)",
    )
    p.add_argument(
        "--no-delay", dest="no_delay", action="store_true",
        help="Disable polite inter-request delays (dev/testing only)",
    )
    p.add_argument(
        "--export-only", dest="export_only", action="store_true",
        help="Re-export CSV/Excel from existing DB without scraping",
    )
    return p


def run_export_only() -> None:
    from database.db import Database
    from storage.csv_export import export_all

    logger.info("Export-only mode — reading from existing database.")
    with Database() as db:
        total = db.get_detail_count()
        logger.info("Records in DB: %d", total)
        if total == 0:
            print("No records in database to export.")
            sys.exit(0)
        paths = export_all(db=db, run_id="export-only")
        print("\nExport complete:")
        for key, path in paths.items():
            print(f"  {key:10s}: {path}")


def _save_partial_export() -> None:
    try:
        from database.db import Database
        from storage.csv_export import export_csv_only
        cfg = get_settings()
        with Database() as db:
            count = db.get_detail_count()
            if count > 0:
                path = export_csv_only(db)
                print(f"\n  Partial CSV saved: {path}  ({count} records)", flush=True)
                logger.info("Partial CSV saved on shutdown: %s (%d records)", path, count)
            else:
                print("\n  No records to export yet.", flush=True)
    except Exception as exc:
        logger.warning("Could not save partial CSV on shutdown: %s", exc)


def main() -> int:
    signal.signal(signal.SIGINT,  _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    parser  = build_parser()
    args    = parser.parse_args()
    cfg     = get_settings()

    logger.info(
        "EduSanjal pipeline starting — Python %s | DB: %s",
        sys.version.split()[0], cfg.db_path,
    )

    if args.export_only:
        run_export_only()
        return 0

    options = PipelineOptions(
        skip_phase1    = args.skip_phase1,
        skip_phase2    = args.skip_phase2,
        force_restart  = args.force_restart,
        max_workers    = args.workers,
        batch_size     = args.batch_size,
        progress_every = args.progress_every,
        apply_delay    = not args.no_delay,
    )

    t_start = time.monotonic()
    result  = None

    try:
        result = run_pipeline(options)

    except KeyboardInterrupt:
        elapsed = time.monotonic() - t_start
        print(
            f"\n\n[!] Interrupted after {elapsed:.1f}s.\n"
            f"    Progress is saved in DB — re-run to resume.\n",
            flush=True,
        )
        logger.warning("KeyboardInterrupt caught in main after %.1fs", elapsed)
        _save_partial_export()
        return 1

    except SystemExit as exc:
        raise

    except Exception as exc:
        logger.critical("Pipeline crashed: %s", exc, exc_info=True)
        print(f"\nFATAL ERROR: {exc}\nCheck logs/ for details.", flush=True)
        _save_partial_export()
        return 1

    finally:
        if _shutdown_requested and result is None:
            print("\n[!] Pipeline interrupted — saving partial results...", flush=True)
            _save_partial_export()
            elapsed = time.monotonic() - t_start
            print(
                f"    Saved. Elapsed: {elapsed:.1f}s\n"
                f"    Re-run with: python main.py --skip-phase1\n"
                f"    (Phase 1 slugs are preserved, Phase 2 resumes where it left off)",
                flush=True,
            )

    return 0 if (result and result.success) else 1


if __name__ == "__main__":
    sys.exit(main())
