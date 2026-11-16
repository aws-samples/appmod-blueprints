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
    echo "$FAKE_CLUSTERS" ;;
  "eks describe-capability")
    C=$(KEY=--cluster-name val "$@")
    N=$(grep -c "describe-capability --cluster-name $C " "$FAKE_AWS_LOG")
    case "$C" in
      acme-spoke-none) echo "An error occurred (ResourceNotFoundException) when calling the DescribeCapability operation" >&2; exit 254 ;;
      acme-spoke-err) echo "An error occurred (ExpiredTokenException) when calling the DescribeCapability operation" >&2; exit 254 ;;
      acme-spoke-prod|acme-spoke-prod2) S=CREATING ;;
      acme-spoke-deg) S=DEGRADED ;;
      acme-spoke-dev) if [ "$N" -le 1 ]; then S=CREATING; else S=ACTIVE; fi ;;
      acme-spoke-upd) if [ "$N" -le 1 ]; then S=UPDATING; else S=ACTIVE; fi ;;
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

ALL = "acme-hub acme-spoke-dev acme-spoke-upd acme-spoke-prod acme-spoke-deg acme-spoke-none acme-spoke-err"


def _run(tmp_path, wait, clusters=ALL, timeout=120):
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
    # the fake sleep records each nap so the tests can pin that the wait really sleeps
    for name, body in (("aws", FAKE_AWS), ("sleep", '#!/bin/sh\necho "$1" >> "$FAKE_SLEEP_LOG"\n')):
        (bindir / name).write_text(body)
        (bindir / name).chmod(0o755)
    tmpd = tmp_path / "tmp"
    tmpd.mkdir()
    state = tmp_path / "state"
    state.mkdir()
    log = tmp_path / "calls.log"
    log.write_text("")
    naps = tmp_path / "sleeps.log"
    naps.write_text("")
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", FAKE_AWS_LOG=str(log), FAKE_SLEEP_LOG=str(naps),
               FAKE_STATE=str(state), FAKE_CLUSTERS=clusters, HOME=str(tmp_path), TMPDIR=str(tmpd), CAP_LOGS_WAIT=wait)
    for k in ("AWS_PROFILE", "AWS_CONFIG_FILE", "AWS_DEFAULT_PROFILE", "KUBECONFIG"):
        env.pop(k, None)
    res = subprocess.run([TASK, "-d", str(r), "enable-capability-logs"], env=env,
                         capture_output=True, text=True, timeout=timeout)
    sources = [l for l in log.read_text().splitlines() if l.startswith("logs put-delivery-source")]
    return res, res.stdout + res.stderr, sources


def _naps(tmp_path):
    return (tmp_path / "sleeps.log").read_text().split()


def _delivered(sources, cluster):
    return any(f"--name {cluster}-kro " in l for l in sources)


def test_waits_for_creating_and_skips_never_active(tmp_path):
    res, out, sources = _run(tmp_path, "45")
    assert res.returncode == 0, out
    assert _delivered(sources, "acme-hub"), out
    assert _delivered(sources, "acme-spoke-dev"), out   # waited CREATING -> ACTIVE
    assert _delivered(sources, "acme-spoke-upd"), out   # waited UPDATING -> ACTIVE
    assert _delivered(sources, "acme-spoke-deg"), out   # DEGRADED still gets logs
    assert not _delivered(sources, "acme-spoke-prod"), out
    # one shared budget: spoke-dev and spoke-upd each used 15 s, spoke-prod gets the last 15 s
    assert "acme-spoke-prod: 'kro' capability is CREATING after 15s (wait budget 45/45s used)" in out, out
    assert _naps(tmp_path) == ["15", "15", "15"], out
    assert "acme-spoke-none: no 'kro' capability" in out, out
    # an expired token is reported as an error, not as "no capability"
    assert "WARN acme-spoke-err: describe-capability failed (rc=254)" in out, out
    assert "ExpiredTokenException" in out, out
    assert "acme-spoke-err: no 'kro' capability" not in out, out
    # skips are summarised instead of a success line (spoke-none has no capability: not a skip)
    assert "✓ kro capability logs enabled" not in out, out
    assert "⚠ kro capability logs NOT enabled for: acme-spoke-prod acme-spoke-err " in out, out


def test_all_ready_prints_success_and_cleans_tmp(tmp_path):
    res, out, sources = _run(tmp_path, "45", "acme-hub acme-spoke-dev acme-spoke-none")
    assert res.returncode == 0, out
    assert "✓ kro capability logs enabled for acme-* clusters" in out, out
    assert "⚠ kro capability logs NOT enabled" not in out, out
    assert list((tmp_path / "tmp").iterdir()) == [], "ERRF temp file left behind"


def test_wait_is_capped_at_cap_logs_wait(tmp_path):
    res, out, _ = _run(tmp_path, "50", "acme-spoke-prod")
    assert "acme-spoke-prod: 'kro' capability is CREATING after 50s" in out, out
    assert _naps(tmp_path) == ["15", "15", "15", "5"], out   # last nap trimmed, no overshoot


def test_wait_budget_is_shared_by_all_clusters(tmp_path):
    # two capabilities stuck CREATING: the second one gets only what the first left (0 s)
    res, out, sources = _run(tmp_path, "45", "acme-spoke-prod acme-spoke-prod2")
    assert res.returncode == 0, out
    assert "acme-spoke-prod: 'kro' capability is CREATING after 45s (wait budget 45/45s used)" in out, out
    assert "acme-spoke-prod2: 'kro' capability is CREATING after 0s (wait budget 45/45s used)" in out, out
    assert _naps(tmp_path) == ["15", "15", "15"], out
    assert not sources, out


def test_non_numeric_wait_falls_back_to_default(tmp_path):
    res, out, sources = _run(tmp_path, "abc", "acme-spoke-prod")
    assert res.returncode == 0, out
    assert "CAP_LOGS_WAIT='abc' is not a number of seconds" in out, out
    assert "acme-spoke-prod: 'kro' capability is CREATING after 600s" in out, out
    assert sum(int(n) for n in _naps(tmp_path)) == 600, out


@pytest.mark.parametrize("wait,secs,naps", [("010", 10, ["10"]), ("08", 8, ["8"]), ("0", 0, []), ("000", 0, [])])
def test_leading_zero_wait_is_decimal(tmp_path, wait, secs, naps):
    # shell arithmetic would read 010 as octal 8 and 08 as an error; 0 must not loop forever
    res, out, _ = _run(tmp_path, wait, "acme-spoke-prod", timeout=20)
    assert res.returncode == 0, out
    assert f"acme-spoke-prod: 'kro' capability is CREATING after {secs}s (wait budget {secs}/{secs}s used)" in out, out
    assert _naps(tmp_path) == naps, out
