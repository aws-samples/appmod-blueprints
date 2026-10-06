"""Centralized retry / transient-error classification for IDC configuration.

Single source of truth for the resilience behaviour that used to be hand-rolled
(``for attempt in range(...)`` + ``time.sleep(...)``) in half a dozen places
across ``configure_identity_center.py``. It defines, once:

* which Chromium/Playwright navigation errors are transient (safe to retry),
* which HTTP failures are transient,
* the `tenacity <https://github.com/jd/tenacity>`_ retry policies the rest of
  the package reuses (federation call, Playwright ``page.goto``), and
* a generic ``poll_until`` helper for the "wait for an endpoint to come up"
  pattern.

This module is deliberately dependency-light (``tenacity`` + stdlib only) so the
transient-classification and retry behaviour can be unit-tested without boto3,
playwright, or network access.
"""

from __future__ import annotations

import sys
from typing import Any, Callable, Tuple, Type

from tenacity import (
    Retrying,
    retry,
    retry_if_exception,
    retry_if_exception_type,
    retry_if_result,
    stop_after_attempt,
    stop_after_delay,
    wait_exponential,
    wait_fixed,
)
from tenacity import RetryError

# ---------------------------------------------------------------------------
# Transient navigation errors (Chromium / Playwright)
# ---------------------------------------------------------------------------
# These are raised by page.goto() when the IDE's network is reconfigured or
# saturated mid-navigation (e.g. a concurrent multi-GB `docker push` of the
# vLLM image during install). They are NOT deterministic failures of the
# automation itself, so they are safe to retry with backoff.
TRANSIENT_NAV_ERROR_TOKENS: Tuple[str, ...] = (
    "ERR_NETWORK_CHANGED",
    "ERR_NETWORK_IO_SUSPENDED",
    "ERR_INTERNET_DISCONNECTED",
    "ERR_NAME_NOT_RESOLVED",
    "ERR_CONNECTION_RESET",
    "ERR_CONNECTION_CLOSED",
    "ERR_CONNECTION_TIMED_OUT",
    "ERR_TIMED_OUT",
    "ERR_ABORTED",
    "ERR_EMPTY_RESPONSE",
    "Timeout",
)


def is_transient_nav_error(exc: BaseException) -> bool:
    """True if ``exc`` is a retryable Chromium/Playwright navigation error."""
    msg = str(exc)
    return any(token in msg for token in TRANSIENT_NAV_ERROR_TOKENS)


# ---------------------------------------------------------------------------
# Transient HTTP failures
# ---------------------------------------------------------------------------
class TransientHTTPError(RuntimeError):
    """An HTTP failure that is safe to retry.

    Raised by call sites (e.g. the AWS console federation request) for the three
    retryable modes that used to each get their own ``range()``/``sleep`` branch:
    a request-level network error, a non-2xx response, or an unparseable body.
    Anything not wrapped in this type is treated as a hard, non-retryable error.
    """


def is_transient_http_error(exc: BaseException) -> bool:
    """True if ``exc`` is a :class:`TransientHTTPError`."""
    return isinstance(exc, TransientHTTPError)


# ---------------------------------------------------------------------------
# Logging hook (matches the script's stderr logging convention)
# ---------------------------------------------------------------------------
def _before_sleep(retry_state) -> None:
    """tenacity ``before_sleep`` callback: log the transient failure to stderr."""
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    if exc is not None:
        first_line = str(exc).splitlines()[0] if str(exc) else exc.__class__.__name__
        detail = f"{exc.__class__.__name__}: {first_line}"
    else:
        detail = "condition not yet met"
    sleep = getattr(retry_state.next_action, "sleep", 0) or 0
    print(
        f"  Transient failure (attempt {retry_state.attempt_number}) — "
        f"retrying in {sleep:.0f}s... {detail}",
        file=sys.stderr,
    )


# ---------------------------------------------------------------------------
# Reusable retry policies (tenacity decorator factories)
# ---------------------------------------------------------------------------
def retry_nav(retries: int = 5, base_delay: int = 3):
    """Retry a (sync or async) callable on transient navigation errors.

    Exponential backoff (base_delay, 2x, 4x, ...) preserving the previous
    ``goto_with_retry`` semantics. Non-transient errors are re-raised
    immediately; the last transient error is re-raised after ``retries``.
    """
    return retry(
        reraise=True,
        stop=stop_after_attempt(retries),
        wait=wait_exponential(multiplier=base_delay, exp_base=2, min=base_delay),
        retry=retry_if_exception(is_transient_nav_error),
        before_sleep=_before_sleep,
    )


def retry_http(attempts: int = 3, delay: int = 5):
    """Retry a callable on :class:`TransientHTTPError` with a fixed delay.

    Preserves the previous federation-request loop (3 attempts, 5s apart).
    """
    return retry(
        reraise=True,
        stop=stop_after_attempt(attempts),
        wait=wait_fixed(delay),
        retry=retry_if_exception_type(TransientHTTPError),
        before_sleep=_before_sleep,
    )


def poll_until(
    fn: Callable[[], Any],
    *,
    timeout: float,
    interval: float,
    retry_on: Tuple[Type[BaseException], ...] = (),
    description: str = "condition",
) -> Any:
    """Call ``fn()`` repeatedly until it returns a truthy value.

    Retries while ``fn()`` returns a falsy value, or raises one of ``retry_on``
    (typically ``requests.RequestException`` for a "wait for endpoint" poll).
    Raises :class:`TimeoutError` once ``timeout`` seconds have elapsed. Returns
    ``fn()``'s truthy value on success. Replaces the hand-rolled
    ``while time.time() < deadline: ... time.sleep(interval)`` loops.
    """
    condition = retry_if_result(lambda result: not result)
    if retry_on:
        condition = condition | retry_if_exception_type(retry_on)
    retryer = Retrying(
        reraise=False,
        stop=stop_after_delay(timeout),
        wait=wait_fixed(interval),
        retry=condition,
        before_sleep=_before_sleep,
    )
    try:
        return retryer(fn)
    except RetryError:
        raise TimeoutError(f"{description} not available after {int(timeout)}s")
