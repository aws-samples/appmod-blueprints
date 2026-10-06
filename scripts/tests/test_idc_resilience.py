"""Unit tests for ``idc.resilience`` — the centralized retry / transient-error
classification layer.

These are fast and hermetic: they exercise only ``idc.resilience`` (tenacity +
stdlib, no boto3/playwright/network) and instantiate the retry policies with
zero delay so no real time is spent.
"""

import asyncio

import pytest

from idc import resilience
from idc.resilience import (
    TransientHTTPError,
    is_transient_http_error,
    is_transient_nav_error,
    poll_until,
    retry_http,
    retry_nav,
)


# ---------------------------------------------------------------------------
# Transient-error classification
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("token", resilience.TRANSIENT_NAV_ERROR_TOKENS)
def test_nav_tokens_are_transient(token):
    exc = RuntimeError(f"page.goto failed: net::{token} at https://example")
    assert is_transient_nav_error(exc) is True


def test_deterministic_nav_error_is_not_transient():
    assert is_transient_nav_error(RuntimeError("Could not find Actions button")) is False
    assert is_transient_nav_error(ValueError("ERR_SOMETHING_ELSE")) is False


def test_transient_http_classification():
    assert is_transient_http_error(TransientHTTPError("HTTP 503")) is True
    assert is_transient_http_error(RuntimeError("hard failure")) is False


# ---------------------------------------------------------------------------
# retry_nav — transient nav errors retried, deterministic ones not
# ---------------------------------------------------------------------------
def test_retry_nav_recovers_after_transient_failures():
    calls = {"n": 0}

    @retry_nav(retries=5, base_delay=0)
    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("net::ERR_NETWORK_CHANGED")
        return "ok"

    assert flaky() == "ok"
    assert calls["n"] == 3


def test_retry_nav_reraises_after_exhausting_retries():
    calls = {"n": 0}

    @retry_nav(retries=3, base_delay=0)
    def always_transient():
        calls["n"] += 1
        raise RuntimeError("net::ERR_TIMED_OUT")

    with pytest.raises(RuntimeError, match="ERR_TIMED_OUT"):
        always_transient()
    assert calls["n"] == 3  # attempted exactly `retries` times


def test_retry_nav_does_not_retry_deterministic_error():
    calls = {"n": 0}

    @retry_nav(retries=5, base_delay=0)
    def hard_fail():
        calls["n"] += 1
        raise RuntimeError("Could not find AWS metadata download button")

    with pytest.raises(RuntimeError, match="metadata download"):
        hard_fail()
    assert calls["n"] == 1  # no retries on a non-transient error


def test_retry_nav_works_on_coroutines():
    calls = {"n": 0}

    @retry_nav(retries=4, base_delay=0)
    async def flaky_async():
        calls["n"] += 1
        if calls["n"] < 2:
            raise RuntimeError("net::ERR_CONNECTION_RESET")
        return "async-ok"

    # tenacity returns an awaitable when wrapping a coroutine; drive it directly
    # so the test needs no pytest-asyncio plugin.
    assert asyncio.run(flaky_async()) == "async-ok"
    assert calls["n"] == 2


# ---------------------------------------------------------------------------
# retry_http — only TransientHTTPError is retried
# ---------------------------------------------------------------------------
def test_retry_http_retries_transient_then_succeeds():
    calls = {"n": 0}

    @retry_http(attempts=3, delay=0)
    def fed():
        calls["n"] += 1
        if calls["n"] < 3:
            raise TransientHTTPError("Federation HTTP 500")
        return "token"

    assert fed() == "token"
    assert calls["n"] == 3


def test_retry_http_gives_up_after_attempts():
    calls = {"n": 0}

    @retry_http(attempts=3, delay=0)
    def fed():
        calls["n"] += 1
        raise TransientHTTPError("Federation request failed")

    with pytest.raises(TransientHTTPError):
        fed()
    assert calls["n"] == 3


def test_retry_http_does_not_retry_hard_error():
    calls = {"n": 0}

    @retry_http(attempts=3, delay=0)
    def fed():
        calls["n"] += 1
        raise KeyError("AccessKeyId")

    with pytest.raises(KeyError):
        fed()
    assert calls["n"] == 1


# ---------------------------------------------------------------------------
# poll_until — wait-for-condition helper
# ---------------------------------------------------------------------------
def test_poll_until_returns_first_truthy_value():
    values = iter([None, None, "descriptor"])

    def fetch():
        return next(values)

    assert poll_until(fetch, timeout=10, interval=0, description="thing") == "descriptor"


def test_poll_until_times_out_when_never_ready():
    def never():
        return None

    with pytest.raises(TimeoutError, match="thing not available after 0s"):
        poll_until(never, timeout=0, interval=0, description="thing")


def test_poll_until_retries_on_listed_exception():
    class Boom(Exception):
        pass

    state = {"n": 0}

    def flaky():
        state["n"] += 1
        if state["n"] < 3:
            raise Boom("not up yet")
        return "up"

    assert poll_until(flaky, timeout=10, interval=0, retry_on=(Boom,), description="ep") == "up"
    assert state["n"] == 3


def test_poll_until_propagates_unlisted_exception():
    class Listed(Exception):
        pass

    def boom():
        raise ValueError("programming error, not transient")

    # ValueError is not in retry_on -> must propagate as-is, not as TimeoutError.
    with pytest.raises(ValueError, match="programming error"):
        poll_until(boom, timeout=10, interval=0, retry_on=(Listed,), description="ep")
