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
