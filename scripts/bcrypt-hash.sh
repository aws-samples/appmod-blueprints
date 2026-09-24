#!/usr/bin/env bash
#
# Print a bcrypt hash of a password on stdout, or fail with guidance on stderr.
#
# WHY THIS IS A SCRIPT AND NOT INLINE SHELL: the same hash is needed at four
# places (seed-secrets + seed-observability, in both the kind-kro-ack and
# kind-crossplane providers). Those four copies had already drifted apart in
# their fallback order, their messages and their failure behaviour. One
# implementation with one error path replaces them; callers get the correct
# behaviour for free from errexit because this script exits non-zero rather than
# printing an empty hash.
#
# WHY IT MUST NEVER PRINT AN EMPTY HASH: Kargo authenticates admin logins
# against this value. An empty string is synced faithfully by ESO (which
# correctly reports SecretSynced=True), so the platform looks healthy while
# admin login is broken, and a workshop participant cannot recompute it. Failing
# here is recoverable — the seed tasks are idempotent, so the operator installs
# a prerequisite and re-runs.
#
# Usage:  bcrypt-hash.sh <plaintext-password>
# Output: the hash on stdout; diagnostics on stderr; non-zero exit on failure.

set -euo pipefail

PASS="${1:-}"
if [ -z "$PASS" ]; then
  echo "bcrypt-hash.sh: no password given" >&2
  exit 2
fi

# 1. htpasswd -B: bcrypt with no interpreter and no package management at all.
#    Preferred because it cannot be broken by Python environment drift.
#    htpasswd emits the $2y$ variant; Go's bcrypt (used by Kargo) wants $2a$.
if command -v htpasswd >/dev/null 2>&1; then
  htpasswd -bnBC 10 "" "$PASS" | tr -d ':\n' | sed 's/^\$2y\$/\$2a\$/'
  exit 0
fi

# 2. An already-importable bcrypt module.
# 3. Failing that, install it with `python3 -m pip` — the form is the point.
#    Bare `pip` routinely resolves to a DIFFERENT interpreter than `python3`
#    (a common Homebrew state is pip -> 3.11 while python3 -> 3.14), so
#    `pip install bcrypt` followed by `python3 -c "import bcrypt"` installs into
#    one interpreter and imports from another and fails with ModuleNotFoundError.
#    `python3 -m pip` always targets the interpreter that will do the import.
if ! python3 -c 'import bcrypt' >/dev/null 2>&1; then
  echo "bcrypt-hash.sh: bcrypt not importable, installing it for this interpreter (python3 -m pip)" >&2
  # --user covers PEP 668 "externally managed environment" setups where a plain
  # install into the system interpreter is refused.
  python3 -m pip install --quiet bcrypt >/dev/null 2>&1 \
    || python3 -m pip install --quiet --user bcrypt >/dev/null 2>&1 \
    || true
fi

if python3 -c 'import bcrypt' >/dev/null 2>&1; then
  python3 -c 'import bcrypt,sys; print(bcrypt.hashpw(sys.argv[1].encode(), bcrypt.gensalt(rounds=10)).decode())' "$PASS"
  exit 0
fi

cat >&2 <<'EOF'
✗ Cannot compute a bcrypt hash: htpasswd is not installed and the bcrypt module
  could not be imported or installed for python3.

  Install ONE of the following, then re-run (the seed tasks are idempotent and
  every other secret is already seeded):

    apt-get install apache2-utils     # Debian/Ubuntu  -> htpasswd
    yum install httpd-tools           # Amazon Linux/RHEL -> htpasswd
    brew install httpd                # macOS -> htpasswd
    python3 -m pip install bcrypt     # note: python3 -m pip, NOT bare pip

  Not failing here would write an EMPTY hash, which silently breaks Kargo admin
  login while every health check still reports success.
EOF
exit 1
