#!/usr/bin/env bash
# pivot-overlay-git.sh — credential-safe git access to the consumer's overlay repo for
# `hub:pivot` (#1033).
#
# WHY: the overlay credential (the PAT the consumer registered in argocd/fleet-config-repo)
# must NEVER appear on a git command line (visible in `ps` / /proc/<pid>/cmdline) and must
# NEVER be persisted (remote.origin.url in .git/config, or a credential helper store).
# Every git operation here therefore:
#   - targets a credential-free https URL;
#   - gets the username via `-c credential.username=` (default x-access-token) and the
#     password out-of-band via GIT_ASKPASS, from a 0700 temp file that only echoes an
#     environment variable (the secret is never written to disk) and is removed by a trap;
#   - clears every inherited credential helper (`-c credential.helper=`) so a user-level
#     `store`/`cache` helper never saves the PAT after a successful auth;
#   - uses `git -c` (process-scoped) rather than `git clone -c` (which would write the
#     key into the clone's .git/config).
#
# USAGE (the secret is passed in the ENVIRONMENT, never as an argument):
#   OVERLAY_GIT_PASSWORD=<pat> [OVERLAY_GIT_USERNAME=<user>] \
#     pivot-overlay-git.sh probe   <https-url>
#   OVERLAY_GIT_PASSWORD=<pat> [OVERLAY_GIT_USERNAME=<user>] \
#     pivot-overlay-git.sh publish <https-url> <revision> <rel-dir> <src-file> <dest-name> <commit-msg>
#
#   probe   : exit 0 iff `git ls-remote` succeeds with the credential.
#   publish : ls-remote, single-branch clone of <revision>, copy <src-file> to
#             <rel-dir>/<dest-name>, commit (a no-op commit is tolerated), push HEAD to
#             <revision>. Exit 0 iff the push succeeded. All git output is silenced;
#             only this script's own refusals (die) reach stderr.
set -euo pipefail

die() { printf 'pivot-overlay-git: %s\n' "$*" >&2; exit 2; }

[ $# -ge 2 ] || die "usage: $0 probe|publish <https-url> ..."
MODE=$1; URL=$2; shift 2
[ -n "${OVERLAY_GIT_PASSWORD:-}" ] || die "OVERLAY_GIT_PASSWORD is not set"
case "$URL" in
  https://*@*) die "refusing a URL that embeds credentials" ;;
  https://*) ;;
  *) die "overlay URL must be https://" ;;
esac
GIT_USER=${OVERLAY_GIT_USERNAME:-x-access-token}

ASKPASS=""; REPO_DIR=""
cleanup() {
  [ -n "$ASKPASS" ] && rm -f "$ASKPASS"
  [ -n "$REPO_DIR" ] && rm -rf "$REPO_DIR"
  return 0
}
trap cleanup EXIT
ASKPASS=$(mktemp)
# Single-quoted: the file holds the literal text "$OVERLAY_GIT_PASSWORD", not the secret.
# shellcheck disable=SC2016
printf '#!/bin/sh\nexec printf "%%s\\n" "$OVERLAY_GIT_PASSWORD"\n' > "$ASKPASS"
chmod 700 "$ASKPASS"
export OVERLAY_GIT_PASSWORD

ogit() {
  GIT_ASKPASS="$ASKPASS" GIT_TERMINAL_PROMPT=0 \
    git -c credential.helper= -c credential.username="$GIT_USER" "$@"
}

case "$MODE" in
  probe)
    ogit ls-remote "$URL" >/dev/null 2>&1
    ;;
  publish)
    [ $# -eq 5 ] || die "usage: $0 publish <https-url> <revision> <rel-dir> <src-file> <dest-name> <commit-msg>"
    REV=$1; REL_DIR=$2; SRC=$3; DEST=$4; MSG=$5
    [ -s "$SRC" ] || die "source manifest missing or empty: $SRC"
    ogit ls-remote "$URL" >/dev/null 2>&1 || exit 1
    REPO_DIR=$(mktemp -d)
    # The clone records the credential-free URL as remote.origin.url.
    ogit clone --branch "$REV" --single-branch "$URL" "$REPO_DIR/repo" >/dev/null 2>&1 || exit 1
    [ -d "$REPO_DIR/repo/.git" ] || exit 1
    cd "$REPO_DIR/repo"
    mkdir -p "$REL_DIR"
    cp "$SRC" "$REL_DIR/$DEST"
    git add -A
    git -c user.email=pivot@peeks.local -c user.name=peeks-pivot \
      commit -m "$MSG" >/dev/null 2>&1 || true
    ogit push origin "HEAD:$REV" >/dev/null 2>&1
    ;;
  *) die "unknown mode: $MODE" ;;
esac
