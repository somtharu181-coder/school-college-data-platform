from __future__ import annotations

import threading
from typing import Final

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import get_settings
from utils.headers import build_headers
from utils.logger import get_logger

logger = get_logger(__name__)

_TRANSPORT_RETRY_TOTAL: Final[int] = 3
_TRANSPORT_RETRY_STATUSES: Final[tuple[int, ...]] = ()
_TRANSPORT_BACKOFF_FACTOR: Final[float] = 0.3

_POOL_CONNECTIONS: Final[int] = 4
_POOL_MAXSIZE: Final[int] = 10


def _build_adapter() -> HTTPAdapter:
    retry = Retry(
        total=_TRANSPORT_RETRY_TOTAL,
        backoff_factor=_TRANSPORT_BACKOFF_FACTOR,
        status_forcelist=list(_TRANSPORT_RETRY_STATUSES),
        allowed_methods={"GET", "HEAD", "OPTIONS"},
        raise_on_status=False,
        raise_on_redirect=False,
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(
        max_retries=retry,
        pool_connections=_POOL_CONNECTIONS,
        pool_maxsize=_POOL_MAXSIZE,
        pool_block=False,
    )
    return adapter


def _build_session() -> requests.Session:
    cfg = get_settings()
    session = requests.Session()

    adapter = _build_adapter()
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    session.headers.update(build_headers())
    session._edusanjal_timeout = (cfg.request_timeout, cfg.request_timeout)

    logger.debug(
        "Session built: timeout=%ds, pool_connections=%d, pool_maxsize=%d",
        cfg.request_timeout,
        _POOL_CONNECTIONS,
        _POOL_MAXSIZE,
    )
    return session


_thread_local = threading.local()


def get_session() -> requests.Session:
    if not hasattr(_thread_local, "session"):
        _thread_local.session = _build_session()
        logger.debug(
            "New session created for thread: %s",
            threading.current_thread().name,
        )
    return _thread_local.session


def refresh_headers(
    category: str | None = None,
    slug: str | None = None,
) -> None:
    from utils.headers import build_detail_headers, build_listing_headers

    if category and slug:
        new_headers = build_detail_headers(category, slug)
    elif category:
        new_headers = build_listing_headers(category)
    else:
        new_headers = build_headers()

    get_session().headers.update(new_headers)


def close_session() -> None:
    session = getattr(_thread_local, "session", None)
    if session is not None:
        session.close()
        del _thread_local.session
        logger.debug(
            "Session closed for thread: %s",
            threading.current_thread().name,
        )


def request_get(
    url: str,
    params: dict | None = None,
    extra_headers: dict | None = None,
) -> requests.Response:
    cfg = get_settings()
    session = get_session()
    timeout = (cfg.request_timeout, cfg.request_timeout)

    merged_headers: dict | None = None
    if extra_headers:
        merged_headers = {**dict(session.headers), **extra_headers}

    logger.debug("GET %s | params=%s", url, params)

    response = session.get(
        url=url,
        params=params,
        headers=merged_headers,
        timeout=timeout,
        allow_redirects=True,
    )

    logger.debug(
        "Response: %s status=%d content-type=%s elapsed=%.3fs",
        url,
        response.status_code,
        response.headers.get("content-type", "?")[:40],
        response.elapsed.total_seconds(),
    )

    return response
