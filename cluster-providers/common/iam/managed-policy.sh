#!/bin/sh
# Scoped customer-managed IAM policy for a role that `task install` creates.
#
#   managed-policy.sh ensure <account-id> <prefix> <role> <document.json>
#   managed-policy.sh delete <account-id> <prefix> <role>
#   managed-policy.sh name   <prefix> <role>
#
# Policy name: "<role>-scoped" (the base name). It gets a "<prefix>-" in front when the role
# name does not already start with it, so the policy always matches policy/<prefix>-*. That is
# the pattern consumers grant IAM writes on (e.g. the PEEKS instance role), and the one the
# prefix-based teardown sweeps delete. When the document changes, the new document is created
# under a second name, "<base>-<sha8>" (first 8 hex digits of the SHA-256 of the canonical
# document), or under the base name again when that one is free.
#
# ensure: idempotent. Every error other than NoSuchEntity is fatal (exit 1). The scoped
# policies of the role are the policies named <base> or <base>-<8 hex> that exist or are
# attached to it.
#   one has the desired document -> AttachRolePolicy (a no-op when already attached), then
#                                   delete the others
#   none has it                  -> CreatePolicy under the free name, AttachRolePolicy, then
#                                   delete the others (detach, non-default versions, delete)
#   The new policy is attached before the old one is detached, so the role always holds a
#   scoped policy. A failed CreatePolicy or AttachRolePolicy changes nothing on the old one. A
#   failed delete of an old one (e.g. DeleteConflict: still attached to another role) attaches
#   it again if it was attached to the role, and fails, so the next run sees it and retries.
#   CreatePolicyVersion is NOT used on purpose: a consumer may grant CreatePolicy and
#   DeletePolicy on policy/<prefix>-* but not CreatePolicyVersion (PEEKS does not).
# delete: for each scoped policy of <role>: DetachRolePolicy from <role>, DeletePolicyVersion
#   (each non-default), DeletePolicy. NoSuchEntity is success. Only <role> is detached: a
#   policy still attached elsewhere makes DeletePolicy fail (DeleteConflict) instead of being
#   torn off another role. A "<base>-<sha8>" policy that is no longer attached to <role> is
#   left to the prefix-based sweeps.
set -eu

usage() { echo "usage: $0 ensure <account-id> <prefix> <role> <document.json> | delete <account-id> <prefix> <role> | name <prefix> <role>" >&2; exit 2; }

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

arn_of() { echo "arn:aws:iam::${ACCT}:policy/$1"; }

# is_scoped <name>: the base name, or the base name plus "-" and 8 hex digits.
is_scoped() {
  case "$1" in
    "$BASE") return 0 ;;
    "$BASE"-[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]) return 0 ;;
  esac
  return 1
}

# attached_scoped: names of the scoped policies attached to $ROLE, one per line (run it in
# $(...) || exit 1). Role absent -> error (ensure) or nothing (delete). Read denied -> fatal in delete; in ensure a warning,
# and only the names probed directly (base and second name) are seen.
attached_scoped() {
  rc=0
  OUT=$(iam list-attached-role-policies --role-name "$ROLE" \
    --query 'AttachedPolicies[].PolicyArn' --output text) || rc=$?
  if [ "$rc" -eq 3 ]; then
    [ "$CMD" = delete ] && return 0
    echo "ERROR: role $ROLE does not exist" >&2; exit 1
  fi
  if [ "$rc" -ne 0 ]; then
    if [ "$CMD" = delete ]; then echo "ERROR: aws iam list-attached-role-policies failed for $ROLE" >&2; exit 1; fi
    echo "  ⚠ could not list the policies attached to $ROLE: an older scoped policy under another name may stay attached" >&2
    return 0
  fi
  for A in $(printf '%s' "$OUT" | tr '\t' ' '); do
    N=${A##*/}
    if is_scoped "$N"; then echo "$N"; fi
  done
}

# exists <name>: 0 = exists, 1 = absent; other errors are fatal.
exists() {
  rc=0; iam get-policy --policy-arn "$(arn_of "$1")" --query 'Policy.Arn' --output text >/dev/null || rc=$?
  case "$rc" in 0) return 0 ;; 3) return 1 ;; esac
  echo "ERROR: aws iam get-policy failed for $(arn_of "$1")" >&2; exit 1
}

# ok_or_absent <name> <cmd...>: success or NoSuchEntity -> 0, any other error -> 1.
ok_or_absent() {
  _n=$1; shift
  rc=0; "$@" >/dev/null || rc=$?
  [ "$rc" -eq 0 ] || [ "$rc" -eq 3 ] || { echo "ERROR: aws iam $2 failed for $(arn_of "$_n")" >&2; return 1; }
}

delete_policy() {  # delete_policy <name>: detach from $ROLE, delete non-default versions, delete
  P=$(arn_of "$1")
  ok_or_absent "$1" iam detach-role-policy --role-name "$ROLE" --policy-arn "$P" || return 1
  rc=0
  # shellcheck disable=SC2016  # JMESPath backticks, not a shell expansion
  VERSIONS=$(iam list-policy-versions --policy-arn "$P" \
    --query 'Versions[?IsDefaultVersion==`false`].VersionId' --output text) || rc=$?
  [ "$rc" -eq 3 ] && return 0
  [ "$rc" -eq 0 ] || { echo "ERROR: aws iam list-policy-versions failed for $P" >&2; return 1; }
  for V in $VERSIONS; do
    [ "$V" = None ] && continue
    ok_or_absent "$1" iam delete-policy-version --policy-arn "$P" --version-id "$V" || return 1
  done
  ok_or_absent "$1" iam delete-policy --policy-arn "$P"
}

# same_document <current-json> <file>: 0 = equal JSON, 1 = different, 2 = error. Any
# exception (unparseable current document, empty output, unreadable or invalid file) is 2,
# never 1: "different" makes the old policy a candidate for deletion.
same_document() {
  printf '%s' "$1" | python3 -c '
import json, sys, urllib.parse
try:
    cur = json.loads(sys.stdin.read())
    if isinstance(cur, str):  # URL-encoded document string
        cur = json.loads(urllib.parse.unquote(cur))
    with open(sys.argv[1]) as f:
        want = json.load(f)
except Exception as e:
    sys.stderr.write("cannot compare policy documents: %s\n" % e)
    sys.exit(2)
sys.exit(0 if cur == want else 1)
' "$2"
}

# has_document <name>: 0 = its default version is $DOC, 1 = another document; errors are fatal.
has_document() {
  P=$(arn_of "$1")
  DEFAULT=$(iam get-policy --policy-arn "$P" --query 'Policy.DefaultVersionId' --output text) \
    || { echo "ERROR: aws iam get-policy failed for $P" >&2; exit 1; }
  CURRENT=$(iam get-policy-version --policy-arn "$P" --version-id "$DEFAULT" \
    --query 'PolicyVersion.Document' --output json) \
    || { echo "ERROR: aws iam get-policy-version failed for $P" >&2; exit 1; }
  src=0; same_document "$CURRENT" "$DOC" || src=$?
  case "$src" in
    0) return 0 ;;
    1) return 1 ;;
  esac
  echo "ERROR: cannot compare the document of $P" >&2; exit 1
}

CMD=${1:-}
case "$CMD" in
  name) [ $# -eq 3 ] || usage; policy_name "$2" "$3"; exit 0 ;;
  ensure) [ $# -eq 5 ] || usage ;;
  delete) [ $# -eq 4 ] || usage ;;
  *) usage ;;
esac
ACCT=$2; PREFIX=$3; ROLE=$4
BASE=$(policy_name "$PREFIX" "$ROLE")

if [ "$CMD" = delete ]; then
  NAMES=$(attached_scoped) || exit 1
  if exists "$BASE"; then NAMES="$NAMES $BASE"; fi
  DONE=" "
  for N in $NAMES; do
    case "$DONE" in *" $N "*) continue ;; esac
    DONE="$DONE$N "
    delete_policy "$N" || exit 1
    echo "  ✓ deleted managed policy $N"
  done
  exit 0
fi

DOC=$5
# Validate the desired document before any AWS call: a broken file must stop here.
SHA8=$(python3 -c '
import hashlib, json, sys
doc = json.load(open(sys.argv[1]))
print(hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:8])
' "$DOC" 2>/dev/null) || { echo "ERROR: policy document $DOC is not readable JSON" >&2; exit 1; }
ALT="$BASE-$SHA8"
# IAM policy names are at most 128 characters.
[ "${#ALT}" -le 128 ] || { echo "ERROR: policy name $ALT is longer than 128 characters" >&2; exit 1; }

# Candidates, the second name first: it can only hold this exact document.
CANDS=""
if exists "$ALT"; then CANDS="$ALT"; fi
BASE_EXISTS=false
if exists "$BASE"; then BASE_EXISTS=true; CANDS="$CANDS $BASE"; fi
ATT=$(attached_scoped) || exit 1
CANDS="$CANDS $ATT"
OLD=""; KEEP=""; SEEN=" "
for N in $CANDS; do
  case "$SEEN" in *" $N "*) continue ;; esac
  SEEN="$SEEN$N "
  if [ -z "$KEEP" ] && has_document "$N"; then KEEP=$N; else OLD="$OLD $N"; fi
done

if [ -z "$KEEP" ]; then
  if [ "$BASE_EXISTS" = false ]; then KEEP=$BASE; else KEEP=$ALT; fi
  case " $OLD " in *" $KEEP "*)
    echo "ERROR: policy $KEEP exists with another document; delete it and re-run" >&2; exit 1 ;;
  esac
  [ -z "$OLD" ] || echo "  policy document changed: creating $KEEP, then removing$OLD"
  iam create-policy --policy-name "$KEEP" --policy-document "file://$DOC" \
    --description "Scoped policy for $ROLE (task install)" >/dev/null \
    || { echo "ERROR: aws iam create-policy failed for $KEEP" >&2; exit 1; }
fi
iam attach-role-policy --role-name "$ROLE" --policy-arn "$(arn_of "$KEEP")" \
  || { echo "ERROR: aws iam attach-role-policy failed: $KEEP -> $ROLE" >&2; exit 1; }
for N in $OLD; do
  if ! delete_policy "$N"; then
    # If it was attached to the role, attach it again so the next run sees it (it may be
    # under a name it cannot probe). One that was not attached is found by name again.
    case " $(printf '%s' "$ATT" | tr '\n' ' ') " in *" $N "*)
      iam attach-role-policy --role-name "$ROLE" --policy-arn "$(arn_of "$N")" >/dev/null 2>&1 || true ;;
    esac
    echo "ERROR: could not remove the older scoped policy $N from $ROLE ($KEEP is attached); re-run after fixing it" >&2
    exit 1
  fi
done
echo "  ✓ $ROLE: managed policy $KEEP"
