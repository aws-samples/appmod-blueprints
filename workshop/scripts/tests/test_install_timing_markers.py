"""Hermetic tests for the install timing markers (scripts/install-timing.sh).

`task install` brackets every foreground step, background job and waiter with a
`start` / `done took=Ns` marker, printed and appended to one timing log, so a Gantt
of the whole install can be rebuilt from that log alone. These tests check the
script's line format and lane semantics, and that the install DAG keeps a marker
for each step. No AWS, no cluster.

Run:  python -m pytest workshop/scripts/tests/test_install_timing_markers.py -q
"""
import os
import re
import shutil
import subprocess

import pytest

yaml = pytest.importorskip("yaml")
if not shutil.which("sh"):
    pytest.skip("sh not available", allow_module_level=True)

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SCRIPT = os.path.join(REPO, "scripts", "install-timing.sh")
LINE = re.compile(r"^\[\d+s\] .+ (start|done( took=\d+s)?.*) @\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")


def _run(tmp_path, *args, env=None):
    e = dict(os.environ, INSTALL_TIMING_LOG=str(tmp_path / "t.log"))
    e.pop("INSTALL_TIMING_T0", None)
    e.update(env or {})
    r = subprocess.run(["sh", SCRIPT, *args], env=e, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout


def _log(tmp_path):
    return (tmp_path / "t.log").read_text().splitlines()


def test_step_closes_previous_and_carries_duration(tmp_path):
    _run(tmp_path, "reset", "1000")
    _run(tmp_path, "step", "w", "hub:wait-for-eks")
    _run(tmp_path, "step", "w", "join prewarm Phase A")  # multi-word names
    _run(tmp_path, "step", "w", "-")
    lines = _log(tmp_path)
    got = [re.sub(r"took=\d+s", "took=Ns", ln.split(" @")[0].split("] ", 1)[1]) for ln in lines]
    assert got == [
        "hub:wait-for-eks start",
        "hub:wait-for-eks done took=Ns",
        "join prewarm Phase A start",
        "join prewarm Phase A done took=Ns",
    ]
    assert all(LINE.match(ln) for ln in lines), lines


def test_background_done_keeps_extra_fields(tmp_path):
    _run(tmp_path, "reset")
    _run(tmp_path, "start", "ray:vllm-image (bg)")
    _run(tmp_path, "done", "ray:vllm-image (bg)", "rc=0")
    assert re.search(r"ray:vllm-image \(bg\) done took=\d+s rc=0 @", _log(tmp_path)[-1])


def test_init_does_not_reset_a_running_install(tmp_path):
    _run(tmp_path, "reset", "1000")
    _run(tmp_path, "start", "a")
    _run(tmp_path, "init", "2000", env={"INSTALL_TIMING_T0": "1000"})
    assert len(_log(tmp_path)) == 1  # the workshop's log survives the platform's init


def test_never_fails(tmp_path):
    _run(tmp_path, "bogus")
    _run(tmp_path, "done", "never-started")


def _cmds(path, task):
    return yaml.safe_load(open(os.path.join(REPO, path)))["tasks"][task]["cmds"]


def _text(cmds):
    return "\n".join(c if isinstance(c, str) else c.get("cmd", "") for c in cmds)


def test_every_install_task_call_has_a_step_marker():
    for path, task, lane in [
        ("cluster-providers/kind-kro-ack/Taskfile.yaml", "install:hub", "hub"),
        ("cluster-providers/kind-kro-ack/Taskfile.yaml", "install:complete", "hub"),
        ("cluster-providers/kind-kro-ack/Taskfile.yaml", "install:finalize", "finalize"),
        ("workshop/Taskfile.yaml", "install", "workshop"),
    ]:
        cmds = _cmds(path, task)
        for i, c in enumerate(cmds):
            if isinstance(c, dict) and "task" in c:
                prev = cmds[i - 1]
                assert isinstance(prev, str) and f"step {lane} " in prev, (path, c)
        assert f"step {lane} -" in _text(cmds), (path, task)


def test_background_jobs_and_waiters_log_their_end():
    wk = open(os.path.join(REPO, "workshop", "Taskfile.yaml")).read()
    kk = open(os.path.join(REPO, "cluster-providers", "kind-kro-ack", "Taskfile.yaml")).read()
    ray = open(os.path.join(REPO, "cluster-providers", "common", "Taskfile.ray.yaml")).read()
    for text, name in [
        (wk, "gitlab:init-ec2 (bg)"),
        (wk, "prewarm Phase A (bg)"),
        (wk, "spoke apps + frontend prewarm (bg)"),
        (wk, "cloudfront:attach (bg)"),
        (wk, "observability re-seed (bg)"),
        (wk, "wait-for-spokes: $S ACTIVE"),
        (wk, "wait-for-spokes: spoke apps"),
        (kk, "hub:settle (bg)"),
        (kk, "observability-seed (bg)"),
        (ray, "ray:vllm-image (bg)"),
    ]:
        assert re.search(r"start ['\"]" + re.escape(name), text), name
        assert re.search(r"done ['\"]" + re.escape(name), text), name
    assert "dump" in _text(_cmds("workshop/Taskfile.yaml", "install"))


def test_step_labels_are_plain_shell_words():
    # A `step` marker is an unquoted shell command line: a label with ( ) ; & | < > $ `
    # breaks the go-task shell parser and aborts the install (seen live).
    bad = re.compile(r"[()&;|<>`$]")
    for path in ("workshop/Taskfile.yaml", "cluster-providers/kind-kro-ack/Taskfile.yaml", "Taskfile.yaml"):
        for line in open(os.path.join(REPO, path)):
            m = re.search(r"install-timing\.sh\"? step \S+ (.*?)'?$|\{\{\.MARK\}\} step \S+ (.*?)'$", line.strip())
            if m:
                label = (m.group(1) or m.group(2) or "").replace("{{.PROVIDER_SPOKE}}", "x").replace(
                    "{{.RESOURCE_PREFIX}}", "x").replace("{{.PROVIDER}}", "x")
                assert not bad.search(label), (path, line.strip())
