"""Hermetic tests for the argocd capability gate of hub:apply-root-appset (kind-kro-ack).

The step polls `aws eks describe-capability` until the argocd capability is ACTIVE before the
10-min wait for its CRDs. The provider Taskfile runs every cmd with
`set: [errexit, nounset, pipefail]` under go-task's own shell interpreter (mvdan/sh), not
bash. There, a false `[ ... ] && X` that ends a case arm or a loop body aborts the whole
cmd, where bash carries on (#1255 review). So the behaviour tests run the REAL task through
go-task, from a copy of the repo layout, as `task kind-kro-ack:hub:apply-root-appset`,
against a fake `aws` (scripted statuses), a fake `kubectl` and a no-op `sleep`.
No AWS, no cluster.

Run:  python -m pytest workshop/scripts/tests/test_argocd_capability_wait.py -q
"""
import os
import re
import shutil
import subprocess

import pytest

yaml = pytest.importorskip("yaml")

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
TASKFILE = os.path.join(REPO, "cluster-providers", "kind-kro-ack", "Taskfile.yaml")
TASK = shutil.which("task")
TASK_EXIT_CMD_FAILED = 201  # go-task's exit code when one of the task's cmds fails

CONFIG = 'aws: {region: us-west-2, accountId: "111122223333"}\nhub: {clusterName: acme-hub}\n'
# Each describe-capability call pops the next scripted status; "ERR" = the CLI fails (no
# output, rc 255). Every other aws call (sts, update-kubeconfig) succeeds silently.
FAKE_AWS = """#!/usr/bin/env bash
echo "aws $*" >> "$T/calls"
case "$1 $2" in
  "eks describe-capability")
    S=$(head -1 "$T/statuses"); sed -i 1d "$T/statuses"
    [ "$S" = ERR ] && exit 255
    echo "${S:-ACTIVE}" ;;
  "sts get-caller-identity") echo "arn:aws:iam::111122223333:role/test" ;;
  *) exit 0 ;;
esac
"""
FAKE_KUBECTL = '#!/usr/bin/env bash\necho "kubectl $*" >> "$T/calls"\nexit 0\n'


def _block():
    cmds = yaml.safe_load(open(TASKFILE))["tasks"]["hub:apply-root-appset"]["cmds"]
    blocks = [c for c in cmds if isinstance(c, str) and "describe-capability" in c]
    assert len(blocks) == 1, blocks
    return blocks[0]


def test_no_case_arm_or_loop_body_ends_with_an_and_list():
    """Static guard, no go-task needed: a `[ ... ] && ...` that ends a case arm (`... ;;`)
    or is the last line before `done` is the pattern that aborts under go-task errexit."""
    lines = [ln.strip() for ln in _block().splitlines() if ln.strip() and not ln.strip().startswith("#")]
    bad = [ln for ln in lines if re.search(r"\]\s*&&[^;]*;;\s*$", ln)]
    bad += [prev for prev, ln in zip(lines, lines[1:])
            if ln.startswith("done") and re.match(r"^\[\[? .*\]\]?\s*&&", prev)]
    assert not bad, "use `if ...; then ...; fi` instead of a trailing `[ ] &&`:\n" + "\n".join(bad)


def _run(tmp_path, statuses):
    if not (TASK and shutil.which("yq")):
        pytest.skip("needs go-task and yq on PATH")
    root = tmp_path / "repo"
    root.mkdir()
    shutil.copy(os.path.join(REPO, "Taskfile.yaml"), root / "Taskfile.yaml")
    shutil.copytree(os.path.join(REPO, "cluster-providers"), root / "cluster-providers")
    shutil.copytree(os.path.join(REPO, "gitops", "addons", "registry"),
                    root / "gitops" / "addons" / "registry")
    (root / "gitops" / "bootstrap").mkdir(parents=True)
    (root / "gitops" / "bootstrap" / "root-appset.yaml").write_text("")
    (root / "config.local.yaml").write_text(CONFIG)
    (tmp_path / "statuses").write_text("\n".join(statuses) + "\n")
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    for name, body in (("aws", FAKE_AWS), ("kubectl", FAKE_KUBECTL),
                       ("sleep", "#!/usr/bin/env bash\nexit 0\n")):
        (bin_ / name).write_text(body)
        os.chmod(bin_ / name, 0o755)
    env = dict(os.environ, PATH=f"{bin_}:{os.environ['PATH']}", T=str(tmp_path))
    r = subprocess.run([TASK, "-d", str(root), "kind-kro-ack:hub:apply-root-appset"],
                       cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120)
    calls = (tmp_path / "calls").read_text().splitlines() if (tmp_path / "calls").exists() else []
    cap = [c for c in calls if "describe-capability" in c]
    applied = any(c.startswith("kubectl apply -f") and "root-appset.yaml" in c for c in calls)
    return r, cap, applied


def test_waits_until_active(tmp_path):
    r, cap, applied = _run(tmp_path, ["CREATING", "CREATING", "CREATING", "ACTIVE"])
    assert r.returncode == 0, r.stdout + r.stderr
    assert len(cap) == 4
    assert all("describe-capability --cluster-name acme-hub --capability-name argocd" in c for c in cap)
    assert "wait done (status=ACTIVE)" in r.stdout
    assert applied


def test_one_read_error_is_retried_not_fatal(tmp_path):
    # The #1255 review case: with `[ "$MISS" -ge 3 ] && break` ending the case arm, go-task
    # exited 201 right after the first failed read and never applied the root appset.
    r, cap, applied = _run(tmp_path, ["ERR", "ACTIVE"])
    assert r.returncode == 0, r.stdout + r.stderr
    assert len(cap) == 2
    assert "wait done (status=ACTIVE)" in r.stdout
    assert applied


def test_stops_on_create_failed(tmp_path):
    r, cap, applied = _run(tmp_path, ["CREATING", "CREATE_FAILED"])
    assert r.returncode == TASK_EXIT_CMD_FAILED and len(cap) == 2
    assert "argocd capability is CREATE_FAILED" in r.stdout
    assert not applied


def test_three_read_errors_fall_through_to_the_crd_wait(tmp_path):
    r, cap, applied = _run(tmp_path, ["ERR", "ERR", "ERR", "ACTIVE"])
    assert r.returncode == 0, r.stdout + r.stderr
    assert len(cap) == 3
    assert "status=unknown" in r.stdout
    assert applied  # the CRD wait (fake kubectl: CRDs served) then applies the root appset


def test_budget_is_bounded(tmp_path):
    r, cap, applied = _run(tmp_path, ["CREATING"] * 400)
    assert r.returncode == 0, r.stdout + r.stderr  # falls through to the CRD wait
    assert len(cap) == 360  # 3600 s / 10 s
    assert applied
