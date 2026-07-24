from __future__ import annotations

import random
from typing import Final

from config import get_settings


_ACCEPT: Final[str] = (
    "application/json, text/plain, */*"
)

_CACHE_CONTROL: Final[str] = "no-cache"
_PRAGMA: Final[str] = "no-cache"

_SEC_FETCH_DEST: Final[str] = "empty"
_SEC_FETCH_MODE: Final[str] = "cors"
_SEC_FETCH_SITE: Final[str] = "same-site"

_CONNECTION_VALUES: Final[tuple[str, ...]] = (
    "keep-alive",
    "keep-alive",
    "keep-alive",
)

_SEC_CH_UA_POOL: Final[tuple[str, ...]] = (
    '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    '"Chromium";v="123", "Microsoft Edge";v="123", "Not-A.Brand";v="99"',
    '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    None,
)

_SEC_CH_UA_MOBILE: Final[str] = "?0"
_SEC_CH_UA_PLATFORM_POOL: Final[tuple[str, ...]] = (
    '"Windows"',
    '"macOS"',
    '"Linux"',
)


def build_headers(referer: str | None = None) -> dict[str, str]:
    cfg = get_settings()

    user_agent: str = random.choice(cfg.user_agents)
    accept_language: str = random.choice(cfg.accept_languages)
    sec_ch_ua: str | None = random.choice(_SEC_CH_UA_POOL)
    platform: str = random.choice(_SEC_CH_UA_PLATFORM_POOL)

    headers: dict[str, str] = {
        "User-Agent":        user_agent,
        "Accept":            _ACCEPT,
        "Accept-Language":   accept_language,
        "Connection":        random.choice(_CONNECTION_VALUES),
        "Cache-Control":     _CACHE_CONTROL,
        "Pragma":            _PRAGMA,
        "Origin":            "https://edusanjal.com",
        "Sec-Fetch-Dest":    _SEC_FETCH_DEST,
        "Sec-Fetch-Mode":    _SEC_FETCH_MODE,
        "Sec-Fetch-Site":    _SEC_FETCH_SITE,
    }

    if sec_ch_ua is not None:
        headers["sec-ch-ua"]          = sec_ch_ua
        headers["sec-ch-ua-mobile"]   = _SEC_CH_UA_MOBILE
        headers["sec-ch-ua-platform"] = platform

    if referer is None:
        referer = "https://edusanjal.com/"
    headers["Referer"] = referer

    return headers


def build_listing_headers(category: str) -> dict[str, str]:
    referer = f"https://edusanjal.com/{category}/"
    return build_headers(referer=referer)


def build_detail_headers(category: str, slug: str) -> dict[str, str]:
    referer = f"https://edusanjal.com/{category}/{slug}/"
    return build_headers(referer=referer)
