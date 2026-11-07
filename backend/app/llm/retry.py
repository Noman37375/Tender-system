"""Retries for transient LLM errors (PRD 7.5): backoff 1s, 4s, 16s + jitter, transient only.

Error classification follows the pattern from the narrative-system fallback chain (rate limit,
overloaded, network, timeout are transient; bad request / auth / validation are not), but by
exception type and HTTP status instead of message text, so no response body is inspected.
"""

import asyncio
import random
from collections.abc import Awaitable, Callable, Sequence

import httpx
import structlog

log = structlog.get_logger(__name__)


RETRY_DELAYS: tuple[float, ...] = (1.0, 4.0, 16.0)
MAX_JITTER = 0.5  # seconds, added uniformly to each delay

_TRANSIENT_STATUS = {408, 409, 425, 429, 500, 502, 503, 504, 529}
_TRANSIENT_NAMES = {
    "APITimeoutError",
    "APIConnectionError",
    "RateLimitError",
    "InternalServerError",
    "OverloadedError",
    "ServiceUnavailableError",
    "GatewayTimeoutError",
    "DeadlineExceededError",
    "RequestTimeoutError",
}

# Indirection so tests can patch the sleep without touching asyncio globally.
sleep: Callable[[float], Awaitable[None]] = asyncio.sleep


def is_transient(exc: BaseException) -> bool:
    """Timeout, connection, rate-limit and 5xx errors. Everything else fails fast."""
    if isinstance(exc, TimeoutError | httpx.TimeoutException | httpx.TransportError):
        return True
    for cls in type(exc).__mro__:
        if cls.__name__ in _TRANSIENT_NAMES:
            return True
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status in _TRANSIENT_STATUS or status >= 500
    return False


async def with_retries[R](
    fn: Callable[[], Awaitable[R]],
    *,
    delays: Sequence[float] = RETRY_DELAYS,
    jitter: float = MAX_JITTER,
    before_attempt: Callable[[], None] | None = None,
    log_fields: dict[str, object] | None = None,
) -> R:
    """Call `fn`; on a transient error wait delays[i] (+ jitter) and try again.

    Up to len(delays) retries after the first attempt. `before_attempt` runs before every
    attempt (used for the budget check, so a retry never starts once the budget is spent).
    """
    attempt = 0
    while True:
        if before_attempt is not None:
            before_attempt()
        try:
            return await fn()
        except Exception as exc:
            if not is_transient(exc) or attempt >= len(delays):
                raise
            wait = delays[attempt] + random.uniform(0, jitter)
            attempt += 1
            log.warning(
                "llm.retry",
                attempt=attempt,
                wait_s=round(wait, 2),
                error_type=type(exc).__name__,
                **(log_fields or {}),
            )
            await sleep(wait)
