from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from database.models import InstitutionDetail
from utils.logger import get_logger

logger = get_logger(__name__)

_EMAIL_RE = re.compile(
    r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$",
    re.IGNORECASE,
)

_PHONE_HAS_DIGITS = re.compile(r"\d{4,}")
_PHONE_JUNK       = re.compile(r"^[a-zA-Z\s]+$")

_REQUIRED_FIELDS: tuple[str, ...] = ("title", "full_address")


@dataclass
class ValidationResult:

    slug:            str
    category:        str
    is_valid:        bool       = True
    missing_fields:  list[str]  = field(default_factory=list)
    invalid_phones:  list[str]  = field(default_factory=list)
    invalid_emails:  list[str]  = field(default_factory=list)
    warnings:        list[str]  = field(default_factory=list)

    @property
    def warning_count(self) -> int:
        return len(self.warnings)

    def add_warning(self, message: str) -> None:
        self.warnings.append(message)
        self.is_valid = False

    def summary(self) -> str:
        if self.is_valid:
            return f"{self.category}/{self.slug}: valid"
        return (
            f"{self.category}/{self.slug}: {self.warning_count} warning(s) — "
            + "; ".join(self.warnings)
        )

    def __repr__(self) -> str:
        return (
            f"ValidationResult(slug={self.slug!r}, is_valid={self.is_valid}, "
            f"warnings={self.warning_count})"
        )


def validate(detail: InstitutionDetail) -> ValidationResult:
    result = ValidationResult(slug=detail.slug, category=detail.category)

    _check_required_fields(detail, result)
    _check_phones(detail, result)
    _check_emails(detail, result)

    if not result.is_valid:
        logger.warning(
            "Validation failed for %s/%s: %d warning(s) — %s",
            detail.category,
            detail.slug,
            result.warning_count,
            "; ".join(result.warnings),
        )
    else:
        logger.debug(
            "Validation passed for %s/%s",
            detail.category,
            detail.slug,
        )

    return result


def is_valid_email(email: str) -> bool:
    s = email.strip()
    if not s or "@" not in s:
        return False
    return bool(_EMAIL_RE.match(s))


def is_valid_phone(phone: str) -> bool:
    s = phone.strip()
    if not s:
        return False
    if _PHONE_JUNK.match(s):
        return False
    return bool(_PHONE_HAS_DIGITS.search(s))


def _check_required_fields(
    detail: InstitutionDetail,
    result: ValidationResult,
) -> None:
    for field_name in _REQUIRED_FIELDS:
        value = getattr(detail, field_name, None)
        if not value:
            msg = f"Missing required field: {field_name!r}"
            result.missing_fields.append(field_name)
            result.add_warning(msg)


def _check_phones(
    detail: InstitutionDetail,
    result: ValidationResult,
) -> None:
    for phone in detail.phone:
        if not is_valid_phone(phone):
            msg = f"Invalid phone format: {phone!r}"
            result.invalid_phones.append(phone)
            result.add_warning(msg)


def _check_emails(
    detail: InstitutionDetail,
    result: ValidationResult,
) -> None:
    for email in detail.email:
        if not is_valid_email(email):
            msg = f"Invalid email format: {email!r}"
            result.invalid_emails.append(email)
            result.add_warning(msg)
