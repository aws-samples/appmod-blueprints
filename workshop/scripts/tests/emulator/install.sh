#!/usr/bin/env bash
# shellcheck source-path=SCRIPTDIR
# Install the PINNED AWS Emulator package and the pinned go-task and yq the job needs, into
# $EMU_WORK/bin, without root. The emulator package is checked twice: its pinned SHA-256, and
# the AWS GPG signature against the published key fingerprint (as documented in
# https://docs.aws.amazon.com/emulator/latest/userguide/getting-started-linux.html).
#
# Bumping the emulator is deliberate: it ships several releases a day and a release can change
# results. Update EMULATOR_VERSION and EMULATOR_DEB_SHA256 together, run the job, read the diff.
set -euo pipefail
# shellcheck source=lib.sh
. "$(dirname "$0")/lib.sh"

EMULATOR_VERSION=1.0.556
EMULATOR_DEB_SHA256=253dc3c5801802eac66a07a3209c0bb221b0f8d6f7bd8a88a2d18f573da026a7
# Primary key of "SSM Publishing <ssm-publishing@amazon.com>", from the page above.
EMULATOR_KEY_FPR=98BCF336A3BE53B734E967C52E5BF49BD940F624
EMULATOR_BASE=https://downloads.aws.com/aws-emulator/packages/aws-emulator/LTS
EMULATOR_KEY_URL=https://downloads.aws.com/keys/gpg/current.asc

TASK_VERSION=3.53.1
TASK_SHA256=a54a408f6861ff921f6e87774180db31bacd8c1e7c944ca696db9fea49a82fc7
YQ_VERSION=4.53.6
YQ_SHA256=c5f056448f973ae7d39b5401949648a78f2dc1947d6a8eb65be60d5c504b9385

[ "$(uname -s)-$(uname -m)" = "Linux-x86_64" ] || die "only Linux x86_64 is pinned here"

DL="${EMU_DOWNLOAD_DIR:-$EMU_WORK/download}"
BIN="$EMU_WORK/bin"
mkdir -p "$DL" "$BIN"

fetch() { # url dest: download unless a cached copy is already there (checked below anyway)
  # Download to .part then rename, so an interrupted download never poisons the cache.
  if [ ! -s "$2" ]; then
    curl -fsSL --retry 3 -o "$2.part" "$1"
    mv -f "$2.part" "$2"
  fi
}
check_sha() { # file sha256
  echo "$2  $1" | sha256sum -c --quiet - || die "SHA-256 mismatch for $1"
}

# --- AWS Emulator ---------------------------------------------------------------------------
DEB="aws-emulator_${EMULATOR_VERSION}-1_amd64.deb"
fetch "$EMULATOR_BASE/$DEB" "$DL/$DEB"
fetch "$EMULATOR_BASE/$DEB.sig" "$DL/$DEB.sig"
fetch "$EMULATOR_KEY_URL" "$DL/aws-publishing.asc"
check_sha "$DL/$DEB" "$EMULATOR_DEB_SHA256"

GNUPGHOME="$EMU_WORK/gnupg"; export GNUPGHOME
mkdir -p "$GNUPGHOME"; chmod 700 "$GNUPGHOME"
# gpg exits 2 on a fresh keyring when it cannot start gpg-agent (minimal gnupg installs) even
# though the key was imported, so judge the import by the keyring content, not the exit code.
gpg --batch --quiet --import "$DL/aws-publishing.asc" || true
gpg --batch --with-colons --list-keys "$EMULATOR_KEY_FPR" 2>/dev/null | grep -q "^fpr:*$EMULATOR_KEY_FPR:" \
  || die "key $EMULATOR_KEY_FPR is not in $EMULATOR_KEY_URL: the published key changed, check the docs before bumping"
# VALIDSIG's last field is the PRIMARY key fingerprint, also when a subkey made the signature.
# `|| true`: a BAD signature makes gpg exit non-zero; let the explicit check below report it.
VALID=$(gpg --batch --status-fd 1 --verify "$DL/$DEB.sig" "$DL/$DEB" 2>/dev/null | awk '$2 == "VALIDSIG" {print $NF}' || true)
[ "$VALID" = "$EMULATOR_KEY_FPR" ] || die "GPG signature of $DEB is not valid for key $EMULATOR_KEY_FPR (got '${VALID:-none}')"
log "emulator package $DEB: SHA-256 and GPG signature OK"

PKG="$EMU_WORK/pkg"
mkdir -p "$PKG"
if command -v dpkg-deb >/dev/null; then
  dpkg-deb -x "$DL/$DEB" "$PKG"
else
  ar p "$DL/$DEB" data.tar.xz | tar -xJ -C "$PKG"
fi
ln -sf "$PKG/opt/aws-emulator/bin/aws-emulator" "$BIN/aws-emulator"
V=$("$BIN/aws-emulator" -v)
grep -qx "Version: $EMULATOR_VERSION" <<<"$V" || die "extracted emulator is not $EMULATOR_VERSION: $V"

# --- go-task and yq (the Taskfile's enable-capability-logs runs under go-task and reads yq) ---
fetch "https://github.com/go-task/task/releases/download/v$TASK_VERSION/task_linux_amd64.tar.gz" "$DL/task-$TASK_VERSION.tar.gz"
check_sha "$DL/task-$TASK_VERSION.tar.gz" "$TASK_SHA256"
tar -xzf "$DL/task-$TASK_VERSION.tar.gz" -C "$BIN" task
fetch "https://github.com/mikefarah/yq/releases/download/v$YQ_VERSION/yq_linux_amd64" "$DL/yq-$YQ_VERSION"
check_sha "$DL/yq-$YQ_VERSION" "$YQ_SHA256"
install -m 0755 "$DL/yq-$YQ_VERSION" "$BIN/yq"
log "installed into $BIN: aws-emulator $EMULATOR_VERSION, task $TASK_VERSION, yq $YQ_VERSION"
