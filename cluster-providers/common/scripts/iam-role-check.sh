#!/bin/sh
# Read-only IAM role existence check for privilegedSteps: external.
#
#   sh iam-role-check.sh ROLE...   exit 0 when every role exists, else list what is missing
#                                  (and any read error) and exit 1. Needs only iam:GetRole.
#   IAM_ROLE_CHECK_LIB=1 . iam-role-check.sh   defines iam_role_state only.
#
# iam_role_state ROLE prints "present" or "missing" (NoSuchEntity only). Any other error
# (expired credentials, AccessDenied, throttling...) prints "error: <the CLI message>":
# a role is never reported missing because it could not be read.
iam_role_state() {
  if _irc_err=$(aws iam get-role --role-name "$1" --query 'Role.RoleName' --output text 2>&1 >/dev/null); then
    echo present
  else
    case "$_irc_err" in
      *NoSuchEntity*) echo missing ;;
      *) echo "error: $(printf '%s' "$_irc_err" | tr '\n' ' ')" ;;
    esac
  fi
}

if [ "${IAM_ROLE_CHECK_LIB:-}" != 1 ]; then
  [ "$#" -gt 0 ] || { echo "usage: sh iam-role-check.sh ROLE..." >&2; exit 2; }
  _irc_missing=""; _irc_errors=""
  for _irc_role in "$@"; do
    _irc_state=$(iam_role_state "$_irc_role")
    case "$_irc_state" in
      present) ;;
      missing) _irc_missing="$_irc_missing $_irc_role" ;;
      *) _irc_errors="${_irc_errors}    - $_irc_role: ${_irc_state#error: }
" ;;
    esac
  done
  if [ -n "$_irc_errors" ]; then
    echo "✗ could not read these IAM roles (not a missing-role problem):" >&2
    printf '%s' "$_irc_errors" >&2
  fi
  if [ -n "$_irc_missing" ]; then
    echo "✗ privilegedSteps=external but these IAM roles do not exist:" >&2
    for _irc_role in $_irc_missing; do echo "    - $_irc_role" >&2; done
    echo "  They are created by the privileged runner (task privileged:pre). This host does" >&2
    echo "  not create them in external mode." >&2
  fi
  [ -z "$_irc_errors$_irc_missing" ] || exit 1
  echo "✓ IAM roles present (verified read-only, privilegedSteps=external):$(printf ' %s' "$@")"
fi
