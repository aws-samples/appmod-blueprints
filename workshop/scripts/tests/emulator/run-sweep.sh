#!/usr/bin/env bash
# shellcheck source-path=SCRIPTDIR
# Run the unmodified workshop sweep against the emulator and judge its exit code.
#
# Only RC 0 passes. Any other code fails the job, with the sweep's own residue lines
# ("DESTROY INCOMPLETE ... ✗ <family>:<id>") shown in the log above. A table still DELETING
# is not residue since #1314, so there is no tolerated residue left.
set -euo pipefail
# shellcheck source=lib.sh
. "$(dirname "$0")/lib.sh"
emu_load
emu_assert_identity

SWEEP="$REPO_ROOT/workshop/scripts/sweep-workshop-resources.py"
OUT="$EMU_WORK/sweep.log"

log "sweep: python3 $SWEEP $EMU_REGION $PREFIX"
start=$(date +%s)
rc=0
emu_run python3 -u "$SWEEP" "$EMU_REGION" "$PREFIX" >"$OUT" 2>&1 || rc=$?
log "sweep finished in $(( $(date +%s) - start ))s with RC=$rc (full log: $OUT)"
sed 's/^/    | /' "$OUT"

# The emulator stubs CloudFront ListVpcOrigins: the reaper logs NotImplemented and the sweep
# carries on. Expected here; anything else from the CloudFront reaper is shown as is above.
if grep -q "ListVpcOrigins" "$OUT" && grep -q "NotImplemented" "$OUT"; then
  echo "::notice::CloudFront reaper skipped: ListVpcOrigins is a stub in the emulator (expected)"
fi

if [ "$rc" -ne 0 ]; then
  grep '✗ ' "$OUT" >&2 || true
  die "sweep exited RC=$rc"
fi
