"""The provider Taskfiles run every cmd with `set: [errexit, nounset, pipefail]` under
go-task's shell interpreter (mvdan/sh). There, a `for`/`while` loop whose last statement
is a false `[ ... ] && X=...` list makes the loop fail, and errexit then ends the whole
cmd. With `ignore_error: true` nothing is printed: every step after the loop is skipped.
bash does not do this, so a bash-only harness can't see it (#1061, seen live in 6ei).

1. A static check: in the `destroy` tasks of both providers, no loop body ends with a
   `[ ... ] && ...` line. Write `if [ ... ]; then ...; fi` instead.
2. If a go-task binary is on PATH, a live check that the pattern really aborts under it
   and that the `if` form doesn't, so the static rule keeps matching go-task's behaviour.

Run:  python -m pytest workshop/scripts/tests/test_destroy_loop_errexit.py -q
"""
import os
import re
import shutil
import subprocess

import pytest

yaml = pytest.importorskip("yaml")

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
PROVIDERS = ("kind-kro-ack", "kind-crossplane")
LOOP_START = re.compile(r"(^|[;\s])do\s*$")  # `for ...; do`, `...); do` on a continuation line, or a bare `do`
LOOP_END = re.compile(r"^\s*done\b")
AND_LIST = re.compile(r"^\s*\[\[? .*\]\]?\s*&&(?!.*\|\|)")  # `... || true` already ends with status 0


def destroy_cmds(provider):
    with open(os.path.join(REPO, "cluster-providers", provider, "Taskfile.yaml")) as f:
        tasks = yaml.safe_load(f)["tasks"]
    for name, task in tasks.items():
        if "destroy" not in name or not isinstance(task, dict):
            continue
        for i, cmd in enumerate(task.get("cmds") or []):
            text = cmd.get("cmd") if isinstance(cmd, dict) else cmd
            if isinstance(text, str):
                yield f"{name}[{i}]", text


def loop_final_and_lists(text):
    """Lines that are the last statement of a loop body and are a `[ ] && ...` list."""
    hits, depth, last = [], 0, {}
    for line in text.splitlines():
        if not line.strip() or line.strip().startswith("#"):
            continue
        if LOOP_END.match(line) and depth:
            if AND_LIST.match(last.get(depth, "")):
                hits.append(last[depth].strip())
            depth -= 1
            continue
        if LOOP_START.search(line):
            depth += 1
            last[depth] = ""
            continue
        if depth:
            last[depth] = line
    return hits


@pytest.mark.parametrize("provider", PROVIDERS)
def test_no_loop_ends_with_and_list(provider):
    bad = []
    for where, text in destroy_cmds(provider):
        bad += [f"{where}: {h}" for h in loop_final_and_lists(text) or []]
    assert not bad, "loop body ends with a `[ ] &&` list (aborts under go-task errexit):\n" + "\n".join(bad)


TASK = shutil.which("task")


@pytest.mark.skipif(not TASK, reason="go-task not on PATH")
def test_go_task_aborts_on_loop_final_and_list(tmp_path):
    (tmp_path / "Taskfile.yml").write_text(
        "version: '3'\n"
        "set: [errexit, nounset, pipefail]\n"
        "tasks:\n"
        "  and-form:\n"
        "    cmds:\n"
        "      - cmd: |\n"
        "          O=''\n"
        "          for C in a b; do\n"
        "            [ \"$C\" = a ] && O=\"$O$C\"\n"
        "          done\n"
        "          echo AFTER-$O\n"
        "        ignore_error: true\n"
        "  if-form:\n"
        "    cmds:\n"
        "      - |\n"
        "        O=''\n"
        "        for C in a b; do\n"
        "          if [ \"$C\" = a ]; then O=\"$O$C\"; fi\n"
        "        done\n"
        "        echo AFTER-$O\n")
    run = lambda t: subprocess.run([TASK, "-s", t], cwd=tmp_path, capture_output=True, text=True).stdout
    assert "AFTER-" not in run("and-form")
    assert "AFTER-a" in run("if-form")
