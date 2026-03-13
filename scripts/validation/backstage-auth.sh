#!/usr/bin/env bash
# Authenticate to Backstage via Keycloak OIDC and return a Backstage identity token.
# Usage:
#   source backstage-auth.sh          # sets BS_TOKEN
#   backstage_get_token               # prints token to stdout
#   backstage_scaffolder "template:default/cicd-pipeline-gitops" '{"appname":"rust",...}'
#
# Requires: BACKSTAGE_URL, USER1_PASSWORD

set -euo pipefail

backstage_get_token() {
  local COOKIE_JAR
  COOKIE_JAR=$(mktemp)
  trap "rm -f ${COOKIE_JAR} /tmp/_bs_s2.txt /tmp/_bs_s3.txt /tmp/_bs_s4.txt /tmp/_bs_s5.txt" RETURN

  # Step 1: Session cookie
  curl -sLk -c "${COOKIE_JAR}" "${BACKSTAGE_URL}" -o /dev/null

  # Step 2: Start OIDC (capture nonce + session cookies from headers)
  curl -sLk -b "${COOKIE_JAR}" \
    "${BACKSTAGE_URL}/api/auth/keycloak-oidc/start?scope=openid%20profile%20email&env=development" \
    -H "X-Requested-With: XMLHttpRequest" \
    --max-redirs 0 -D /tmp/_bs_s2.txt -o /dev/null 2>/dev/null || true

  local KC_URL NONCE SID
  KC_URL=$(grep -i "^location:" /tmp/_bs_s2.txt | sed 's/^[Ll]ocation: //' | tr -d '\r\n')
  NONCE=$(grep "keycloak-oidc-nonce=" /tmp/_bs_s2.txt | sed 's/.*keycloak-oidc-nonce=//' | sed 's/;.*//' | tr -d '\r')
  SID=$(grep "connect.sid=" /tmp/_bs_s2.txt | sed 's/.*connect.sid=//' | sed 's/;.*//' | tr -d '\r')

  # Step 3: Get Keycloak login form
  curl -sLk "${KC_URL}" -c "${COOKIE_JAR}" -o /tmp/_bs_s3.txt
  local FORM_ACTION
  FORM_ACTION=$(grep -oP 'action="[^"]*"' /tmp/_bs_s3.txt | head -1 | sed 's/action="//;s/"//' | sed 's/&amp;/\&/g')

  # Step 4: Submit credentials
  curl -sLk -X POST "${FORM_ACTION}" \
    -b "${COOKIE_JAR}" -c "${COOKIE_JAR}" \
    --data-urlencode "username=user1" \
    --data-urlencode "password=${USER1_PASSWORD}" \
    --max-redirs 0 -D /tmp/_bs_s4.txt -o /dev/null 2>/dev/null || true

  local CALLBACK
  CALLBACK=$(grep -i "^location:" /tmp/_bs_s4.txt | sed 's/^[Ll]ocation: //' | tr -d '\r\n')

  # Step 5: Hit callback with nonce + session cookies
  curl -sLk "${CALLBACK}" \
    -H "Cookie: keycloak-oidc-nonce=${NONCE}; connect.sid=${SID}" \
    -D /tmp/_bs_s5.txt -o /dev/null

  local BS_SERVER SCOPE REFRESH
  BS_SERVER=$(grep "backstage-server=" /tmp/_bs_s5.txt | sed 's/.*backstage-server=//' | sed 's/;.*//' | tr -d '\r')
  SCOPE=$(grep "keycloak-oidc-granted-scope=" /tmp/_bs_s5.txt | sed 's/.*keycloak-oidc-granted-scope=//' | sed 's/;.*//' | tr -d '\r')
  REFRESH=$(grep "keycloak-oidc-refresh-token=" /tmp/_bs_s5.txt | sed 's/.*keycloak-oidc-refresh-token=//' | sed 's/;.*//' | tr -d '\r')

  # Step 6: Refresh to get Backstage identity token
  curl -sLk "${BACKSTAGE_URL}/api/auth/keycloak-oidc/refresh?env=development" \
    -H "Cookie: backstage-server=${BS_SERVER}; connect.sid=${SID}; keycloak-oidc-granted-scope=${SCOPE}; keycloak-oidc-refresh-token=${REFRESH}" \
    -H "X-Requested-With: XMLHttpRequest" | jq -r '.backstageIdentity.token'
}

backstage_scaffolder() {
  local TEMPLATE_REF="$1"
  local VALUES="$2"
  local TOKEN
  TOKEN=$(backstage_get_token)

  local TASK_ID
  TASK_ID=$(curl -sLk -X POST "${BACKSTAGE_URL}/api/scaffolder/v2/tasks" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "Content-Type: application/json" \
    -d "{\"templateRef\": \"${TEMPLATE_REF}\", \"values\": ${VALUES}}" | jq -r '.id')

  echo "Task ID: ${TASK_ID}" >&2

  # Poll until completed or failed (up to 5 min)
  for i in $(seq 1 30); do
    local STATUS
    STATUS=$(curl -sLk "${BACKSTAGE_URL}/api/scaffolder/v2/tasks/${TASK_ID}" \
      -H "Authorization: Bearer ${TOKEN}" | jq -r '.status')
    echo "  [$i] status: ${STATUS}" >&2
    case "${STATUS}" in
      completed) echo "${TASK_ID}"; return 0 ;;
      failed|cancelled) echo "${TASK_ID}"; return 1 ;;
    esac
    sleep 10
  done
  echo "${TASK_ID}"; return 1
}

# When sourced, export BS_TOKEN for direct use
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  backstage_get_token
else
  export BS_TOKEN
  BS_TOKEN=$(backstage_get_token)
  echo "BS_TOKEN set (${#BS_TOKEN} chars)" >&2
fi
