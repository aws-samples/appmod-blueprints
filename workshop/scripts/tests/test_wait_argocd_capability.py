"""Hermetic tests for scripts/wait-argocd-capability.sh and its wiring into
hub:apply-root-appset (kind-kro-ack and kind-crossplane).

`aws` is a fake on PATH that replays a scripted sequence of capability statuses (one per
call to `describe-capability --query capability.status`), so the loop runs with no AWS.

Run:  python -m pytest workshop/scripts/tests/test_wait_argocd_capability.py -q
"""
import os
import shutil
import subprocess

import pytest

yaml = pytest.importorskip("yaml")
if not shutil.which("bash"):
    pytest.skip("bash not available", allow_module_level=True)

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SCRIPT = os.path.join(REPO, "scripts", "wait-argocd-capability.sh")

# Fake aws: each status call pops the next line of $FAKE_STATUSES (the last one repeats).
# "NOTFOUND" -> ResourceNotFoundException on stderr, rc 254. "ERR" -> other error.
FAKE_AWS = r'''#!/usr/bin/env bash
echo "$*" >> "$FAKE_AWS_LOG"
case "$*" in
  *capability.health.issues*) echo '[{"code":"X","message":"boom"}]'; exit 0 ;;
esac
n=$(cat "$FAKE_COUNT" 2>/dev/null || echo 0)
total=$(wc -l < "$FAKE_STATUSES")
idx=$(( n < total ? n + 1 : total ))
echo $((n + 1)) > "$FAKE_COUNT"
s=$(sed -n "${idx}p" "$FAKE_STATUSES")
case "$s" in
  NOTFOUND) echo "An error occurred (ResourceNotFoundException) when calling the DescribeCapability operation" >&2; exit 254 ;;
  ERR) echo "An error occurred (AccessDeniedException) when calling the DescribeCapability operation" >&2; exit 254 ;;
  *) echo "$s" ;;
esac
'''


def _run(tmp_path, statuses, ceiling="600", args=("peeks-hub", "us-west-2")):
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    (bindir / "aws").write_text(FAKE_AWS)
    (bindir / "aws").chmod(0o755)
    (bindir / "sleep").write_text("#!/usr/bin/env bash\nexit 0\n")  # no real waiting
    (bindir / "sleep").chmod(0o755)
    (tmp_path / "statuses").write_text("\n".join(statuses) + "\n")
    env = dict(os.environ,
               PATH=f"{bindir}:{os.environ['PATH']}",
               FAKE_STATUSES=str(tmp_path / "statuses"),
               FAKE_COUNT=str(tmp_path / "count"),
               FAKE_AWS_LOG=str(tmp_path / "aws.log"),
               ARGOCD_CAPABILITY_WAIT_SECS=ceiling,
               ARGOCD_CAPABILITY_POLL_SECS="0")
    p = subprocess.run(["bash", SCRIPT, *args], env=env, capture_output=True, text=True, timeout=60)
    log = (tmp_path / "aws.log").read_text() if (tmp_path / "aws.log").exists() else ""
    return p, log


def test_waits_through_not_created_and_creating_then_active(tmp_path):
    p, log = _run(tmp_path, ["NOTFOUND", "NOTFOUND", "CREATING", "CREATING", "ACTIVE"])
    assert p.returncode == 0, p.stderr
    assert "status=NOT_CREATED" in p.stdout
    assert "status=CREATING" in p.stdout
    assert "is ACTIVE" in p.stdout
    assert "--cluster-name peeks-hub --capability-name argocd --region us-west-2" in log


def test_lines_carry_elapsed_seconds_marker(tmp_path):
    p, _ = _run(tmp_path, ["CREATING", "ACTIVE"])
    assert p.returncode == 0
    assert all(line.lstrip().startswith("[") and "s]" in line for line in p.stdout.splitlines())


def test_transient_describe_error_keeps_waiting(tmp_path):
    p, _ = _run(tmp_path, ["ERR", "ACTIVE"])
    assert p.returncode == 0
    assert "DESCRIBE_ERROR(" in p.stdout and "AccessDeniedException" in p.stdout


@pytest.mark.parametrize("terminal", ["CREATE_FAILED", "DELETE_FAILED", "DELETING"])
def test_terminal_status_fails_fast_with_health(tmp_path, terminal):
    p, _ = _run(tmp_path, ["CREATING", terminal, "ACTIVE"])
    assert p.returncode == 2
    assert terminal in p.stderr and "boom" in p.stderr


def test_degraded_continues_to_crd_wait(tmp_path):
    p, _ = _run(tmp_path, ["DEGRADED"])
    assert p.returncode == 0
    assert "DEGRADED" in p.stdout


def test_ceiling_reached_fails(tmp_path):
    p, _ = _run(tmp_path, ["CREATING"], ceiling="0")
    assert p.returncode == 1
    assert "not ACTIVE after 0s ceiling" in p.stderr and "status=CREATING" in p.stderr


def test_custom_capability_name(tmp_path):
    p, log = _run(tmp_path, ["ACTIVE"], args=("hub", "eu-west-1", "my-argocd"))
    assert p.returncode == 0
    assert "--capability-name my-argocd --region eu-west-1" in log


def test_usage_error(tmp_path):
    p, _ = _run(tmp_path, ["ACTIVE"], args=())
    assert p.returncode == 64


@pytest.mark.parametrize("provider,name_arg", [
    ("kind-kro-ack", "argocd"),
    ("kind-crossplane", '"{{.CAPABILITY_NAME}}"'),
])
def test_apply_root_appset_waits_for_capability_before_crds(provider, name_arg):
    tf = os.path.join(REPO, "cluster-providers", provider, "Taskfile.yaml")
    cmds = yaml.safe_load(open(tf))["tasks"]["hub:apply-root-appset"]["cmds"]
    text = [c if isinstance(c, str) else (c.get("cmd") or c.get("task") or "") for c in cmds]
    wait = [i for i, c in enumerate(text) if "wait-argocd-capability.sh" in c]
    crd = [i for i, c in enumerate(text) if "applicationsets.argoproj.io" in c]
    apply = [i for i, c in enumerate(text) if "root-appset.yaml" in c]
    assert len(wait) == 1 and crd and apply
    assert wait[0] < crd[0] < apply[0]
    assert text[wait[0]] == (
        'bash "{{.ROOT_DIR}}/scripts/wait-argocd-capability.sh" '
        f'"{{{{.HUB_CLUSTER_NAME}}}}" "{{{{.AWS_REGION}}}}" {name_arg}')
