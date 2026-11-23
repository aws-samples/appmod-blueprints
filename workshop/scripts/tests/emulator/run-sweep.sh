#!/usr/bin/env bash
# shellcheck source-path=SCRIPTDIR
# Run the unmodified workshop sweep against the emulator and judge its exit code.
#
# RC 0 passes. RC 1 ("DESTROY INCOMPLETE") passes ONLY when every resource the §17 gate lists
# is in KNOWN_FALSE_RESIDUE; verify.py then checks on its own, with a short poll, that those
# resources are really gone. Any other code, or any other listed resource, fails the job.
#
# KNOWN_FALSE_RESIDUE: the §17 gate counts a DynamoDB table that is still DELETING as present
# (describe_table succeeds during the deletion), so the sweep ends RC=1 although the table is
# being deleted. Whether AWS behaves the same is being checked separately; when the sweep is
# fixed, RC becomes 0 and this list should be emptied.
set -euo pipefail
# shellcheck source=lib.sh
. "$(dirname "$0")/lib.sh"
emu_load
emu_assert_identity

KNOWN_FALSE_RESIDUE=("dynamodb:$PREFIX-terraform-lock")
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

case "$rc" in
  0) ;;
  1)
    # Lines look like "  ✗ dynamodb:peeks-terraform-lock" after "DESTROY INCOMPLETE".
    grep -q "DESTROY INCOMPLETE" "$OUT" || die "sweep RC=1 without a DESTROY INCOMPLETE report"
    mapfile -t listed < <(sed -n 's/^.*✗ \([^ ]*\).*$/\1/p' "$OUT")
    [ "${#listed[@]}" -gt 0 ] || die "sweep RC=1 but no residue line could be parsed"
    # "DESTROY INCOMPLETE — N owned resource(s)": every one of the N must have been parsed.
    n=$(sed -n 's/^.*DESTROY INCOMPLETE — \([0-9]*\) owned.*$/\1/p' "$OUT" | head -n 1)
    [ "$n" = "${#listed[@]}" ] || die "sweep reports ${n:-?} residue(s) but ${#listed[@]} were parsed"
    for r in "${listed[@]}"; do
      known=no
      for k in "${KNOWN_FALSE_RESIDUE[@]}"; do [ "$r" = "$k" ] && known=yes; done
      [ "$known" = yes ] || die "sweep reports real residue: $r"
      echo "::warning::sweep RC=1 for known false residue $r (DELETING table counted as present); verify.py checks it is gone"
    done ;;
  *) die "sweep exited RC=$rc" ;;
esac
