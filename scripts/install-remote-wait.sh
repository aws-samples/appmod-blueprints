#!/bin/sh
# Wait for the remote half of the install (task workshop:install:remote, run in CodeBuild)
# from the host that follows it (the IDE). Read-only: it only calls ssm get-parameter and
# codebuild batch-get-builds, so the host needs no write right for this.
#
#   RESOURCE_PREFIX   resource prefix (default: resourcePrefix of the config)
#   INSTALL_REMOTE_TIMEOUT   seconds to wait (default 6600)
#   INSTALL_REMOTE_INTERVAL  poll interval in seconds (default 20)
#   INSTALL_REMOTE_LOCAL_RC  optional file holding the exit code of a step this host runs in
#                            the background and the build depends on (install:ide passes
#                            /tmp/gitlab-init.rc): a non-zero code there ends the wait at once
#
# The build records its id in /<prefix>/install-build-id. A state written before that build
# started (an earlier build's OK or FAILED) is ignored, and a build that ended SUCCEEDED
# without recording OK is a failure, not a wait until the timeout.
# shortcut: until the current build has written its id, the previous build's id and state are
# what the wait sees; the IDE has no other way to know which build to expect.
#
# Exit: 0 = install-state is OK, 1 = FAILED / build ended badly / local step failed / timeout.
# The state parameter is written by the build; the IDE role can write it too (it is not
# a secret), so it only gates the IDE's own next steps, never anything privileged.
CFG="${CONFIG_FILE:-$(dirname "$0")/../config.local.yaml}"
PREFIX="${RESOURCE_PREFIX:-$(yq '.resourcePrefix // ""' "$CFG" 2>/dev/null)}"
[ -n "$PREFIX" ] && [ "$PREFIX" != "null" ] || { echo "install-remote-wait: no resource prefix" >&2; exit 1; }
MAX="${INSTALL_REMOTE_TIMEOUT:-6600}"
EVERY="${INSTALL_REMOTE_INTERVAL:-20}"
LOCAL_RC="${INSTALL_REMOTE_LOCAL_RC:-}"
TAB=$(printf '\t')

# epoch <time>: whole seconds from what the CLI prints for a timestamp (ISO 8601 or epoch).
epoch() {
  case "$1" in
    ""|None) echo "" ;;
    *[!0-9.]*) date -d "$1" +%s 2>/dev/null || echo "" ;;
    *) echo "${1%%.*}" ;;
  esac
}

# read_state: sets S (value) and S_AT (epoch of its last write).
read_state() {
  OUT=$(aws ssm get-parameter --name "/$PREFIX/install-state" \
    --query '[Parameter.Value,Parameter.LastModifiedDate]' --output text 2>/dev/null || echo "")
  case "$OUT" in
    *"$TAB"*) S="${OUT%"$TAB"*}"; S_AT=$(epoch "${OUT##*"$TAB"}") ;;
    *) S="$OUT"; S_AT="" ;;
  esac
}

# read_build: sets BS (status) and B_START (epoch) of the build in /<prefix>/install-build-id.
read_build() {
  BS=""; B_START=""
  BID=$(aws ssm get-parameter --name "/$PREFIX/install-build-id" --query Parameter.Value --output text 2>/dev/null || echo "")
  [ -n "$BID" ] && [ "$BID" != "None" ] || return 0
  OUT=$(aws codebuild batch-get-builds --ids "$BID" --query 'builds[0].[buildStatus,startTime]' --output text 2>/dev/null || echo "")
  case "$OUT" in
    *"$TAB"*) BS="${OUT%%"$TAB"*}"; B_START=$(epoch "${OUT#*"$TAB"}") ;;
    *) BS="$OUT" ;;
  esac
}

# current: the state belongs to the current build (no build known, or written after it started).
current() { [ -z "$B_START" ] || [ -z "$S_AT" ] || [ "$S_AT" -ge "$B_START" ]; }

LAST=""
STALE=""
W=0
echo "▸ Waiting for the CodeBuild install (/$PREFIX/install-state), max ${MAX}s. Logs: aws logs tail /aws/codebuild/${PREFIX}-install --follow"
while [ "$W" -lt "$MAX" ]; do
  if [ -n "$LOCAL_RC" ] && [ -s "$LOCAL_RC" ]; then
    RC=$(cat "$LOCAL_RC" 2>/dev/null || echo "")
    if [ "$RC" != "0" ]; then
      echo "✗ a step this install depends on failed on this host (rc=${RC:-?}, $LOCAL_RC): the build would wait for it in vain" >&2
      exit 1
    fi
  fi
  read_build
  read_state
  if [ -n "$S" ] && ! current; then
    if [ "$S" != "$STALE" ]; then
      echo "  [${W}s] ignoring a state from an earlier build: $S"
      STALE="$S"
    fi
    S=""
  fi
  if [ "$S" != "$LAST" ] && [ -n "$S" ]; then
    echo "  [${W}s] $S"
    LAST="$S"
  fi
  case "$S" in
    OK*) echo "✓ remote install finished: $S"; exit 0 ;;
    FAILED*) echo "✗ remote install failed: $S" >&2; exit 1 ;;
  esac
  case "$BS" in
    FAILED|FAULT|TIMED_OUT|STOPPED)
      echo "✗ the CodeBuild install build ended as $BS without recording OK (state: ${S:-none})" >&2
      exit 1 ;;
    SUCCEEDED)
      # The build records OK before it ends: read the state once more before concluding.
      read_state
      if current; then
        case "$S" in OK*) echo "✓ remote install finished: $S"; exit 0 ;; esac
      fi
      echo "✗ the CodeBuild install build ended as SUCCEEDED without recording OK (state: ${S:-none})" >&2
      exit 1 ;;
  esac
  sleep "$EVERY"
  W=$((W + EVERY))
done
echo "✗ the remote install did not finish within ${MAX}s (last state: ${LAST:-none})" >&2
exit 1
