"""Centralized resilience primitives for the teardown sweep (issue #924).

Mikhail's review principles applied here:
  1. Adopt a standard retry library (tenacity) instead of hand-rolled
     `for i in range(N): ... time.sleep(S)` loops.
  3. Classify transient vs. permanent vs. already-gone AWS errors in ONE place
     (`classify` / `is_transient` / `is_already_gone` / `is_access_denied`),
     instead of scattering broad `except Exception` swallows.

Runtime constraint (why the import bootstrap exists):
  The sweep runs in the teardown CodeBuild project
  (`aws/codebuild/amazonlinux2-x86_64-standard:5.0`) whose buildspec pre_build
  installs helm/terraform/jq/kubectl/yq but NO python deps — there is no
  `pip install` step on that path. This is a *destruction-critical* path: it
  must NEVER hard-fail merely because an optional dependency is missing.
  `ensure_tenacity()` therefore (a) imports tenacity if present, (b) tries a
  quiet `pip install` if not, and (c) falls back to a tiny stdlib-backed shim
  implementing the same `Retrying` surface we use, so the sweep always runs.
  The durable path (pin `tenacity` in the CodeBuild buildspec pre_build in the
  platform-engineering-on-eks repo) is tracked in issue #924.
"""

from __future__ import annotations

import subprocess
import sys
import time
from typing import Any, Callable, Optional

# ── Transient / terminal AWS error classification (principle 3: ONE place) ──────
#
# Kept as plain string sets so this module is importable and unit-testable with
# NO boto3/botocore/network dependency — the classifier inspects the error code
# defensively (botocore ClientError, or any exception exposing a code/message).

# Recoverable-with-retry: eventual consistency, dependency ordering, throttling.
TRANSIENT_CODES = frozenset({
    "DependencyViolation",          # ENIs/subnets still attached; re-drive after detach
    "ResourceInUseException",
    "ResourceInUse",
    "InvalidParameterException",    # often "resource is being deleted" style races
    "ConcurrentModificationException",
    "OperationNotPermitted",        # transient during in-flight deletes
    "RequestLimitExceeded",
    "Throttling",
    "ThrottlingException",
    "ThrottledException",
    "TooManyRequestsException",
    "ServiceUnavailable",
    "InternalError",
    "InternalFailure",
})

# Already-gone: a delete of an absent resource is an idempotent no-op success,
# NOT a failure — the sweep is rerunnable by design.
GONE_CODES = frozenset({
    "ResourceNotFoundException",
    "ResourceNotFound",
    "NoSuchEntity",
    "NotFoundException",
    "InvalidParameterValue",        # e.g. "does not exist" on some EC2 deletes
    "NoSuchBucket",
    "NoSuchDistribution",
    "DBInstanceNotFound",
    "WorkspaceNotFound",
})

GONE_SUBSTRINGS = (
    "not found",
    "does not exist",
    "no such",
    "notfound",
    "already deleted",
    "could not be found",
)

ACCESS_DENIED_CODES = frozenset({
    "AccessDenied",
    "AccessDeniedException",
    "UnauthorizedOperation",
    "AuthFailure",
    "Forbidden",
})


def error_code(exc: BaseException) -> str:
    """Best-effort extraction of an AWS error code from any exception.

    Works for botocore ClientError (``exc.response['Error']['Code']``) and
    degrades gracefully to the class name / message for anything else — so the
    classifier never itself raises on an unexpected exception shape.
    """
    resp = getattr(exc, "response", None)
    if isinstance(resp, dict):
        code = resp.get("Error", {}).get("Code")
        if code:
            return str(code)
    # botocore also exposes .operation_name / .fmt; fall back to the class name.
    return exc.__class__.__name__


def _message(exc: BaseException) -> str:
    resp = getattr(exc, "response", None)
    if isinstance(resp, dict):
        msg = resp.get("Error", {}).get("Message")
        if msg:
            return str(msg)
    return str(exc)


def is_transient(exc: BaseException) -> bool:
    """True if the error is worth retrying (eventual consistency / throttle)."""
    return error_code(exc) in TRANSIENT_CODES


def is_already_gone(exc: BaseException) -> bool:
    """True if the target resource is already absent (idempotent-delete success)."""
    if error_code(exc) in GONE_CODES:
        return True
    msg = _message(exc).lower()
    return any(s in msg for s in GONE_SUBSTRINGS)


def is_access_denied(exc: BaseException) -> bool:
    """True for permission errors — these must be surfaced/counted, never swallowed
    silently (principle 4 + the #932 completeness gate relies on honest reporting)."""
    return error_code(exc) in ACCESS_DENIED_CODES


def classify(exc: BaseException) -> str:
    """Single classification entry point → one of:
    'gone' | 'access_denied' | 'transient' | 'permanent'."""
    if is_already_gone(exc):
        return "gone"
    if is_access_denied(exc):
        return "access_denied"
    if is_transient(exc):
        return "transient"
    return "permanent"


# ── tenacity bootstrap with defensive stdlib fallback ───────────────────────────

def _install_tenacity() -> bool:
    """Try a quiet runtime `pip install tenacity`. Returns True on success."""
    for args in (
        [sys.executable, "-m", "pip", "install", "--quiet", "--disable-pip-version-check", "tenacity"],
        [sys.executable, "-m", "pip", "install", "--quiet", "--user", "tenacity"],
    ):
        try:
            subprocess.run(args, check=True, capture_output=True, timeout=120)
            return True
        except Exception:
            continue
    return False


class _StdlibRetrying:
    """Minimal drop-in for the tenacity API surface this module uses.

    Supports the two call shapes `retry_aws` and `poll_until` need:
      - retry on exception matching a predicate, with fixed/backoff waits;
      - retry on a *result* predicate (for polling to a terminal state).
    Used only when tenacity cannot be imported OR installed, so the
    destruction-critical sweep still runs (degraded but functional).
    """

    def __init__(self, *, attempts: int, wait: float, backoff: float = 1.0,
                 retry_on_exc: Optional[Callable[[BaseException], bool]] = None,
                 retry_on_result: Optional[Callable[[Any], bool]] = None,
                 sleep: Callable[[float], None] = time.sleep):
        self.attempts = max(1, attempts)
        self.wait = wait
        self.backoff = backoff
        self.retry_on_exc = retry_on_exc
        self.retry_on_result = retry_on_result
        self.sleep = sleep

    def __call__(self, fn: Callable[..., Any], *a, **kw) -> Any:
        delay = self.wait
        last_exc: Optional[BaseException] = None
        for attempt in range(1, self.attempts + 1):
            try:
                result = fn(*a, **kw)
            except BaseException as exc:  # noqa: BLE001 - re-raised below if not retryable
                last_exc = exc
                if self.retry_on_exc and self.retry_on_exc(exc) and attempt < self.attempts:
                    self.sleep(delay)
                    delay *= self.backoff
                    continue
                raise
            else:
                if self.retry_on_result and self.retry_on_result(result) and attempt < self.attempts:
                    self.sleep(delay)
                    delay *= self.backoff
                    continue
                return result
        if last_exc is not None:
            raise last_exc
        return None


# Resolved lazily by ensure_tenacity(); None until then.
_tenacity = None
_USING_STDLIB_FALLBACK = False


def ensure_tenacity():
    """Import tenacity, installing it if needed; return the module or None.

    Never raises — on total failure returns None and callers transparently use
    the stdlib fallback. Idempotent/cached.
    """
    global _tenacity, _USING_STDLIB_FALLBACK
    if _tenacity is not None or _USING_STDLIB_FALLBACK:
        return _tenacity
    try:
        import tenacity  # type: ignore
        _tenacity = tenacity
        return _tenacity
    except ImportError:
        pass
    if _install_tenacity():
        try:
            import tenacity  # type: ignore
            _tenacity = tenacity
            return _tenacity
        except ImportError:
            pass
    _USING_STDLIB_FALLBACK = True
    return None


def using_stdlib_fallback() -> bool:
    return _USING_STDLIB_FALLBACK


# ── Public helpers used by the reapers ──────────────────────────────────────────

def retry_aws(fn: Callable[..., Any], *args,
              attempts: int = 5, wait: float = 5.0, backoff: float = 2.0,
              retryable: Callable[[BaseException], bool] = is_transient,
              sleep: Callable[[float], None] = time.sleep, **kwargs) -> Any:
    """Call a boto3 operation, retrying transient AWS errors with exponential backoff.

    A delete that hits an already-gone resource is treated as success (returns
    None) — the sweep is idempotent by design.
    """
    def _wrapped():
        try:
            return fn(*args, **kwargs)
        except BaseException as exc:  # noqa: BLE001
            if is_already_gone(exc):
                return None
            raise

    ten = ensure_tenacity()
    if ten is None:
        return _StdlibRetrying(attempts=attempts, wait=wait, backoff=backoff,
                               retry_on_exc=retryable, sleep=sleep)(_wrapped)
    retrying = ten.Retrying(
        stop=ten.stop_after_attempt(attempts),
        wait=ten.wait_exponential(multiplier=wait, max=wait * (backoff ** attempts)),
        retry=ten.retry_if_exception(retryable),
        reraise=True,
        sleep=sleep,
    )
    return retrying(_wrapped)


def poll_until(predicate: Callable[[], bool], *,
               attempts: int, delay: float, backoff: float = 1.0,
               sleep: Callable[[float], None] = time.sleep) -> bool:
    """Poll ``predicate`` until it returns truthy or attempts are exhausted.

    Replaces the hand-rolled ``for i in range(N): if cond: break; time.sleep(S)``
    loops. Returns True if the predicate became truthy, False on timeout — the
    caller decides whether a timeout is fatal (matching current behavior, where
    most waits are best-effort before a re-drive).
    """
    ten = ensure_tenacity()
    if ten is None:
        def _p():
            return bool(predicate())
        got = _StdlibRetrying(attempts=attempts, wait=delay, backoff=backoff,
                              retry_on_result=lambda r: not r, sleep=sleep)(_p)
        return bool(got)

    retrying = ten.Retrying(
        stop=ten.stop_after_attempt(attempts),
        wait=(ten.wait_fixed(delay) if backoff == 1.0
              else ten.wait_exponential(multiplier=delay, max=delay * (backoff ** attempts))),
        retry=ten.retry_if_result(lambda r: not r),
        reraise=False,
        sleep=sleep,
    )
    try:
        return bool(retrying(lambda: bool(predicate())))
    except Exception:
        # tenacity RetryError when all attempts returned falsy → timed out.
        return False
