"""Unit tests for ``idc.browser.screenshot``: owner-only files (new or pre-existing),
no write without debug, False on failure. A fake page stands in for Playwright, and a
stub ``playwright.async_api`` keeps ``idc.browser`` from bootstrapping Playwright."""

import asyncio
import os
import stat
import sys
import types

try:  # real Playwright if installed, else a stub (never pip-install from a unit test)
    import playwright.async_api  # noqa: F401
except ImportError:
    _pw = types.ModuleType("playwright")
    _api = types.ModuleType("playwright.async_api")
    _api.async_playwright = None
    _pw.async_api = _api
    sys.modules["playwright"] = _pw
    sys.modules["playwright.async_api"] = _api

from idc.browser import screenshot  # noqa: E402


class FakePage:
    def __init__(self, fail=False):
        self.fail = fail
        self.calls = 0

    async def screenshot(self, path):
        self.calls += 1
        if self.fail:
            raise RuntimeError("boom")
        with open(path, "wb") as f:  # like Playwright: plain open(), keeps an existing mode
            f.write(b"png")


def _mode(p):
    return stat.S_IMODE(os.stat(p).st_mode)


def test_new_file_is_owner_only(tmp_path):
    p = tmp_path / "new.png"
    assert asyncio.run(screenshot(FakePage(), str(p), True)) is True
    assert _mode(p) == 0o600


def test_preexisting_world_readable_file_becomes_owner_only(tmp_path):
    p = tmp_path / "old.png"
    p.write_bytes(b"stale")
    os.chmod(p, 0o644)
    assert asyncio.run(screenshot(FakePage(), str(p), True)) is True
    assert _mode(p) == 0o600
    assert p.read_bytes() == b"png"


def test_no_debug_writes_nothing(tmp_path):
    page = FakePage()
    p = tmp_path / "x.png"
    assert asyncio.run(screenshot(page, str(p), False)) is False
    assert page.calls == 0 and not p.exists()


def test_failure_returns_false(tmp_path):
    assert asyncio.run(screenshot(FakePage(fail=True), str(tmp_path / "x.png"), True)) is False
