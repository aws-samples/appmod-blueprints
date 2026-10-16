"""Hermetic tests for the last step of `task install` (workshop/Taskfile.yaml): the #1033 hub
pivot gets only what is left of the install's time budget, so it always ends before the
self-paced template's SSM step would kill `task install` (7000 s; a kill skips the pivot's
EXIT trap and leaves kind stopped mid-gate).

The step's shell block is read verbatim from the Taskfile, its go-task variables are filled
in (INSTALL_START = now - elapsed), and it runs with bash. `task` is a fake that records its
arguments, so no pivot runs. No AWS, no cluster.

Run:  python -m pytest workshop/scripts/tests/test_install_pivot_budget.py -q
"""
import os
import re
import shutil
import subprocess
import time

import pytest

yaml = pytest.importorskip("yaml")
if not shutil.which("bash"):
    pytest.skip("bash not available", allow_module_level=True)

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
TASKFILE = os.path.join(REPO, "workshop", "Taskfile.yaml")
FAKE_TASK = '#!/usr/bin/env bash\necho "$*" >> "$FAKE_TASK_LOG"\n'
TEMPLATE_VAR = re.compile(r'\{\{\s*\.([A-Z0-9_]+)\s*(?:\|\s*default\s+"([^"]*)"\s*)?\}\}')


def _pivot_step():
    cmds = yaml.safe_load(open(TASKFILE))["tasks"]["install"]["cmds"]
    steps = [c["cmd"] for c in cmds if isinstance(c, dict) and "hub:pivot" in c.get("cmd", "")]
    assert len(steps) == 1, steps
    return steps[0]


def _run(tmp_path, elapsed, **task_vars):
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    (bindir / "task").write_text(FAKE_TASK)
    (bindir / "task").chmod(0o755)
    values = {"PROVIDER": "kind-kro-ack", "PLATFORM_DIR": str(tmp_path),
              "INSTALL_START": str(int(time.time()) - elapsed),
              "C_STEP": "", "C_OK": "", "C_ERR": "", "C_INFO": "", "C_RESET": ""}
    values.update(task_vars)

    def fill(m):
        name, default = m.group(1), m.group(2)
        return values[name] if name in values else (default if default is not None else "")

    script = TEMPLATE_VAR.sub(fill, _pivot_step())
    assert "{{" not in script, re.findall(r"\{\{[^}]*\}\}", script)
    (tmp_path / "step.sh").write_text("set -euo pipefail\n" + script)
    log = tmp_path / "task.log"
    res = subprocess.run(["bash", str(tmp_path / "step.sh")], capture_output=True, text=True,
                         env=dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}",
                                  FAKE_TASK_LOG=str(log)), timeout=60)
    assert res.returncode == 0, res.stdout + res.stderr
    calls = log.read_text().splitlines() if log.exists() else []
    return calls, res.stdout


def _gate(call):
    m = re.search(r"PIVOT_ADOPT_TIMEOUT_SEC=(\d+)", call)
    assert m, call
    return int(m.group(1))


def test_gate_gets_only_the_remaining_budget(tmp_path):
    # 80 min in: 6600 - 4800 - 300 = 1500 s left for the adoption gate
    calls, _ = _run(tmp_path, elapsed=4800)
    assert len(calls) == 1 and calls[0].startswith("kind-kro-ack:hub:pivot PIVOT_DRY_RUN=false")
    assert 1490 <= _gate(calls[0]) <= 1500


def test_gate_is_capped_at_the_provider_timeout(tmp_path):
    # a short re-run of `task install` keeps the provider's 1800 s, or an explicit override
    calls, _ = _run(tmp_path, elapsed=600)
    assert _gate(calls[0]) == 1800
    calls, _ = _run(tmp_path, elapsed=600, PIVOT_ADOPT_TIMEOUT_SEC="900")
    assert _gate(calls[-1]) == 900


def test_pivot_is_skipped_when_the_budget_is_used_up(tmp_path):
    # the 2026-10-15 fresh install reached the pivot 6557 s in, 7 min before the SSM kill
    calls, out = _run(tmp_path, elapsed=6557)
    assert calls == []
    assert "hub pivot skipped (non-fatal)" in out
    # a larger budget (another template, or a manual install) still pivots
    calls, _ = _run(tmp_path, elapsed=6557, INSTALL_BUDGET_SEC="99999")
    assert _gate(calls[0]) == 1800
