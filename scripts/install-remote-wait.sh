#!/bin/sh
# Wait for the remote half of the install (task workshop:install:remote, run in CodeBuild)
# from the host that follows it (the IDE). Read-only: it only calls ssm get-parameter,
# codebuild batch-get-builds and secretsmanager describe-secret, so the host needs no write
# right for this.
#
#   install-remote-wait.sh                       wait
#   install-remote-wait.sh --print-not-before    print the cut-off described below and exit
#
#   RESOURCE_PREFIX   resource prefix (default: resourcePrefix of the config)
#   INSTALL_REMOTE_TIMEOUT   seconds to wait (default 6600)
#   INSTALL_REMOTE_INTERVAL  poll interval in seconds (default 20)
#   INSTALL_REMOTE_LOCAL_RC  optional file holding the exit code of a step this host runs in
#                            the background and the build depends on (install:ide passes
#                            /tmp/gitlab-init.rc): a non-zero code there ends the wait at once
#   INSTALL_REMOTE_NOT_BEFORE  cut-off, epoch seconds. Default: when <prefix>/install-config
#                            was last written, that is when the build this host took its config
#                            from published it (fetch-install-config.sh), before its install
#                            step. A state written earlier, and a build that ended earlier, belong
#                            to an earlier build and are ignored; every state of the current build
#                            that matters (FAILED of a step after the publish, OK) is later. An
#                            empty default (secret unreadable) disables the check; 0 also does.
#
# The build records its id in /<prefix>/install-build-id. A state written before that build
# started, or before the cut-off, is ignored (an earlier build's OK or FAILED), and so is the
# end status of a build that ended before the cut-off. A current build that ended SUCCEEDED
# without recording OK is a failure, not a wait until the timeout, and one that ended
# FAILED/FAULT/TIMED_OUT/STOPPED ends the wait at once. Re-running install:ide after its build
# finished follows that build (its states are later than its publish).
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

if [ -z "$NOT_BEFORE" ] && [ -z "${INSTALL_REMOTE_NOT_BEFORE+set}" ]; then
  NOT_BEFORE=$(epoch "$(aws secretsmanager describe-secret --secret-id "$PREFIX/install-config" \
    --query LastChangedDate --output text 2>/dev/null || true)")
fi
if [ "${1:-}" = --print-not-before ]; then echo "$NOT_BEFORE"; exit 0; fi

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
# A build that ended before the cut-off is an earlier build's: BS is cleared.
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
      echo "  build $BID ended ($BS) before the config this host uses was published: waiting for the new build"
      OLD_BUILD_SAID=1
    fi
    BS=""
  fi
}

# current: the state belongs to the current run: written after the build in install-build-id
# started and not before the cut-off (each check applies when its time is known).
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
      echo "  [${W}s] ignoring a state of an earlier build (written before the config this host uses was published): $S"
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
[ -z "$STALE$OLD_BUILD_SAID" ] || echo "  Only an earlier build's state or status was seen (cut-off ${NOT_BEFORE:-none}: when ${PREFIX}/install-config was last published). Re-run fetch-install-config.sh once the new build has published it." >&2
exit 1
