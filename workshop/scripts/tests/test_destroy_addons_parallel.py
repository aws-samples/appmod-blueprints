"""Hermetic timing test for kind-kro-ack `hub:destroy-addons` step 7: the addons of one
sync wave are deleted in parallel, and the waves still go one after the other in
descending order.

Step 7 used to delete one addon at a time, each spending ~20-30 s on its ApplicationSet
delete and on the wait for its Applications (more than 20 min on an agentic hub with ~70
addons). The cmd is read verbatim from cluster-providers/kind-kro-ack/Taskfile.yaml and run
under go-task with the Taskfile's `set:` options. `kubectl` is the stateful fake of
test_destroy_addons_order.py, plus a real delay on `delete applicationset` that stands for
the time Argo CD takes to prune an addon; `sleep` is a no-op fake. No cluster, no network.

Run:  python -m pytest workshop/scripts/tests/test_destroy_addons_parallel.py -q
Set DESTROY_ADDONS_TASKFILE=<path> to run the same checks against another Taskfile.
"""
import json
import os
import shutil
import subprocess
import sys
import time

import pytest

yaml = pytest.importorskip("yaml")

sys.path.insert(0, os.path.dirname(__file__))
import test_destroy_addons_order as base  # noqa: E402

TASK = shutil.which("task")
DELAY = 1.0  # seconds one addon's ApplicationSet delete takes in the fake
# 4 waves, 18 addons: sequentially that is 18 x DELAY, per wave in parallel 4 x DELAY
# (wave 5 has 10 addons, so with ADDON_DELETE_PARALLEL=8 it takes two batches: 5 x DELAY).
WAVES = {"9": 2, "5": 10, "3": 4, "0": 2}

TIMED_FAKE = base.FAKE_KUBECTL.replace(
    'import json, os, re, sys\n', 'import json, os, re, sys, time\n', 1,
).replace(
    '            log("delete-appset", name, mode)\n',
    '            log("delete-appset", name, mode)\n            TIMED.append(name)\n', 1,
).replace(
    'rc = 0\nif verb == "get":', 'TIMED = []\nrc = 0\nif verb == "get":', 1,
).replace(
    'json.dump(st, open(STATE, "w"))\nsys.exit(rc)\n',
    'json.dump(st, open(STATE, "w"))\n'
    'fcntl.flock(_LOCK, fcntl.LOCK_UN)\n'
    'for n in TIMED:\n'
    '    log("t0", n, time.time())\n'
    '    time.sleep(float(os.environ["FAKE_DELAY"]))\n'
    '    log("t1", n, time.time())\n'
    'sys.exit(rc)\n', 1,
)
assert "TIMED.append" in TIMED_FAKE and 'log("t1"' in TIMED_FAKE and "LOCK_UN" in TIMED_FAKE


def _state():
    appsets, apps = {}, {}
    for wave, n in WAVES.items():
        for i in range(n):
            name = f"addon-w{wave}-{i}"
            appsets[name] = {"wave": "", "preserve": True}
            apps[f"{name}-{base.HUB}"] = {"owner": name, "wave": wave,
                                          "finalizers": ["resources-finalizer.argocd.argoproj.io"]}
    return {"appsets": appsets, "apps": apps, "pivoted": False, "broken": False}


def _step7():
    with open(base.TASKFILE) as f:
        task = yaml.safe_load(f)["tasks"]["hub:destroy-addons"]
    text = lambda c: c.get("cmd", "") if isinstance(c, dict) else c
    cmd = next(c for c in task["cmds"] if 'SKIP="{{.INFRA_STACK}}' in text(c))
    return task["vars"], cmd


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    if not TASK:
        pytest.skip("go-task not on PATH")
    tmp = tmp_path_factory.mktemp("destroy-addons-parallel")
    tvars, cmd = _step7()
    bindir = tmp / "bin"
    bindir.mkdir()
    (bindir / "kubectl").write_text(TIMED_FAKE.replace("{python}", sys.executable))
    (bindir / "sleep").write_text(base.FAKE_SLEEP)
    for f in ("kubectl", "sleep"):
        (bindir / f).chmod(0o755)
    state, log = tmp / "state.json", tmp / "log.jsonl"
    state.write_text(json.dumps(_state()))
    log.write_text("")
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", FAKE_DELAY=str(DELAY),
               FAKE_K8S_STATE=str(state), FAKE_K8S_LOG=str(log))
    tf = tmp / "Taskfile.yml"
    tf.write_text(yaml.safe_dump({
        "version": "3", "set": ["errexit", "nounset", "pipefail"],
        "vars": {k: "" for k in ("C_ERR", "C_RESET", "C_OK", "C_INFO", "C_STEP")},
        "tasks": {"run": {"vars": tvars, "cmds": [cmd]}}}, sort_keys=False))
    t0 = time.time()
    res = subprocess.run([TASK, "-s", "-t", str(tf), "run"], cwd=tmp, env=env,
                         capture_output=True, text=True, timeout=300)
    elapsed = time.time() - t0
    events = [json.loads(line) for line in log.read_text().splitlines()]
    return res, elapsed, events, json.loads(state.read_text())


def _spans(events):
    t0 = {e[1]: e[2] for e in events if e[0] == "t0"}
    t1 = {e[1]: e[2] for e in events if e[0] == "t1"}
    return {n: (t0[n], t1[n]) for n in t0}


def test_exit_code_and_every_addon_gone(run):
    res, _elapsed, _events, st = run
    assert res.returncode == 0, res.stdout + res.stderr
    assert st["appsets"] == {}, f"ApplicationSets left: {sorted(st['appsets'])}"
    assert st["apps"] == {}, f"Applications left: {sorted(st['apps'])}"


def test_waves_never_overlap_and_go_in_descending_order(run):
    spans = _spans(run[2])
    assert len(spans) == sum(WAVES.values())
    waves = sorted(WAVES, key=int, reverse=True)
    for hi, lo in zip(waves, waves[1:]):
        end_hi = max(e for n, (_s, e) in spans.items() if n.startswith(f"addon-w{hi}-"))
        start_lo = min(s for n, (s, _e) in spans.items() if n.startswith(f"addon-w{lo}-"))
        assert end_hi <= start_lo, f"wave {lo} started before wave {hi} was gone"


def test_addons_of_one_wave_run_in_parallel(run):
    res, elapsed, events, _st = run
    sequential = sum(WAVES.values()) * DELAY
    # 5 batches of DELAY plus process start-up; far below the sequential 18 x DELAY.
    assert elapsed < sequential * 0.6, f"{elapsed:.1f}s, sequential would be {sequential:.0f}s"
    assert "step 7: wave 0 done" in res.stdout, res.stdout


def test_parallelism_is_capped(run):
    spans = _spans(run[2])
    points = sorted([(s, 1) for s, _e in spans.values()] + [(e, -1) for _s, e in spans.values()],
                    key=lambda p: (p[0], p[1]))
    cur = peak = 0
    for _t, d in points:
        cur += d
        peak = max(peak, cur)
    assert peak <= 8, f"{peak} addons deleted at once (cap 8)"
