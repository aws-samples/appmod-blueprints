"""Hermetic tests for the IDE SharedRole lookup in `spokes:enable-kro` and
`spokes:enable-crossplane` (workshop/Taskfile.yaml).

Each spoke gets a cluster-admin access entry for the IDE's instance role, found by
listing the account's roles whose name contains `SharedRole`. With two workshop stacks
in one account the first match by name can be the other stack's role: the spokes then
grant the other stack's IDE admin and this stack's IDE no access at all, so the
destroy's Phase 1 drain (kubectl from the IDE) silently does nothing. The lookup must
prefer this stack's own role (`<prefix>-workshop…`) and keep the first match otherwise.

The `INSTANCE_ROLE=$(aws iam list-roles …)` line of each task is read verbatim from the
Taskfile and run under go-task's own interpreter with the Taskfile's `set:` options
(bash with the same options if go-task is not on PATH), against a fake `aws` that
prints the already-filtered ListRoles result. No AWS, no network.

Run:  python -m pytest workshop/scripts/tests/test_spoke_admin_instance_role.py -q
"""
import json
import os
import shutil
import subprocess

import pytest

yaml = pytest.importorskip("yaml")
for _tool in ("bash", "jq"):
    if not shutil.which(_tool):
        pytest.skip(f"{_tool} not available", allow_module_level=True)

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
TASKFILE = os.path.join(REPO, "workshop", "Taskfile.yaml")
TASKS = ("spokes:enable-kro", "spokes:enable-crossplane")
TASK = shutil.which("task")

FAKE_AWS = """#!/usr/bin/env bash
[ "$1 $2" = "iam list-roles" ] && { cat "$FAKE_ROLES"; exit 0; }
echo "unexpected aws call: $*" >&2; exit 1
"""

STACK1 = "peeks-workshop-main-PEEKSSharedRole61C60677-aaaa"
STACK2 = "tdv-workshop-PEEKSSharedRole61C60677-bbbb"


def _taskfile():
    with open(TASKFILE) as f:
        return yaml.safe_load(f)


def _lookup_line(task):
    cmds = _taskfile()["tasks"][task]["cmds"]
    body = "\n".join(c if isinstance(c, str) else c.get("cmd", "") for c in cmds)
    lines = [l.strip() for l in body.splitlines()
             if l.strip().startswith("INSTANCE_ROLE=$(aws iam list-roles")]
    assert len(lines) == 1, (task, lines)
    return lines[0]


def _run(tmp_path, task, prefix, roles):
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    (bindir / "aws").write_text(FAKE_AWS)
    (bindir / "aws").chmod(0o755)
    (tmp_path / "roles.json").write_text(json.dumps(roles))
    line = _lookup_line(task)
    show = 'printf "%s" "$INSTANCE_ROLE"'
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}",
               FAKE_ROLES=str(tmp_path / "roles.json"))
    opts = _taskfile().get("set", [])
    if TASK:
        tf = tmp_path / "Taskfile.yml"
        tf.write_text(yaml.safe_dump({
            "version": "3", "set": opts, "vars": {"RESOURCE_PREFIX": prefix},
            "tasks": {"run": {"cmds": [{"cmd": line + "\n" + show}]}}}, sort_keys=False))
        r = subprocess.run([TASK, "-s", "-t", str(tf), "run"], cwd=tmp_path, env=env,
                           capture_output=True, text=True, timeout=60)
    else:
        script = tmp_path / "lookup.sh"
        script.write_text("".join(f"set -o {o}\n" for o in opts)
                          + line.replace("{{.RESOURCE_PREFIX}}", prefix) + "\n" + show + "\n")
        r = subprocess.run(["bash", str(script)], cwd=tmp_path, env=env,
                           capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return r.stdout


@pytest.mark.parametrize("task", TASKS)
def test_second_stack_gets_its_own_role(tmp_path, task):
    # ListRoles sorts by name, so stack 1's role comes first for a prefix after "peeks".
    assert _run(tmp_path, task, "tdv", [STACK1, STACK2]) == STACK2


@pytest.mark.parametrize("task", TASKS)
def test_first_stack_keeps_its_role(tmp_path, task):
    assert _run(tmp_path, task, "peeks", [STACK1, STACK2]) == STACK1


@pytest.mark.parametrize("task", TASKS)
def test_no_prefix_match_keeps_first_match(tmp_path, task):
    # e.g. a stack not named <prefix>-workshop…: same result as before.
    assert _run(tmp_path, task, "peeks", ["ws-PEEKSSharedRole-1", "zz-SharedRole-2"]) == "ws-PEEKSSharedRole-1"


@pytest.mark.parametrize("task", TASKS)
def test_no_shared_role(tmp_path, task):
    assert _run(tmp_path, task, "peeks", []) == ""
