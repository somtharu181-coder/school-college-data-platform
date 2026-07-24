from __future__ import annotations

import re
from typing import Any

from config import get_settings
from database.models import InstitutionDetail
from utils.logger import get_logger

logger = get_logger(__name__)

_CONTACT_SPLIT = re.compile(r"[|,;/]")

_EMAIL_PATTERN = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
    re.IGNORECASE,
)


def parse(
    raw: dict[str, Any],
    category: str,
    slug: str,
    source_url: str = "",
) -> InstitutionDetail:

    title        = _extract_title(raw)
    established  = _extract_established(raw)
    full_address = _extract_full_address(raw)
    inst_type    = _extract_type(raw)
    phone        = _extract_phone(raw)
    email        = _extract_email(raw)
    affiliations = _extract_affiliations(raw)

    detail = InstitutionDetail(
        slug         = slug,
        category     = category,
        title        = title,
        established  = established,
        full_address = full_address,
        type         = inst_type,
        phone        = phone,
        email        = email,
        affiliations = affiliations,
        source_url   = source_url,
    )
    logger.debug(
        "Parsed %s/%s: title=%r established=%r type=%r phones=%d emails=%d affiliations=%r",
        category, slug, title, established, inst_type,
        len(phone), len(email), affiliations,
    )
    return detail


def _extract_title(raw: dict[str, Any]) -> str | None:
    v = raw.get("title")
    if not v:
        return None
    s = str(v).strip()
    return s if s else None


def _extract_established(raw: dict[str, Any]) -> str | None:
    v = raw.get("established")
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def _extract_full_address(raw: dict[str, Any]) -> str | None:
    v = raw.get("full_address")
    if not v:
        return None
    s = str(v).strip()
    return s if s else None


def _extract_type(raw: dict[str, Any]) -> str | None:
    v = raw.get("type")
    if not v:
        return None
    s = str(v).strip()
    return s if s else None


def _extract_phone(raw: dict[str, Any]) -> list[str]:
    return _split_contact(raw.get("phone"))


def _extract_email(raw: dict[str, Any]) -> list[str]:
    raw_list = _split_contact(raw.get("email"))
    emails: list[str] = []
    for item in raw_list:
        item_clean = item.strip().lower()
        if not item_clean:
            continue
        if "@" in item_clean:
            emails.append(item_clean)
        else:
            found = _EMAIL_PATTERN.findall(item_clean)
            emails.extend(f.lower() for f in found)

    seen: dict[str, bool] = {}
    unique: list[str] = []
    for e in emails:
        if e not in seen:
            seen[e] = True
            unique.append(e)
    return unique


def _extract_text(raw: dict[str, Any], key: str) -> str | None:
    v = raw.get(key)
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def _extract_district(raw: dict[str, Any]) -> str | None:
    v = raw.get("district")
    if not v:
        return None
    if isinstance(v, dict):
        return v.get("name") or None
    s = str(v).strip()
    return s if s else None


def _extract_affiliations(raw: dict[str, Any]) -> str | None:
    v = raw.get("affiliations")
    if not v or not isinstance(v, list):
        return None
    titles = [
        a.get("title", "")
        for a in v
        if isinstance(a, dict) and a.get("title")
    ]
    result = ", ".join(t for t in titles if t)
    return result if result else None


def _extract_boarding(raw: dict[str, Any]) -> str | None:
    v = raw.get("boarding_status")
    if not v:
        return None
    if isinstance(v, list):
        parts = [str(x).strip() for x in v if x]
        result = ", ".join(parts)
        return result if result else None
    s = str(v).strip()
    return s if s else None


def _extract_coord(raw: dict[str, Any], key: str) -> str | None:
    v = raw.get(key)
    if v is None:
        return None
    try:
        return str(float(v))
    except (TypeError, ValueError):
        return None


def _split_contact(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    text = str(value).strip()
    if not text:
        return []
    parts = _CONTACT_SPLIT.split(text)
    return [p.strip() for p in parts if p.strip()]
