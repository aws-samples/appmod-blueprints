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

# Per cluster: hub ACTIVE; spoke-dev CREATING on the first describe then ACTIVE;
# spoke-prod CREATING forever; spoke-deg DEGRADED; spoke-none has no capability;
# spoke-err gets an expired-token error. Like the real API, put-delivery-source fails
# with a ConflictException (exit 254) when the capability's last status was not
# ACTIVE/DEGRADED.
FAKE_AWS = r"""#!/usr/bin/env bash
echo "$*" >> "$FAKE_AWS_LOG"
val() { prev=""; for a in "$@"; do [ "$prev" = "$KEY" ] && { echo "$a"; return; }; prev="$a"; done; }
case "$1 $2" in
  "sts get-caller-identity") echo 111122223333 ;;
  "eks list-clusters")
    printf 'acme-hub\tacme-spoke-dev\tacme-spoke-prod\tacme-spoke-deg\tacme-spoke-none\tacme-spoke-err\n' ;;
  "eks describe-capability")
    C=$(KEY=--cluster-name val "$@")
    N=$(grep -c "describe-capability --cluster-name $C " "$FAKE_AWS_LOG")
    case "$C" in
      acme-spoke-none) echo "An error occurred (ResourceNotFoundException) when calling the DescribeCapability operation" >&2; exit 254 ;;
      acme-spoke-err) echo "An error occurred (ExpiredTokenException) when calling the DescribeCapability operation" >&2; exit 254 ;;
      acme-spoke-prod) S=CREATING ;;
      acme-spoke-deg) S=DEGRADED ;;
      acme-spoke-dev) if [ "$N" -le 1 ]; then S=CREATING; else S=ACTIVE; fi ;;
      *) S=ACTIVE ;;
    esac
    echo "$S" > "$FAKE_STATE/$C"
    printf 'arn:aws:eks:us-west-2:111122223333:capability/%s/kro\t%s\n' "$C" "$S" ;;
  "logs put-delivery-source")
    N=$(KEY=--name val "$@"); C=${N%-kro}
    case "$(cat "$FAKE_STATE/$C" 2>/dev/null)" in
      ACTIVE|DEGRADED) echo ok ;;
      *) echo "An error occurred (ConflictException) when calling the PutDeliverySource operation: Capability kro cannot be updated as it is currently in CREATING state" >&2; exit 254 ;;
    esac ;;
  "logs describe-delivery-sources"|"logs describe-deliveries") echo None ;;
  "logs describe-delivery-destinations") echo arn:dest ;;
  *) echo ok ;;
esac
"""


def _run(tmp_path, wait):
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
    state = tmp_path / "state"
    state.mkdir()
    log = tmp_path / "calls.log"
    log.write_text("")
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", FAKE_AWS_LOG=str(log),
               FAKE_STATE=str(state), HOME=str(tmp_path), CAP_LOGS_WAIT=wait)
    for k in ("AWS_PROFILE", "AWS_CONFIG_FILE", "AWS_DEFAULT_PROFILE", "KUBECONFIG"):
        env.pop(k, None)
    res = subprocess.run([TASK, "-d", str(r), "enable-capability-logs"], env=env,
                         capture_output=True, text=True, timeout=120)
    sources = [l for l in log.read_text().splitlines() if l.startswith("logs put-delivery-source")]
    return res, res.stdout + res.stderr, sources


def _delivered(sources, cluster):
    return any(f"--name {cluster}-kro " in l for l in sources)


def test_waits_for_creating_and_skips_never_active(tmp_path):
    res, out, sources = _run(tmp_path, "45")
    assert res.returncode == 0, out
    assert _delivered(sources, "acme-hub"), out
    assert _delivered(sources, "acme-spoke-dev"), out   # waited CREATING -> ACTIVE
    assert _delivered(sources, "acme-spoke-deg"), out   # DEGRADED still gets logs
    assert not _delivered(sources, "acme-spoke-prod"), out
    assert "acme-spoke-prod: 'kro' capability is CREATING after 45s" in out, out
    assert "acme-spoke-none: no 'kro' capability" in out, out
    # an expired token is reported as an error, not as "no capability"
    assert "WARN acme-spoke-err: describe-capability failed (rc=254)" in out, out
    assert "ExpiredTokenException" in out, out
    assert "acme-spoke-err: no 'kro' capability" not in out, out


def test_non_numeric_wait_falls_back_to_default(tmp_path):
    res, out, sources = _run(tmp_path, "abc")
    assert res.returncode == 0, out
    assert "CAP_LOGS_WAIT='abc' is not a number of seconds" in out, out
    assert "acme-spoke-prod: 'kro' capability is CREATING after 600s" in out, out
