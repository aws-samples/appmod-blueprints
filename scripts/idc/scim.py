"""SCIM export of Keycloak users/groups into AWS IAM Identity Center, plus a
post-configuration assertion that federation is actually active.
"""

from __future__ import annotations

import sys

import boto3
import requests

from .constants import KEYCLOAK_REALM
from .keycloak import keycloak_token


def export_to_aws_scim(keycloak_dns, keycloak_password, scim_endpoint, scim_token):
    """Export Keycloak users and groups to AWS IAM Identity Center via SCIM."""
    kc_base = f"https://{keycloak_dns}/keycloak"
    realm = KEYCLOAK_REALM
    token = keycloak_token(kc_base, keycloak_password)
    kc_headers = {"Authorization": f"Bearer {token}"}
    scim_headers = {"Authorization": f"Bearer {scim_token}", "Content-Type": "application/json"}

    existing_users = (
        requests.get(f"{scim_endpoint}/Users", headers=scim_headers).json().get("Resources", [])
    )
    aws_user_map = {u["userName"]: u["id"] for u in existing_users}

    kc_user_map = {}
    for u in requests.get(
        f"{kc_base}/admin/realms/{realm}/users?max=1000", headers=kc_headers, verify=False
    ).json():
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
            print(
                f"Failed to export user {username}: {resp.status_code} {resp.text[:200]}",
                file=sys.stderr,
            )

    existing_groups = (
        requests.get(f"{scim_endpoint}/Groups", headers=scim_headers).json().get("Resources", [])
    )
    aws_group_map = {g["displayName"]: g["id"] for g in existing_groups}

    for g in requests.get(
        f"{kc_base}/admin/realms/{realm}/groups?max=1000", headers=kc_headers, verify=False
    ).json():
        name = g.get("name", "")
        members = [
            {"value": kc_user_map[m["id"]]}
            for m in requests.get(
                f"{kc_base}/admin/realms/{realm}/groups/{g['id']}/members",
                headers=kc_headers,
                verify=False,
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
            resp = requests.patch(
                f"{scim_endpoint}/Groups/{aws_group_map[name]}", headers=scim_headers, json=patch
            )
            if resp.status_code in (200, 204):
                print(f"Updated group members: {name}", file=sys.stderr)
            else:
                print(
                    f"Failed to update group {name}: {resp.status_code} {resp.text[:200]}",
                    file=sys.stderr,
                )
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
                print(
                    f"Failed to export group {name}: {resp.status_code} {resp.text[:200]}",
                    file=sys.stderr,
                )


def verify_federation_active(region: str, expected_username: str = "user1"):
    """Assert IDC is actually federated with an external IdP (SAML + SCIM).

    The browser automation can report success while the identity source silently
    reverted or SCIM never provisioned — the failure mode that let a broken
    ArgoCD SSO ship "green". This is a hard, AWS-side gate: it confirms the
    reference user was provisioned VIA SCIM (its ExternalIds carry a
    provisioning-tenant Issuer), which is only true when IDC's identity source is
    an external IdP with automatic provisioning enabled. A native IDC-directory
    user has no such ExternalIds. Raises on failure so the caller exits non-zero.
    """
    sso = boto3.client("sso-admin", region_name=region)
    ids = boto3.client("identitystore", region_name=region)

    instance = sso.list_instances()["Instances"][0]
    identity_store_id = instance["IdentityStoreId"]

    users = ids.list_users(
        IdentityStoreId=identity_store_id,
        Filters=[{"AttributePath": "UserName", "AttributeValue": expected_username}],
    ).get("Users", [])
    if not users:
        raise RuntimeError(
            f"Federation verification FAILED: user '{expected_username}' not found in "
            f"identity store {identity_store_id}. SCIM provisioning did not run — IDC is "
            f"NOT federated with Keycloak."
        )

    external_ids = users[0].get("ExternalIds") or []
    provisioned = any("provisioningtenant" in (e.get("Issuer") or "") for e in external_ids)
    if not provisioned:
        raise RuntimeError(
            f"Federation verification FAILED: user '{expected_username}' exists but has no "
            f"SCIM provisioning-tenant ExternalId (ExternalIds={external_ids}). The identity "
            f"source is NOT an external IdP with automatic provisioning — IDC federation is "
            f"not effective."
        )

    print(
        f"✓ Federation verified: '{expected_username}' provisioned via SCIM "
        f"(external IdP active).",
        file=sys.stderr,
    )
    return True
