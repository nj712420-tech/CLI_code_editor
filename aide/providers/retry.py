"""Retry utilities with exponential backoff for provider resilience."""

from __future__ import annotations

import asyncio
import random
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, TypeVar

from aide.core.errors import ProviderError, RateLimitError, ServerError

T = TypeVar("T")
StreamFactory = Callable[[], AsyncIterator[Any]]


async def with_retry(
    func: Callable[..., Awaitable[T]],
    *args: Any,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    exponential_base: float = 2.0,
    jitter: bool = True,
    retryable_exceptions: tuple[type[Exception], ...] = (
        RateLimitError,
        ServerError,
        ProviderError,
        TimeoutError,
        ConnectionError,
    ),
    **kwargs: Any,
) -> T:
    """Execute an async function with exponential backoff retry.

    Args:
        func: Async function to call
        *args: Positional arguments for func
        max_retries: Maximum number of retry attempts (default 3)
        base_delay: Initial delay in seconds (default 1.0)
        max_delay: Maximum delay in seconds (default 30.0)
        exponential_base: Multiplier for exponential backoff (default 2.0)
        jitter: Add random jitter to prevent thundering herd (default True)
        retryable_exceptions: Exception types that trigger a retry
        **kwargs: Keyword arguments for func

    Returns:
        Result of func

    Raises:
        The last exception if all retries exhausted
    """
    last_exception: Exception | None = None
    delay = base_delay

    for attempt in range(max_retries + 1):
        try:
            return await func(*args, **kwargs)
        except retryable_exceptions as exc:
            last_exception = exc
            if attempt < max_retries:
                # Add jitter to prevent thundering herd
                actual_delay = delay
                if jitter:
                    actual_delay = delay * (0.5 + random.random())
                actual_delay = min(actual_delay, max_delay)

                # For rate limits, respect Retry-After header if available
                if isinstance(exc, RateLimitError):
                    actual_delay = max(actual_delay, base_delay * exponential_base)

                await asyncio.sleep(actual_delay)
                delay *= exponential_base
            else:
                break
        except Exception:
            # Non-retryable exception, re-raise immediately
            raise

    raise last_exception or ProviderError("Retry exhausted")


async def retry_stream(
    stream_factory: Callable[[], AsyncIterator[Any]],
    *,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    exponential_base: float = 2.0,
    jitter: bool = True,
    retryable_exceptions: tuple[type[Exception], ...] = (
        RateLimitError,
        ServerError,
        ProviderError,
        TimeoutError,
        ConnectionError,
    ),
) -> AsyncIterator[Any]:
    """Retry a stream factory with exponential backoff.

    Note: This re-starts the stream from the beginning on retry.
    For true stream resumption, the provider would need to support it.

    Args:
        stream_factory: Callable that returns an async iterator
        max_retries: Maximum number of retry attempts
        base_delay: Initial delay in seconds
        max_delay: Maximum delay in seconds
        exponential_base: Multiplier for exponential backoff
        jitter: Add random jitter
        retryable_exceptions: Exception types that trigger a retry

    Yields:
        Items from the stream

    Raises:
        The last exception if all retries exhausted
    """
    last_exception: Exception | None = None
    delay = base_delay

    for attempt in range(max_retries + 1):
        try:
            async for item in stream_factory():
                yield item
            return  # Stream completed successfully
        except retryable_exceptions as exc:
            last_exception = exc
            if attempt < max_retries:
                actual_delay = delay
                if jitter:
                    actual_delay = delay * (0.5 + random.random())
                actual_delay = min(actual_delay, max_delay)

                if isinstance(exc, RateLimitError):
                    actual_delay = max(actual_delay, base_delay * exponential_base)

                await asyncio.sleep(actual_delay)
                delay *= exponential_base
            else:
                break
        except Exception:
            raise

    raise last_exception or ProviderError("Stream retry exhausted")
