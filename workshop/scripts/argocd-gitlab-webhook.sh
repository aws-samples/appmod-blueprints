#!/usr/bin/env bash
# Wire GitLab push webhooks to the EKS managed Argo CD capability so a participant's
# push to fleet-config refreshes Argo CD within seconds instead of waiting for the
# next poll (no webhook = poll latency, about 6 min by default).
#
# Consumer-side (workshop) only: the cluster providers stay consumer-agnostic.
#
# Steps:
#   1. serverUrl from `aws eks describe-capability` (configuration.argoCd.serverUrl)
#   2. READ webhook.gitlab.secret from argocd/argocd-webhook-creds-secret (the capability
#      creates that Secret with a value for every provider key). A non-empty value is REUSED
#      as the GitLab hook token and the Secret is NOT modified. Only when the key is empty or
#      absent is a random token generated and merge-patched in (and a warning says the
#      ApplicationSet receiver may only pick it up after the capability restarts).
#      Why reuse: the ApplicationSet receiver reads the secret once at start-up, so it holds
#      the capability's ORIGINAL value; overwriting the key made /api/webhook accept the new
#      value while /api/applicationset/webhook kept answering 400.
#   3. upsert two push-event project hooks on <user>/fleet-config (SSL verify on), same token:
#        <serverUrl>/api/webhook                  (Applications)
#        <serverUrl>/api/applicationset/webhook   (ApplicationSet git generators)
#
# The token never appears in output or argv: it is held in a shell variable, written only to
# 0600 files in a private temp dir (removed on exit) that curl/kubectl read, and `set -x` is off.
#
# Contract: WARN ONLY. Every failure prints a warning and the script exits 0, so it can
# never fail an install. Polling stays the fallback. Idempotent: re-running updates the
# existing hooks (matched by URL) and never duplicates them.
#
# Inputs (env): HUB_CLUSTER_NAME AWS_REGION GIT_DOMAIN GIT_USERNAME GITLAB_TOKEN (user PAT,
# glpat-...) KUBECONFIG. Optional: ARGOCD_WEBHOOK_CAPABILITY_NAME (default argocd),
# ARGOCD_WEBHOOK_PROJECT (default fleet-config), ARGOCD_WEBHOOK_SECRET_NAME (default
# argocd-webhook-creds-secret), ARGOCD_APPSET_WEBHOOK (0 = opt out of the ApplicationSet hook).
# shellcheck disable=SC2015  # ok() never fails, so A && ok || warn is a safe if/else
set +x
set -uo pipefail

warn() { printf '  ⚠ argocd webhook: %s (skipping; Argo CD keeps polling)\n' "$1"; }
ok()   { printf '  ✓ argocd webhook: %s\n' "$1"; }

TMP=$(mktemp -d 2>/dev/null) || { warn "mktemp failed"; exit 0; }
chmod 700 "$TMP"
trap 'rm -rf "$TMP"' EXIT

main() {
  local need
  for need in aws kubectl curl jq; do
    command -v "$need" >/dev/null 2>&1 || { warn "$need not found"; return 0; }
  done
  [ -n "${HUB_CLUSTER_NAME:-}" ] && [ -n "${AWS_REGION:-}" ] || { warn "hub/region unset"; return 0; }
  [ -n "${GIT_DOMAIN:-}" ]    || { warn "GitLab domain unresolved"; return 0; }
  [ -n "${GITLAB_TOKEN:-}" ]  || { warn "no GitLab token yet"; return 0; }
  # Prefixed names: a stray PROJECT/SECRET_NAME/CAPABILITY_NAME in the caller's shell is ignored.
  local user="${GIT_USERNAME:-user1}" project="${ARGOCD_WEBHOOK_PROJECT:-fleet-config}"
  local cap="${ARGOCD_WEBHOOK_CAPABILITY_NAME:-argocd}"
  local secret="${ARGOCD_WEBHOOK_SECRET_NAME:-argocd-webhook-creds-secret}"

  # 1. Argo CD server URL
  local server
  server=$(aws eks describe-capability --cluster-name "$HUB_CLUSTER_NAME" --capability-name "$cap" \
    --region "$AWS_REGION" --query 'capability.configuration.argoCd.serverUrl' --output text 2>/dev/null) \
    || { warn "describe-capability failed"; return 0; }
  case "$server" in https://*) ;; *) warn "no Argo CD serverUrl"; return 0 ;; esac
  server=${server%/}

  # 2. token: reuse the capability's existing value, patch only if empty/absent.
  # A failed or unparseable read is NOT an empty key: overwriting the capability's value
  # on a transient error (API/TLS timeout, RBAC) is the unrecoverable case described above,
  # so warn and stop. Generate only when the read succeeded and the key is empty/absent.
  local sj b64 tok="" key='webhook.gitlab.secret'
  sj=$(kubectl -n argocd get secret "$secret" -o json 2>/dev/null) \
    || { warn "cannot read $secret"; return 0; }
  b64=$(printf '%s' "$sj" | jq -er --arg k "$key" '.data // {} | .[$k] // ""' 2>/dev/null) \
    || { warn "cannot read $secret (unexpected JSON)"; return 0; }
  if [ -n "$b64" ]; then
    tok=$(printf '%s' "$b64" | base64 -d 2>/dev/null) \
      || { warn "cannot decode ${key} in $secret"; return 0; }
  fi
  if [ -n "$tok" ] && [ "$(printf %s "$tok" | wc -l)" -eq 0 ]; then
    ok "reusing the capability's existing ${key} (Secret not modified)"
  else
    tok=$(head -c 32 /dev/urandom 2>/dev/null | od -An -tx1 | tr -d ' \n')
    case "$tok" in *[!0-9a-f]*) tok="" ;; esac
    [ "${#tok}" -eq 64 ] || { warn "could not generate token"; return 0; }
    # printf is a builtin, so the token never reaches an argv; hex-only needs no JSON escaping.
    ( umask 077; printf '{"stringData":{"%s":"%s"}}\n' "$key" "$tok" > "$TMP/patch.json" ) \
      || { warn "patch build failed"; return 0; }
    kubectl -n argocd patch secret "$secret" --type merge --patch-file "$TMP/patch.json" >/dev/null 2>&1 \
      || { warn "cannot patch $secret"; return 0; }
    rm -f "$TMP/patch.json"
    printf '  ⚠ argocd webhook: %s was empty, generated and set one; the ApplicationSet receiver may keep rejecting it until the capability restarts\n' "$key"
  fi
  # curl config escaping for the double-quoted value
  local tokq
  tokq=$(printf %s "$tok" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g')

  # 3. GitLab hooks. The PAT goes through a 0600 header file, not argv.
  printf 'PRIVATE-TOKEN: %s\n' "$GITLAB_TOKEN" > "$TMP/hdr"; chmod 600 "$TMP/hdr"
  local api="https://${GIT_DOMAIN}/api/v4" pid="${user}%2F${project}"
  local hooks
  # per_page=100: GitLab defaults to 20, and a hook past the first page would be duplicated.
  hooks=$(curl -fsS --max-time 20 -H "@$TMP/hdr" "$api/projects/$pid/hooks?per_page=100" 2>/dev/null) \
    || { warn "cannot list hooks on ${user}/${project}"; return 0; }
  echo "$hooks" | jq -e 'type=="array"' >/dev/null 2>&1 || { warn "unexpected hooks response"; return 0; }

  # Each hook is sent with a 0600 curl config file (form fields), so neither the webhook
  # token nor the PAT is ever in argv.
  local path url id cfg="$TMP/hook.cfg" method target
  local paths="/api/webhook /api/applicationset/webhook"
  [ "${ARGOCD_APPSET_WEBHOOK:-1}" = 0 ] && paths="/api/webhook"
  for path in $paths; do
    url="${server}${path}"
    id=$(echo "$hooks" | jq -r --arg u "$url" '[.[]|select(.url==$u)][0].id // empty')
    if [ -n "$id" ]; then method=PUT;  target="$api/projects/$pid/hooks/$id"
    else                  method=POST; target="$api/projects/$pid/hooks"; fi
    ( umask 077
      {
        printf 'data-urlencode = "url=%s"\n' "$url"
        printf 'data-urlencode = "token=%s"\n' "$tokq"
        printf 'data-urlencode = "push_events=true"\n'
        printf 'data-urlencode = "tag_push_events=false"\n'
        printf 'data-urlencode = "merge_requests_events=false"\n'
        printf 'data-urlencode = "issues_events=false"\n'
        printf 'data-urlencode = "note_events=false"\n'
        printf 'data-urlencode = "pipeline_events=false"\n'
        printf 'data-urlencode = "enable_ssl_verification=true"\n'
      } > "$cfg" ) || { warn "cannot write hook request"; continue; }
    curl -fsS --max-time 20 -o /dev/null -X "$method" -H "@$TMP/hdr" -K "$cfg" "$target" 2>/dev/null \
      && ok "hook ${method} (${path})" || warn "cannot ${method} hook ${path}"
    rm -f "$cfg"
  done
  return 0
}

main || true
exit 0
