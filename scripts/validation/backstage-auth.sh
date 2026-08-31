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
  # `trap ... RETURN` is bash-only. Under zsh (the workshop IDE's default shell) it
  # errors with "trap: undefined signal: RETURN" and, with `set -e`, aborts the
  # function so BS_TOKEN is never set. Register the cleanup only under bash; the temp
  # files live under /tmp and are harmless if left uncleaned under zsh.
  if [ -n "${BASH_VERSION:-}" ]; then
    trap "rm -f ${COOKIE_JAR} /tmp/_bs_s2.txt /tmp/_bs_s3.txt /tmp/_bs_s4.txt /tmp/_bs_frame.txt" RETURN
  fi

  # Step 1: Session cookie
  curl -sLk -c "${COOKIE_JAR}" "${BACKSTAGE_URL}" -o /dev/null

  # Step 2: Start OIDC. MUST persist cookies (-c): /start rotates connect.sid and stores
  # the OAuth authorization-request details server-side keyed by that session id. Without
  # -c the rotated connect.sid is dropped, so the callback below runs against a session
  # that has no OAuth state and Backstage fails with "did not find expected authorization
  # request details in session" -> "Missing session cookie".
  curl -sLk -b "${COOKIE_JAR}" -c "${COOKIE_JAR}" \
    "${BACKSTAGE_URL}/api/auth/keycloak-oidc/start?scope=openid%20profile%20email&env=production" \
    -H "X-Requested-With: XMLHttpRequest" \
    --max-redirs 0 -D /tmp/_bs_s2.txt -o /dev/null 2>/dev/null || true

  local KC_URL FORM_ACTION CALLBACK
  KC_URL=$(grep -i "^location:" /tmp/_bs_s2.txt | sed 's/^[Ll]ocation: //' | tr -d '\r\n')

  # Step 3: Get Keycloak login form
  curl -sLk "${KC_URL}" -b "${COOKIE_JAR}" -c "${COOKIE_JAR}" -o /tmp/_bs_s3.txt
  FORM_ACTION=$(grep -oP 'action="[^"]*"' /tmp/_bs_s3.txt | head -1 | sed 's/action="//;s/"//' | sed 's/&amp;/\&/g')

  # Step 4: Submit credentials -> Keycloak issues a 302 back to the Backstage callback
  curl -sLk -X POST "${FORM_ACTION}" \
    -b "${COOKIE_JAR}" -c "${COOKIE_JAR}" \
    --data-urlencode "username=user1" \
    --data-urlencode "password=${USER1_PASSWORD}" \
    --max-redirs 0 -D /tmp/_bs_s4.txt -o /dev/null 2>/dev/null || true
  CALLBACK=$(grep -i "^location:" /tmp/_bs_s4.txt | sed 's/^[Ll]ocation: //' | tr -d '\r\n')

  # Step 5: Hit the callback (handler/frame) with the preserved session cookie. Backstage
  # exchanges the code and embeds the identity token in the returned HTML frame, which the
  # browser flow would postMessage back to the opener.
  curl -sLk "${CALLBACK}" -b "${COOKIE_JAR}" -c "${COOKIE_JAR}" -o /tmp/_bs_frame.txt 2>/dev/null || true

  # Step 6: Extract the Backstage identity token from the frame's authResponse payload.
  python3 -c "import urllib.parse,re,json; html=open('/tmp/_bs_frame.txt').read(); m=re.search(r\"decodeURIComponent\('([^']+)'\)\", html); d=json.loads(urllib.parse.unquote(m.group(1))); print(d.get('response',{}).get('backstageIdentity',{}).get('token',''))"
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
if [[ "${BASH_SOURCE[0]:-}" == "${0}" ]] || [[ "${ZSH_EVAL_CONTEXT:-}" == "toplevel" ]]; then
  backstage_get_token
else
  export BS_TOKEN
  BS_TOKEN=$(backstage_get_token)
  echo "BS_TOKEN set (${#BS_TOKEN} chars)" >&2
fi
