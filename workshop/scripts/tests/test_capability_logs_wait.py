"""Hermetic go-task test: `task enable-capability-logs` waits for a capability that is
still CREATING (spokes created just before install:complete) instead of failing the
install on put-delivery-source's ConflictException, and skips one that never gets ACTIVE.
It also waits for a capability that does not exist YET because its cluster is still being
created (describe-capability ResourceNotFound), all waits sharing one CAP_LOGS_WAIT budget.

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
# ACTIVE/DEGRADED. spoke-late: cluster CREATING on the 1st look, ACTIVE after, capability
# not found twice, then CREATING, then ACTIVE. spoke-new/new2: cluster CREATING forever,
# never a capability. spoke-clerr: no capability and describe-cluster fails.
FAKE_AWS = r"""#!/usr/bin/env bash
echo "$*" >> "$FAKE_AWS_LOG"
val() { prev=""; for a in "$@"; do [ "$prev" = "$KEY" ] && { echo "$a"; return; }; prev="$a"; done; }
case "$1 $2" in
  "sts get-caller-identity") echo 111122223333 ;;
  "eks list-clusters")
    if [ "$FAKE_CLUSTERS" = __DENY__ ]; then echo "An error occurred (AccessDeniedException) when calling the ListClusters operation" >&2; exit 254; fi
    echo "$FAKE_CLUSTERS" ;;
  "eks describe-capability")
    C=$(KEY=--cluster-name val "$@")
    N=$(grep -c "describe-capability --cluster-name $C " "$FAKE_AWS_LOG")
    case "$C" in
      acme-spoke-none|acme-spoke-new|acme-spoke-new2|acme-spoke-clerr) echo "An error occurred (ResourceNotFoundException) when calling the DescribeCapability operation" >&2; exit 254 ;;
      acme-spoke-late)
        if [ "$N" -le 2 ]; then echo "An error occurred (ResourceNotFoundException) when calling the DescribeCapability operation" >&2; exit 254; fi
        if [ "$N" -eq 3 ]; then S=CREATING; else S=ACTIVE; fi ;;
      acme-spoke-err) echo "An error occurred (ExpiredTokenException) when calling the DescribeCapability operation" >&2; exit 254 ;;
      acme-spoke-prod) S=CREATING ;;
      acme-spoke-deg) S=DEGRADED ;;
      acme-spoke-dev) if [ "$N" -le 1 ]; then S=CREATING; else S=ACTIVE; fi ;;
      acme-spoke-upd) if [ "$N" -le 1 ]; then S=UPDATING; else S=ACTIVE; fi ;;
      *) S=ACTIVE ;;
    esac
    echo "$S" > "$FAKE_STATE/$C"
    printf 'arn:aws:eks:us-west-2:111122223333:capability/%s/kro\t%s\n' "$C" "$S" ;;
  "eks describe-cluster")
    C=$(KEY=--name val "$@")
    N=$(grep -c "describe-cluster --name $C " "$FAKE_AWS_LOG")
    case "$C" in
      acme-spoke-new|acme-spoke-new2|acme-spoke-err) echo CREATING ;;
      acme-spoke-late) if [ "$N" -le 1 ]; then echo CREATING; else echo ACTIVE; fi ;;
      acme-spoke-clerr) echo "An error occurred (AccessDeniedException) when calling the DescribeCluster operation" >&2; exit 254 ;;
      *) echo ACTIVE ;;
    esac ;;
  "logs put-delivery-source")
    N=$(KEY=--name val "$@"); C=${N%-kro}
    case "$(cat "$FAKE_STATE/$C" 2>/dev/null)" in
      ACTIVE|DEGRADED) echo ok ;;
      *) echo "An error occurred (ConflictException) when calling the PutDeliverySource operation: Capability kro cannot be updated as it is currently in CREATING state" >&2; exit 254 ;;
    esac ;;
  "logs describe-delivery-sources")
    if [ -n "$FAKE_STALE" ] && grep -q "$FAKE_STALE" <<<"$*"; then echo arn:aws:eks:us-west-2:111122223333:capability/old/kro; else echo None; fi ;;
  "logs describe-deliveries") echo None ;;
  "logs describe-delivery-destinations") echo arn:dest ;;
  *) echo ok ;;
esac
"""

ALL = "acme-hub acme-spoke-dev acme-spoke-upd acme-spoke-prod acme-spoke-deg acme-spoke-none acme-spoke-err"


def _run(tmp_path, wait, clusters=ALL, task_args=(), stale=""):
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
    for name, body in (("aws", FAKE_AWS), ("sleep", "#!/bin/sh\necho \"sleep $*\" >> \"$FAKE_AWS_LOG\"\n")):
        (bindir / name).write_text(body)
        (bindir / name).chmod(0o755)
    tmpd = tmp_path / "tmp"
    tmpd.mkdir()
    state = tmp_path / "state"
    state.mkdir()
    log = tmp_path / "calls.log"
    log.write_text("")
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", FAKE_AWS_LOG=str(log),
               FAKE_STATE=str(state), FAKE_CLUSTERS=clusters, FAKE_STALE=stale, HOME=str(tmp_path), TMPDIR=str(tmpd))
    if wait is not None:
        env["CAP_LOGS_WAIT"] = wait
    for k in ("AWS_PROFILE", "AWS_CONFIG_FILE", "AWS_DEFAULT_PROFILE", "KUBECONFIG"):
        env.pop(k, None)
    res = subprocess.run([TASK, "-d", str(r), "enable-capability-logs", *task_args], env=env,
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
    assert _delivered(sources, "acme-spoke-upd"), out   # waited UPDATING -> ACTIVE
    assert _delivered(sources, "acme-spoke-deg"), out   # DEGRADED still gets logs
    assert not _delivered(sources, "acme-spoke-prod"), out
    # dev and upd waited 15 s each, prod gets the 15 s left of the shared 45 s budget
    assert "acme-spoke-prod: 'kro' capability is CREATING after 15s" in out, out
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
    assert res.returncode == 0, out
    assert "acme-spoke-prod: 'kro' capability is CREATING after 50s" in out, out
    sleeps = [l for l in (tmp_path / "calls.log").read_text().splitlines() if l.startswith("sleep ")]
    assert sleeps == ["sleep 15", "sleep 15", "sleep 15", "sleep 5"], sleeps


def test_list_clusters_failure_is_not_a_success(tmp_path):
    res, out, sources = _run(tmp_path, "45", "__DENY__")
    assert res.returncode == 0, out
    assert "WARN: list-clusters failed: An error occurred (AccessDeniedException)" in out, out
    assert "⚠ kro capability logs NOT enabled for: (all: list-clusters failed)" in out, out
    assert "✓ kro capability logs enabled" not in out, out
    assert sources == [], sources


@pytest.mark.parametrize("wait", ["08", "010", "99999999999999999999"])
def test_octal_or_huge_wait_falls_back_without_spinning(tmp_path, wait):
    res, out, _ = _run(tmp_path, wait, "acme-spoke-prod")
    assert res.returncode == 0, out
    assert f"CAP_LOGS_WAIT='{wait}' is not a number of seconds" in out, out
    assert "acme-spoke-prod: 'kro' capability is CREATING after 600s" in out, out


def test_non_numeric_wait_falls_back_to_default(tmp_path):
    res, out, sources = _run(tmp_path, "abc", "acme-spoke-prod")
    assert res.returncode == 0, out
    assert "CAP_LOGS_WAIT='abc' is not a number of seconds" in out, out
    assert "acme-spoke-prod: 'kro' capability is CREATING after 600s" in out, out


def test_cluster_still_creating_is_a_skip_not_absent(tmp_path):
    res, out, sources = _run(tmp_path, "45", "acme-hub acme-spoke-new acme-spoke-none")
    assert res.returncode == 0, out
    assert "acme-spoke-new: cluster is CREATING, no 'kro' capability yet" in out, out
    assert "acme-spoke-none: no 'kro' capability — skipping" in out, out
    assert "⚠ kro capability logs NOT enabled for: acme-spoke-new " in out, out
    assert "✓ kro capability logs enabled" not in out, out


def test_wait_settable_as_task_var(tmp_path):
    res, out, _ = _run(tmp_path, None, "acme-spoke-prod", task_args=("CAP_LOGS_WAIT=30",))
    assert res.returncode == 0, out
    assert "acme-spoke-prod: 'kro' capability is CREATING after 30s" in out, out


def _sleeps(tmp_path):
    return [l for l in (tmp_path / "calls.log").read_text().splitlines() if l.startswith("sleep ")]


def test_waits_for_a_capability_not_created_yet_on_a_creating_cluster(tmp_path):
    # Regression: the spokes were still CREATING when install:complete ran, describe-capability
    # answered ResourceNotFound, and the task skipped them without waiting: no spoke kro logs.
    res, out, sources = _run(tmp_path, "120", "acme-hub acme-spoke-late")
    assert res.returncode == 0, out
    assert _delivered(sources, "acme-hub"), out
    assert _delivered(sources, "acme-spoke-late"), out  # not found x2 (cluster CREATING, then ACTIVE) -> CREATING -> ACTIVE
    assert "acme-spoke-late: kro log delivery created" in out, out
    assert "✓ kro capability logs enabled for acme-* clusters" in out and "⚠ kro capability logs NOT enabled" not in out, out
    assert _sleeps(tmp_path) == ["sleep 15"] * 3, _sleeps(tmp_path)


def test_never_created_capability_on_creating_cluster_is_skipped_after_the_budget(tmp_path):
    res, out, sources = _run(tmp_path, "50", "acme-spoke-new")
    assert res.returncode == 0, out
    assert "acme-spoke-new: cluster is CREATING, no 'kro' capability yet after 50s" in out, out
    assert "⚠ kro capability logs NOT enabled for: acme-spoke-new " in out, out
    assert sources == [], sources
    assert _sleeps(tmp_path) == ["sleep 15", "sleep 15", "sleep 15", "sleep 5"], _sleeps(tmp_path)


def test_wait_budget_is_total_not_per_cluster(tmp_path):
    res, out, _ = _run(tmp_path, "50", "acme-spoke-new acme-spoke-new2")
    assert res.returncode == 0, out
    # the first cluster uses the whole 50 s, the second still gets one look but no wait
    assert sum(int(l.split()[1]) for l in _sleeps(tmp_path)) == 50, _sleeps(tmp_path)
    assert "acme-spoke-new: cluster is CREATING, no 'kro' capability yet after 50s" in out, out
    assert "acme-spoke-new2: cluster is CREATING, no 'kro' capability yet after 0s" in out, out
    assert "⚠ kro capability logs NOT enabled for: acme-spoke-new acme-spoke-new2 " in out, out


def test_active_cluster_without_capability_is_not_waited_for(tmp_path):
    res, out, sources = _run(tmp_path, "600", "acme-hub acme-spoke-none")
    assert res.returncode == 0, out
    assert "acme-spoke-none: no 'kro' capability — skipping" in out, out
    assert _sleeps(tmp_path) == [], _sleeps(tmp_path)
    assert "✓ kro capability logs enabled" in out, out


def test_describe_cluster_failure_does_not_wait_or_abort(tmp_path):
    res, out, sources = _run(tmp_path, "600", "acme-hub acme-spoke-clerr")
    assert res.returncode == 0, out
    assert "acme-spoke-clerr: cluster is UNKNOWN (An error occurred (AccessDeniedException)" in out, out
    assert "⚠ kro capability logs NOT enabled for: acme-spoke-clerr " in out, out
    assert _delivered(sources, "acme-hub"), out
    assert _sleeps(tmp_path) == [], _sleeps(tmp_path)


def test_stale_delivery_source_is_still_reconciled_after_the_wait(tmp_path):
    # PR #865: a source left by an earlier cluster incarnation points at the OLD capability ARN.
    res, out, sources = _run(tmp_path, "120", "acme-spoke-late", stale="acme-spoke-late-kro")
    assert res.returncode == 0, out
    assert "acme-spoke-late: stale 'kro' delivery source" in out, out
    calls = (tmp_path / "calls.log").read_text().splitlines()
    dele = [i for i, l in enumerate(calls) if l.startswith("logs delete-delivery-source --name acme-spoke-late-kro")]
    put = [i for i, l in enumerate(calls) if l.startswith("logs put-delivery-source --name acme-spoke-late-kro")]
    assert dele and put and dele[0] < put[0], calls
    assert list((tmp_path / "tmp").iterdir()) == [], "temp files left behind"


def test_other_describe_capability_errors_are_not_waited_for(tmp_path):
    # ExpiredToken on a cluster that is CREATING must be reported at once, not waited out.
    res, out, sources = _run(tmp_path, "600", "acme-spoke-err")
    assert res.returncode == 0, out
    assert "WARN acme-spoke-err: describe-capability failed (rc=254)" in out, out
    assert _sleeps(tmp_path) == [], _sleeps(tmp_path)
