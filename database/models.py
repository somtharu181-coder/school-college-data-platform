from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalise_contact(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if v]

    import re
    parts = re.split(r"[|,;/]", str(value))
    return [p.strip() for p in parts if p.strip()]


class SlugStatus:
    PENDING   = "pending"
    COMPLETED = "completed"
    FAILED    = "failed"


@dataclass
class SlugRecord:

    slug:        str
    category:    str
    source_url:  str
    id:          int  = 0
    status:      str  = SlugStatus.PENDING
    retry_count: int  = 0
    created_at:  str  = field(default_factory=_now_utc)
    updated_at:  str  = field(default_factory=_now_utc)

    def __post_init__(self) -> None:
        if not self.slug:
            raise ValueError("SlugRecord.slug must not be empty")
        if self.category not in ("college", "school"):
            raise ValueError(
                f"SlugRecord.category must be 'college' or 'school', got {self.category!r}"
            )
        if self.status not in (
            SlugStatus.PENDING, SlugStatus.COMPLETED, SlugStatus.FAILED
        ):
            raise ValueError(f"Invalid SlugRecord.status: {self.status!r}")

    def mark_completed(self) -> None:
        self.status     = SlugStatus.COMPLETED
        self.updated_at = _now_utc()

    def mark_failed(self) -> None:
        self.status      = SlugStatus.FAILED
        self.retry_count += 1
        self.updated_at  = _now_utc()

    def requeue(self) -> None:
        self.status     = SlugStatus.PENDING
        self.updated_at = _now_utc()

    def to_db_row(self) -> tuple:
        return (
            self.slug,
            self.category,
            self.source_url,
            self.status,
            self.retry_count,
            self.created_at,
            self.updated_at,
        )

    @classmethod
    def from_db_row(cls, row: tuple | Any) -> "SlugRecord":
        return cls(
            id          = row[0],
            slug        = row[1],
            category    = row[2],
            source_url  = row[3],
            status      = row[4],
            retry_count = row[5],
            created_at  = row[6],
            updated_at  = row[7],
        )

    def __repr__(self) -> str:
        return (
            f"SlugRecord(slug={self.slug!r}, category={self.category!r}, "
            f"status={self.status!r}, retries={self.retry_count})"
        )


@dataclass
class InstitutionDetail:

    slug:         str
    category:     str
    title:        str       | None = None
    established:  str       | None = None
    full_address: str       | None = None
    type:         str       | None = None
    phone:        list[str] = field(default_factory=list)
    email:        list[str] = field(default_factory=list)
    affiliations: str       | None = None
    source_url:   str       = ""
    scraped_at:   str       = field(default_factory=_now_utc)

    def __post_init__(self) -> None:
        if isinstance(self.phone, str) or self.phone is None:
            self.phone = _normalise_contact(self.phone)
        if isinstance(self.email, str) or self.email is None:
            self.email = _normalise_contact(self.email)

    @property
    def phone_str(self) -> str | None:
        return ", ".join(self.phone) if self.phone else None

    @property
    def email_str(self) -> str | None:
        return ", ".join(self.email) if self.email else None

    def to_db_row(self) -> tuple:
        return (
            self.slug,
            self.category,
            self.title,
            self.established,
            self.full_address,
            self.type,
            json.dumps(self.phone, ensure_ascii=False),
            json.dumps(self.email, ensure_ascii=False),
            self.affiliations,
            self.source_url,
            self.scraped_at,
        )

    @classmethod
    def from_db_row(cls, row: tuple | Any) -> "InstitutionDetail":
        phone_raw = row[7]
        email_raw = row[8]
        return cls(
            slug         = row[1],
            category     = row[2],
            title        = row[3],
            established  = row[4],
            full_address = row[5],
            type         = row[6],
            phone        = json.loads(phone_raw) if phone_raw else [],
            email        = json.loads(email_raw) if email_raw else [],
            affiliations = row[9],
            source_url   = row[10],
            scraped_at   = row[11],
        )

    def to_export_dict(self) -> dict[str, Any]:
        def _v(val: Any) -> Any:
            if val is None or val == "":
                return "N/A"
            return val
        return {
            "title":        _v(self.title),
            "full_address": _v(self.full_address),
            "email":        _v(self.email_str),
            "affiliations": _v(self.affiliations),
            "type":         _v(self.type),
            "established":  _v(self.established),
            "phone":        _v(self.phone_str),
        }

    def __repr__(self) -> str:
        return (
            f"InstitutionDetail(slug={self.slug!r}, category={self.category!r}, "
            f"title={self.title!r})"
        )


@dataclass
class CrawlStatus:

    run_id:           str
    phase:            str
    total_slugs:      int   = 0
    completed:        int   = 0
    failed:           int   = 0
    retried:          int   = 0
    started_at:       str   = field(default_factory=_now_utc)
    finished_at:      str | None = None
    elapsed_seconds:  float = 0.0
    avg_speed_rps:    float = 0.0

    @property
    def success_rate(self) -> float:
        if self.total_slugs == 0:
            return 0.0
        return round(self.completed / self.total_slugs * 100, 2)

    @property
    def pending(self) -> int:
        return max(0, self.total_slugs - self.completed - self.failed)

    def finish(self, elapsed: float) -> None:
        self.finished_at     = _now_utc()
        self.elapsed_seconds = elapsed
        if elapsed > 0:
            self.avg_speed_rps = round(self.completed / elapsed, 3)

    def to_db_row(self) -> tuple:
        return (
            self.run_id,
            self.phase,
            self.total_slugs,
            self.completed,
            self.failed,
            self.retried,
            self.started_at,
            self.finished_at,
            self.elapsed_seconds,
            self.avg_speed_rps,
        )

    def to_summary_dict(self) -> dict[str, Any]:
        from utils.delay import seconds_to_human
        return {
            "run_id":        self.run_id,
            "phase":         self.phase,
            "total_slugs":   self.total_slugs,
            "completed":     self.completed,
            "failed":        self.failed,
            "pending":       self.pending,
            "retried":       self.retried,
            "success_rate":  f"{self.success_rate:.1f}%",
            "elapsed":       seconds_to_human(self.elapsed_seconds),
            "avg_speed_rps": f"{self.avg_speed_rps:.3f} req/s",
            "started_at":    self.started_at,
            "finished_at":   self.finished_at or "—",
        }

    def __repr__(self) -> str:
        return (
            f"CrawlStatus(phase={self.phase!r}, "
            f"completed={self.completed}/{self.total_slugs}, "
            f"failed={self.failed}, success={self.success_rate:.1f}%)"
        )
