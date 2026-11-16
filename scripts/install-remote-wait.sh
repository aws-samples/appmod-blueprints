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
#   INSTALL_REMOTE_NOT_BEFORE  optional epoch seconds (install:ide passes its start time): a
#                            state written earlier, and a build that ended earlier, belong to an
#                            earlier run and are ignored. On a fresh account the build cannot
#                            record OK before the IDE half starts (it waits for the GitLab PAT the
#                            IDE half writes). To follow a build that already finished (re-running
#                            install:ide), pass INSTALL_REMOTE_NOT_BEFORE=0.
#
# The build records its id in /<prefix>/install-build-id. A state written before that build
# started, or before INSTALL_REMOTE_NOT_BEFORE, is ignored (an earlier build's OK or FAILED),
# and so is the end status of a build that ended before INSTALL_REMOTE_NOT_BEFORE. A current
# build that ended SUCCEEDED without recording OK is a failure, not a wait until the timeout,
# and one that ended FAILED/FAULT/TIMED_OUT/STOPPED ends the wait at once. A build that fails
# before it writes its id is only caught by the timeout.
# Timestamps need GNU date -d for the ISO 8601 form (AL2023, CodeBuild); without it the
# comparison is skipped and every state counts as current.
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
NOT_BEFORE="${INSTALL_REMOTE_NOT_BEFORE:-}"
case "$NOT_BEFORE" in *[!0-9]*) echo "install-remote-wait: INSTALL_REMOTE_NOT_BEFORE must be epoch seconds" >&2; exit 1 ;; esac
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

# read_build: sets BS (status), B_START and B_END (epoch) of the build in /<prefix>/install-build-id.
# A build that ended before INSTALL_REMOTE_NOT_BEFORE is an earlier run's: BS is cleared.
read_build() {
  BS=""; B_START=""; B_END=""
  BID=$(aws ssm get-parameter --name "/$PREFIX/install-build-id" --query Parameter.Value --output text 2>/dev/null || echo "")
  [ -n "$BID" ] && [ "$BID" != "None" ] || return 0
  OUT=$(aws codebuild batch-get-builds --ids "$BID" --query 'builds[0].[buildStatus,startTime,endTime]' --output text 2>/dev/null || echo "")
  case "$OUT" in
    *"$TAB"*"$TAB"*)
      BS="${OUT%%"$TAB"*}"; REST="${OUT#*"$TAB"}"
      B_START=$(epoch "${REST%%"$TAB"*}"); B_END=$(epoch "${REST#*"$TAB"}") ;;
    *"$TAB"*) BS="${OUT%%"$TAB"*}"; B_START=$(epoch "${OUT#*"$TAB"}") ;;
    *) BS="$OUT" ;;
  esac
  if [ -n "$B_END" ] && [ -n "$NOT_BEFORE" ] && [ "$B_END" -lt "$NOT_BEFORE" ]; then
    if [ -z "$OLD_BUILD_SAID" ]; then
      echo "  build $BID ended ($BS) before this run started: waiting for a new build (INSTALL_REMOTE_NOT_BEFORE=0 follows that one instead)"
      OLD_BUILD_SAID=1
    fi
    BS=""
  fi
}

# current: the state belongs to the current run: written after the build in install-build-id
# started and not before INSTALL_REMOTE_NOT_BEFORE (each check applies when its time is known).
current() {
  [ -z "$S_AT" ] && return 0
  if [ -n "$B_START" ] && [ "$S_AT" -lt "$B_START" ]; then return 1; fi
  if [ -n "$NOT_BEFORE" ] && [ "$S_AT" -lt "$NOT_BEFORE" ]; then return 1; fi
  return 0
}

LAST=""
STALE=""
OLD_BUILD_SAID=""
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
      echo "  [${W}s] ignoring a state written before this run started: $S"
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
[ -z "$STALE$OLD_BUILD_SAID" ] || echo "  Only an earlier run's state or build was seen. To follow a build that already finished, re-run with INSTALL_REMOTE_NOT_BEFORE=0." >&2
exit 1
