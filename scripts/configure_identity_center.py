#!/usr/bin/env python3
"""Configure AWS IAM Identity Center with Keycloak as an external IdP.

Thin CLI entrypoint. The implementation lives in the ``idc`` package (split by
concern — see ``idc/__init__.py``); this file only parses arguments, runs the
async orchestrator, and redacts the SCIM token from stdout.

Flow (see ``idc.orchestrator``):
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

import argparse
import asyncio
import json
import os
import sys

# Ensure the sibling ``idc`` package is importable when run as a script from any CWD.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Bootstrap the resilience dependency if absent (the IDE Taskfile installs it, but
# the SSM bashrc.d path invokes this script directly with no pip step). Mirrors the
# Playwright bootstrap in idc.browser.
try:
    import tenacity  # noqa: F401
except ImportError:
    import subprocess

    subprocess.check_call([sys.executable, "-m", "pip", "install", "tenacity"])

import urllib3  # noqa: E402

from idc.constants import SCIM_DATA_FILE  # noqa: E402
from idc.orchestrator import configure_identity_center  # noqa: E402

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def main():
    parser = argparse.ArgumentParser(
        description="Configure AWS IAM Identity Center with Keycloak as external IdP"
    )
    parser.add_argument("--region", required=True)
    parser.add_argument("--instance-id", required=True)
    parser.add_argument("--keycloak-dns", required=True)
    parser.add_argument("--keycloak-admin-password", required=True)
    parser.add_argument("--no-headless", action="store_true")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--no-reuse-session", action="store_true")
    parser.add_argument("--scim-only", action="store_true")
    parser.add_argument("--keycloak-client-only", action="store_true")
    parser.add_argument(
        "--verify-username",
        default="user1",
        help="Username expected to be SCIM-provisioned; used for the post-config federation assertion.",
    )
    args = parser.parse_args()

    if not args.keycloak_dns or args.keycloak_dns in ("null", "None", ""):
        print(
            "ERROR: --keycloak-dns is empty. Platform domain not set — cannot configure Keycloak.",
            file=sys.stderr,
        )
        print("Fix: set 'domain' in config.local.yaml, then run: task idc:configure", file=sys.stderr)
        sys.exit(1)

    result = asyncio.run(
        configure_identity_center(
            region=args.region,
            keycloak_dns=args.keycloak_dns,
            instance_id=args.instance_id,
            keycloak_admin_password=args.keycloak_admin_password,
            headless=not args.no_headless,
            debug=args.debug,
            reuse_session=not args.no_reuse_session,
            scim_only=args.scim_only,
            keycloak_client_only=args.keycloak_client_only,
            verify_username=args.verify_username,
        )
    )

    if result:
        # Do not leak the SCIM bearer token into stdout (it ends up in the SSM
        # bootstrap logs). The full value is still persisted to SCIM_DATA_FILE for
        # --scim-only reruns, so redact only the stdout copy.
        safe_result = dict(result)
        if safe_result.get("token"):
            safe_result["token"] = f"***REDACTED*** (saved to {SCIM_DATA_FILE})"
        print(json.dumps(safe_result))
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
