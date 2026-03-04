#!/usr/bin/env python3
"""
Headless browser automation for ArgoCD token retrieval via AWS IAM Identity Center SSO.
"""

import asyncio
import json
import os
import sys

try:
    from playwright.async_api import async_playwright
except ImportError:
    os.system("pip install playwright && playwright install chromium")
    from playwright.async_api import async_playwright

try:
    import pyotp
except ImportError:
    os.system("pip install pyotp")
    import pyotp


async def get_argocd_token(
    argocd_url: str,
    username: str,
    password: str,
    mfa_secret: str = None,
    headless: bool = True,
    timeout: int = 60000,
    debug: bool = False,
) -> dict:
    result = {"token": None, "cookies": None}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(ignore_https_errors=True)
        page = await context.new_page()
        page.set_default_timeout(timeout)

        try:
            print(f"Navigating to ArgoCD: {argocd_url}", file=sys.stderr)
            await page.goto(argocd_url, wait_until="networkidle")
            
            print(f"Current URL: {page.url}", file=sys.stderr)
            if debug:
                await page.screenshot(path="/tmp/step1_initial.png")

            # Click "LOG IN VIA SSO" button
            sso_button = await page.query_selector('button:has-text("LOG IN VIA SSO")')
            if not sso_button:
                # Try going to login page directly
                await page.goto(argocd_url.rstrip('/') + '/login', wait_until="networkidle")
                print(f"Navigated to login page: {page.url}", file=sys.stderr)
                sso_button = await page.query_selector('button:has-text("LOG IN VIA SSO")')
            
            if sso_button:
                print("Clicking SSO login button...", file=sys.stderr)
                await sso_button.click()
                # Wait for Keycloak username field to appear after redirect chain
                await page.wait_for_selector('#username', state="visible")
                print(f"Keycloak login page: {page.url}", file=sys.stderr)
                if debug:
                    await page.screenshot(path="/tmp/step2_sso_redirect.png")

                await page.fill('#username', username)
                await page.fill('#password', password)
                if debug:
                    await page.screenshot(path="/tmp/step3_keycloak_creds.png")
                await page.click('#kc-login, button[type="submit"]')
                await page.wait_for_load_state("domcontentloaded")
                await page.wait_for_timeout(2000)
                if debug:
                    print(f"After Keycloak login URL: {page.url}", file=sys.stderr)
                    await page.screenshot(path="/tmp/step4_keycloak_after.png")
            else:
                print("SSO button not found", file=sys.stderr)

            # Wait for redirect back to ArgoCD
            await page.wait_for_timeout(3000)
            if debug:
                print(f"Final URL: {page.url}", file=sys.stderr)
                await page.screenshot(path="/tmp/step7_final.png")

            # Extract token
            token = await page.evaluate("""() => {
                return localStorage.getItem('token') || 
                       sessionStorage.getItem('token') ||
                       document.cookie.split('; ').find(c => c.startsWith('argocd.token='))?.split('=')[1];
            }""")

            cookies = await context.cookies()
            result["cookies"] = {c["name"]: c["value"] for c in cookies}
            result["token"] = token or result["cookies"].get("argocd.token")
            
            if debug:
                print(f"Cookies: {list(result['cookies'].keys())}", file=sys.stderr)
            
            if result["token"]:
                print("Token retrieved successfully", file=sys.stderr)
            else:
                print(f"No token found. URL: {page.url}", file=sys.stderr)

        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            if debug:
                await page.screenshot(path="/tmp/error.png")
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
    parser.add_argument("--mfa-secret")
    parser.add_argument("--no-headless", action="store_true")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--output", choices=["token", "json"], default="token")
    args = parser.parse_args()

    result = asyncio.run(get_argocd_token(
        argocd_url=args.url,
        username=args.username,
        password=args.password,
        mfa_secret=args.mfa_secret,
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
