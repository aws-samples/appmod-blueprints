#!/bin/sh
# Wait for the remote half of the install (task workshop:install:remote, run in CodeBuild)
# from the host that follows it (the IDE). Read-only: it only calls ssm get-parameter and
# codebuild batch-get-builds, so the host needs no write right for this.
#
#   RESOURCE_PREFIX   resource prefix (default: resourcePrefix of the config)
#   INSTALL_REMOTE_TIMEOUT   seconds to wait (default 6600)
#   INSTALL_REMOTE_INTERVAL  poll interval in seconds (default 20)
#   INSTALL_REMOTE_PROJECT   CodeBuild project name; with /<prefix>/install-build-id it lets
#                            the wait notice a build that died without writing FAILED
#
# Exit: 0 = install-state is OK, 1 = FAILED / build ended badly / timeout.
# The state parameter is written by the build; the IDE role can write it too (it is not
# a secret), so it only gates the IDE's own next steps, never anything privileged.
CFG="${CONFIG_FILE:-$(dirname "$0")/../config.local.yaml}"
PREFIX="${RESOURCE_PREFIX:-$(yq '.resourcePrefix // ""' "$CFG" 2>/dev/null)}"
[ -n "$PREFIX" ] && [ "$PREFIX" != "null" ] || { echo "install-remote-wait: no resource prefix" >&2; exit 1; }
MAX="${INSTALL_REMOTE_TIMEOUT:-6600}"
EVERY="${INSTALL_REMOTE_INTERVAL:-20}"
LAST=""
W=0
echo "▸ Waiting for the CodeBuild install (/$PREFIX/install-state), max ${MAX}s. Logs: aws logs tail /aws/codebuild/${PREFIX}-install --follow"
while [ "$W" -lt "$MAX" ]; do
  S=$(aws ssm get-parameter --name "/$PREFIX/install-state" --query Parameter.Value --output text 2>/dev/null || echo "")
  if [ "$S" != "$LAST" ] && [ -n "$S" ]; then
    echo "  [${W}s] $S"
    LAST="$S"
  fi
  case "$S" in
    OK*) echo "✓ remote install finished: $S"; exit 0 ;;
    FAILED*) echo "✗ remote install failed: $S" >&2; exit 1 ;;
  esac
  BID=$(aws ssm get-parameter --name "/$PREFIX/install-build-id" --query Parameter.Value --output text 2>/dev/null || echo "")
  if [ -n "$BID" ] && [ "$BID" != "None" ]; then
    BS=$(aws codebuild batch-get-builds --ids "$BID" --query 'builds[0].buildStatus' --output text 2>/dev/null || echo "")
    case "$BS" in
      FAILED|FAULT|TIMED_OUT|STOPPED)
        echo "✗ the CodeBuild install build ended as $BS without recording OK (state: ${S:-none})" >&2
        exit 1 ;;
    esac
  fi
  sleep "$EVERY"
  W=$((W + EVERY))
done
echo "✗ the remote install did not finish within ${MAX}s (last state: ${LAST:-none})" >&2
exit 1
