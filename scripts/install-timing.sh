#!/bin/sh
# install-timing.sh — uniform start/done timing markers for `task install`.
#
# Every marker is printed to stdout AND appended to the timing log
# ($INSTALL_TIMING_LOG, default /tmp/install-timing.log), so background jobs whose
# stdout goes to their own log still land in one place. One line per event:
#
#   [<s since T0>s] <name> start @<UTC ISO-8601>
#   [<s since T0>s] <name> done took=<s>s [extra] @<UTC ISO-8601>
#
# A Gantt chart of the whole install (foreground steps, background jobs, waiters)
# can be rebuilt from the timing log alone: each `done` line carries its duration.
#
# Usage:
#   install-timing.sh reset <epoch>      new install: truncate the log, T0 = <epoch>
#   install-timing.sh init <epoch>       set T0 only if no install set it (standalone run)
#   install-timing.sh step <lane> <name...> close <lane>'s open step, open <name>
#   install-timing.sh step <lane> -      close <lane>'s open step
#   install-timing.sh start <name>       open <name> (background job, async wait, ...)
#   install-timing.sh done <name> [extra...]
#   install-timing.sh dump               print the timing log
#
# T0: $INSTALL_TIMING_T0 if set, else the T0 file written by reset/init, else now.
# Never fails: timing must not change the install outcome.

LOG="${INSTALL_TIMING_LOG:-/tmp/install-timing.log}"
STATE="${LOG}.d"
mkdir -p "$STATE" 2>/dev/null || true

now() { date +%s; }
t0() {
  if [ -n "${INSTALL_TIMING_T0:-}" ]; then echo "$INSTALL_TIMING_T0"
  elif [ -s "$STATE/t0" ]; then cat "$STATE/t0"
  else now
  fi
}
key() { printf '%s' "$1" | tr -c 'A-Za-z0-9._-' '_'; }

emit() { # <name> <event> [extra...]
  N=$(now)
  T=$(t0)
  LINE=$(printf '[%ds] %s @%s' "$((N - T))" "$*" "$(date -u +%Y-%m-%dT%H:%M:%SZ)")
  printf '  %s\n' "$LINE"
  printf '%s\n' "$LINE" >> "$LOG" 2>/dev/null || true
}

open_() { # <name>
  now > "$STATE/s.$(key "$1")" 2>/dev/null || true
  emit "$1" start
}

close_() { # <name> [extra...]
  C_NAME=$1; shift
  F="$STATE/s.$(key "$C_NAME")"
  if [ -s "$F" ]; then
    S=$(cat "$F"); rm -f "$F"
    emit "$C_NAME" "done" "took=$(( $(now) - S ))s" "$@"
  else
    emit "$C_NAME" "done" "$@"
  fi
}

CMD=${1:-}; [ $# -gt 0 ] && shift
case "$CMD" in
  reset)
    rm -rf "$STATE"; mkdir -p "$STATE" 2>/dev/null || true
    : > "$LOG" 2>/dev/null || true
    echo "${1:-$(now)}" > "$STATE/t0" 2>/dev/null || true ;;
  init)
    [ -n "${INSTALL_TIMING_T0:-}" ] || {
      rm -rf "$STATE"; mkdir -p "$STATE" 2>/dev/null || true
      : > "$LOG" 2>/dev/null || true
      echo "${1:-$(now)}" > "$STATE/t0" 2>/dev/null || true
    } ;;
  step)
    LANE=$(key "${1:-main}"); [ $# -gt 0 ] && shift; NAME=${*:--}
    CUR="$STATE/lane.$LANE"
    if [ -s "$CUR" ]; then close_ "$(cat "$CUR")"; rm -f "$CUR"; fi
    if [ "$NAME" != "-" ]; then printf '%s' "$NAME" > "$CUR" 2>/dev/null || true; open_ "$NAME"; fi ;;
  start) [ -n "${1:-}" ] && open_ "$1" ;;
  done)  [ -n "${1:-}" ] && close_ "$@" ;;
  dump)
    printf '  ── install timing (%s) ──\n' "$LOG"
    sed 's/^/  /' "$LOG" 2>/dev/null || true ;;
  *) echo "usage: install-timing.sh reset|init|step|start|done|dump ..." >&2 ;;
esac
exit 0
