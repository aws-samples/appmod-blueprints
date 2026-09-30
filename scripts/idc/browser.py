"""Playwright/Chromium console-navigation helpers.

Browser bootstrap (install Chromium + system deps on demand) and the resilient
page-interaction primitives used by the orchestrator. ``goto_with_retry`` now
delegates its backoff to the shared ``resilience.retry_nav`` policy rather than
hand-rolling the attempt loop.

Importing this module bootstraps Playwright (pip-installing it and Chromium if
absent), mirroring the original script's import-time behaviour. Keep it out of
unit tests that only need the pure resilience layer.
"""

from __future__ import annotations

import subprocess
import sys

from .resilience import retry_nav

_CHROMIUM_YUM_DEPS = [
    "atk", "at-spi2-atk", "cups-libs", "libdrm", "libxkbcommon",
    "libXcomposite", "libXdamage", "libXrandr", "mesa-libgbm", "pango",
    "alsa-lib", "nss", "nspr", "libXScrnSaver", "libXtst", "gtk3",
]


def _install_system_deps():
    print("Installing Chromium system dependencies via yum...", file=sys.stderr)
    subprocess.run(["sudo", "yum", "install", "-y"] + _CHROMIUM_YUM_DEPS, capture_output=True)


def ensure_playwright_browsers():
    """Install the Chromium browser + system deps if not already present."""
    try:
        from playwright._impl._driver import compute_driver_executable

        driver = compute_driver_executable()
        result = subprocess.run(
            [str(driver), "install", "--dry-run", "chromium"], capture_output=True, text=True
        )
        needs_install = result.returncode != 0
    except Exception:
        needs_install = True
    if needs_install:
        _install_system_deps()
        subprocess.check_call([sys.executable, "-m", "playwright", "install", "chromium"])


# Bootstrap the Playwright package itself (import-time, matches original script).
try:
    from playwright.async_api import async_playwright
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "playwright"])
    _install_system_deps()
    subprocess.check_call([sys.executable, "-m", "playwright", "install", "chromium"])
    from playwright.async_api import async_playwright


async def click_first_visible(page, selectors, timeout=10000, description="element"):
    """Try multiple selectors, click the first visible one. Raises if none found."""
    for sel in selectors:
        try:
            el = await page.wait_for_selector(sel, state="visible", timeout=timeout)
            if el:
                await el.click()
                return el
        except Exception:
            continue
    raise RuntimeError(f"Could not find {description} with selectors: {selectors}")


async def find_first_visible(page, selectors, timeout=5000):
    """Return the first visible element matching any selector, or None."""
    for sel in selectors:
        try:
            el = await page.wait_for_selector(sel, state="visible", timeout=timeout)
            if el:
                return el
        except Exception:
            continue
    return None


async def goto_with_retry(page, url, *, wait_until="domcontentloaded", retries=5, base_delay=3):
    """``page.goto()`` with retry/backoff on transient network errors.

    Chromium surfaces flaky IDE-network conditions (notably
    ``net::ERR_NETWORK_CHANGED`` when the network is reconfigured/saturated
    mid-request) as ``goto()`` exceptions. A single failure would otherwise abort
    the whole IDC federation. Transient errors (see
    ``resilience.TRANSIENT_NAV_ERROR_TOKENS``) are retried with exponential
    backoff; anything else re-raises immediately.
    """

    @retry_nav(retries=retries, base_delay=base_delay)
    async def _do():
        return await page.goto(url, wait_until=wait_until)

    return await _do()


async def wait_for_stable(page, timeout=10000):
    try:
        await page.wait_for_load_state("networkidle", timeout=timeout)
    except Exception:
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=timeout)
        except Exception:
            pass
    await page.wait_for_timeout(2000)
    # Wait for spinners to disappear
    for spinner_sel in [".awsui-spinner", '[class*="spinner"]', '[role="progressbar"]']:
        try:
            await page.wait_for_selector(spinner_sel, state="hidden", timeout=5000)
        except Exception:
            pass


async def screenshot(page, path, debug):
    if debug:
        try:
            await page.screenshot(path=path)
        except Exception:
            pass


async def dismiss_overlays(page):
    """Dismiss tutorial overlays, notification banners, cookie consents, etc."""
    for _ in range(10):
        dismissed = False
        for sel in [
            'button[data-testid="awsc-tutorial-skip-button"]',
            'button:has-text("Skip tour")',
            'button:has-text("Done")',
            'button:has-text("Got it")',
            'button:has-text("Dismiss")',
            'button:has-text("Try now")',  # "Account color" promo
            'button:has-text("Not now")',
            'button:has-text("Accept")',   # Cookie consent popup
            '[class*="hotspot"] button:has-text("Next")',  # Service menu tooltip
            '[class*="tutorial"] button:has-text("Next")',  # Tutorial tooltip
            '[class*="popover"] button:has-text("Next")',  # Popover tooltip
            '[role="dialog"] button:has-text("Next")',  # Dialog tooltip
            '[class*="awsui-popover"] button:has-text("Next")',  # CloudScape popover
        ]:
            try:
                btn = await page.wait_for_selector(sel, state="visible", timeout=1500)
                if btn:
                    await btn.click()
                    await page.wait_for_timeout(500)
                    dismissed = True
                    break
            except Exception:
                continue
        if not dismissed:
            break
