"""Tests for the pod-identity-restart-hook PostSync script (charts/pod-identity-restart-hook).

The hook restarts a workload whose pods started before their pod identity association
existed, so they have no AWS credentials. It must inspect EVERY pod matching the
selector: on a DaemonSet one node's pod can lack the credentials while the first pod
listed is fine (seen live on aws-for-fluent-bit).

The script is rendered with `helm template` for a Deployment and a DaemonSet target,
then run against a fake `kubectl` that serves canned pod lists and records calls.

Run:  python -m pytest workshop/scripts/tests/test_pod_identity_restart_hook.py -q
"""
import os
import shutil
import stat
import subprocess
import textwrap

import pytest

yaml = pytest.importorskip("yaml")

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
CHART = os.path.join(REPO, "gitops", "addons", "charts", "pod-identity-restart-hook")

TARGETS = {
    "targets": [
        {"name": "lbc", "namespace": "kube-system",
         "serviceAccount": "aws-load-balancer-controller-sa",
         "deploymentLabel": "app.kubernetes.io/name=aws-load-balancer-controller"},
        {"name": "aws-for-fluentbit", "namespace": "kube-system",
         "serviceAccount": "aws-for-fluent-bit", "workloadKind": "daemonset",
         "deploymentLabel": "app.kubernetes.io/name=aws-for-fluent-bit"},
    ]
}

# One line per pod, in the format the script's jsonpath prints:
# name|deletionTimestamp|<env names> <volume names>
OK = "{n}||AWS_REGION AWS_CONTAINER_CREDENTIALS_FULL_URI AWS_CONTAINER_AUTHORIZATION_TOKEN_FILE config eks-pod-identity-token"
OK_VOLUME_ONLY = "{n}||AWS_REGION config eks-pod-identity-token"
NO_CREDS = "{n}||AWS_REGION config kube-api-access-x"
TERMINATING_NO_CREDS = "{n}|2026-10-30T10:15:00Z|AWS_REGION config"

FAKE_KUBECTL = textwrap.dedent("""\
    #!/bin/sh
    # Fake kubectl: `get pods` prints the current state file; `rollout restart`
    # moves to the next state file (state.N -> state.N+1) when one exists.
    echo "$*" >> "$FAKE_DIR/calls"
    N=$(cat "$FAKE_DIR/idx")
    case "$1 $2" in
      "get pods") cat "$FAKE_DIR/state.$N" ;;
      "rollout restart")
        if [ -f "$FAKE_DIR/state.$((N + 1))" ]; then echo $((N + 1)) > "$FAKE_DIR/idx"; fi ;;
      "rollout status") exit "${FAKE_STATUS_RC:-0}" ;;
    esac
    """)


@pytest.fixture(scope="module")
def scripts():
    if not shutil.which("helm"):
        pytest.skip("helm not installed")
    out = subprocess.run(
        ["helm", "template", "t", CHART, "-f", "/dev/stdin"],
        input=yaml.safe_dump(TARGETS), capture_output=True, text=True, check=True).stdout
    jobs = {}
    for doc in yaml.safe_load_all(out):
        if doc and doc.get("kind") == "Job":
            c = doc["spec"]["template"]["spec"]["containers"][0]
            jobs[doc["metadata"]["name"]] = c["args"][0]
    assert set(jobs) == {"lbc-credential-check", "aws-for-fluentbit-credential-check"}
    return jobs


def run(tmp_path, script, states, status_rc=0, shell="sh"):
    """Run the hook script; states is a list of pod lists (one per restart step)."""
    fake = tmp_path / "fake"
    fake.mkdir()
    kubectl = fake / "kubectl"
    kubectl.write_text(FAKE_KUBECTL)
    kubectl.chmod(kubectl.stat().st_mode | stat.S_IEXEC)
    for i, pods in enumerate(states):
        (fake / f"state.{i}").write_text("".join(p + "\n" for p in pods))
    (fake / "idx").write_text("0")
    (fake / "calls").write_text("")
    env = dict(os.environ, PATH=f"{fake}:{os.environ['PATH']}", FAKE_DIR=str(fake),
               RETRY_DELAY="0", FAKE_STATUS_RC=str(status_rc))
    cmd = [shell, "--posix", "-c", script] if shell == "bash" else [shell, "-c", script]
    p = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=30)
    calls = (fake / "calls").read_text().splitlines()
    restarts = [c for c in calls if c.startswith("rollout restart")]
    return p, restarts


SHELLS = ["sh"] + (["bash"] if shutil.which("bash") else [])


@pytest.mark.parametrize("shell", SHELLS)
def test_daemonset_one_pod_without_creds_restarts(tmp_path, scripts, shell):
    # The live case: items[0] is fine, the second pod has no credentials.
    s = scripts["aws-for-fluentbit-credential-check"]
    p, restarts = run(tmp_path, s, [
        [OK.format(n="fb-sv5vb"), NO_CREDS.format(n="fb-xpxgr")],
        [OK.format(n="fb-a"), OK.format(n="fb-b")],
    ], shell=shell)
    assert p.returncode == 0, p.stderr
    assert restarts == ["rollout restart daemonset -n kube-system -l app.kubernetes.io/name=aws-for-fluent-bit"]
    assert "Missing pod identity credentials in pod(s): fb-xpxgr, restarting" in p.stdout
    assert "injected in all 2 pod(s)" in p.stdout


@pytest.mark.parametrize("shell", SHELLS)
def test_all_pods_ok_no_restart(tmp_path, scripts, shell):
    s = scripts["aws-for-fluentbit-credential-check"]
    p, restarts = run(tmp_path, s, [[OK.format(n="a"), OK_VOLUME_ONLY.format(n="b"), OK.format(n="c")]],
                      shell=shell)
    assert p.returncode == 0, p.stderr
    assert restarts == []
    assert "injected in all 3 pod(s)" in p.stdout


@pytest.mark.parametrize("shell", SHELLS)
def test_zero_pods_no_op(tmp_path, scripts, shell):
    s = scripts["aws-for-fluentbit-credential-check"]
    p, restarts = run(tmp_path, s, [[]], shell=shell)
    assert p.returncode == 0, p.stderr
    assert restarts == []
    assert "No pod found" in p.stdout


def test_terminating_pods_ignored(tmp_path, scripts):
    s = scripts["aws-for-fluentbit-credential-check"]
    p, restarts = run(tmp_path, s, [[OK.format(n="new"), TERMINATING_NO_CREDS.format(n="old")]])
    assert p.returncode == 0, p.stderr
    assert restarts == []


def test_association_late_retries_then_succeeds(tmp_path, scripts):
    # First restart happens before the association exists: pods still lack creds.
    s = scripts["aws-for-fluentbit-credential-check"]
    p, restarts = run(tmp_path, s, [
        [NO_CREDS.format(n="a"), NO_CREDS.format(n="b")],
        [NO_CREDS.format(n="a2"), NO_CREDS.format(n="b2")],
        [OK.format(n="a3"), OK.format(n="b3")],
    ])
    assert p.returncode == 0, p.stderr
    assert len(restarts) == 2
    assert "Waiting 0s for the pod identity association" in p.stdout


def test_retries_are_bounded(tmp_path, scripts):
    # The association never appears: stop after 3 restarts, warn, do not fail the sync.
    s = scripts["aws-for-fluentbit-credential-check"]
    p, restarts = run(tmp_path, s, [[NO_CREDS.format(n="a")]])
    assert p.returncode == 0, p.stderr
    assert len(restarts) == 3
    assert "WARNING" in p.stdout


def test_rollout_status_failure_fails_job(tmp_path, scripts):
    # Same as before the change: a rollout that does not finish fails the Job (backoffLimit retries).
    s = scripts["aws-for-fluentbit-credential-check"]
    p, restarts = run(tmp_path, s, [[NO_CREDS.format(n="a")]], status_rc=1)
    assert p.returncode == 1
    assert len(restarts) == 1


def test_deployment_target_checks_all_replicas(tmp_path, scripts):
    # Deployments benefit too: a 2-replica LBC with one replica missing creds is restarted.
    s = scripts["lbc-credential-check"]
    p, restarts = run(tmp_path, s, [
        [OK.format(n="lbc-1"), NO_CREDS.format(n="lbc-2")],
        [OK.format(n="lbc-3"), OK.format(n="lbc-4")],
    ])
    assert p.returncode == 0, p.stderr
    assert restarts == ["rollout restart deployment -n kube-system -l app.kubernetes.io/name=aws-load-balancer-controller"]


def test_deployment_single_pod_unchanged_behaviour(tmp_path, scripts):
    s = scripts["lbc-credential-check"]
    p, restarts = run(tmp_path, s, [[OK.format(n="lbc-1")]])
    assert p.returncode == 0 and restarts == []
    (tmp_path / "x").mkdir()
    p, restarts = run(tmp_path / "x", s, [[NO_CREDS.format(n="lbc-1")], [OK.format(n="lbc-2")]])
    assert p.returncode == 0 and len(restarts) == 1
