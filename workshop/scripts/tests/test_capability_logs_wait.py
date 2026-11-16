"""Hermetic go-task test: `task enable-capability-logs` waits for a capability that is
still CREATING (spokes created just before install:complete) instead of failing the
install on put-delivery-source's ConflictException, and skips one that never gets ACTIVE.

Run:  python -m pytest workshop/scripts/tests/test_capability_logs_wait.py -q
"""
import os
import shutil
import subprocess

import pytest

TASK = shutil.which("task")
if not TASK:
    pytest.skip("go-task not on PATH", allow_module_level=True)

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

# acme-hub ACTIVE; acme-spoke-dev CREATING on the first describe then ACTIVE;
# acme-spoke-prod CREATING forever. put-delivery-source fails like the real API on a
# non-ACTIVE capability.
FAKE_AWS = r"""#!/usr/bin/env bash
echo "$*" >> "$FAKE_AWS_LOG"
case "$1 $2" in
  "sts get-caller-identity") echo 111122223333 ;;
  "eks list-clusters") printf 'acme-hub\tacme-spoke-dev\tacme-spoke-prod\n' ;;
  "eks describe-capability")
    C=$(prev=""; for a in "$@"; do [ "$prev" = "--cluster-name" ] && echo "$a"; prev="$a"; done)
    N=$(grep -c "describe-capability --cluster-name $C " "$FAKE_AWS_LOG")
    S=ACTIVE
    [ "$C" = acme-spoke-prod ] && S=CREATING
    [ "$C" = acme-spoke-dev ] && [ "$N" -le 1 ] && S=CREATING
    printf 'arn:aws:eks:us-west-2:111122223333:capability/%s/kro\t%s\n' "$C" "$S" ;;
  "logs describe-delivery-sources"|"logs describe-deliveries") echo None ;;
  "logs describe-delivery-destinations") echo arn:dest ;;
  *) echo ok ;;
esac
"""


def test_waits_for_creating_and_skips_never_active(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    shutil.copy(os.path.join(REPO, "Taskfile.yaml"), r / "Taskfile.yaml")
    shutil.copytree(os.path.join(REPO, "cluster-providers"), r / "cluster-providers")
    (r / "scripts").mkdir()
    shutil.copy(os.path.join(REPO, "scripts", "install-timing.sh"), r / "scripts" / "install-timing.sh")
    shutil.copytree(os.path.join(REPO, "gitops", "addons", "registry"), r / "gitops" / "addons" / "registry")
    (r / "workshop").mkdir()
    shutil.copy(os.path.join(REPO, "workshop", "Taskfile.yaml"), r / "workshop" / "Taskfile.yaml")
    (r / "config.local.yaml").write_text(
        "clusterProvider: kind-kro-ack\nresourcePrefix: acme\naws: {region: us-west-2}\n")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name, body in (("aws", FAKE_AWS), ("sleep", "#!/bin/sh\nexit 0\n")):
        (bindir / name).write_text(body)
        (bindir / name).chmod(0o755)
    log = tmp_path / "calls.log"
    log.write_text("")
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", FAKE_AWS_LOG=str(log),
               HOME=str(tmp_path), CAP_LOGS_WAIT="45")
    for k in ("AWS_PROFILE", "AWS_CONFIG_FILE", "AWS_DEFAULT_PROFILE", "KUBECONFIG"):
        env.pop(k, None)
    res = subprocess.run([TASK, "-d", str(r), "enable-capability-logs"], env=env,
                         capture_output=True, text=True, timeout=120)
    out = res.stdout + res.stderr
    assert res.returncode == 0, out
    sources = [l for l in log.read_text().splitlines() if l.startswith("logs put-delivery-source")]
    assert any("--name acme-hub-kro " in l for l in sources), out
    assert any("--name acme-spoke-dev-kro " in l for l in sources), out
    assert not any("acme-spoke-prod" in l for l in sources), out
    assert "acme-spoke-prod: 'kro' capability is CREATING after 45s" in out, out
