from __future__ import annotations

import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Iterator

from config import get_settings
from database.db import Database
from database.models import CrawlStatus, SlugRecord, SlugStatus
from utils.delay import seconds_to_human
from utils.logger import get_logger, get_progress_logger
from workers.worker import WorkerResult, run_worker, worker_thread_cleanup

logger          = get_logger(__name__)
progress_logger = get_progress_logger()

_CSV_FLUSH_EVERY: int = 100


@dataclass
class QueueMetrics:

    total:      int   = 0
    completed:  int   = 0
    failed:     int   = 0
    skipped:    int   = 0
    retried:    int   = 0
    elapsed:    float = 0.0
    _lock:      threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record_success(self, elapsed: float) -> None:
        with self._lock:
            self.completed += 1
            self.elapsed   += elapsed

    def record_failure(self, retryable: bool) -> None:
        with self._lock:
            self.failed += 1
            if retryable:
                self.retried += 1

    @property
    def processed(self) -> int:
        return self.completed + self.failed

    @property
    def remaining(self) -> int:
        return max(0, self.total - self.processed)

    @property
    def avg_speed(self) -> float:
        return (self.elapsed / self.completed) if self.completed else 0.0

    @property
    def success_rate(self) -> float:
        return (self.completed / self.processed * 100) if self.processed else 0.0

    def to_crawl_status(self, run_id: str, started_at: str) -> CrawlStatus:
        cs = CrawlStatus(
            run_id      = run_id,
            phase       = "detail_scraping",
            total_slugs = self.total,
            completed   = self.completed,
            failed      = self.failed,
            retried     = self.retried,
            started_at  = started_at,
        )
        return cs


def run_detail_scraping(
    db: Database,
    run_id: str,
    max_workers: int | None = None,
    batch_size: int = 50,
    progress_every: int = 100,
    apply_delay: bool = True,
) -> CrawlStatus:

    cfg         = get_settings()
    workers     = max_workers or cfg.max_workers
    started_at  = _iso_now()
    t_start     = time.monotonic()

    logger.info(
        "run_detail_scraping: run_id=%r workers=%d batch_size=%d",
        run_id, workers, batch_size,
    )

    total = db.get_slug_counts().get(SlugStatus.PENDING, 0)
    logger.info(
        "Pending slugs: %d (completed so far: %d)",
        total,
        db.get_slug_counts().get(SlugStatus.COMPLETED, 0),
    )

    metrics        = QueueMetrics(total=total)
    all_time_start = time.monotonic()

    _run_pass(
        db             = db,
        metrics        = metrics,
        workers        = workers,
        batch_size     = batch_size,
        progress_every = progress_every,
        apply_delay    = apply_delay,
    )

    requeued = db.requeue_failed_slugs(max_retries=cfg.max_retries)
    if requeued > 0:
        logger.info(
            "Requeued %d failed slugs (max_retries=%d) — running retry pass",
            requeued, cfg.max_retries,
        )
        retry_metrics = QueueMetrics(total=requeued)
        _run_pass(
            db             = db,
            metrics        = retry_metrics,
            workers        = workers,
            batch_size     = batch_size,
            progress_every = progress_every,
            apply_delay    = apply_delay,
        )
        metrics.completed += retry_metrics.completed
        metrics.failed    += retry_metrics.failed
        metrics.retried   += retry_metrics.completed

    total_elapsed = time.monotonic() - all_time_start

    cs = metrics.to_crawl_status(run_id=run_id, started_at=started_at)
    cs.finish(elapsed=total_elapsed)

    logger.info(
        "Detail scraping done — completed=%d failed=%d retried=%d "
        "success=%.1f%% elapsed=%s speed=%.3f req/s",
        cs.completed, cs.failed, cs.retried,
        cs.success_rate,
        seconds_to_human(total_elapsed),
        cs.avg_speed_rps,
    )

    db.save_crawl_status(cs)
    return cs


def _run_pass(
    db: Database,
    metrics: QueueMetrics,
    workers: int,
    batch_size: int,
    progress_every: int,
    apply_delay: bool,
) -> None:

    slug_iterator: Iterator[SlugRecord] = db.iter_pending_slugs(
        batch_size=batch_size
    )

    def _make_initializer():
        pass

    with ThreadPoolExecutor(
        max_workers=workers,
        thread_name_prefix="Scraper",
        initializer=_make_initializer,
    ) as executor:

        active_futures: dict[Future, SlugRecord] = {}

        for slug_record in slug_iterator:
            if len(active_futures) >= batch_size:
                break
            fut = executor.submit(run_worker, slug_record, db, apply_delay)
            active_futures[fut] = slug_record

        if not active_futures:
            logger.info("No pending slugs found — pass complete.")
            return

        while active_futures:
            done_iter = as_completed(list(active_futures.keys()), timeout=120)

            try:
                done_future = next(iter(done_iter))
            except StopIteration:
                logger.warning("as_completed returned no done futures — continuing")
                break

            slug_record_done = active_futures.pop(done_future)

            try:
                result: WorkerResult = done_future.result()
            except Exception as exc:
                logger.error(
                    "Future raised for %s/%s: %s",
                    slug_record_done.category,
                    slug_record_done.slug,
                    exc,
                )
                metrics.record_failure(retryable=True)
                result = WorkerResult(
                    slug     = slug_record_done.slug,
                    category = slug_record_done.category,
                    success  = False,
                    error    = exc,
                )

            if result.success:
                metrics.record_success(result.elapsed)
            else:
                metrics.record_failure(result.is_retryable)

            if metrics.processed % progress_every == 0 or metrics.remaining == 0:
                _log_progress(metrics)

            if metrics.completed > 0 and metrics.completed % _CSV_FLUSH_EVERY == 0:
                _flush_csv(db)

            try:
                next_slug = next(slug_iterator)
                new_fut = executor.submit(
                    run_worker, next_slug, db, apply_delay
                )
                active_futures[new_fut] = next_slug
            except StopIteration:
                pass

    logger.debug("Thread pool shut down — worker threads finished.")


def _log_progress(metrics: QueueMetrics) -> None:
    pct = (metrics.processed / metrics.total * 100) if metrics.total else 0.0
    avg = metrics.avg_speed

    progress_logger.info(
        "Progress: %d/%d (%.1f%%) | ok=%d fail=%d avg=%.2fs remaining=%d",
        metrics.processed,
        metrics.total,
        pct,
        metrics.completed,
        metrics.failed,
        avg,
        metrics.remaining,
    )


def _flush_csv(db: Database) -> None:
    try:
        from storage.csv_export import export_csv_only
        path = export_csv_only(db)
        logger.info("Incremental CSV flushed: %s", path)
    except Exception as exc:
        logger.warning("Incremental CSV flush failed: %s", exc)


def _iso_now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
