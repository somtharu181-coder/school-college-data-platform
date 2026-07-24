from __future__ import annotations

import functools
import time
from typing import Any, Callable, Type, TypeVar

from utils.delay import backoff_delay
from utils.logger import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


def retry_on_failure(
    max_retries: int = 3,
    retryable_exceptions: tuple[Type[Exception], ...] = (Exception,),
    backoff_base: float = 2.0,
) -> Callable[[Callable[..., T]], Callable[..., T]]:

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            last_exception: Exception | None = None
            func_name = f"{func.__module__}.{func.__qualname__}"

            for attempt in range(1, max_retries + 2):
                try:
                    result = func(*args, **kwargs)
                    if attempt > 1:
                        logger.info(
                            "%s succeeded on attempt %d/%d",
                            func_name, attempt, max_retries + 1,
                        )
                    return result

                except retryable_exceptions as exc:
                    last_exception = exc
                    if attempt <= max_retries:
                        logger.warning(
                            "%s failed (attempt %d/%d): %s: %s — retrying",
                            func_name, attempt, max_retries + 1,
                            type(exc).__name__, str(exc)[:120],
                        )
                        backoff_delay(attempt)
                    else:
                        logger.error(
                            "%s exhausted %d retries: %s: %s",
                            func_name, max_retries + 1,
                            type(exc).__name__, str(exc)[:200],
                        )

                except Exception as exc:
                    logger.error(
                        "%s raised non-retryable %s: %s",
                        func_name, type(exc).__name__, str(exc)[:200],
                    )
                    raise

            if last_exception:
                raise last_exception
            else:
                raise RuntimeError(
                    f"{func_name} exhausted retries without an exception"
                )

        return wrapper

    return decorator


def retry_once_on_failure(
    retryable_exceptions: tuple[Type[Exception], ...] = (Exception,),
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    return retry_on_failure(
        max_retries=1,
        retryable_exceptions=retryable_exceptions,
    )


def call_with_retry(
    func: Callable[..., T],
    *args: Any,
    max_retries: int = 3,
    retryable_exceptions: tuple[Type[Exception], ...] = (Exception,),
    **kwargs: Any,
) -> T:
    decorated = retry_on_failure(
        max_retries=max_retries,
        retryable_exceptions=retryable_exceptions,
    )(func)
    return decorated(*args, **kwargs)


def with_timeout_retry(
    timeout_seconds: float,
    max_retries: int = 2,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    raise NotImplementedError(
        "with_timeout_retry is not yet implemented"
    )
