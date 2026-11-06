"""Hermetic timing test for workshop `destroy`: Phase 2 (spokes:disable-all) runs in the
background alongside Phase 2.5 (DevLake RDS), and is waited for before Phase 3.

Live: Phase 2 took ~435 s (waiting on the spoke clusters) and Phase 2.5 ~701 s (waiting on
the RDS delete), one after the other. Both only need the hub controllers alive.

The destroy cmds from Phase 2 to just before Phase 3 are read verbatim from
workshop/Taskfile.yaml and run under go-task with `set: [errexit, nounset, pipefail]`.
Phase 2.5's own script is replaced by a stand-in that sleeps, and spokes:disable-all by a
task that sleeps then exits with FAKE_P2_RC: real (short) sleeps, wall-clock measured.

Run:  python -m pytest workshop/scripts/tests/test_destroy_phase2_parallel.py -q
Set WORKSHOP_TASKFILE=<path> to run the same checks against another Taskfile.
"""
import os
import shutil
import subprocess
import time

import pytest

yaml = pytest.importorskip("yaml")

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
WORKSHOP_TF = os.environ.get("WORKSHOP_TASKFILE") or os.path.join(REPO, "workshop", "Taskfile.yaml")
TASK = shutil.which("task")
P2, P25 = 4.0, 4.0  # > the 2 s poll of the wait, so overlap shows


def _text(c):
    return c.get("cmd", "") if isinstance(c, dict) else (c if isinstance(c, str) else "")


def _slice():
    cmds = yaml.safe_load(open(WORKSHOP_TF))["tasks"]["destroy"]["cmds"]
    is_mark = lambda c: _text(c).startswith("{{.DESTROY_MARK}}")
    i2 = next(i for i, c in enumerate(cmds) if "Phase 2 — deleting spoke clusters" in _text(c))
    i25 = next(i for i, c in enumerate(cmds) if "Phase 2.5 —" in _text(c))
    i3 = next(i for i, c in enumerate(cmds) if "Phase 3 —" in _text(c))
    before = [c for c in cmds[i2:i25] if not is_mark(c)]
    after = [c for c in cmds[i25 + 1:i3] if not is_mark(c)]
    return before, after


def _run(tmp, p2_rc=0):
    if not TASK:
        pytest.skip("go-task not on PATH")
    before, after = _slice()
    stand_in = f"echo P25-START; sleep {P25}; echo P25-END"
    tvars = {k: "" for k in ("C_ERR", "C_RESET", "C_OK", "C_INFO", "C_STEP")}
    tvars["REPO"] = str(tmp)
    tf = {"version": "3", "set": ["errexit", "nounset", "pipefail"], "vars": tvars, "tasks": {
        "run": {"cmds": before + [stand_in] + after + ["echo PHASE3"]},
        "spokes:disable-all": {"cmds": [f"echo P2-START; sleep {P2}; echo P2-END; exit {p2_rc}"]},
    }}
    (tmp / "Taskfile.yml").write_text(yaml.safe_dump(tf, sort_keys=False))
    t0 = time.time()
    res = subprocess.run([TASK, "-s", "run"], cwd=tmp, capture_output=True, text=True, timeout=120)
    return res, time.time() - t0


def test_phase2_overlaps_phase25_and_is_done_before_phase3(tmp_path):
    res, elapsed = _run(tmp_path)
    out = res.stdout
    assert res.returncode == 0, out + res.stderr
    assert elapsed < P2 + P25, f"{elapsed:.1f}s: Phase 2 and 2.5 ran one after the other"
    assert out.index("P2-END") < out.index("PHASE3"), out


def test_phase2_failure_still_stops_the_destroy(tmp_path):
    res, _elapsed = _run(tmp_path, p2_rc=3)
    assert res.returncode != 0
    assert "PHASE3" not in res.stdout
    assert "P2-END" in res.stdout, "Phase 2's output was not shown"
