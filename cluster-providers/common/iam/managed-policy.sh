#!/bin/sh
# Scoped customer-managed IAM policy for a role that `task install` creates.
#
#   managed-policy.sh ensure <account-id> <prefix> <role> <document.json> [<legacy-inline-name>]
#   managed-policy.sh delete <account-id> <prefix> <role>
#   managed-policy.sh name   <prefix> <role>
#
# Policy name: "<role>-scoped". It gets a "<prefix>-" in front when the role name does not
# already start with it, so the policy always matches policy/<prefix>-*. That is the pattern
# consumers grant IAM writes on (e.g. the PEEKS instance role), and the one the prefix-based
# teardown sweeps delete.
#
# ensure: idempotent. Every error other than NoSuchEntity is fatal (exit 1).
#   policy absent           -> CreatePolicy, AttachRolePolicy
#   same default document   -> AttachRolePolicy only (a no-op when already attached)
#   different document      -> DetachRolePolicy, DeletePolicyVersion (each non-default),
#                              DeletePolicy, CreatePolicy, AttachRolePolicy
#   then, with <legacy-inline-name>: DeleteRolePolicy of the inline policy an earlier
#   version of the install wrote with the same document (NoSuchEntity = nothing to do).
#   CreatePolicyVersion is NOT used on purpose: a consumer may grant CreatePolicy and
#   DeletePolicy on policy/<prefix>-* but not CreatePolicyVersion (PEEKS does not). The cost
#   is a short window, during a drift recreate only, where the role has no scoped policy.
#   A failure inside that window leaves the policy absent, and the next run creates it.
# delete: DetachRolePolicy from <role>, DeletePolicyVersion (each non-default), DeletePolicy.
#   NoSuchEntity is success. Only <role> is detached: a policy still attached elsewhere makes
#   DeletePolicy fail (DeleteConflict) instead of being torn off another role.
set -eu

usage() { echo "usage: $0 ensure <account-id> <prefix> <role> <document.json> [<legacy-inline-name>] | delete <account-id> <prefix> <role> | name <prefix> <role>" >&2; exit 2; }

policy_name() {  # policy_name <prefix> <role>
  case "$2" in
    "$1"-*) echo "$2-scoped" ;;
    *) if [ -n "$1" ]; then echo "$1-$2-scoped"; else echo "$2-scoped"; fi ;;
  esac
}

ERRF=$(mktemp)
trap 'rm -f "$ERRF"' EXIT

# iam <args>: run `aws iam <args>`; return 0 on success, 3 on NoSuchEntity, 1 on any other
# error (its stderr is printed).
iam() {
  if aws iam "$@" 2>"$ERRF"; then return 0; fi
  if grep -q NoSuchEntity "$ERRF"; then return 3; fi
  cat "$ERRF" >&2
  return 1
}

# ok_or_absent <cmd...>: success or NoSuchEntity -> 0, any other error -> exit 1.
ok_or_absent() {
  rc=0; "$@" >/dev/null || rc=$?
  [ "$rc" -eq 0 ] || [ "$rc" -eq 3 ] || { echo "ERROR: aws iam $2 failed for $ARN" >&2; exit 1; }
}

delete_policy() {  # detach from $ROLE, delete non-default versions, delete the policy
  ok_or_absent iam detach-role-policy --role-name "$ROLE" --policy-arn "$ARN"
  rc=0
  # shellcheck disable=SC2016  # JMESPath backticks, not a shell expansion
  VERSIONS=$(iam list-policy-versions --policy-arn "$ARN" \
    --query 'Versions[?IsDefaultVersion==`false`].VersionId' --output text) || rc=$?
  [ "$rc" -eq 3 ] && return 0
  [ "$rc" -eq 0 ] || { echo "ERROR: aws iam list-policy-versions failed for $ARN" >&2; exit 1; }
  for V in $VERSIONS; do
    [ "$V" = None ] && continue
    ok_or_absent iam delete-policy-version --policy-arn "$ARN" --version-id "$V"
  done
  ok_or_absent iam delete-policy --policy-arn "$ARN"
}

# same_document <current-json> <file>: 0 = equal JSON, 1 = different, other = error.
same_document() {
  printf '%s' "$1" | python3 -c '
import json, sys, urllib.parse
cur = json.loads(sys.stdin.read())
if isinstance(cur, str):  # URL-encoded document string
    cur = json.loads(urllib.parse.unquote(cur))
with open(sys.argv[1]) as f:
    sys.exit(0 if cur == json.load(f) else 1)
' "$2"
}

CMD=${1:-}
case "$CMD" in
  name) [ $# -eq 3 ] || usage; policy_name "$2" "$3"; exit 0 ;;
  ensure) [ $# -eq 5 ] || [ $# -eq 6 ] || usage ;;
  delete) [ $# -eq 4 ] || usage ;;
  *) usage ;;
esac
ACCT=$2; PREFIX=$3; ROLE=$4
NAME=$(policy_name "$PREFIX" "$ROLE")
ARN="arn:aws:iam::${ACCT}:policy/${NAME}"

if [ "$CMD" = delete ]; then
  delete_policy
  echo "  ✓ deleted managed policy $NAME (if it existed)"
  exit 0
fi

DOC=$5; LEGACY=${6:-}
[ -r "$DOC" ] || { echo "ERROR: policy document $DOC not readable" >&2; exit 1; }
rc=0
DEFAULT=$(iam get-policy --policy-arn "$ARN" --query 'Policy.DefaultVersionId' --output text) || rc=$?
CREATE=false
case "$rc" in
  3) CREATE=true ;;
  0)
    CURRENT=$(iam get-policy-version --policy-arn "$ARN" --version-id "$DEFAULT" \
      --query 'PolicyVersion.Document' --output json) \
      || { echo "ERROR: aws iam get-policy-version failed for $ARN" >&2; exit 1; }
    src=0; same_document "$CURRENT" "$DOC" || src=$?
    case "$src" in
      0) ;;
      1) echo "  policy $NAME differs from $(basename "$DOC"): recreating it (no CreatePolicyVersion)"
         delete_policy; CREATE=true ;;
      *) echo "ERROR: cannot compare the document of $ARN" >&2; exit 1 ;;
    esac ;;
  *) echo "ERROR: aws iam get-policy failed for $ARN" >&2; exit 1 ;;
esac
if [ "$CREATE" = true ]; then
  iam create-policy --policy-name "$NAME" --policy-document "file://$DOC" \
    --description "Scoped policy for $ROLE (task install)" >/dev/null \
    || { echo "ERROR: aws iam create-policy failed for $NAME" >&2; exit 1; }
fi
iam attach-role-policy --role-name "$ROLE" --policy-arn "$ARN" \
  || { echo "ERROR: aws iam attach-role-policy failed: $NAME -> $ROLE" >&2; exit 1; }
if [ -n "$LEGACY" ]; then
  ok_or_absent iam delete-role-policy --role-name "$ROLE" --policy-name "$LEGACY"
fi
echo "  ✓ $ROLE: managed policy $NAME"
