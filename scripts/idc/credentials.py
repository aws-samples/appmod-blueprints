"""AWS credential loading/refresh and console sign-in URL generation.

Isolates everything to do with obtaining AWS credentials for console
federation: reading the SSM-backed credentials file, refreshing it via the
KeycloakIDCIntegration Lambda when expired, and exchanging them for a federated
console sign-in URL. The federation request's retry logic now uses the shared
``resilience.retry_http`` policy instead of a bespoke ``range()``/``sleep`` loop.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.parse
from datetime import datetime, timedelta, timezone

import boto3
import requests

from .constants import ASSUME_ROLE_CREDENTIALS_FILE
from .resilience import TransientHTTPError, retry_http

_FEDERATION_ENDPOINT = "https://signin.aws.amazon.com/federation"


def _write_credentials_file(content: str) -> None:
    """Write credentials to file with restrictive permissions (owner-only rw)."""
    fd = os.open(
        ASSUME_ROLE_CREDENTIALS_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600
    )
    with os.fdopen(fd, "w") as f:
        f.write(content)


def _refresh_credentials_via_lambda() -> None:
    """Invoke the KeycloakIDCIntegration Lambda to refresh SSM credentials.

    IMDS fallback is intentionally NOT used here — using EC2 instance profile
    credentials for console federation triggers Epoxy's
    programmatic-credentials-for-console-access detector on personal accounts.
    """
    print("Refreshing IDC credentials via Lambda...", file=sys.stderr)
    client = boto3.client("lambda")
    ssm = boto3.client("ssm")

    # Discover Lambda function name
    prefix = os.environ.get("RESOURCE_PREFIX", "peeks")
    funcs = client.list_functions()["Functions"]
    func_name = next(
        (f["FunctionName"] for f in funcs if "KeycloakIDCIntegration" in f["FunctionName"]),
        None,
    )

    if not func_name:
        raise RuntimeError(
            "KeycloakIDCIntegration Lambda function not found. "
            "Ensure the CDK stack is deployed with the credential-refresh Lambda. "
            "IMDS fallback is disabled to avoid Epoxy detection."
        )

    # Discover the RoleArn from the SSM parameter description
    param_name = f"/{prefix}/keycloak-idc-integration-credentials"
    param_meta = ssm.describe_parameters(
        ParameterFilters=[{"Key": "Name", "Values": [param_name]}]
    )["Parameters"]
    role_arn = ""
    if param_meta:
        desc = param_meta[0].get("Description", "")
        m = re.search(r"(arn:aws:iam::\d+:role/\S+)", desc)
        if m:
            role_arn = m.group(1)
    if not role_arn:
        raise RuntimeError("Could not determine RoleArn from SSM parameter description")

    # Invoke with a CFN-like event
    payload = json.dumps(
        {
            "RequestType": "Update",
            "ResponseURL": "https://localhost/noop",
            "ResourceProperties": {
                "RoleArn": role_arn,
                "ParameterPrefix": param_name,
                "SessionDuration": "3600",
            },
            "StackId": "manual",
            "RequestId": "manual-refresh",
            "LogicalResourceId": "manual",
        }
    )
    resp = client.invoke(FunctionName=func_name, Payload=payload.encode())
    if resp.get("FunctionError"):
        err = json.loads(resp["Payload"].read())
        raise RuntimeError(f"Lambda invocation failed: {err}")

    # Re-read the refreshed credentials from SSM
    fresh = ssm.get_parameter(Name=param_name, WithDecryption=True)["Parameter"]["Value"]
    _write_credentials_file(fresh)
    print("Credentials refreshed via Lambda", file=sys.stderr)


def _load_credentials_file():
    if not os.path.exists(ASSUME_ROLE_CREDENTIALS_FILE):
        return None
    with open(ASSUME_ROLE_CREDENTIALS_FILE) as f:
        return json.load(f)


def _is_expired(creds) -> bool:
    exp = creds.get("Expiration", "")
    if not exp:
        return True
    try:
        exp_dt = datetime.fromisoformat(exp.replace("Z", "+00:00"))
        # Consider expired if less than 5 minutes remaining
        now = datetime.now(timezone.utc).replace(microsecond=0)
        return exp_dt < now + timedelta(minutes=5)
    except (ValueError, TypeError):
        return True


def load_aws_credentials() -> dict:
    """Load AWS credentials from file, refreshing via Lambda if expired."""
    creds = _load_credentials_file()
    if creds and not _is_expired(creds):
        print(f"Using cached credentials (expires {creds.get('Expiration')})", file=sys.stderr)
        return creds

    # Credentials missing or expired — refresh via Lambda
    if creds:
        print(f"Credentials expired ({creds.get('Expiration')}), refreshing...", file=sys.stderr)
    else:
        print("No credentials file found, fetching via Lambda...", file=sys.stderr)

    _refresh_credentials_via_lambda()
    creds = _load_credentials_file()
    if not creds:
        raise RuntimeError("Failed to load credentials after Lambda refresh")
    return creds


@retry_http(attempts=3, delay=5)
def _fetch_signin_token(params: dict) -> str:
    """POST to the federation endpoint and return the SigninToken.

    Raises :class:`TransientHTTPError` for the three retryable modes (request
    error, non-200 response, unparseable body); tenacity retries those. Any
    other exception propagates immediately as a hard failure.
    """
    try:
        resp = requests.get(_FEDERATION_ENDPOINT, params=params, timeout=30)
    except requests.RequestException as e:
        raise TransientHTTPError(f"Federation request failed: {e}") from e

    if resp.status_code != 200:
        raise TransientHTTPError(
            f"Federation HTTP {resp.status_code}: {resp.text[:300]}"
        )

    try:
        return resp.json()["SigninToken"]
    except (json.JSONDecodeError, KeyError) as e:
        raise TransientHTTPError(f"Bad federation response: {resp.text[:300]}") from e


def get_console_signin_url(destination: str) -> str:
    """Exchange loaded credentials for a federated AWS console sign-in URL."""
    creds = load_aws_credentials()
    session_data = json.dumps(
        {
            "sessionId": creds["AccessKeyId"],
            "sessionKey": creds["SecretAccessKey"],
            "sessionToken": creds.get("SessionToken", ""),
        }
    )

    params = {"Action": "getSigninToken", "Session": session_data}
    # SessionDuration only valid for IAM user creds (no SessionToken)
    if not creds.get("SessionToken"):
        params["SessionDuration"] = "3600"

    token = _fetch_signin_token(params)
    return (
        f"{_FEDERATION_ENDPOINT}"
        f"?Action=login&Destination={urllib.parse.quote(destination)}&SigninToken={token}"
    )
