"""Hermetic test for install perf R10: spokes:enable-kro asks the clusters-kro and fleet-secrets
ApplicationSets to re-read git right after it pushes the spoke into fleet-config.

The whole task block runs under bash with fake git / aws / kubectl / sleep on PATH (real yq and
jq). The fake git models a fleet-config clone; `diff --cached --quiet` exits 1 (changes) unless
NOCHANGE is set, and `push` fails PUSH_FAILS times first. No cluster, no network.

Asserts: refresh after a successful push (both appsets, annotation, ordering after the push),
no refresh when nothing was pushed (idempotent re-run) or when the push failed, and that a
failing kubeconfig or annotate never fails the task.

Run:  python -m pytest workshop/scripts/tests/test_install_r10_appset_refresh.py -q
"""
import os
import re
import shutil
import subprocess

import pytest

yaml = pytest.importorskip("yaml")
for tool in ("bash", "yq", "jq"):
    if not shutil.which(tool):
        pytest.skip(f"{tool} required", allow_module_level=True)

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
TASKFILE = os.path.join(REPO, "workshop", "Taskfile.yaml")
ANNOT = "argocd.argoproj.io/application-set-refresh=true"


def block(tmp_path):
    b = yaml.safe_load(open(TASKFILE))["tasks"]["spokes:enable-kro"]["cmds"][0]
    mark = tmp_path / "mark.sh"
    mark.write_text('#!/bin/sh\necho "$@" >> "$T/marks"\n')
    subs = {"CLUSTER": "p-spoke-prod", "CLUSTER_PROVIDER": "kind-kro-ack", "CONFIG_FILE": str(tmp_path / "cfg.yaml"),
            "GIT_DOMAIN": "git.example", "GIT_PASSWORD": "pw", "GIT_USERNAME": "user1",
            "HUB_CLUSTER_NAME": "hub", "AWS_REGION": "us-east-1", "AWS_ACCOUNT_ID": "111111111111",
            "K8S_VERSION": "1.35", "RESOURCE_PREFIX": "p", "MARK": f"sh {mark}"}
    for k, v in subs.items():
        b = b.replace("{{.%s}}" % k, v)
    return re.sub(r"\{\{\s*\.C_[A-Z]+\s*\}\}", "", b)


def run(tmp_path, nochange=False, push_fails=0, kubeconfig_fails=False, annotate_fails=False):
    (tmp_path / "cfg.yaml").write_text("adminRoleName: WSParticipantRole\n")
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    fakes = {
        "git": '#!/usr/bin/env bash\n'
               'echo "git $*" >> "$T/events"\n'
               'case "$1" in\n'
               '  clone) mkdir -p "${@: -1}/.git";;\n'
               f'  diff) [ "{int(nochange)}" = 1 ] && exit 0 || exit 1;;\n'
               '  push) N=$(cat "$T/pushes" 2>/dev/null || echo 0); N=$((N+1)); echo $N > "$T/pushes"\n'
               f'        [ "$N" -le {push_fails} ] && exit 1; exit 0;;\n'
               'esac\nexit 0\n',
        "aws": '#!/usr/bin/env bash\n'
               'case "$*" in\n'
               f'  *update-kubeconfig*) echo "aws update-kubeconfig" >> "$T/events"; [ "{int(kubeconfig_fails)}" = 1 ] && exit 255; exit 0;;\n'
               '  *list-roles*) echo "[]";;\n'
               'esac\nexit 0\n',
        "kubectl": '#!/usr/bin/env bash\n'
                   'echo "kubectl $*" >> "$T/events"\n'
                   f'case "$*" in *annotate*) [ "{int(annotate_fails)}" = 1 ] && exit 1;; esac\nexit 0\n',
        "sleep": "#!/usr/bin/env bash\nexit 0\n",
    }
    for n, body in fakes.items():
        (bin_ / n).write_text(body)
        os.chmod(bin_ / n, 0o755)
    home = tmp_path / "home"
    home.mkdir()
    env = dict(os.environ, PATH=f"{bin_}:{os.environ['PATH']}", T=str(tmp_path), HOME=str(home))
    r = subprocess.run(["bash", "-c", block(tmp_path)], env=env, capture_output=True, text=True, timeout=120)
    ev = (tmp_path / "events").read_text().splitlines() if (tmp_path / "events").exists() else []
    marks = (tmp_path / "marks").read_text().splitlines() if (tmp_path / "marks").exists() else []
    return r, ev, marks


def annotated(ev):
    return [e for e in ev if e.startswith("kubectl") and "annotate" in e]


def test_refresh_after_push_both_appsets(tmp_path):
    r, ev, marks = run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    a = annotated(ev)
    assert len(a) == 2 and all(ANNOT in x and "-n argocd" in x for x in a)
    assert "applicationsets.argoproj.io clusters-kro" in a[0] and "applicationsets.argoproj.io fleet-secrets" in a[1]
    push = max(i for i, e in enumerate(ev) if e.startswith("git push"))
    assert ev.index(a[0]) > push, "refresh must come after the push"
    assert any("refresh=ok" in m and m.startswith("done") for m in marks), marks
    assert any(m.startswith("start") and "appset refresh after push" in m for m in marks)


def test_no_refresh_when_nothing_was_pushed(tmp_path):
    r, ev, marks = run(tmp_path, nochange=True)
    assert r.returncode == 0 and annotated(ev) == [] and marks == []
    assert not any(e.startswith("git push") for e in ev)


def test_push_retry_then_success_refreshes_once(tmp_path):
    r, ev, _ = run(tmp_path, push_fails=2)
    assert r.returncode == 0 and len(annotated(ev)) == 2


def test_no_refresh_when_push_fails_and_task_fails(tmp_path):
    r, ev, _ = run(tmp_path, push_fails=99)
    assert r.returncode == 1 and annotated(ev) == []


def test_kubeconfig_failure_is_not_fatal(tmp_path):
    r, ev, marks = run(tmp_path, kubeconfig_fails=True)
    assert r.returncode == 0 and annotated(ev) == []
    assert any("refresh=failed" in m for m in marks), marks
    assert "enabled via KRO" in r.stdout


def test_annotate_failure_is_not_fatal(tmp_path):
    r, ev, marks = run(tmp_path, annotate_fails=True)
    assert r.returncode == 0 and len(annotated(ev)) == 2
    assert any("refresh=partial" in m for m in marks), marks
    assert "enabled via KRO" in r.stdout


def test_temp_kubeconfig_removed(tmp_path):
    tmpdir = tmp_path / "tmpd"
    tmpdir.mkdir()
    os.environ["TMPDIR"] = str(tmpdir)
    try:
        run(tmp_path)
    finally:
        del os.environ["TMPDIR"]
    assert list(tmpdir.iterdir()) == []
