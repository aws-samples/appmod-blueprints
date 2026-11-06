#!/usr/bin/env bash
# Authenticate to Backstage via Keycloak OIDC and return a Backstage identity token.
# Usage:
#   source backstage-auth.sh          # sets BS_TOKEN
#   backstage_get_token               # prints token to stdout
#   backstage_scaffolder "template:default/cicd-pipeline-gitops" '{"appname":"rust",...}'
#
# Requires: BACKSTAGE_URL, USER1_PASSWORD
#
# Safe to source from an interactive bash or zsh. This file is meant to be
# sourced, so it must not change the caller's shell options: a top-level
# `set -euo pipefail` here used to stay on in the caller's terminal, and the next
# unset variable or failing command (or a failed token fetch during the source
# itself) closed the terminal with exit code 1 ("parameter not set" in zsh).
# Strict mode now lives inside the functions, whose bodies run in a subshell
# `( ... )`, so it never reaches the caller.

backstage_get_token() (
  set -euo pipefail
  local COOKIE_JAR
  COOKIE_JAR=$(mktemp)
  # The body is a subshell, so an EXIT trap cleans up on return in both bash and
  # zsh (`trap ... RETURN` is bash-only).
  trap "rm -f ${COOKIE_JAR} /tmp/_bs_s2.txt /tmp/_bs_s3.txt /tmp/_bs_s4.txt /tmp/_bs_frame.txt" EXIT

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
)

backstage_scaffolder() (
  set -euo pipefail
  local TEMPLATE_REF="$1"
  local VALUES="$2"
  local TOKEN
  TOKEN=$(backstage_get_token)

  # Fail at once when the POST is refused. A 503 (catalog not started, e.g. the backend
  # failed with MigrationLocked) or a 404 (template not in the catalog) used to yield
  # id=null, and the loop below then polled tasks/null for ~300 s before failing with
  # no hint of the cause. Exit code 2 = the POST itself failed; the HTTP code and the
  # start of the error body are printed on stderr as
  # "backstage_scaffolder: POST ... returned HTTP <code>: <body>".
  local RESP CODE BODY TASK_ID
  RESP=$(curl -sLk --max-time 60 -w '\n%{http_code}' -X POST "${BACKSTAGE_URL}/api/scaffolder/v2/tasks" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "Content-Type: application/json" \
    -d "{\"templateRef\": \"${TEMPLATE_REF}\", \"values\": ${VALUES}}" 2>/dev/null || true)
  CODE=$(printf '%s\n' "$RESP" | tail -n 1)
  BODY=$(printf '%s\n' "$RESP" | sed '$d')
  case "$CODE" in [0-9][0-9][0-9]) ;; *) CODE=000 ;; esac
  TASK_ID=$(printf '%s' "$BODY" | jq -r '.id // empty' 2>/dev/null || true)
  case "$CODE" in
    2??) ;;
    *) TASK_ID="" ;;
  esac
  if [ -z "$TASK_ID" ] || [ "$TASK_ID" = "null" ]; then
    printf 'backstage_scaffolder: POST %s/api/scaffolder/v2/tasks returned HTTP %s: %.500s\n' \
      "$BACKSTAGE_URL" "$CODE" "$(printf '%s' "$BODY" | tr '\r\n' '  ')" >&2
    return 2
  fi

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
)

# Print the HTTP code of an AUTHENTICATED catalog read of a template (default
# cicd-pipeline-gitops), following redirects. 200 means the backend started and the
# catalog serves the template. An unauthenticated request is not a health signal: it
# gets 401 on the scaffolder and 302 (login redirect) on the catalog whether or not the
# backend started.
#   backstage_template_status [template-name]   -> e.g. 200, 404, 503, 000
backstage_template_status() (
  set -uo pipefail
  local NAME="${1:-cicd-pipeline-gitops}" TOKEN CODE
  TOKEN=$(backstage_get_token 2>/dev/null || true)
  CODE=$(curl -sLk -o /dev/null -w '%{http_code}' --max-time 20 \
    -H "Authorization: Bearer ${TOKEN}" \
    "${BACKSTAGE_URL}/api/catalog/entities/by-name/template/default/${NAME}" 2>/dev/null || true)
  case "$CODE" in [0-9][0-9][0-9]) echo "$CODE" ;; *) echo 000 ;; esac
)

# When sourced, export BS_TOKEN for direct use
if [[ "${BASH_SOURCE[0]:-}" == "${0}" ]] || [[ "${ZSH_EVAL_CONTEXT:-}" == "toplevel" ]]; then
  set -euo pipefail
  backstage_get_token
else
  export BS_TOKEN
  if BS_TOKEN=$(backstage_get_token) && [ -n "$BS_TOKEN" ]; then
    echo "BS_TOKEN set (${#BS_TOKEN} chars)" >&2
  else
    echo "backstage-auth: no Backstage token (check BACKSTAGE_URL and USER1_PASSWORD); BS_TOKEN is empty" >&2
  fi
fi
