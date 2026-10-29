"""Hermetic tests for kind-kro-ack `config:check-platform-tags`.

`platformTags` is optional (default {}). Without it the hub and the spokes get no
platform-wide AWS tags, which is silent until an account cleanup sweeper reaps them. The
task only WARNS (never fails, never adds a default tag), and `validate` and `hub:claim` call
it, so `task install` shows the warning before the hub is created.

The task's cmds are read verbatim from cluster-providers/kind-kro-ack/Taskfile.yaml and run
under go-task with the Taskfile's `set:` options; the real `yq` reads a temporary config.

Run:  python -m pytest workshop/scripts/tests/test_platform_tags_warning.py -q
"""
import os
import shutil
import subprocess

import pytest

yaml = pytest.importorskip("yaml")

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
TASKFILE = os.path.join(REPO, "cluster-providers", "kind-kro-ack", "Taskfile.yaml")
TASK, YQ = shutil.which("task"), shutil.which("yq")
NAME = "config:check-platform-tags"
COLORS = ("C_ERR", "C_RESET", "C_OK", "C_INFO", "C_STEP", "C_WARN")

pytestmark = pytest.mark.skipif(not (TASK and YQ), reason="go-task and yq required")


def _tasks():
    with open(TASKFILE) as f:
        return yaml.safe_load(f)["tasks"]


def _run(tmp_path, config_text):
    cfg = tmp_path / "config.local.yaml"
    cfg.write_text(config_text)
    tf = tmp_path / "Taskfile.yml"
    tf.write_text(yaml.safe_dump({
        "version": "3", "set": ["errexit", "nounset", "pipefail"],
        "vars": dict({k: "" for k in COLORS}, CONFIG_FILE=str(cfg)),
        "tasks": {"run": {"cmds": _tasks()[NAME]["cmds"]}}}, sort_keys=False))
    return subprocess.run([TASK, "-s", "-t", str(tf), "run"], cwd=tmp_path,
                          capture_output=True, text=True, timeout=60)


@pytest.mark.parametrize("cfg", [
    "hub:\n  clusterName: acme-hub\n",                 # key absent
    "platformTags: {}\n",                              # explicit empty (config.yaml default)
    "platformTags:\n",                                 # null
])
def test_warns_when_no_tags(tmp_path, cfg):
    res = _run(tmp_path, cfg)
    assert res.returncode == 0, res.stdout + res.stderr
    assert "No platformTags in" in res.stdout, res.stdout
    assert 'auto-delete: "no"' in res.stdout, res.stdout


@pytest.mark.parametrize("cfg", [
    'platformTags:\n  auto-delete: "no"\n',
    'platformTags:\n  cost-center: "acme"\n',
])
def test_silent_when_tags_set(tmp_path, cfg):
    res = _run(tmp_path, cfg)
    assert res.returncode == 0, res.stdout + res.stderr
    assert res.stdout.strip() == "", res.stdout


def test_missing_config_is_not_fatal(tmp_path):
    tf = tmp_path / "Taskfile.yml"
    tf.write_text(yaml.safe_dump({
        "version": "3", "set": ["errexit", "nounset", "pipefail"],
        "vars": dict({k: "" for k in COLORS}, CONFIG_FILE=str(tmp_path / "nope.yaml")),
        "tasks": {"run": {"cmds": _tasks()[NAME]["cmds"]}}}, sort_keys=False))
    res = subprocess.run([TASK, "-s", "-t", str(tf), "run"], cwd=tmp_path,
                         capture_output=True, text=True, timeout=60)
    assert res.returncode == 0, res.stdout + res.stderr


@pytest.mark.parametrize("caller", ["validate", "hub:claim"])
def test_called_before_the_hub_is_created(caller):
    cmds = _tasks()[caller]["cmds"]
    names = [c.get("task") for c in cmds if isinstance(c, dict)]
    assert NAME in names, (caller, names)
    if caller == "hub:claim":
        assert cmds.index({"task": NAME}) == 0, "warn before any kubectl apply"


def test_never_writes_a_default_tag():
    body = "\n".join(c if isinstance(c, str) else c.get("cmd", "") for c in _tasks()[NAME]["cmds"])
    assert "kubectl" not in body and "aws " not in body and "yq -i" not in body
