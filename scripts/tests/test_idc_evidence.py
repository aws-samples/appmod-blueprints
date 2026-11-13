"""Unit tests for ``idc.evidence``: the always-on error screenshot must never capture
the SCIM token without --debug, and screenshots are written owner-only. Stdlib only."""

import os
import stat

import pytest

from idc.constants import ERROR_SCREENSHOT
from idc.evidence import private_umask, should_take_error_screenshot


@pytest.mark.parametrize(
    "debug,token_exposed,expected",
    [
        (False, False, True),   # failure before the token dialog: keep evidence
        (False, True, False),   # token dialog open, no --debug: never capture the token
        (True, True, True),     # operator asked for --debug (as for step10.png)
        (True, False, True),
    ],
)
def test_error_screenshot_policy(debug, token_exposed, expected):
    assert should_take_error_screenshot(debug, token_exposed) is expected


def test_private_umask_writes_owner_only_and_restores(tmp_path):
    before = os.umask(0o022)
    os.umask(before)
    with private_umask():
        p = tmp_path / "shot.png"
        p.write_bytes(b"x")
    assert stat.S_IMODE(p.stat().st_mode) == 0o600
    after = os.umask(before)
    os.umask(after)
    assert after == before


def test_error_screenshot_has_distinct_name():
    # /tmp/error.png is also written by other scripts (argocd token automation).
    assert ERROR_SCREENSHOT == "/tmp/idc-error.png"


# --- orchestrator wiring of the token-exposed flag (static: the orchestrator needs
# Playwright, so its source is read instead of imported) -----------------------------
import ast  # noqa: E402

_ORCH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "idc", "orchestrator.py")


def _sets_flag(stmt):
    return (
        isinstance(stmt, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "token_exposed" for t in stmt.targets)
        and isinstance(stmt.value, ast.Constant)
        and stmt.value.value is True
    )


def _is_click(stmt, needle):
    return isinstance(stmt, ast.Expr) and needle in ast.unparse(stmt)


def _blocks():
    for node in ast.walk(ast.parse(open(_ORCH).read())):
        for field in ("body", "orelse"):
            body = getattr(node, field, None)
            if isinstance(body, list):
                yield body


def _flag_set_before(needle):
    for body in _blocks():
        for i, stmt in enumerate(body):
            if _is_click(stmt, needle):
                return any(_sets_flag(s) for s in body[:i])
    raise AssertionError(f"click not found: {needle}")


def test_flag_set_before_enable_click():
    # A click that raises after dispatch may still have opened the token dialog.
    assert _flag_set_before("enable_btn.click()")


def test_flag_set_before_generate_token_click():
    assert _flag_set_before("Generate token")


def test_flag_set_only_before_the_clicks_and_before_show_token():
    src = open(_ORCH).read()
    assert src.index("token_exposed = True") < src.index('Show token')
    assert src.count("token_exposed = True") == 2
