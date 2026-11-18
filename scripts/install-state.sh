#!/bin/sh
# Record where a remote install (task workshop:install:remote, run in CodeBuild) is, in the
# SSM parameter /<resourcePrefix>/install-state, so the host that follows it (the IDE, see
# scripts/install-remote-wait.sh) and the CloudFormation InitScriptStatus output can read it.
#
#   install-state.sh "RUNNING step=hub:seed"     writes "RUNNING step=hub:seed <utc>"
#
# Best effort by design: a status write that fails must never fail the install. The prefix is
# RESOURCE_PREFIX, else resourcePrefix of the config (CONFIG_FILE, else <repo>/config.local.yaml).
# shortcut: values are written as-is (String parameter, <= 4096 chars); keep them short.
CFG="${CONFIG_FILE:-$(dirname "$0")/../config.local.yaml}"
PREFIX="${RESOURCE_PREFIX:-$(yq '.resourcePrefix // ""' "$CFG" 2>/dev/null)}"
[ -n "$PREFIX" ] && [ "$PREFIX" != "null" ] || { echo "install-state: no resource prefix, state not recorded" >&2; exit 0; }
VALUE="$* $(date -u +%Y-%m-%dT%H:%M:%SZ)"
aws ssm put-parameter --name "/$PREFIX/install-state" --type String --overwrite \
  --cli-connect-timeout 5 --cli-read-timeout 15 --value "$VALUE" >/dev/null 2>&1 \
  || echo "install-state: could not write /$PREFIX/install-state" >&2
exit 0
