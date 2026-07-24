from __future__ import annotations

import re

from database.models import InstitutionDetail
from utils.logger import get_logger

logger = get_logger(__name__)

_MULTI_WHITESPACE = re.compile(r"\s+")


def clean(detail: InstitutionDetail) -> InstitutionDetail:
    detail.title        = _clean_title(detail.title)
    detail.established  = _clean_established(detail.established)
    detail.full_address = _clean_full_address(detail.full_address)
    detail.type         = _clean_type(detail.type)
    detail.phone        = _clean_phone(detail.phone)
    detail.email        = _clean_email(detail.email)
    detail.affiliations = _clean_title(detail.affiliations)
    logger.debug(
        "Cleaned %s/%s: type=%r phones=%d emails=%d affiliations=%r",
        detail.category, detail.slug, detail.type,
        len(detail.phone), len(detail.email), detail.affiliations,
    )
    return detail


def _clean_title(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = _MULTI_WHITESPACE.sub(" ", value).strip()
    return cleaned if cleaned else None


def _clean_established(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = _MULTI_WHITESPACE.sub(" ", value).strip()
    return cleaned if cleaned else None


def _clean_full_address(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = _MULTI_WHITESPACE.sub(" ", value).strip()
    return cleaned if cleaned else None


def _clean_type(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = _MULTI_WHITESPACE.sub(" ", value).strip()
    if not cleaned:
        return None
    return cleaned.title()


def _clean_phone(values: list[str]) -> list[str]:
    if not values:
        return []
    stripped = [v.strip() for v in values if v.strip()]
    seen: dict[str, bool] = {}
    unique: list[str] = []
    for phone in stripped:
        if phone not in seen:
            seen[phone] = True
            unique.append(phone)
    return unique


def _clean_email(values: list[str]) -> list[str]:
    if not values:
        return []
    normalized = [v.strip().lower() for v in values if v.strip()]
    seen: dict[str, bool] = {}
    unique: list[str] = []
    for email in normalized:
        if email not in seen:
            seen[email] = True
            unique.append(email)
    return unique


def normalize_whitespace(text: str) -> str:
    return _MULTI_WHITESPACE.sub(" ", text).strip()


def _clean_url(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = str(value).strip()
    return cleaned if cleaned else None
