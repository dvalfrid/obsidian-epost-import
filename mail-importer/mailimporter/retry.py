from __future__ import annotations

import logging
import time
from typing import Callable, TypeVar

log = logging.getLogger("retry")

T = TypeVar("T")


class RetryError(RuntimeError):
    """Raised when all attempts have failed (or been aborted by shutdown)."""


def with_retry(
    func: Callable[[], T],
    *,
    what: str,
    retryable: tuple[type[BaseException], ...],
    max_attempts: int = 3,
    base_delay: float = 2.0,
    max_delay: float = 30.0,
    should_stop: Callable[[], bool] | None = None,
) -> T:
    """Runs ``func`` with exponential backoff. Non-retryable exceptions are
    passed straight through. Gives up after ``max_attempts`` and raises
    RetryError."""
    attempt = 0
    while True:
        attempt += 1
        try:
            return func()
        except retryable as exc:
            if should_stop is not None and should_stop():
                raise RetryError(f"{what}: aborted during shutdown") from exc
            if attempt >= max_attempts:
                raise RetryError(
                    f"{what}: gave up after {attempt} attempts ({exc!r})"
                ) from exc
            delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
            log.warning(
                "%s failed (attempt %d/%d): %s — retrying in %.1fs",
                what, attempt, max_attempts, exc, delay,
            )
            time.sleep(delay)
