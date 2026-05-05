#!/usr/bin/env python3
"""
Headless browser automation for ArgoCD token retrieval via AWS IAM Identity Center SSO.

Supports two login flows:
  1. AWS IAM Identity Center (IDC) direct → multi-step: Username → Next → Password → Sign in
  2. IDC → Keycloak external IdP redirect → Keycloak form with #username + #password

The script auto-detects which flow is active based on the page URL after SSO redirect.
"""

import asyncio
import json
import os
import sys

_CHROMIUM_YUM_DEPS = [
    "atk", "at-spi2-atk", "cups-libs", "libdrm", "libxkbcommon",
    "libXcomposite", "libXdamage", "libXrandr", "mesa-libgbm", "pango",
    "alsa-lib", "nss", "nspr", "libXScrnSaver", "libXtst", "gtk3",
]


def _ensure_chromium_deps():
    """Install Chromium system libraries if missing."""
    import subprocess
    import shutil
    # Quick check: if libatk-1.0.so.0 is missing, install all deps
    if not shutil.which("playwright") or not os.path.exists("/usr/lib64/libatk-1.0.so.0"):
        subprocess.run(["sudo", "yum", "install", "-y"] + _CHROMIUM_YUM_DEPS, capture_output=True)


try:
    from playwright.async_api import async_playwright
    _ensure_chromium_deps()
except ImportError:
    print("Installing playwright and Chromium system dependencies...", file=sys.stderr)
    _ensure_chromium_deps()
    os.system("pip install playwright >/dev/null 2>&1 && playwright install chromium >/dev/null 2>&1")
    from playwright.async_api import async_playwright


async def _extract_token(page, context):
    """Extract ArgoCD auth token from browser storage or cookies."""
    token = await page.evaluate("""() => {
        return localStorage.getItem('token') ||
               sessionStorage.getItem('token') ||
               document.cookie.split('; ').find(c => c.startsWith('argocd.token='))?.split('=').slice(1).join('=');
    }""")
    if token:
        return token
    cookies = await context.cookies()
    for c in cookies:
        if c["name"] == "argocd.token":
            return c["value"]
    return None


async def _handle_idc_login(page, username, password, debug):
    """Handle AWS IAM Identity Center multi-step login (Username → Next → Password → Sign in)."""
    print("Detected AWS IAM Identity Center login page", file=sys.stderr)

    # Step 1: Username
    username_input = await page.wait_for_selector(
        'input[type="text"], input[type="email"]', state="visible", timeout=10000
    )
    await username_input.fill(username)
    if debug:
        await page.screenshot(path="/tmp/idc_step1.png")

    next_btn = await page.query_selector('button:has-text("Next"), button[type="submit"]')
    if next_btn:
        await next_btn.click()
    await page.wait_for_load_state("networkidle")
    await page.wait_for_timeout(2000)

    if debug:
        print(f"After username: {page.url}", file=sys.stderr)
        await page.screenshot(path="/tmp/idc_step2.png")

    # After Next, IDC may redirect to external IdP (Keycloak) or show password field
    if any(kw in page.url for kw in ["keycloak", "/auth/realms", "/realms/"]):
        print("IDC redirected to Keycloak", file=sys.stderr)
        return await _handle_keycloak_login(page, username, password, debug)

    # Step 2: Password on IDC page
    password_input = await page.wait_for_selector(
        'input[type="password"]', state="visible", timeout=15000
    )
    await password_input.fill(password)
    if debug:
        await page.screenshot(path="/tmp/idc_step3.png")

    signin_btn = await page.query_selector(
        'button:has-text("Sign in"), button:has-text("Submit"), button[type="submit"]'
    )
    if signin_btn:
        await signin_btn.click()
    await page.wait_for_load_state("networkidle")
    await page.wait_for_timeout(3000)

    # Handle consent/allow page if present
    allow_btn = await page.query_selector('button:has-text("Allow"), button:has-text("Accept")')
    if allow_btn:
        await allow_btn.click()
        await page.wait_for_load_state("networkidle")
        await page.wait_for_timeout(2000)


async def _handle_keycloak_login(page, username, password, debug):
    """Handle Keycloak login form (#username + #password on same page)."""
    print("Detected Keycloak login page", file=sys.stderr)

    await page.wait_for_selector('#username', state="visible", timeout=15000)
    await page.fill('#username', username)
    await page.fill('#password', password)
    if debug:
        await page.screenshot(path="/tmp/kc_creds.png")

    await page.click('#kc-login, button[type="submit"]')
    # Don't wait for networkidle — SAML redirect chain may keep network busy
    # Instead wait for domcontentloaded and give time for redirects
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=15000)
    except Exception:
        pass
    await page.wait_for_timeout(5000)


async def get_argocd_token(
    argocd_url: str,
    username: str,
    password: str,
    headless: bool = True,
    timeout: int = 90000,
    debug: bool = False,
) -> dict:
    result = {"token": None, "cookies": None}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(ignore_https_errors=True)
        page = await context.new_page()
        page.set_default_timeout(timeout)

        try:
            login_url = argocd_url.rstrip('/') + '/login'
            print(f"Navigating to: {login_url}", file=sys.stderr)
            await page.goto(login_url, wait_until="networkidle")
            current = page.url
            print(f"Landed on: {current}", file=sys.stderr)
            if debug:
                await page.screenshot(path="/tmp/step1_initial.png")

            # Already authenticated?
            if '/applications' in current and 'login' not in current:
                result["token"] = await _extract_token(page, context)
                if result["token"]:
                    print("Token found from existing session", file=sys.stderr)
                    return result

            # Determine which login flow we're in
            if 'signin.aws' in current:
                await _handle_idc_login(page, username, password, debug)
            else:
                # ArgoCD login page — click SSO button
                try:
                    sso_button = await page.wait_for_selector(
                        'button:has-text("LOG IN VIA SSO")', state="visible", timeout=15000
                    )
                except Exception:
                    sso_button = None
                if sso_button:
                    print("Clicking SSO login button...", file=sys.stderr)
                    await sso_button.click()
                    await page.wait_for_load_state("networkidle")
                    await page.wait_for_timeout(3000)
                    current = page.url
                    print(f"After SSO click: {current}", file=sys.stderr)
                    if debug:
                        await page.screenshot(path="/tmp/step2_after_sso.png")

                    if 'signin.aws' in current:
                        await _handle_idc_login(page, username, password, debug)
                    elif any(kw in current for kw in ["keycloak", "/auth/realms", "/realms/"]):
                        await _handle_keycloak_login(page, username, password, debug)
                    else:
                        print(f"Unexpected redirect: {current}", file=sys.stderr)
                else:
                    print("No SSO button found", file=sys.stderr)

            # Wait for redirect back to ArgoCD
            argocd_host = argocd_url.split("//")[-1].split("/")[0]
            for _ in range(15):
                if argocd_host in page.url:
                    break
                await page.wait_for_timeout(1000)

            if debug:
                print(f"Final URL: {page.url}", file=sys.stderr)
                await page.screenshot(path="/tmp/step_final.png")

            result["token"] = await _extract_token(page, context)
            cookies = await context.cookies()
            result["cookies"] = {c["name"]: c["value"] for c in cookies}

            if result["token"]:
                print("Token retrieved successfully", file=sys.stderr)
            else:
                print(f"No token found. Final URL: {page.url}", file=sys.stderr)

        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            if debug:
                try:
                    await page.screenshot(path="/tmp/error.png")
                except Exception:
                    pass
            raise
        finally:
            await browser.close()

    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--no-headless", action="store_true")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--output", choices=["token", "json"], default="token")
    args = parser.parse_args()

    result = asyncio.run(get_argocd_token(
        argocd_url=args.url,
        username=args.username,
        password=args.password,
        headless=not args.no_headless,
        debug=args.debug,
    ))

    if args.output == "json":
        print(json.dumps(result, indent=2))
    elif result["token"]:
        print(result["token"])
    else:
        print("Failed to retrieve token", file=sys.stderr)
        sys.exit(1)
