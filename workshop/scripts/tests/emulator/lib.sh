# shellcheck shell=bash
# Shared helpers for the sweep-on-emulator job (see README.md). Source this file; do not run it.
#
# Every AWS call of the job goes through emu_run / emu_aws. They start the command from an
# EMPTY environment (/usr/bin/env -i, never a PATH `env` shim) holding only the emulator's
# endpoint, its generated keys and its CA, after checking that the endpoint is the local
# emulator. A real credential in the caller's environment therefore cannot reach the command,
# and run-all.sh refuses to start at all when one is present (guard_host_env).

EMU_REGION="${EMU_REGION:-us-west-2}"
EMU_ACCOUNT=000000000000
EMU_WORK="${EMU_WORK:-${RUNNER_TEMP:-${TMPDIR:-/tmp}}/sweep-emulator}"
EMU_HOME="$EMU_WORK/home"
EMU_STATE="$EMU_WORK/emulator.env"
EMU_LOG="$EMU_WORK/emulator.log"
EMU_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC2034 # REPO_ROOT, PREFIX and CONTROL are read by the scripts that source this file.
REPO_ROOT="$(cd "$EMU_DIR/../../../.." && pwd)"
# The test prefix and the control prefix. peeks2 starts with "peeks" on purpose: the sweep
# must not take a stack whose prefix merely starts with ours (#1111).
# shellcheck disable=SC2034
PREFIX=peeks
# shellcheck disable=SC2034
CONTROL=peeks2

die() { echo "ERROR: $*" >&2; exit 1; }
log() { printf '[emulator-ci] %s\n' "$*"; }

# Refuse ANY AWS_* variable (credentials, profiles, config files, endpoints incl. the
# per-service AWS_ENDPOINT_URL_<SVC>, CA bundles, IMDS endpoints) and the GitHub OIDC token
# variables. The AWS calls run from an empty environment anyway (emu_run); this makes a
# misconfigured job fail loudly instead of relying on that alone.
guard_host_env() {
  local v bad=""
  for v in $(compgen -v | grep -E '^(AWS_|ACTIONS_ID_TOKEN_)' || true); do
    if [ -n "${!v+x}" ]; then bad="$bad $v"; fi  # set, even to an empty value
  done
  [ -z "$bad" ] || die "refusing to run: set in the environment:$bad. This job must never see real AWS credentials or endpoints."
}

emu_load() {
  [ -f "$EMU_STATE" ] || die "no running emulator ($EMU_STATE missing): run-all.sh starts it"
  # shellcheck source=/dev/null
  . "$EMU_STATE"
}

# Checked before every command started by emu_run: the endpoint is https://127.0.0.1:<port>,
# the emulator process we started is alive, and its generated files exist.
emu_check_endpoint() {
  [[ "${EMU_ENDPOINT:-}" =~ ^https://127\.0\.0\.1:[0-9]+$ ]] \
    || die "emulator endpoint '${EMU_ENDPOINT:-}' is not https://127.0.0.1:<port>"
  if [ -z "${EMU_PID:-}" ] || ! kill -0 "$EMU_PID" 2>/dev/null; then
    die "emulator process '${EMU_PID:-}' is not running"
  fi
  if [ ! -f "${EMU_CONFIG:-}" ] || [ ! -f "${EMU_CREDS:-}" ] || [ ! -f "${EMU_CA:-}" ]; then
    die "emulator files missing under $EMU_HOME"
  fi
}

emu_run() {
  emu_check_endpoint
  /usr/bin/env -i \
    PATH="$PATH" HOME="$EMU_HOME" LANG=C.UTF-8 TMPDIR="$EMU_WORK/tmp" \
    AWS_ENDPOINT_URL="$EMU_ENDPOINT" \
    AWS_CONFIG_FILE="$EMU_CONFIG" AWS_SHARED_CREDENTIALS_FILE="$EMU_CREDS" AWS_CA_BUNDLE="$EMU_CA" \
    AWS_EC2_METADATA_DISABLED=true AWS_DISABLE_HOST_PREFIX_INJECTION=true \
    AWS_REGION="$EMU_REGION" AWS_DEFAULT_REGION="$EMU_REGION" AWS_PAGER="" \
    EMU_ENDPOINT="$EMU_ENDPOINT" \
    "$@"
}

emu_aws() { emu_run aws "$@"; }

emu_assert_identity() {
  local acct
  acct=$(emu_aws sts get-caller-identity --query Account --output text) \
    || die "sts get-caller-identity failed against the emulator"
  [ "$acct" = "$EMU_ACCOUNT" ] || die "caller account is '$acct', not the emulator's $EMU_ACCOUNT: refusing to continue"
}

emu_start() {
  local bin="$EMU_WORK/bin/aws-emulator" line i
  [ -x "$bin" ] || die "$bin missing: run install.sh first"
  if [ -f "$EMU_STATE" ]; then
    die "$EMU_STATE exists: an emulator from an earlier run may still be up. Stop the process whose EMU_PID it names, remove the file, or use another EMU_WORK."
  fi
  mkdir -p "$EMU_HOME" "$EMU_WORK/tmp"
  : >"$EMU_LOG"
  # -p 0: a free port; -b 127.0.0.1: loopback only (also the default); -t off: no telemetry.
  /usr/bin/env -i PATH=/usr/bin:/bin HOME="$EMU_HOME" EMULATOR_TELEMETRY=off \
    "$bin" -b 127.0.0.1 -p 0 -t off --idle-timeout 900 >"$EMU_LOG" 2>&1 &
  EMU_PID=$!
  # Recorded at once, so the caller's `trap emu_stop EXIT` (set BEFORE emu_start) stops the
  # emulator and removes this file whichever check below fails.
  printf 'EMU_PID=%q\n' "$EMU_PID" >"$EMU_STATE"
  EMU_OWNS_STATE=1
  line=""
  for i in $(seq 60); do
    line=$(jq -Rc 'fromjson? | .fields | select(.endpoint_url != null)' "$EMU_LOG" 2>/dev/null | head -n 1 || true)
    [ -n "$line" ] && break
    kill -0 "$EMU_PID" 2>/dev/null || { cat "$EMU_LOG" >&2; die "emulator exited during startup"; }
    sleep 1
  done
  [ -n "$line" ] || die "no startup line from the emulator after 60 s"
  EMU_ENDPOINT=$(jq -r .endpoint_url <<<"$line")
  EMU_CONFIG=$(jq -r .config_file <<<"$line")
  EMU_CA=$(jq -r .ca_file <<<"$line")
  EMU_CREDS="$(dirname "$EMU_CONFIG")/emulator_credentials"
  printf 'EMU_PID=%q\nEMU_ENDPOINT=%q\nEMU_CONFIG=%q\nEMU_CA=%q\nEMU_CREDS=%q\n' \
    "$EMU_PID" "$EMU_ENDPOINT" "$EMU_CONFIG" "$EMU_CA" "$EMU_CREDS" >"$EMU_STATE"
  emu_check_endpoint
  for i in $(seq 30); do
    curl -sf --cacert "$EMU_CA" "$EMU_ENDPOINT/__admin/health" >/dev/null && break
    [ "$i" -lt 30 ] || die "emulator health check failed"
    sleep 1
  done
  # Belt and braces: every socket the emulator listens on must be on loopback.
  if command -v ss >/dev/null; then
    local socks
    socks=$(ss -Hltnp | grep "pid=$EMU_PID," | awk '{print $4}' || true)
    [ -n "$socks" ] || die "ss shows no listening socket for the emulator (pid $EMU_PID)"
    if grep -qv '^127\.0\.0\.1:' <<<"$socks"; then
      die "emulator listens on a non-loopback address: $socks"
    fi
  fi
  log "emulator $("$bin" -v | sed -n 1p) up at $EMU_ENDPOINT (pid $EMU_PID)"
}

emu_stop() {
  # Only the shell that started the emulator stops it: never another run's emulator/state.
  if [ "${EMU_OWNS_STATE:-}" != 1 ] || [ ! -f "$EMU_STATE" ]; then return 0; fi
  # shellcheck source=/dev/null
  . "$EMU_STATE"
  if [ -n "${EMU_PID:-}" ] && kill -0 "$EMU_PID" 2>/dev/null; then
    kill "$EMU_PID"
    # Started through env, so not our direct child: poll instead of `wait`.
    for _ in $(seq 20); do kill -0 "$EMU_PID" 2>/dev/null || break; sleep 0.5; done
  fi
  rm -f "$EMU_STATE"
}
