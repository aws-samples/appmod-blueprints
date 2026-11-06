"""Hermetic test for install perf R2: wait-for-spokes asks ESO to reconcile the spoke's
fleet-secret ExternalSecret while the Argo CD cluster secret is missing.

The fake `kubectl` models ESO's error backoff: the cluster secret appears on its own only
after BACKOFF_POLLS polls (default 20 polls = 5 min of 15 s polls, the order seen live), or
on the next poll after a force-sync annotation. `aws` reports every spoke ACTIVE and
`sleep` is a no-op. No cluster.

Run:  python -m pytest workshop/scripts/tests/test_install_r2_spoke_secret_kick.py -q
"""
import os
import re
import shutil
import subprocess

import pytest

yaml = pytest.importorskip("yaml")
if not shutil.which("bash"):
    pytest.skip("bash not available", allow_module_level=True)

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
TASKFILE = os.path.join(REPO, "workshop", "Taskfile.yaml")


def block(text=None):
    t = yaml.safe_load(text if text is not None else open(TASKFILE))["tasks"]["wait-for-spokes"]
    b = t["cmds"][0]
    b = (b.replace("{{.SPOKES}}", "p-spoke-dev p-spoke-prod").replace("{{.HUB_CLUSTER_NAME}}", "hub")
          .replace("{{.AWS_REGION}}", "r").replace("{{.MARK}}", "true"))
    return re.sub(r"\{\{\s*\.C_[A-Z]+\s*\}\}", "", b)


def run(tmp_path, b, backoff_polls=20, eso_alive=True):
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    (bin_ / "aws").write_text(
        '#!/usr/bin/env bash\ncase "$*" in *describe-cluster*) echo ACTIVE;; esac\nexit 0\n')
    (bin_ / "kubectl").write_text(
        '#!/usr/bin/env bash\n'
        'case "$*" in\n'
        '  *"annotate externalsecret fleet-secret-"*)\n'
        '     A="$*"; S=${A##*fleet-secret-}; S=${S%% *}; echo "$S" >> "$T/annotated"; exit 0;;\n'
        '  *"get secret"*)\n'
        '     N=$(cat "$T/polls" 2>/dev/null || echo 0); N=$((N+1)); echo $N > "$T/polls"\n'
        '     for S in p-spoke-dev p-spoke-prod; do\n'
        f'       if [ "$N" -gt {backoff_polls} ] || grep -qx "$S" "$T/seen" 2>/dev/null; then echo "$S"; fi\n'
        '     done\n'
        '     # a force-sync done since the last poll makes ESO write the secret now\n'
        f'     [ "{1 if eso_alive else 0}" = 1 ] && [ -f "$T/annotated" ] && sort -u "$T/annotated" > "$T/seen"\n'
        '     exit 0;;\n'
        'esac\nexit 0\n')
    (bin_ / "sleep").write_text("#!/usr/bin/env bash\nexit 0\n")
    for f in ("aws", "kubectl", "sleep"):
        os.chmod(bin_ / f, 0o755)
    env = dict(os.environ, PATH=f"{bin_}:{os.environ['PATH']}", T=str(tmp_path))
    r = subprocess.run(["bash", "-c", b], env=env, capture_output=True, text=True, timeout=60)
    polls = int((tmp_path / "polls").read_text())
    ann = (tmp_path / "annotated").read_text().split() if (tmp_path / "annotated").exists() else []
    return r, polls, ann


def test_force_sync_gets_both_secrets_in_three_polls(tmp_path):
    r, polls, ann = run(tmp_path, block())
    assert r.returncode == 0, r.stderr
    assert "not registered" not in r.stdout
    # per spoke: poll 1 missing -> annotate; ESO writes during the next interval; present
    # by poll 3. So 3 polls (30 s) per spoke, against BACKOFF_POLLS (5 min) without it.
    assert polls == 6, (polls, r.stdout)
    assert ann == ["p-spoke-dev", "p-spoke-prod"]


def test_no_annotation_once_secret_is_present(tmp_path):
    r, polls, ann = run(tmp_path, block(), backoff_polls=0)
    assert r.returncode == 0
    assert ann == []
    assert polls == 2


def test_annotates_every_30s_while_missing(tmp_path):
    # ESO never writes the secret: each spoke runs its 60 polls, annotated on the odd ones.
    r, polls, ann = run(tmp_path, block(), backoff_polls=10_000, eso_alive=False)
    assert r.returncode == 0
    assert polls == 120
    assert ann.count("p-spoke-dev") == 30 and ann.count("p-spoke-prod") == 30
    assert r.stdout.count("not registered") == 2
