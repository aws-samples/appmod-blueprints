#!/usr/bin/env python3
"""
Automate AWS IAM Identity Center configuration to use Keycloak as external IdP.

Flow:
  1. Sign in to AWS Console via federation URL
  2. Navigate to IAM Identity Center Settings → Identity source
  3. Change identity source to External IdP
  4. Download AWS SAML metadata → /tmp/aws-id.xml
  5. Wait for Keycloak SAML descriptor to become available
  6. Upload Keycloak SAML metadata to AWS
  7. Confirm identity source change
  8. Enable automatic provisioning and extract SCIM endpoint/token → /tmp/scim-data.json
  9. Create Keycloak SAML client for AWS IAM Identity Center
  10. Export Keycloak users and groups to AWS via SCIM

Shortcut flags:
  --scim-only            Skip browser automation; run SCIM export using /tmp/scim-data.json
  --keycloak-client-only Skip browser automation; create Keycloak SAML client using /tmp/aws-id.xml
"""

import asyncio
import json
import re
import sys
import os
import time
import urllib.parse

import boto3
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

try:
    from playwright.async_api import async_playwright
except ImportError:
    os.system("pip install playwright")
    os.system("sudo yum install -y atk at-spi2-atk cups-libs libdrm libxkbcommon "
              "libXcomposite libXdamage libXrandr mesa-libgbm pango alsa-lib 2>/dev/null || true")
    os.system("playwright install chromium 2>/dev/null")
    from playwright.async_api import async_playwright

STORAGE_STATE_FILE = "/tmp/aws_console_state.json"
AWS_METADATA_FILE = "/tmp/aws-id.xml"
KEYCLOAK_SAML_FILE = "/tmp/keycloak-saml.xml"
SCIM_DATA_FILE = "/tmp/scim-data.json"
ASSUME_ROLE_CREDENTIALS_FILE = '/tmp/keycloak-idc-integration-credentials.json'


# ---------------------------------------------------------------------------
# AWS Credentials loader
# ---------------------------------------------------------------------------

def load_aws_credentials():
    """Load AWS credentials from ASSUME_ROLE_CREDENTIALS_FILE."""
    if not os.path.exists(ASSUME_ROLE_CREDENTIALS_FILE):
        print(f"Error: Credentials file not found: {ASSUME_ROLE_CREDENTIALS_FILE}", file=sys.stderr)
        sys.exit(1)
    
    try:
        with open(ASSUME_ROLE_CREDENTIALS_FILE, 'r') as f:
            creds = json.load(f)
        
        required_keys = ['AccessKeyId', 'SecretAccessKey', 'SessionToken']
        missing_keys = [key for key in required_keys if key not in creds]
        if missing_keys:
            print(f"Error: Missing required keys in credentials file: {', '.join(missing_keys)}", file=sys.stderr)
            sys.exit(1)
        
        return creds
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in credentials file: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: Failed to load credentials: {e}", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# AWS Console helpers
# ---------------------------------------------------------------------------

def is_console_aws_url(url: str) -> bool:
    """
    Check if URL is on console.aws.amazon.com domain.
    Uses hostname parsing to avoid substring bypass vulnerabilities.
    """
    try:
        parsed = urllib.parse.urlparse(url)
        hostname = parsed.hostname
        if not hostname:
            return False
        # Allow exact match or subdomain
        return hostname == "console.aws.amazon.com" or hostname.endswith(".console.aws.amazon.com")
    except Exception:
        return False


def get_console_signin_url(destination: str) -> str:
    creds = load_aws_credentials()
    session_data = json.dumps({
        "sessionId": creds['AccessKeyId'],
        "sessionKey": creds['SecretAccessKey'],
        "sessionToken": creds['SessionToken'],
    })
    token = requests.get(
        "https://signin.aws.amazon.com/federation",
        params={"Action": "getSigninToken", "SessionDuration": "3600", "Session": session_data},
    ).json()["SigninToken"]
    return (
        f"https://signin.aws.amazon.com/federation"
        f"?Action=login&Destination={urllib.parse.quote(destination)}&SigninToken={token}"
    )


async def wait_for_stable(page, timeout=10000):
    await page.wait_for_load_state("networkidle")
    await page.wait_for_timeout(2000)
    try:
        await page.wait_for_selector(".awsui-spinner", state="hidden", timeout=timeout)
    except Exception:
        pass


async def screenshot(page, path, debug):
    if debug:
        await page.screenshot(path=path)


# ---------------------------------------------------------------------------
# Keycloak helpers
# ---------------------------------------------------------------------------

def keycloak_token(kc_base: str, password: str) -> str:
    return requests.post(
        f"{kc_base}/realms/master/protocol/openid-connect/token",
        data={"username": "admin", "password": password,
              "grant_type": "password", "client_id": "admin-cli"},
        verify=False,
    ).json()["access_token"]


def keycloak_api(method, url, token, **kwargs):
    resp = requests.request(
        method, url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        verify=False, **kwargs,
    )
    if resp.status_code == 409:
        print(f"Already exists: {url}", file=sys.stderr)
        return None
    resp.raise_for_status()
    return resp


def create_keycloak_saml_client(keycloak_dns: str, keycloak_password: str, aws_metadata_xml: str):
    kc_base = f"https://{keycloak_dns}/keycloak"
    realm = "platform"
    token = keycloak_token(kc_base, keycloak_password)

    # Convert AWS SAML metadata XML into a Keycloak client representation
    resp = requests.post(
        f"{kc_base}/admin/realms/{realm}/client-description-converter",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/xml"},
        data=aws_metadata_xml, verify=False,
    )
    resp.raise_for_status()
    client = resp.json()

    # Merge expected configuration on top of the converted client
    client.update({
        "name": "aws-idc",
        "description": "AWS IAM Identity Center",
        "rootUrl": f"{kc_base}/realms/{realm}/protocol/saml/clients/aws-idc",
        "enabled": True,
        "frontchannelLogout": True,
        "defaultClientScopes": ["saml_organization", "role_list"],
        "optionalClientScopes": [],
        "attributes": {
            **client.get("attributes", {}),
            "saml.assertion.signature": "true",
            "saml.server.signature": "true",
            "saml.force.post.binding": "true",
            "saml.signature.algorithm": "RSA_SHA256",
            "saml.authnstatement": "true",
            "saml.client.signature": "false",
            "saml.encrypt": "false",
            "saml_name_id_format": "username",
            "saml_force_name_id_format": "false",
            "saml_idp_initiated_sso_url_name": "aws-idc",
            "saml_signature_canonicalization_method": "http://www.w3.org/2001/10/xml-exc-c14n#",
        },
        "protocolMappers": [
            {
                "name": "group",
                "protocol": "saml",
                "protocolMapper": "saml-group-membership-mapper",
                "consentRequired": False,
                "config": {
                    "single": "true",
                    "attribute.nameformat": "Basic",
                    "full.path": "true",
                    "attribute.name": "member",
                },
            },
            {
                "name": "name",
                "protocol": "saml",
                "protocolMapper": "saml-user-attribute-nameid-mapper",
                "consentRequired": False,
                "config": {
                    "mapper.nameid.format": "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress",
                    "user.attribute": "username",
                },
            },
        ],
    })

    result = keycloak_api("POST", f"{kc_base}/admin/realms/{realm}/clients", token, json=client)
    if result:
        print(f"Created Keycloak SAML client: {client.get('clientId')}", file=sys.stderr)


# ---------------------------------------------------------------------------
# SCIM export
# ---------------------------------------------------------------------------

def export_to_aws_scim(keycloak_dns: str, keycloak_password: str, scim_endpoint: str, scim_token: str):
    kc_base = f"https://{keycloak_dns}/keycloak"
    realm = "platform"
    token = keycloak_token(kc_base, keycloak_password)
    kc_headers = {"Authorization": f"Bearer {token}"}
    scim_headers = {"Authorization": f"Bearer {scim_token}", "Content-Type": "application/json"}

    # Build map of existing AWS SCIM users (userName → id)
    existing_users = requests.get(f"{scim_endpoint}/Users", headers=scim_headers).json().get("Resources", [])
    aws_user_map = {u["userName"]: u["id"] for u in existing_users}

    # Export Keycloak users
    kc_user_map = {}  # Keycloak user id → AWS SCIM user id
    for u in requests.get(f"{kc_base}/admin/realms/{realm}/users?max=1000", headers=kc_headers, verify=False).json():
        username = u.get("username", "")
        if username in aws_user_map:
            print(f"User already exists: {username}", file=sys.stderr)
            kc_user_map[u["id"]] = aws_user_map[username]
            continue
        first = u.get("firstName") or ""
        last = u.get("lastName") or ""
        payload = {
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
            "userName": username,
            "displayName": f"{first} {last}".strip() or username,
            "name": {"givenName": first, "familyName": last},
            "emails": [{"value": u.get("email", f"{username}@example.com"), "primary": True}],
            "active": u.get("enabled", True),
        }
        resp = requests.post(f"{scim_endpoint}/Users", headers=scim_headers, json=payload)
        if resp.status_code == 201:
            kc_user_map[u["id"]] = resp.json()["id"]
            print(f"Exported user: {username}", file=sys.stderr)
        else:
            print(f"Failed to export user {username}: {resp.status_code} {resp.text}", file=sys.stderr)

    # Build map of existing AWS SCIM groups (displayName → id)
    existing_groups = requests.get(f"{scim_endpoint}/Groups", headers=scim_headers).json().get("Resources", [])
    aws_group_map = {g["displayName"]: g["id"] for g in existing_groups}

    # Export Keycloak groups
    for g in requests.get(f"{kc_base}/admin/realms/{realm}/groups?max=1000", headers=kc_headers, verify=False).json():
        name = g.get("name", "")
        members = [
            {"value": kc_user_map[m["id"]]}
            for m in requests.get(
                f"{kc_base}/admin/realms/{realm}/groups/{g['id']}/members",
                headers=kc_headers, verify=False,
            ).json()
            if m["id"] in kc_user_map
        ]
        if name in aws_group_map:
            if not members:
                continue
            patch = {
                "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
                "Operations": [{"op": "add", "path": "members", "value": members}],
            }
            resp = requests.patch(f"{scim_endpoint}/Groups/{aws_group_map[name]}", headers=scim_headers, json=patch)
            if resp.status_code in (200, 204):
                print(f"Updated group members: {name}", file=sys.stderr)
            else:
                print(f"Failed to update group {name}: {resp.status_code} {resp.text}", file=sys.stderr)
        else:
            payload = {
                "schemas": ["urn:ietf:params:scim:schemas:core:2.0:Group"],
                "displayName": name,
                "members": members,
            }
            resp = requests.post(f"{scim_endpoint}/Groups", headers=scim_headers, json=payload)
            if resp.status_code == 201:
                print(f"Exported group: {name}", file=sys.stderr)
            else:
                print(f"Failed to export group {name}: {resp.status_code} {resp.text}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Main automation
# ---------------------------------------------------------------------------

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
) -> dict:

    # Shortcut: SCIM export only
    if scim_only:
        data = json.load(open(SCIM_DATA_FILE))
        export_to_aws_scim(keycloak_dns, keycloak_admin_password, data["endpoint"], data["token"])
        return data

    # Shortcut: Keycloak client creation only
    if keycloak_client_only:
        create_keycloak_saml_client(keycloak_dns, keycloak_admin_password, open(AWS_METADATA_FILE).read())
        return {}

    sso_url = f"https://{region}.console.aws.amazon.com/singlesignon/home?region={region}"
    settings_url = f"{sso_url}#/instances/{instance_id}/settings"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        storage_state = STORAGE_STATE_FILE if reuse_session and os.path.exists(STORAGE_STATE_FILE) else None
        context = await browser.new_context(ignore_https_errors=True, storage_state=storage_state)
        page = await context.new_page()
        page.set_default_timeout(60000)

        try:
            # Step 1: Sign in
            logged_in = False
            if storage_state:
                print("Reusing existing session...", file=sys.stderr)
                await page.goto(sso_url, wait_until="domcontentloaded")
                await wait_for_stable(page)
                logged_in = (
                    is_console_aws_url(page.url)
                    and "signin" not in page.url.lower()
                    and await page.locator('[data-testid="awsc-nav-account-menu-button"]').count() > 0
                )
            if not logged_in:
                print("Signing into AWS Console...", file=sys.stderr)
                await page.goto(get_console_signin_url(sso_url), wait_until="domcontentloaded")
                await wait_for_stable(page)
                await context.storage_state(path=STORAGE_STATE_FILE)
                print(f"Session saved to {STORAGE_STATE_FILE}", file=sys.stderr)
            await screenshot(page, "/tmp/step1.png", debug)

            # Step 2: Navigate to Settings → Identity source tab
            print("Navigating to Identity source settings...", file=sys.stderr)
            await page.goto(settings_url, wait_until="domcontentloaded")
            await wait_for_stable(page)
            await page.click('[data-testid="identity-source"]')
            await wait_for_stable(page)
            await screenshot(page, "/tmp/step2.png", debug)

            # Step 3: Open Actions → Change identity source
            print("Opening 'Change identity source'...", file=sys.stderr)
            await page.wait_for_selector('[data-testid="identity-source-actions"]', state="visible")
            await page.click('[data-testid="identity-source-actions"]')
            await page.wait_for_selector('[data-testid="CHANGE_IDENTITY_SOURCE"]', state="visible")
            await page.click('[data-testid="CHANGE_IDENTITY_SOURCE"]')
            await wait_for_stable(page)
            await screenshot(page, "/tmp/step3.png", debug)

            # Step 4: Select External identity provider → Next
            print("Selecting 'External identity provider'...", file=sys.stderr)
            await page.wait_for_selector('text="External identity provider"', state="visible")
            await page.click('text="External identity provider"')
            await page.click('button:has-text("Next")')
            await wait_for_stable(page)
            await screenshot(page, "/tmp/step4.png", debug)

            # Step 5: Download AWS SAML metadata
            print("Downloading AWS SAML metadata...", file=sys.stderr)
            download_btn = None
            for sel in ['[data-testid="saml-metadata"]', 'a:has-text("Download")', 'button:has-text("Download")']:
                try:
                    download_btn = await page.wait_for_selector(sel, state="visible", timeout=10000)
                    break
                except Exception:
                    continue
            if not download_btn:
                raise RuntimeError("Could not find AWS metadata download button")
            async with page.expect_download() as dl:
                await download_btn.click()
            await (await dl.value).save_as(AWS_METADATA_FILE)
            print(f"Saved AWS metadata to {AWS_METADATA_FILE}", file=sys.stderr)
            await screenshot(page, "/tmp/step5.png", debug)

            # Step 6: Wait for Keycloak SAML descriptor (up to 30 min)
            print("Waiting for Keycloak SAML descriptor...", file=sys.stderr)
            saml_url = f"https://{keycloak_dns}/keycloak/realms/platform/protocol/saml/descriptor"
            deadline = time.time() + 1800
            while True:
                try:
                    resp = requests.get(saml_url, verify=False, timeout=10)
                    if resp.status_code == 200:
                        open(KEYCLOAK_SAML_FILE, "w").write(resp.text)
                        print(f"Saved Keycloak SAML descriptor to {KEYCLOAK_SAML_FILE}", file=sys.stderr)
                        break
                except Exception:
                    pass
                if time.time() > deadline:
                    raise TimeoutError("Keycloak SAML endpoint not available after 30 minutes")
                print("Keycloak not ready, retrying in 30s...", file=sys.stderr)
                time.sleep(30)

            # Step 7: Upload Keycloak SAML metadata → Next
            print("Uploading Keycloak SAML metadata...", file=sys.stderr)
            await (await page.wait_for_selector('input[type="file"]')).set_input_files(KEYCLOAK_SAML_FILE)
            await page.wait_for_timeout(1000)
            await page.click('button:has-text("Next")')
            await wait_for_stable(page)
            await screenshot(page, "/tmp/step7.png", debug)

            # Step 8: Confirm identity source change
            print("Confirming identity source change...", file=sys.stderr)
            input_el = None
            for sel in ['input[placeholder*="ACCEPT"]', 'input[placeholder*="accept"]',
                        'awsui-input input', 'form input[type="text"]']:
                try:
                    input_el = await page.wait_for_selector(sel, state="visible", timeout=5000)
                    break
                except Exception:
                    continue
            if input_el:
                await input_el.fill("ACCEPT")
            else:
                await page.keyboard.type("ACCEPT")
            await page.click('button:has-text("Change identity source")')
            await wait_for_stable(page)
            await page.wait_for_timeout(3000)
            await screenshot(page, "/tmp/step8.png", debug)

            # Step 9: Enable automatic provisioning
            print("Enabling automatic provisioning...", file=sys.stderr)
            await page.goto(settings_url, wait_until="domcontentloaded")
            await wait_for_stable(page)
            await page.wait_for_selector('button:has-text("Enable")', state="visible")
            await page.click('button:has-text("Enable")')
            await wait_for_stable(page)
            await screenshot(page, "/tmp/step9.png", debug)

            # Step 10: Extract SCIM endpoint and token
            print("Extracting SCIM token...", file=sys.stderr)
            await page.wait_for_timeout(2000)
            await page.click('button:has-text("Show token")')
            await page.wait_for_timeout(1000)
            await screenshot(page, "/tmp/step10.png", debug)

            token_el = page.locator('[data-testid="scim-token"]')
            scim_token = (await token_el.text_content()).strip() if await token_el.count() > 0 else None
            page_text = await page.evaluate("() => document.body.innerText")
            m = re.search(r"https://scim[^\s]+/scim/v2[^\s]*", page_text)
            scim_endpoint = m.group(0).strip() if m else None

            if not scim_token:
                raise RuntimeError("Failed to extract SCIM access token")

            scim_data = {"endpoint": scim_endpoint, "token": scim_token}
            json.dump(scim_data, open(SCIM_DATA_FILE, "w"))
            print(f"SCIM endpoint: {scim_endpoint}", file=sys.stderr)
            print(f"SCIM data saved to {SCIM_DATA_FILE}", file=sys.stderr)

            # Step 11: Create Keycloak SAML client
            print("Creating Keycloak SAML client...", file=sys.stderr)
            create_keycloak_saml_client(keycloak_dns, keycloak_admin_password, open(AWS_METADATA_FILE).read())

            # Step 12: Export users and groups to AWS via SCIM
            print("Exporting users and groups to AWS IAM Identity Center...", file=sys.stderr)
            export_to_aws_scim(keycloak_dns, keycloak_admin_password, scim_endpoint, scim_token)

            return scim_data

        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            await screenshot(page, "/tmp/error.png", debug)
            raise
        finally:
            await browser.close()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Configure AWS IAM Identity Center with Keycloak as external IdP")
    parser.add_argument("--region", required=True)
    parser.add_argument("--instance-id", required=True)
    parser.add_argument("--keycloak-dns", required=True)
    parser.add_argument("--keycloak-admin-password", required=True)
    parser.add_argument("--no-headless", action="store_true", help="Show browser window")
    parser.add_argument("--debug", action="store_true", help="Save screenshots to /tmp/step*.png")
    parser.add_argument("--no-reuse-session", action="store_true", help="Don't reuse saved browser session")
    parser.add_argument("--scim-only", action="store_true", help="Run SCIM export only using cached /tmp/scim-data.json")
    parser.add_argument("--keycloak-client-only", action="store_true", help="Create Keycloak SAML client only using cached /tmp/aws-id.xml")
    args = parser.parse_args()

    result = asyncio.run(configure_identity_center(
        region=args.region,
        keycloak_dns=args.keycloak_dns,
        instance_id=args.instance_id,
        keycloak_admin_password=args.keycloak_admin_password,
        headless=not args.no_headless,
        debug=args.debug,
        reuse_session=not args.no_reuse_session,
        scim_only=args.scim_only,
        keycloak_client_only=args.keycloak_client_only,
    ))

    if result:
        print(json.dumps(result))
    else:
        sys.exit(1)
