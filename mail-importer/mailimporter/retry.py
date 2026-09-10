from __future__ import annotations

import logging
import time
from typing import Callable, TypeVar

log = logging.getLogger("retry")

T = TypeVar("T")


class RetryError(RuntimeError):
    """Kastas när alla försök misslyckats (eller avbrutits av nedstängning)."""


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
    """Kör ``func`` med exponential backoff. Vidarebefordrar icke-retrybara
    undantag direkt. Ger upp efter ``max_attempts`` och kastar RetryError."""
    attempt = 0
    while True:
        attempt += 1
        try:
            return func()
        except retryable as exc:
            if should_stop is not None and should_stop():
                raise RetryError(f"{what}: avbruten under nedstängning") from exc
            if attempt >= max_attempts:
                raise RetryError(
                    f"{what}: gav upp efter {attempt} försök ({exc!r})"
                ) from exc
            delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
            log.warning(
                "%s misslyckades (försök %d/%d): %s — nytt försök om %.1fs",
                what, attempt, max_attempts, exc, delay,
            )
            time.sleep(delay)
