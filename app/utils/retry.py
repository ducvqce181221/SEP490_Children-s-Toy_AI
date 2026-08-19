"""
app/utils/retry.py
------------------
Async retry decorator with exponential backoff using tenacity.
"""

from __future__ import annotations

import functools
from collections.abc import Callable, Coroutine
from typing import Any, TypeVar

from tenacity import (
    AsyncRetrying,
    RetryError,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.logging import get_logger

logger = get_logger(__name__)

F = TypeVar("F", bound=Callable[..., Coroutine[Any, Any, Any]])


def async_retry(
    max_attempts: int = 3,
    min_wait: float = 1.0,
    max_wait: float = 8.0,
    multiplier: float = 2.0,
    exceptions: tuple[type[Exception], ...] = (Exception,),
) -> Callable[[F], F]:
    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                async for attempt in AsyncRetrying(
                    stop=stop_after_attempt(max_attempts),
                    wait=wait_exponential(multiplier=multiplier, min=min_wait, max=max_wait),
                    retry=retry_if_exception_type(exceptions),
                    reraise=False,
                ):
                    with attempt:
                        attempt_number = attempt.retry_state.attempt_number
                        if attempt_number > 1:
                            logger.warning(
                                "Retrying function",
                                function=func.__name__,
                                attempt=attempt_number,
                                max_attempts=max_attempts,
                            )
                        return await func(*args, **kwargs)
            except RetryError as exc:
                logger.error("All retry attempts exhausted", function=func.__name__, max_attempts=max_attempts)
                raise exc.last_attempt.exception() from exc.last_attempt.exception()  # type: ignore[misc]
        return wrapper  # type: ignore[return-value]
    return decorator
