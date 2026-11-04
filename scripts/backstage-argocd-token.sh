#!/bin/bash
# backstage-argocd-token — mint an Argo CD API token for the Backstage Argo CD plugin.
#
# Why: the EKS managed Argo CD capability has no local login, so the plugin's
# username/password pair cannot get a session and the entity "Argo CD overview" card
# finds no application (GET /api/argocd/find/name/<app> fails). The capability accepts
# API tokens; this script mints one for your own SSO account with your current session
# (the same as Settings > Accounts > <you> > Generate New Token in the UI). The capability
# has no local `admin` account: it only lists Identity Center users. The script
# stores it in Secrets Manager <hub>/secrets under `argocd_api_token`, and restarts
# Backstage so it reads it (ExternalSecret argocd-api-token, refresh 5m).
#
# Note: the token carries the caller's role (ADMIN for user1), so it is not read-only.
# The managed capability does not let you define a read-only local account; project-role
# tokens are read-only but limited to one project.
#
# Usage (on the IDE, after `source scripts/argocd-refresh-token.sh`):
#   bash scripts/backstage-argocd-token.sh
# Env:
#   ARGOCD_SERVER, ARGOCD_AUTH_TOKEN  SSO session of a user mapped to the ADMIN role
#   RESOURCE_PREFIX                   hub is <prefix>-hub (default peeks)
#   AWS_DEFAULT_REGION / AWS_REGION   region of the hub secrets (default us-west-2)
#   BACKSTAGE_ARGOCD_TOKEN_TTL        token lifetime in seconds (default 2592000 = 30 days, 0 = no expiry)
set -euo pipefail

HUB="${RESOURCE_PREFIX:-peeks}-hub"
REGION="${AWS_DEFAULT_REGION:-${AWS_REGION:-us-west-2}}"
TTL="${BACKSTAGE_ARGOCD_TOKEN_TTL:-2592000}"
SECRET_ID="${HUB}/secrets"

if [[ -z "${ARGOCD_SERVER:-}" || -z "${ARGOCD_AUTH_TOKEN:-}" ]]; then
  echo "ERROR: ARGOCD_SERVER and ARGOCD_AUTH_TOKEN are not set. Run: source scripts/argocd-refresh-token.sh" >&2
  exit 1
fi
if ! [[ "$TTL" =~ ^[0-9]+$ ]]; then
  echo "ERROR: BACKSTAGE_ARGOCD_TOKEN_TTL must be a number of seconds" >&2
  exit 1
fi

TMP=$(mktemp -d)
chmod 700 "$TMP"
trap 'rm -rf "$TMP"' EXIT
# Keep tokens out of the process list: curl reads the header from a file.
printf 'Authorization: Bearer %s\n' "$ARGOCD_AUTH_TOKEN" > "$TMP/auth"
jq -n --arg id "backstage-$(date -u +%Y%m%d%H%M%S)" --argjson ttl "$TTL" \
  '{id: $id, expiresIn: $ttl}' > "$TMP/body"

SERVER="https://${ARGOCD_SERVER#https://}"
# The account to mint on is the caller itself (its Identity Center user id).
ACCOUNT=$(curl -sS -H @"$TMP/auth" "$SERVER/api/v1/session/userinfo" | jq -r '.username // empty')
if [[ -z "$ACCOUNT" ]]; then
  echo "ERROR: the SSO session is not valid; refresh it with scripts/argocd-refresh-token.sh." >&2
  exit 1
fi
HTTP=$(curl -sS -o "$TMP/resp" -w '%{http_code}' -X POST \
  -H @"$TMP/auth" -H 'Content-Type: application/json' --data @"$TMP/body" \
  "$SERVER/api/v1/account/${ACCOUNT}/token")
if [[ "$HTTP" != "200" ]]; then
  echo "ERROR: Argo CD refused to mint the token (HTTP $HTTP). Your SSO session must map to the ADMIN role; refresh it with scripts/argocd-refresh-token.sh." >&2
  exit 1
fi
jq -e -r '.token // empty' "$TMP/resp" > "$TMP/token" || {
  echo "ERROR: no token in the Argo CD response" >&2
  exit 1
}

# Merge the property into <hub>/secrets (same read-merge-write as the install seeds).
aws secretsmanager get-secret-value --secret-id "$SECRET_ID" --region "$REGION" \
  --query SecretString --output text > "$TMP/current"
jq --rawfile t "$TMP/token" '. + {argocd_api_token: ($t | rtrimstr("\n"))}' "$TMP/current" > "$TMP/updated"
aws secretsmanager put-secret-value --secret-id "$SECRET_ID" --region "$REGION" \
  --secret-string "file://$TMP/updated" >/dev/null
echo "✓ argocd_api_token stored in $SECRET_ID (value not shown)"

# Backstage reads the token at start: force the ExternalSecret to resync, then restart.
if kubectl -n backstage get externalsecret argocd-api-token >/dev/null 2>&1; then
  kubectl -n backstage annotate externalsecret argocd-api-token force-sync="$(date +%s)" --overwrite >/dev/null
  for _ in $(seq 1 30); do
    if [[ -n "$(kubectl -n backstage get secret argocd-api-token -o jsonpath='{.data.ARGOCD_AUTH_TOKEN}' 2>/dev/null)" ]]; then
      break
    fi
    sleep 5
  done
  kubectl -n backstage rollout restart deployment/backstage >/dev/null
  echo "✓ Backstage restarted; the Argo CD card works once the new pod is Ready"
else
  echo "ExternalSecret backstage/argocd-api-token not found on the current kube context (hub expected)." >&2
  echo "The token is stored; restart Backstage on the hub once the chart with argocd-api-token is synced." >&2
fi
