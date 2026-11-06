"""Hermetic tests for HUB_DELETE_WAIT (kind-kro-ack `destroy`) and the workshop destroy that
sets it: under the CloudFormation stack delete, task destroy no longer waits up to
5 + 10 + 30 min for the hub's capabilities and cluster to be deleted, since the stack's
Clusters build runs an AWS sweep that deletes them right after.

The cmds are read verbatim from the Taskfiles and run under go-task with
`set: [errexit, nounset, pipefail]`. `aws` and `sleep` are fakes on PATH; `sleep` only adds
to a virtual clock. The hub stays ACTIVE with its capabilities, as right after the deletes
were submitted.

Run:  python -m pytest workshop/scripts/tests/test_destroy_hub_delete_wait.py -q
Set DESTROY_ADDONS_TASKFILE / WORKSHOP_TASKFILE=<path> to run against other Taskfiles.
"""
import json
import os
import shutil
import subprocess
import sys

import pytest

yaml = pytest.importorskip("yaml")

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
PROVIDER_TF = os.environ.get("DESTROY_ADDONS_TASKFILE") or os.path.join(
    REPO, "cluster-providers", "kind-kro-ack", "Taskfile.yaml")
WORKSHOP_TF = os.environ.get("WORKSHOP_TASKFILE") or os.path.join(REPO, "workshop", "Taskfile.yaml")
TASK = shutil.which("task")

FAKE_AWS = r'''#!/bin/sh
echo "aws $*" >> "$FAKE_LOG"
case "$1 $2" in
  "eks list-capabilities")
    case "$*" in *length*) echo 3 ;; *) echo ACTIVE ;; esac ;;
  "eks describe-cluster") echo ACTIVE ;;
  "eks delete-cluster") echo "An error occurred (ResourceInUseException) when calling the DeleteCluster operation: capabilities attached" >&2; exit 254 ;;
  "ssm get-parameter") [ -n "$FAKE_STACK_DELETE" ] && exit 0; echo "ParameterNotFound" >&2; exit 254 ;;
esac
exit 0
'''
FAKE_SLEEP = '#!/bin/sh\necho "$1" >> "$FAKE_CLOCK"\n'
FAKE_TASK = '#!/bin/sh\necho "task $*" >> "$FAKE_LOG"\n'


def _text(c):
    return c.get("cmd", "") if isinstance(c, dict) else (c if isinstance(c, str) else "")


def _env(tmp, bins, extra=None):
    bindir = tmp / "bin"
    bindir.mkdir()
    for n, b in bins.items():
        (bindir / n).write_text(b)
        (bindir / n).chmod(0o755)
    (tmp / "log").write_text("")
    (tmp / "clock").write_text("")
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", FAKE_LOG=str(tmp / "log"),
               FAKE_CLOCK=str(tmp / "clock"))
    env.update(extra or {})
    return env


def _run_provider(tmp, wait):
    if not TASK:
        pytest.skip("go-task not on PATH")
    task = yaml.safe_load(open(PROVIDER_TF))["tasks"]["destroy"]
    cmds = task["cmds"]
    keep = [c for c in cmds if any(k in _text(c) for k in (
        "Wait up to 5 min for all capabilities", "HUB_DELETE_TRIES", "Hub EKS status",
        "Destroy incomplete: EKS cluster"))]
    assert len(keep) == 4, [_text(c)[:60] for c in keep]
    # The final-check cmd also reads the sweep-failure file; keep only its hub check.
    tvars = {k: "" for k in ("C_ERR", "C_RESET", "C_OK", "C_INFO", "C_STEP")}
    tvars.update({"HUB_CLUSTER_NAME": "acme-hub", "AWS_REGION": "eu-west-3", "ROOT_DIR": str(tmp)})
    if wait is not None:
        tvars["HUB_DELETE_WAIT"] = wait
    tf = {"version": "3", "set": ["errexit", "nounset", "pipefail"], "vars": tvars,
          "tasks": {"run": {"vars": {"HUB_DELETE_WAIT": task["vars"].get("HUB_DELETE_WAIT", "true")},
                            "cmds": keep}}}
    (tmp / "Taskfile.yml").write_text(yaml.safe_dump(tf, sort_keys=False))
    (tmp / "private").mkdir()
    env = _env(tmp, {"aws": FAKE_AWS, "sleep": FAKE_SLEEP})
    res = subprocess.run([TASK, "-s", "run"] + ([f"HUB_DELETE_WAIT={wait}"] if wait else []),
                         cwd=tmp, env=env, capture_output=True, text=True, timeout=120)
    waited = sum(int(x) for x in (tmp / "clock").read_text().split() if x.isdigit())
    return res, waited, (tmp / "log").read_text()


def test_default_still_waits_and_fails_when_the_hub_survives(tmp_path):
    res, waited, _log = _run_provider(tmp_path, None)
    assert waited >= 2400, waited          # 5 + 10 + 30 min of polling, as before
    assert res.returncode != 0 and "Destroy incomplete" in res.stdout + res.stderr


def test_no_wait_submits_the_deletes_once_and_does_not_fail(tmp_path):
    res, waited, log = _run_provider(tmp_path, "false")
    assert res.returncode == 0, res.stdout + res.stderr
    assert waited == 0, waited
    assert log.count("eks delete-capability") == 3 and log.count("eks delete-cluster") == 1, log
    assert "still being deleted" in res.stdout


def _run_workshop(tmp, stack_delete, cli=None):
    if not TASK:
        pytest.skip("go-task not on PATH")
    cmds = yaml.safe_load(open(WORKSHOP_TF))["tasks"]["destroy"]["cmds"]
    cmd = next(c for c in cmds if "HUB_DELETE_WAIT" in _text(c))
    tvars = {k: "" for k in ("C_ERR", "C_RESET", "C_OK", "C_INFO", "C_STEP")}
    tvars.update({"RESOURCE_PREFIX": "acme", "AWS_REGION": "eu-west-3", "PLATFORM_DIR": str(tmp),
                  "PROVIDER": "kind-kro-ack"})
    tf = {"version": "3", "set": ["errexit", "nounset", "pipefail"], "vars": tvars,
          "tasks": {"run": {"cmds": [cmd]}}}
    (tmp / "Taskfile.yml").write_text(yaml.safe_dump(tf, sort_keys=False))
    env = _env(tmp, {"aws": FAKE_AWS, "sleep": FAKE_SLEEP, "task": FAKE_TASK},
               {"FAKE_STACK_DELETE": "1"} if stack_delete else {})
    # the real go-task runs the outer Taskfile; the provider call hits the fake `task`
    res = subprocess.run([TASK, "-s", "run"] + (cli or []), cwd=tmp, env=env,
                         capture_output=True, text=True, timeout=60)
    calls = [line for line in (tmp / "log").read_text().splitlines() if line.startswith("task ")]
    return res, calls


@pytest.mark.parametrize("stack_delete, cli, expect", [
    (True, None, "HUB_DELETE_WAIT=false DESTROY_DEADLINE=0"),
    (False, None, "HUB_DELETE_WAIT=true DESTROY_DEADLINE=0"),
    (True, ["HUB_DELETE_WAIT=true"], "HUB_DELETE_WAIT=true DESTROY_DEADLINE=0"),
])
def test_workshop_destroy_tells_the_provider(tmp_path, stack_delete, cli, expect):
    res, calls = _run_workshop(tmp_path, stack_delete, cli)
    assert res.returncode == 0, res.stdout + res.stderr
    assert calls == [f"task kind-kro-ack:destroy {expect}"], calls
