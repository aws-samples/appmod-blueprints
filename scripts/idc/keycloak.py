"""Keycloak admin API interactions for AWS IAM Identity Center federation.

Obtaining an admin token, a thin request wrapper, and creating the SAML client
that represents AWS IAM Identity Center in the ``platform`` realm.
"""

from __future__ import annotations

import sys

import requests

from .constants import KEYCLOAK_REALM


def keycloak_token(kc_base: str, password: str) -> str:
    """Obtain a Keycloak admin access token from the master realm."""
    resp = requests.post(
        f"{kc_base}/realms/master/protocol/openid-connect/token",
        data={
            "username": "admin",
            "password": password,
            "grant_type": "password",
            "client_id": "admin-cli",
        },
        verify=False,
    )
    if resp.status_code != 200:
        raise RuntimeError(
            f"Keycloak admin token request failed: HTTP {resp.status_code} — "
            f"{resp.text[:300]}. A 500 usually means Keycloak cannot reach its "
            f"PostgreSQL database (check that keycloak + postgresql pods are Running); "
            f"a 401 means the admin password is wrong."
        )
    body = resp.json()
    if "access_token" not in body:
        raise RuntimeError(f"Keycloak token response missing 'access_token': {body}")
    return body["access_token"]


def keycloak_api(method, url, token, **kwargs):
    """Thin Keycloak admin request wrapper; returns None on 409 (already exists)."""
    resp = requests.request(
        method,
        url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        verify=False,
        **kwargs,
    )
    if resp.status_code == 409:
        print(f"Already exists: {url}", file=sys.stderr)
        return None
    resp.raise_for_status()
    return resp


def create_keycloak_saml_client(keycloak_dns, keycloak_password, aws_metadata_xml):
    """Create the AWS IAM Identity Center SAML client in the platform realm."""
    kc_base = f"https://{keycloak_dns}/keycloak"
    realm = KEYCLOAK_REALM
    token = keycloak_token(kc_base, keycloak_password)

    resp = requests.post(
        f"{kc_base}/admin/realms/{realm}/client-description-converter",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/xml"},
        data=aws_metadata_xml,
        verify=False,
    )
    resp.raise_for_status()
    client = resp.json()

    client.update(
        {
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
        }
    )

    result = keycloak_api("POST", f"{kc_base}/admin/realms/{realm}/clients", token, json=client)
    if result:
        print(f"Created Keycloak SAML client: {client.get('clientId')}", file=sys.stderr)
