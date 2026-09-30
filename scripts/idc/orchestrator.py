"""Orchestration of the end-to-end IDC ↔ Keycloak configuration flow.

Drives the AWS console browser automation (identity-source change, SCIM
enablement, token extraction) and stitches together the credentials, keycloak,
and scim modules. The transient-wait for the Keycloak SAML descriptor now uses
the shared ``resilience.poll_until`` helper instead of a hand-rolled
``while deadline`` loop.
"""

from __future__ import annotations

import json
import os
import re
import sys

import requests

from .browser import (
    async_playwright,
    click_first_visible,
    dismiss_overlays,
    ensure_playwright_browsers,
    find_first_visible,
    goto_with_retry,
    screenshot,
    wait_for_stable,
)
from .constants import (
    AWS_METADATA_FILE,
    KEYCLOAK_SAML_FILE,
    SCIM_DATA_FILE,
    STORAGE_STATE_FILE,
)
from .credentials import get_console_signin_url
from .keycloak import create_keycloak_saml_client
from .resilience import poll_until
from .scim import export_to_aws_scim, verify_federation_active


async def configure_identity_center(
    region: str,
    keycloak_dns: str,
    instance_id: str,
    keycloak_admin_password: str,
    headless: bool = True,
    debug: bool = False,
    reuse_session: bool = True,
    scim_only: bool = False,
    keycloak_client_only: bool = False,
    verify_username: str = "user1",
) -> dict:

    if scim_only:
        data = json.load(open(SCIM_DATA_FILE))
        export_to_aws_scim(keycloak_dns, keycloak_admin_password, data["endpoint"], data["token"])
        verify_federation_active(region, expected_username=verify_username)
        return data

    if keycloak_client_only:
        create_keycloak_saml_client(
            keycloak_dns, keycloak_admin_password, open(AWS_METADATA_FILE).read()
        )
        return {}

    sso_url = f"https://{region}.console.aws.amazon.com/singlesignon/home?region={region}"
    settings_url = f"{sso_url}#/instances/{instance_id}/settings"

    ensure_playwright_browsers()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        storage_state = (
            STORAGE_STATE_FILE if reuse_session and os.path.exists(STORAGE_STATE_FILE) else None
        )
        context = await browser.new_context(ignore_https_errors=True, storage_state=storage_state)
        page = await context.new_page()
        page.set_default_timeout(60000)

        try:
            # --- Step 1: Sign in to AWS Console ---
            logged_in = False
            if storage_state:
                print("Reusing existing session...", file=sys.stderr)
                await goto_with_retry(page, sso_url, wait_until="domcontentloaded")
                await wait_for_stable(page)
                # Check if we're actually logged in (look for account menu)
                logged_in = (
                    "console.aws" in page.url
                    and "signin" not in page.url.lower()
                    and await page.locator(
                        '[data-testid="awsc-nav-account-menu-button"], #nav-usernameMenu, [data-testid="account-menu"]'
                    ).count()
                    > 0
                )
            if not logged_in:
                print("Signing into AWS Console...", file=sys.stderr)
                await goto_with_retry(
                    page, get_console_signin_url(sso_url), wait_until="domcontentloaded"
                )
                await wait_for_stable(page)
                await context.storage_state(path=STORAGE_STATE_FILE)
                print(f"Session saved to {STORAGE_STATE_FILE}", file=sys.stderr)
            await dismiss_overlays(page)
            await screenshot(page, "/tmp/step1.png", debug)

            # --- Step 2: Navigate to Settings → Identity source tab ---
            print("Navigating to Identity source settings...", file=sys.stderr)
            await goto_with_retry(page, settings_url, wait_until="domcontentloaded")
            await wait_for_stable(page)
            await dismiss_overlays(page)
            # Click the Identity source tab — try data-testid first, then text
            await click_first_visible(
                page,
                [
                    '[data-testid="identity-source"]',
                    'button:has-text("Identity source")',
                    'a:has-text("Identity source")',
                    '[role="tab"]:has-text("Identity source")',
                ],
                description="Identity source tab",
            )
            await wait_for_stable(page)
            await screenshot(page, "/tmp/step2.png", debug)

            # --- Step 3: Actions → Change identity source ---
            print("Opening 'Change identity source'...", file=sys.stderr)
            await click_first_visible(
                page,
                [
                    '[data-testid="identity-source-actions"]',
                    'button:has-text("Actions")',
                ],
                description="Actions button",
            )
            await page.wait_for_timeout(1000)
            await click_first_visible(
                page,
                [
                    '[data-testid="CHANGE_IDENTITY_SOURCE"]',
                    'li:has-text("Change identity source")',
                    'a:has-text("Change identity source")',
                    '[role="menuitem"]:has-text("Change identity source")',
                    'button:has-text("Change identity source")',
                ],
                description="Change identity source menu item",
            )
            await wait_for_stable(page)
            await screenshot(page, "/tmp/step3.png", debug)

            # --- Step 4: Select "External identity provider" → Next ---
            print("Selecting 'External identity provider'...", file=sys.stderr)
            # Click the radio/card for external IdP — try multiple patterns
            await click_first_visible(
                page,
                [
                    'text="External identity provider"',
                    ':has-text("External identity provider") >> input[type="radio"]',
                    'label:has-text("External identity provider")',
                    '[class*="card"]:has-text("External identity provider")',
                ],
                description="External identity provider option",
            )
            await page.wait_for_timeout(500)
            # Click Next — avoid tutorial overlay "Next" by targeting the wizard/form area
            await click_first_visible(
                page,
                [
                    '[data-testid="wizard-next-button"]',
                    'main button:has-text("Next")',
                    '[class*="wizard"] button:has-text("Next")',
                    'form button:has-text("Next")',
                    'button:has-text("Next")',
                ],
                description="Next button",
            )
            await wait_for_stable(page)
            await screenshot(page, "/tmp/step4.png", debug)

            # --- Step 5: Download AWS SAML metadata ---
            print("Downloading AWS SAML metadata...", file=sys.stderr)
            download_btn = await find_first_visible(
                page,
                [
                    '[data-testid="saml-metadata"]',
                    'a:has-text("Download metadata file")',
                    'button:has-text("Download metadata file")',
                    'a:has-text("Download metadata")',
                    'button:has-text("Download metadata")',
                    'a:has-text("Download")',
                    'a[href*="metadata"]',
                ],
                timeout=10000,
            )
            if not download_btn:
                await screenshot(page, "/tmp/step5_fail.png", debug)
                raise RuntimeError("Could not find AWS metadata download button")
            async with page.expect_download() as dl:
                await download_btn.click()
            await (await dl.value).save_as(AWS_METADATA_FILE)
            print(f"Saved AWS metadata to {AWS_METADATA_FILE}", file=sys.stderr)
            await screenshot(page, "/tmp/step5.png", debug)

            # --- Step 6: Wait for Keycloak SAML descriptor ---
            print("Waiting for Keycloak SAML descriptor...", file=sys.stderr)
            saml_url = (
                f"https://{keycloak_dns}/keycloak/realms/platform/protocol/saml/descriptor"
            )

            # 5 min is ample: the caller (task idc:configure) already waits for the
            # SAML descriptor (HTTP 200) before invoking this script, so the realm
            # exists and the descriptor responds in seconds. Fail fast otherwise
            # (was 1800s / 30 min — a 30-minute hang on failure, see #821/#856).
            def _fetch_saml_descriptor():
                resp = requests.get(saml_url, verify=False, timeout=10)
                if resp.status_code == 200 and "EntityDescriptor" in resp.text:
                    return resp.text
                return None

            descriptor = poll_until(
                _fetch_saml_descriptor,
                timeout=300,
                interval=30,
                retry_on=(requests.RequestException,),
                description="Keycloak SAML endpoint",
            )
            with open(KEYCLOAK_SAML_FILE, "w") as f:
                f.write(descriptor)
            print(f"Saved Keycloak SAML descriptor to {KEYCLOAK_SAML_FILE}", file=sys.stderr)

            # --- Step 7: Upload Keycloak SAML metadata → Next ---
            print("Uploading Keycloak SAML metadata...", file=sys.stderr)
            file_input = await find_first_visible(
                page,
                [
                    'input[type="file"]',
                ],
                timeout=10000,
            )
            if not file_input:
                # Sometimes the file input is hidden; find it without visibility check
                file_input = await page.query_selector('input[type="file"]')
            if file_input:
                await file_input.set_input_files(KEYCLOAK_SAML_FILE)
            else:
                raise RuntimeError("Could not find file upload input")
            await page.wait_for_timeout(2000)
            await click_first_visible(
                page,
                [
                    '[data-testid="wizard-next-button"]',
                    'main button:has-text("Next")',
                    '[class*="wizard"] button:has-text("Next")',
                    'button:has-text("Next")',
                ],
                description="Next button after upload",
            )
            await wait_for_stable(page)
            await screenshot(page, "/tmp/step7.png", debug)

            # --- Step 8: Confirm — type ACCEPT and click confirm button ---
            print("Confirming identity source change...", file=sys.stderr)
            # Find the ACCEPT text input — try multiple selectors
            accept_input = await find_first_visible(
                page,
                [
                    'input[placeholder*="ACCEPT"]',
                    'input[placeholder*="accept"]',
                    'input[placeholder*="CONFIRM"]',
                ],
                timeout=5000,
            )
            if not accept_input:
                # Broader: find any text input in the confirmation area
                accept_input = await find_first_visible(
                    page,
                    [
                        'main input[type="text"]',
                        'form input[type="text"]',
                        '[class*="wizard"] input[type="text"]',
                    ],
                    timeout=5000,
                )
            if accept_input:
                await accept_input.fill("ACCEPT")
            else:
                # Last resort: type it and hope focus is right
                print("WARNING: Could not find ACCEPT input, typing blindly", file=sys.stderr)
                await page.keyboard.type("ACCEPT")

            await page.wait_for_timeout(500)
            # Click the confirm button — try many variations
            await click_first_visible(
                page,
                [
                    'button:has-text("Change identity source")',
                    'button:has-text("Confirm")',
                    'button:has-text("Submit")',
                    '[data-testid="wizard-submit-button"]',
                    'main button.awsui-button--primary:not(:has-text("Cancel")):not(:has-text("Previous"))',
                    'button.awsui-button--primary',
                ],
                timeout=15000,
                description="Change identity source confirm button",
            )
            await wait_for_stable(page)
            await page.wait_for_timeout(3000)
            await screenshot(page, "/tmp/step8.png", debug)

            # Verify success — look for success banner or check we're back on settings
            page_text = await page.evaluate("() => document.body.innerText")
            if (
                "successfully changed" in page_text.lower()
                or "external identity provider" in page_text.lower()
            ):
                print("Identity source change confirmed!", file=sys.stderr)
            else:
                print(
                    f"WARNING: Could not confirm success. Page text snippet: {page_text[:200]}",
                    file=sys.stderr,
                )

            # --- Step 9: Enable automatic provisioning ---
            print("Enabling automatic provisioning...", file=sys.stderr)
            # Dismiss any overlays/tooltips aggressively
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(500)
            await page.evaluate(
                "document.querySelectorAll('[class*=\"popover\"], [class*=\"hotspot\"], [class*=\"tutorial-overlay\"]').forEach(e => e.remove())"
            )
            await dismiss_overlays(page)
            # Click Settings in left nav (use CSS selector for the nav link)
            settings_clicked = False
            for sel in [
                'nav a:text-is("Settings")',
                'aside a:text-is("Settings")',
                '[class*="navigation"] a:text-is("Settings")',
                'a:text-is("Settings")',
            ]:
                try:
                    link = await page.wait_for_selector(sel, state="visible", timeout=3000)
                    if link:
                        await link.click()
                        await wait_for_stable(page)
                        settings_clicked = True
                        break
                except Exception:
                    continue
            if not settings_clicked:
                # Try direct URL navigation
                await goto_with_retry(
                    page,
                    f"{sso_url}#/instances/{instance_id}/settings",
                    wait_until="domcontentloaded",
                )
                await wait_for_stable(page)
            await dismiss_overlays(page)
            await page.wait_for_timeout(2000)
            # Click Provisioning tab/link
            for tab_sel in [
                'a:text-is("Provisioning")',
                'button:text-is("Provisioning")',
                '[role="tab"]:has-text("Provisioning")',
                'a:has-text("Provisioning")',
                'span:text-is("Provisioning")',
            ]:
                try:
                    tab = await page.wait_for_selector(tab_sel, state="visible", timeout=3000)
                    if tab:
                        await tab.click()
                        await wait_for_stable(page)
                        break
                except Exception:
                    continue
            await page.wait_for_timeout(2000)
            await dismiss_overlays(page)

            # Click Enable button — skip gracefully if provisioning already enabled
            await screenshot(page, "/tmp/step9_before_enable.png", debug)
            try:
                await click_first_visible(
                    page,
                    [
                        'button:has-text("Enable")',
                        'button:has-text("Enable automatic provisioning")',
                    ],
                    timeout=10000,
                    description="Enable provisioning button",
                )
                await wait_for_stable(page)
                await page.wait_for_timeout(2000)
            except RuntimeError:
                # Check if provisioning is already enabled (Disable button present)
                try:
                    disable_btn = await page.wait_for_selector(
                        'button:has-text("Disable")', state="visible", timeout=3000
                    )
                    if disable_btn:
                        print(
                            "Automatic provisioning already enabled — skipping Enable step.",
                            file=sys.stderr,
                        )
                except Exception:
                    raise  # Re-raise original error if Disable button not found either
            await screenshot(page, "/tmp/step9.png", debug)

            # --- Step 10: Extract SCIM endpoint and token ---
            print("Extracting SCIM token...", file=sys.stderr)
            # Click "Show token"
            await click_first_visible(
                page,
                [
                    'button:has-text("Show token")',
                    'button:has-text("Show access token")',
                    'a:has-text("Show token")',
                ],
                timeout=10000,
                description="Show token button",
            )
            await page.wait_for_timeout(2000)
            await screenshot(page, "/tmp/step10.png", debug)

            # Extract SCIM data from page text
            page_text = await page.evaluate("() => document.body.innerText")

            # Find SCIM endpoint — match any scim URL pattern
            scim_endpoint = None
            for pattern in [
                r"(https://scim[^\s]+/scim/v2[^\s]*)",
                r"(https://[^\s]*scim[^\s]*/v2[^\s]*)",
            ]:
                m = re.search(pattern, page_text)
                if m:
                    scim_endpoint = m.group(1).strip().rstrip(".")
                    break

            # Find SCIM token — try data-testid first, then regex
            scim_token = None
            token_el = page.locator('[data-testid="scim-token"]')
            if await token_el.count() > 0:
                scim_token = (await token_el.text_content()).strip()

            if not scim_token:
                # Try to find a long token-like string near "Access token" text
                # Tokens are long base64-ish strings with colons
                m = re.search(r"([0-9a-f]{8}-[0-9a-f]{4}-[^\s]{20,})", page_text)
                if m:
                    scim_token = m.group(1).strip()

            if not scim_token:
                # Try copy button approach — find all copyable text elements
                copy_els = await page.query_selector_all(
                    '[class*="copy"] + span, [class*="copyable"]'
                )
                for el in copy_els:
                    text = (await el.text_content() or "").strip()
                    if len(text) > 50 and "scim" not in text.lower():
                        scim_token = text
                        break

            if not scim_token:
                raise RuntimeError("Failed to extract SCIM access token from page")

            scim_data = {"endpoint": scim_endpoint, "token": scim_token}
            json.dump(scim_data, open(SCIM_DATA_FILE, "w"))
            print(f"SCIM endpoint: {scim_endpoint}", file=sys.stderr)
            print(f"SCIM data saved to {SCIM_DATA_FILE}", file=sys.stderr)

            # --- Step 11: Create Keycloak SAML client ---
            print("Creating Keycloak SAML client...", file=sys.stderr)
            create_keycloak_saml_client(
                keycloak_dns, keycloak_admin_password, open(AWS_METADATA_FILE).read()
            )

            # --- Step 12: Export users and groups via SCIM ---
            print("Exporting users and groups to AWS IAM Identity Center...", file=sys.stderr)
            export_to_aws_scim(keycloak_dns, keycloak_admin_password, scim_endpoint, scim_token)

            # --- Step 13: Verify federation is actually active (defence in depth) ---
            # The steps above can each "succeed" in the browser while IDC silently
            # ends up unfederated (identity source reverted, SCIM not provisioning).
            # Assert against AWS state so a broken SSO never ships as success.
            verify_federation_active(region, expected_username=verify_username)

            return scim_data

        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            await screenshot(page, "/tmp/error.png", debug)
            raise
        finally:
            await browser.close()
