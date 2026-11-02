#!/usr/bin/env bash
# Workshop app helpers — auto-sourced via ~/.bashrc.d/* (see hack/.zshrc).
# Provide a robust way to open deployed app URLs only once the load balancer
# (ALB) is provisioned AND serving, so participants don't hit a blank/error page.

# open_when_ready <url> [timeout_seconds]
#   Polls <url> until the ALB answers with a 2xx/3xx, then opens it in the IDE
#   browser. Guards against a URL with no host (e.g. an empty $DNS_DEV in this shell).
open_when_ready() {
  local url="$1" timeout="${2:-300}" start=$SECONDS code
  local host="${url#*://}"; host="${host%%/*}"
  if [ -z "$url" ] || [ -z "$host" ]; then
    # An empty host means the shell variable holding the hostname is unset/empty,
    # not that the ALB is slow: say so, so participants fix the right thing.
    echo "⚠️  URL has no host ('$url'): the variable that holds the app hostname" >&2
    echo "    (e.g. \$DNS_DEV / \$DNS_PROD) is empty in this shell. Re-export it" >&2
    echo "    (see the step above) or open a new terminal, then retry." >&2
    return 1
  fi
  echo "⏳ Waiting for the load balancer to serve ${url} (can take 1-2 min)…"
  while :; do
    # curl already prints 000 (and exits non-zero) when it cannot connect, so only
    # default the code when it printed nothing (e.g. a malformed URL).
    code=$(curl -sk -o /dev/null -w '%{http_code}' --max-time 5 "$url" 2>/dev/null) || code=${code:-000}
    case "$code" in
      2*|3*) echo "✅ ${url} is reachable (HTTP ${code})."; break ;;
    esac
    if (( SECONDS - start > timeout )); then
      echo "⚠️  Timed out after ${timeout}s (last HTTP ${code}). The ALB may still be" >&2
      echo "    provisioning / registering targets — wait a moment and retry." >&2
      return 1
    fi
    printf '.'; sleep 10
  done
  if command -v xdg-open >/dev/null 2>&1; then xdg-open "$url" 2>/dev/null
  else echo "Open in your browser: $url"; fi
}

# wait_for_ingress <kube-context> <ingress-name> [namespace] [timeout_seconds]
#   Echoes the ingress ALB hostname once assigned (progress goes to stderr so it
#   is safe in command substitution): DNS_DEV=$(wait_for_ingress peeks-spoke-dev next-js-app)
wait_for_ingress() {
  local ctx="$1" name="$2" ns="$3" timeout="${4:-300}" start=$SECONDS host
  local nsarg=(); [ -n "$ns" ] && nsarg=(-n "$ns")
  echo "⏳ Waiting for ingress '$name' (context $ctx) to get an ALB address…" >&2
  while :; do
    host=$(kubectl --context "$ctx" "${nsarg[@]}" get ingress "$name" \
      -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null)
    [ -n "$host" ] && { echo "$host"; return 0; }
    if (( SECONDS - start > timeout )); then
      echo "⚠️  Ingress '$name' still has no address after ${timeout}s." >&2; return 1
    fi
    sleep 5
  done
}
