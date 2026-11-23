#!/usr/bin/env bash
# shellcheck source-path=SCRIPTDIR
# The whole sweep-on-emulator job, the same locally and in GitHub Actions (README.md):
#   guard -> install (pinned, verified) -> start (loopback, no telemetry) -> identity guard
#   -> seed peeks + peeks2 -> issue #10 replay -> sweep -> verify.
# Needs: bash, curl, gpg, jq, tar/xz (or dpkg-deb), the AWS CLI v2, and a python3 with the
# packages of requirements.txt on PATH. Never needs, and refuses, real AWS credentials.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=lib.sh
. "$HERE/lib.sh"

guard_host_env
for t in curl gpg jq aws python3; do command -v "$t" >/dev/null || die "$t not found on PATH"; done
python3 -c 'import boto3, tenacity' 2>/dev/null || die "python3 lacks boto3/tenacity: pip install -r $HERE/requirements.txt"

mkdir -p "$EMU_WORK"
bash "$HERE/install.sh"
export PATH="$EMU_WORK/bin:$PATH"

trap emu_stop EXIT
emu_start
emu_load
emu_assert_identity
log "identity guard OK: account $EMU_ACCOUNT at $EMU_ENDPOINT"

bash "$HERE/seed.sh"
bash "$HERE/scenario-10.sh"
bash "$HERE/run-sweep.sh"
emu_run python3 "$HERE/verify.py" "$EMU_WORK/manifest.tsv" "$EMU_REGION" "$PREFIX"
log "sweep-on-emulator: PASS"
