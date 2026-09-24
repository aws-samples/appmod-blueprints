"""Hermetic unit tests for sweep.resilience (issue #924, principle 5).

No boto3, no network, no real sleeping — `sleep` is injected as a no-op and the
tenacity-vs-stdlib-fallback paths are both exercised deterministically.

Run:  python -m pytest workshop/scripts/tests/test_sweep_resilience.py -q
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sweep import resilience as r  # noqa: E402


class FakeClientError(Exception):
    """Mimics botocore ClientError shape: .response['Error']['Code'/'Message']."""
    def __init__(self, code, message=""):
        super().__init__(f"{code}: {message}")
        self.response = {"Error": {"Code": code, "Message": message}}


def noop_sleep(_):  # injected so tests never actually wait
    return None


# ── classification ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("code", sorted(r.TRANSIENT_CODES))
def test_transient_codes_classified_transient(code):
    exc = FakeClientError(code)
    assert r.is_transient(exc) is True
    assert r.classify(exc) == "transient"


@pytest.mark.parametrize("code", sorted(r.GONE_CODES))
def test_gone_codes_classified_gone(code):
    exc = FakeClientError(code)
    assert r.is_already_gone(exc) is True
    # 'gone' takes priority over everything in classify()
    assert r.classify(exc) == "gone"


@pytest.mark.parametrize("msg", [
    "The subnet 'subnet-x' does not exist",
    "Resource NOT FOUND",
    "No such distribution",
    "The security group was already deleted",
])
def test_gone_by_message_substring(msg):
    exc = FakeClientError("SomeOtherCode", msg)
    assert r.is_already_gone(exc) is True
    assert r.classify(exc) == "gone"


@pytest.mark.parametrize("code", sorted(r.ACCESS_DENIED_CODES))
def test_access_denied_classified_and_not_swallowed(code):
    exc = FakeClientError(code)
    assert r.is_access_denied(exc) is True
    assert r.classify(exc) == "access_denied"
    # access-denied must NOT be treated as transient (would loop) or gone (would hide it)
    assert r.is_transient(exc) is False
    assert r.is_already_gone(exc) is False


def test_permanent_default():
    exc = FakeClientError("ValidationException", "bad input")
    assert r.classify(exc) == "permanent"


def test_error_code_degrades_on_non_client_error():
    assert r.error_code(ValueError("boom")) == "ValueError"


# ── retry_aws ─────────────────────────────────────────────────────────────────

def _make_flaky(n_transient, then=("ok",), exc=None):
    calls = {"n": 0}
    exc = exc or FakeClientError("Throttling")

    def fn():
        calls["n"] += 1
        if calls["n"] <= n_transient:
            raise exc
        return then[0]
    fn.calls = calls
    return fn


@pytest.mark.parametrize("force_fallback", [False, True])
def test_retry_aws_recovers_after_transient(monkeypatch, force_fallback):
    if force_fallback:
        monkeypatch.setattr(r, "_tenacity", None, raising=False)
        monkeypatch.setattr(r, "_USING_STDLIB_FALLBACK", True, raising=False)
        monkeypatch.setattr(r, "ensure_tenacity", lambda: None)
    fn = _make_flaky(2)
    out = r.retry_aws(fn, attempts=5, wait=0.0, backoff=1.0, sleep=noop_sleep)
    assert out == "ok"
    assert fn.calls["n"] == 3


@pytest.mark.parametrize("force_fallback", [False, True])
def test_retry_aws_idempotent_delete_returns_none(monkeypatch, force_fallback):
    if force_fallback:
        monkeypatch.setattr(r, "ensure_tenacity", lambda: None)

    def fn():
        raise FakeClientError("ResourceNotFoundException", "already gone")
    # already-gone is swallowed → None, no raise, treated as success
    assert r.retry_aws(fn, attempts=3, wait=0.0, sleep=noop_sleep) is None


@pytest.mark.parametrize("force_fallback", [False, True])
def test_retry_aws_reraises_permanent(monkeypatch, force_fallback):
    if force_fallback:
        monkeypatch.setattr(r, "ensure_tenacity", lambda: None)

    def fn():
        raise FakeClientError("ValidationException", "nope")
    with pytest.raises(FakeClientError):
        r.retry_aws(fn, attempts=3, wait=0.0, sleep=noop_sleep)


@pytest.mark.parametrize("force_fallback", [False, True])
def test_retry_aws_gives_up_after_attempts(monkeypatch, force_fallback):
    if force_fallback:
        monkeypatch.setattr(r, "ensure_tenacity", lambda: None)
    fn = _make_flaky(10)  # always transient within attempt budget
    with pytest.raises(FakeClientError):
        r.retry_aws(fn, attempts=3, wait=0.0, backoff=1.0, sleep=noop_sleep)
    assert fn.calls["n"] == 3


# ── poll_until ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("force_fallback", [False, True])
def test_poll_until_true_when_predicate_becomes_true(monkeypatch, force_fallback):
    if force_fallback:
        monkeypatch.setattr(r, "ensure_tenacity", lambda: None)
    state = {"n": 0}

    def pred():
        state["n"] += 1
        return state["n"] >= 3
    assert r.poll_until(pred, attempts=5, delay=0.0, sleep=noop_sleep) is True
    assert state["n"] == 3


@pytest.mark.parametrize("force_fallback", [False, True])
def test_poll_until_false_on_timeout(monkeypatch, force_fallback):
    if force_fallback:
        monkeypatch.setattr(r, "ensure_tenacity", lambda: None)
    assert r.poll_until(lambda: False, attempts=3, delay=0.0, sleep=noop_sleep) is False


def test_ensure_tenacity_is_cached_and_safe():
    # Should not raise regardless of environment; returns module or None.
    first = r.ensure_tenacity()
    second = r.ensure_tenacity()
    assert first is second
