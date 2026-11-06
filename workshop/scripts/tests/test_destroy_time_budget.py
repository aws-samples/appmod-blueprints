"""Hermetic tests for the workshop `destroy` time budget (DESTROY_BUDGET / the deadline).

Live: under the CloudFormation stack delete, the Bootstrap build runs `task destroy` over
SSM with a 40 min executionTimeout. On every live run of 2026-11-06 SSM killed it (teams
40, 50, 54, 55) somewhere in Phase 3, after Phase 1 (LB gate 2 x 300 s, PVC deletes 2 x
120 s) and Phase 2.5 (900 s cap) had used most of the time. A killed destroy runs nothing
after the kill point and cannot hand over cleanly.

Checked here, on the cmds read verbatim from workshop/Taskfile.yaml and run under go-task:
  * the deadline is set under the stack delete (2100 s), on DESTROY_BUDGET, and not otherwise;
  * Phase 1 stops its waits when the budget is spent, and never waits on PVC deletes;
  * Phase 3 hands the deadline to the provider (DESTROY_DEADLINE=<epoch>).

Run:  python -m pytest workshop/scripts/tests/test_destroy_time_budget.py -q
"""
import json
import os
import shutil
import subprocess
import sys
import time

import pytest

yaml = pytest.importorskip("yaml")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_destroy_drain_owners as drain  # noqa: E402

TASK = shutil.which("task")
TASKFILE = drain.TASKFILE
COLORS = {k: "" for k in ("C_ERR", "C_RESET", "C_OK", "C_INFO", "C_STEP")}


def _destroy():
    return yaml.safe_load(open(TASKFILE))["tasks"]["destroy"]


def _text(c):
    return c.get("cmd", "") if isinstance(c, dict) else (c if isinstance(c, str) else "")


def _budget_vars(tmp):
    v = _destroy()["vars"]
    out = {k: v[k] for k in ("DL_RESERVE_P1", "DL_RESERVE_P3")}
    out["DESTROY_DEADLINE_FILE"] = str(tmp / "private" / "destroy-deadline")
    out["DL_FN"] = v["DL_FN"]
    return out


FAKE_AWS = r'''#!/bin/sh
echo "aws $*" >> "$FAKE_LOG"
case "$1 $2" in
  "ssm get-parameter") [ -n "${FAKE_STACK_DELETE:-}" ] && exit 0; exit 254 ;;
esac
exit 0
'''


def _run_cmds(tmp, cmds, extra_vars=None, cli=None, env_extra=None):
    if not TASK:
        pytest.skip("go-task not on PATH")
    (tmp / "private").mkdir(exist_ok=True)
    bindir = tmp / "bin"
    bindir.mkdir(exist_ok=True)
    (bindir / "aws").write_text(FAKE_AWS)
    (bindir / "aws").chmod(0o755)
    tvars = dict(COLORS, REPO=str(tmp), RESOURCE_PREFIX="acme", AWS_REGION="eu-west-3")
    tvars.update(_budget_vars(tmp))
    tvars.update(extra_vars or {})
    tf = {"version": "3", "set": ["errexit", "nounset", "pipefail"], "vars": tvars,
          "tasks": {"run": {"cmds": cmds}}}
    (tmp / "Taskfile.yml").write_text(yaml.safe_dump(tf, sort_keys=False))
    (tmp / "log").write_text("")
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", FAKE_LOG=str(tmp / "log"),
               **(env_extra or {}))
    return subprocess.run([TASK, "-s", "run"] + (cli or []), cwd=tmp, env=env,
                          capture_output=True, text=True, timeout=120)


def _deadline_cmd():
    return next(c for c in _destroy()["cmds"] if "DESTROY_BUDGET" in _text(c))


@pytest.mark.parametrize("stack_delete, cli, budget", [
    (True, None, 2100),                  # stack delete: 35 min, 5 min under the SSM limit
    (False, None, None),                 # anywhere else: no deadline
    (False, ["DESTROY_BUDGET=600"], 600),
    (True, ["DESTROY_BUDGET=0"], None),  # explicitly off
])
def test_deadline_is_set_only_under_the_stack_delete_or_on_request(tmp_path, stack_delete, cli, budget):
    t0 = int(time.time())
    res = _run_cmds(tmp_path, [_deadline_cmd()], cli=cli,
                    env_extra={"FAKE_STACK_DELETE": "1"} if stack_delete else {})
    assert res.returncode == 0, res.stdout + res.stderr
    f = tmp_path / "private" / "destroy-deadline"
    if budget is None:
        assert not f.exists(), f.read_text()
        assert "No time budget" in res.stdout
    else:
        d = int(f.read_text())
        assert t0 + budget <= d <= int(time.time()) + budget, (d, t0)
        assert f"Time budget: {budget}s" in res.stdout, res.stdout


def test_phase3_hands_the_deadline_to_the_provider(tmp_path):
    cmd = _text(next(c for c in _destroy()["cmds"] if "HUB_DELETE_WAIT" in _text(c)))
    (tmp_path / "private").mkdir()
    (tmp_path / "private" / "destroy-deadline").write_text("1900000000\n")
    # The outer Taskfile runs on the real go-task, the provider call on a fake `task`
    # outside PATH: the cmd is pointed at it.
    shim = tmp_path / "shim"
    shim.mkdir()
    (shim / "task").write_text('#!/bin/sh\necho "task $*" >> "$FAKE_LOG"\n')
    (shim / "task").chmod(0o755)
    res = _run_cmds(tmp_path, [cmd.replace("&& task ", f"&& {shim / 'task'} ")],
                    extra_vars={"PLATFORM_DIR": str(tmp_path), "PROVIDER": "kind-kro-ack"})
    assert res.returncode == 0, res.stdout + res.stderr
    calls = [x for x in (tmp_path / "log").read_text().splitlines() if x.startswith("task ")]
    assert calls == ["task kind-kro-ack:destroy HUB_DELETE_WAIT=true DESTROY_DEADLINE=1900000000"], calls


# ── Phase 1 ─────────────────────────────────────────────────────────────────────
FAKE_P1 = drain.FAKE.replace(
    '''    elif a[:2] == ["elbv2", "describe-load-balancers"]:
        print(lbs())''',
    '''    elif a[:2] == ["elbv2", "describe-load-balancers"]:
        print(1 if os.environ.get("FAKE_LB_STUCK") else lbs())''', 1).replace(
    '''    elif verb == "delete" and pos[1] in ("ingress", "pvc") and "--all" in a:''',
    '''    elif verb == "delete" and pos[1] in ("ingress", "pvc") and "--all" in a:
        st["log"].append(["delete-all", pos[1], [x for x in a if x.startswith("--wait") or x.startswith("--timeout")]])''', 1)
assert "FAKE_LB_STUCK" in FAKE_P1 and "delete-all" in FAKE_P1


def _run_phase1(tmp, deadline_in=None):
    if not TASK:
        pytest.skip("go-task not on PATH")
    src = yaml.safe_load(open(TASKFILE))
    bindir = tmp / "bin"
    bindir.mkdir()
    for n in ("kubectl", "aws"):
        (bindir / n).write_text(FAKE_P1.replace("{python}", sys.executable))
        (bindir / n).chmod(0o755)
    (bindir / "sleep").write_text(drain.FAKE_SLEEP)
    (bindir / "sleep").chmod(0o755)
    state, clock = tmp / "state.json", tmp / "clock"
    state.write_text(json.dumps(drain._state()))
    clock.write_text("")
    (tmp / "config.yaml").write_text("resourcePrefix: acme\naws:\n  region: eu-west-3\n")
    (tmp / "private").mkdir()
    if deadline_in is not None:
        (tmp / "private" / "destroy-deadline").write_text(str(int(time.time()) + deadline_in))
    hub_kc = tmp / "hub-kubeconfig"
    hub_kc.write_text("hub\n")
    gvars = dict(COLORS, CONFIG_FILE=str(tmp / "config.yaml"), HUB_KUBECONFIG=str(hub_kc),
                 AWS_REGION="eu-west-3", RESOURCE_PREFIX="acme", LB_DRAIN_WAIT="60")
    gvars.update(_budget_vars(tmp))
    tf = {"version": "3", "set": ["errexit", "nounset", "pipefail"], "vars": gvars,
          "tasks": {"run": {"cmds": [drain._phase1(src)]}}}
    (tmp / "Taskfile.yml").write_text(yaml.safe_dump(tf, sort_keys=False))
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", FAKE_STATE=str(state),
               FAKE_CLOCK=str(clock), FAKE_SPOKE=drain.SPOKE, FAKE_HUB_KC=str(hub_kc), FAKE_LB_STUCK="1")
    res = subprocess.run([TASK, "-s", "run"], cwd=tmp, env=env, capture_output=True, text=True, timeout=120)
    waited = sum(int(x) for x in clock.read_text().split() if x.isdigit())
    return res, json.loads(state.read_text()), waited


def test_pvc_deletes_are_not_waited_for(tmp_path):
    # Live: `delete pvc --timeout=120s` waited 120 s per spoke on a PVC still mounted.
    res, st, _w = _run_phase1(tmp_path)
    assert res.returncode == 0, res.stdout + res.stderr
    pvc = [e for e in st["log"] if e[0] == "delete-all" and e[1] == "pvc"]
    assert pvc and pvc[0][2] == ["--wait=false"], pvc


def test_lb_gate_without_budget_keeps_its_cap(tmp_path):
    res, _st, waited = _run_phase1(tmp_path)
    assert res.returncode == 0, res.stdout + res.stderr
    assert waited >= 60, waited
    assert "load balancer(s) still in the VPC" in res.stdout


def test_lb_gate_stops_when_the_budget_is_spent(tmp_path):
    # 1000 s left < DL_RESERVE_P1 (1500): Phase 1 must not wait at all, the later phases
    # need that time; the gate still reports what is left.
    res, _st, waited = _run_phase1(tmp_path, deadline_in=1000)
    assert res.returncode == 0, res.stdout + res.stderr
    assert waited == 0, f"{waited}s of Phase 1 waits past the budget"
    assert "load balancer(s) still in the VPC" in res.stdout
