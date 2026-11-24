#!/usr/bin/env bash
# shellcheck source-path=SCRIPTDIR
# Issue #10 replay: on a reused account a delivery source "<cluster>-kro" survives from an
# earlier cluster incarnation and points at the OLD capability ARN. A plain
# put-delivery-source for the new ARN then fails with a ConflictException, which aborted
# `task install`. This runs the REAL `task enable-capability-logs` from the repo's
# Taskfile.yaml against the emulator and checks that it reconciles the stale source, then
# that a second run is a no-op.
#
# Emulator gap: its capability ARN does not change when a capability is recreated, so the
# "old" ARN is a synthetic one, injected directly.
set -euo pipefail
# shellcheck source=lib.sh
. "$(dirname "$0")/lib.sh"
emu_load
emu_assert_identity

HUB="$PREFIX-hub"; SRC="$HUB-kro"
CAP_ARN=$(emu_aws eks describe-capability --cluster-name "$HUB" --capability-name kro --query capability.arn --output text)
OLD_ARN="${CAP_ARN}-previous-incarnation"
LG_ARN="arn:aws:logs:$EMU_REGION:$EMU_ACCOUNT:log-group:/aws/eks/$HUB/capability/kro"

# 1. The stale state: a source on the old ARN, with a delivery that references it (so the
#    source cannot simply be deleted: the delivery must go first).
emu_aws logs create-log-group --log-group-name "/aws/eks/$HUB/capability/kro"
emu_aws logs put-delivery-source --name "$SRC" --resource-arn "$OLD_ARN" --log-type EKS_CAPABILITY_KRO_LOGS >/dev/null
emu_aws logs put-delivery-destination --name "$SRC-cwl" \
  --delivery-destination-configuration "destinationResourceArn=$LG_ARN" >/dev/null
DEST_ARN=$(emu_aws logs describe-delivery-destinations --query "deliveryDestinations[?name=='$SRC-cwl'].arn | [0]" --output text)
emu_aws logs create-delivery --delivery-source-name "$SRC" --delivery-destination-arn "$DEST_ARN" >/dev/null

# 2. Control: the pre-fix behaviour (a plain put) fails exactly like the issue.
if OUT=$(emu_aws logs put-delivery-source --name "$SRC" --resource-arn "$CAP_ARN" --log-type EKS_CAPABILITY_KRO_LOGS 2>&1); then
  die "#10 control: a plain put-delivery-source over a stale source succeeded; the scenario no longer reproduces"
fi
if ! grep -q "ConflictException" <<<"$OUT" \
  || ! grep -q "Update to existing Delivery Source with new ResourceId is not allowed" <<<"$OUT"; then
  die "#10 control: unexpected error: $OUT"
fi
log "#10 control reproduced: $(grep -o 'ConflictException.*' <<<"$OUT" | head -c 160)"

# 3. The real task, from a scratch copy of the repo pieces the Taskfile loads (same list as
#    test_capability_logs_wait.py), with a config naming the prefix and the region.
# A fresh copy per run, so a local rerun never parses files deleted from the checkout since.
R=$(mktemp -d "$EMU_WORK/taskrepo.XXXXXX")
mkdir -p "$R/scripts" "$R/workshop" "$R/gitops/addons"
cp "$REPO_ROOT/Taskfile.yaml" "$R/"
cp -R "$REPO_ROOT/cluster-providers" "$R/"
cp "$REPO_ROOT/scripts/install-timing.sh" "$R/scripts/"
cp -R "$REPO_ROOT/gitops/addons/registry" "$R/gitops/addons/"
cp "$REPO_ROOT/workshop/Taskfile.yaml" "$R/workshop/"
printf 'clusterProvider: kind-kro-ack\nresourcePrefix: %s\naws: {region: %s}\n' "$PREFIX" "$EMU_REGION" >"$R/config.local.yaml"

run_task() { # log-file
  emu_assert_identity
  # --silent: go-task otherwise echoes the script, whose comments contain the words grepped below.
  emu_run /usr/bin/env CAP_LOGS_WAIT=30 task --silent -d "$R" enable-capability-logs >"$1" 2>&1 \
    || { cat "$1"; die "task enable-capability-logs failed"; }
  sed 's/^/    | /' "$1"
}

run_task "$EMU_WORK/task-10-first.log"
grep -q "$HUB: stale 'kro' delivery source ($OLD_ARN) — recreating for $CAP_ARN" "$EMU_WORK/task-10-first.log" \
  || die "#10: the task did not detect the stale delivery source"
grep -q "$HUB: kro log delivery created" "$EMU_WORK/task-10-first.log" || die "#10: no delivery created after the reconcile"
NOW=$(emu_aws logs describe-delivery-sources --query "deliverySources[?name=='$SRC'].resourceArns[0] | [0]" --output text)
[ "$NOW" = "$CAP_ARN" ] || die "#10: delivery source points at '$NOW', expected $CAP_ARN"

run_task "$EMU_WORK/task-10-second.log"
grep -q "$HUB: stale 'kro' delivery source" "$EMU_WORK/task-10-second.log" && die "#10: second run reconciled again (not idempotent)"
grep -q "$HUB: kro log delivery already present" "$EMU_WORK/task-10-second.log" || die "#10: second run did not find the delivery"
log "#10 OK: stale source reconciled, second run is a no-op"

# What the sweep must now remove (its §11b reaper takes <prefix>-* delivery objects).
MANIFEST="$EMU_WORK/manifest.tsv"
printf 'gone\tdelivery-source\t%s\ngone\tdelivery-destination\t%s\ngone\tlog-group\t%s\n' \
  "$SRC" "$SRC-cwl" "/aws/eks/$HUB/capability/kro" >>"$MANIFEST"
