"""Prewarm Phase A must scaffold under go-task's OWN shell, and fail visibly.

prewarm-rust-cicd-phase-a used to source scripts/validation/backstage-auth.sh into the
go-task cmd shell and call backstage_scaffolder there. go-task runs cmds with its built-in
POSIX interpreter (mvdan/sh), not bash, and the helper's subshell-bodied functions
(`f() ( local ...; ... )`) die there with "local: can only be used in a function" before
any HTTP call. Phase A therefore never scaffolded; its output went to /dev/null, it
exited 0 and Phase B did the work. The other prewarm tests render the cmd and run it with
bash, which is why they never saw it: the Phase A tests here run the real `task` binary.

Also covered (bash harness, like the other prewarm tests): prewarm-rust-cicd says loudly
when it falls back for a failed Phase A, and does not scaffold a second time while
Phase A is still running.

Run:  python -m pytest workshop/scripts/tests/test_prewarm_phase_a_gotask.py -q
"""
import os
import shutil
import subprocess

import pytest

yaml = pytest.importorskip("yaml")
from test_prewarm_rust_waits import REPO, VARS, fakes, lines, render, run  # noqa: E402

BSAUTH = os.path.join(REPO, "scripts", "validation", "backstage-auth.sh")


def task_bin():
    t = os.environ.get("TASK_BIN") or shutil.which("task") or shutil.which("go-task")
    if not t:
        pytest.skip("go-task binary not available (set TASK_BIN)")
    return t


# Fake curl for the real backstage-auth.sh: Keycloak OIDC login, authenticated catalog
# read, scaffolder POST and task status. Behaviour comes from files in $FAKE_T.
FAKE_CURL = r'''#!/usr/bin/env bash
C=$(cat "$FAKE_T/clock"); echo "$C curl $*" >> "$FAKE_T/curl.calls"
get() { cat "$FAKE_T/$1" 2>/dev/null || echo "$2"; }
out=""; hdr=""; wfmt=""; url=""
while [ $# -gt 0 ]; do
  case "$1" in
    -o) out="$2"; shift ;; -D) hdr="$2"; shift ;; -w) wfmt="$2"; shift ;;
    -X|-c|-b|-H|-d|--data-urlencode|--max-time|--max-redirs) shift ;;
    http*) url="$1" ;;
  esac; shift
done
[ -n "$hdr" ] && printf 'location: https://kc.example/next\r\n' > "$hdr"
case "$url" in
  */api/catalog/entities/by-name/*)
    if [ "$C" -ge "$(get bs_up_at 0)" ]; then printf 200; else printf 503; fi; exit 0 ;;
  */api/scaffolder/v2/tasks)
    echo "$C post" >> "$FAKE_T/post.calls"
    code=$(get post_code 201)
    case "$code" in 2??) printf '{"id":"t1"}' ;; *) printf '{"error":"nope"}' ;; esac
    printf '\n%s' "$code"; exit 0 ;;
  */api/scaffolder/v2/tasks/t1)
    s=$(get task_status completed); [ "$s" = completed ] && touch "$FAKE_T/scaffolded"
    printf '{"status":"%s"}' "$s"; exit 0 ;;
esac
if [ -n "$out" ] && [ "$out" != /dev/null ]; then
  case "$out" in
    *_bs_s3.txt) echo '<form action="https://kc.example/login">' > "$out" ;;
    *_bs_frame.txt) echo "decodeURIComponent('%7B%22response%22%3A%7B%22backstageIdentity%22%3A%7B%22token%22%3A%22TOK%22%7D%7D%7D')" > "$out" ;;
    *) : > "$out" ;;
  esac
fi
exit 0
'''


def run_phase_a(tmp_path, **files):
    b, plat = fakes(tmp_path)
    shutil.copy(BSAUTH, plat / "scripts" / "validation" / "backstage-auth.sh")   # the REAL helper
    (b / "curl").write_text(FAKE_CURL)
    os.chmod(b / "curl", 0o755)
    for k, v in files.items():
        (tmp_path / k).write_text(str(v))
    log = tmp_path / "scaffold.log"
    VARS["PHASE_A_SCAFFOLD_LOG"] = str(log)
    try:
        cmd = render("prewarm-rust-cicd-phase-a", plat)
    finally:
        VARS.pop("PHASE_A_SCAFFOLD_LOG", None)
    d = tmp_path / "tf"
    d.mkdir()
    (d / "Taskfile.yaml").write_text(yaml.safe_dump({"version": "3", "tasks": {"a": {"cmds": [cmd]}}}))
    env = dict(os.environ, PATH=f"{b}:{os.environ['PATH']}", FAKE_T=str(tmp_path), HOME=str(tmp_path))
    r = subprocess.run([task_bin(), "-s", "-d", str(d), "a"], env=env,
                       capture_output=True, text=True, timeout=120, cwd=str(tmp_path))
    return r, int((tmp_path / "clock").read_text()), log


def test_phase_a_scaffolds_under_go_task(tmp_path):
    # Before: "scaffolder did not complete cleanly", rc 0, and not a single POST.
    r, _, log = run_phase_a(tmp_path)
    assert "scaffolder task completed" in r.stdout, r.stdout + r.stderr + log.read_text()
    assert "did not complete cleanly" not in r.stdout
    assert len(lines(tmp_path, "post.calls")) == 1
    assert (tmp_path / "scaffolded").exists()
    assert "local: can only be used in a function" not in r.stdout + r.stderr + log.read_text()
    assert r.returncode == 0


def test_phase_a_waits_for_backstage_then_scaffolds(tmp_path):
    r, clock, _ = run_phase_a(tmp_path, bs_up_at=300)
    assert "waiting for Backstage" in r.stdout, r.stdout
    assert "scaffolder task completed" in r.stdout, r.stdout
    posts = lines(tmp_path, "post.calls")
    assert len(posts) == 1 and int(posts[0].split()[0]) >= 300
    assert r.returncode == 0


def test_phase_a_backstage_wait_is_bounded_and_visible(tmp_path):
    r, clock, _ = run_phase_a(tmp_path, bs_up_at=10_000)
    assert "not served by Backstage after" in r.stdout, r.stdout
    assert "Phase B fallback" in r.stdout
    assert lines(tmp_path, "post.calls") == []
    assert r.returncode != 0
    assert "prewarm-rust-cicd-phase-a done" not in r.stdout
    assert clock <= 660, clock


def test_phase_a_post_refused_retries_then_fails_visibly(tmp_path):
    r, _, log = run_phase_a(tmp_path, post_code=500)
    assert len(lines(tmp_path, "post.calls")) == 3            # first try + 2 bounded retries
    assert "scaffold failed (rc=2" in r.stdout, r.stdout
    assert "returned HTTP 500" in r.stdout                    # log tail printed, not discarded
    assert r.returncode != 0
    assert "prewarm-rust-cicd-phase-a done" not in r.stdout


def test_phase_a_failed_task_is_not_resubmitted(tmp_path):
    # A created task that fails may already have published the repo: never POST again.
    r, _, _ = run_phase_a(tmp_path, task_status="failed")
    assert len(lines(tmp_path, "post.calls")) == 1
    assert "scaffold failed (rc=1" in r.stdout, r.stdout
    assert r.returncode != 0


# ── prewarm-rust-cicd (Phase B) ────────────────────────────────────────────────────────
def test_phase_b_fallback_is_loud(tmp_path, monkeypatch):
    rc = tmp_path / "pa.rc"
    rc.write_text("1\n")
    monkeypatch.setitem(VARS, "PHASE_A_RC_FILE", str(rc))
    monkeypatch.setitem(VARS, "PHASE_A_PID_FILE", str(tmp_path / "pa.pid"))
    r, _ = run(tmp_path, "prewarm-rust-cicd")
    assert "PREWARM FALLBACK: Phase A did not scaffold rust (rc=1" in r.stdout, r.stdout
    assert len(lines(tmp_path, "scaffold.calls")) == 1


def test_phase_b_no_second_scaffold_while_phase_a_runs(tmp_path, monkeypatch):
    pid = tmp_path / "pa.pid"
    pid.write_text(str(os.getpid()))                          # a live process, no rc yet
    monkeypatch.setitem(VARS, "PHASE_A_PID_FILE", str(pid))
    monkeypatch.setitem(VARS, "PHASE_A_RC_FILE", str(tmp_path / "pa.rc"))
    r, _ = run(tmp_path, "prewarm-rust-cicd")
    assert "Phase A still running" in r.stdout, r.stdout
    assert lines(tmp_path, "scaffold.calls") == []
    assert "nothing will create the pipeline" not in r.stdout
    assert "waiting for CICDPipeline" in r.stdout
    assert r.returncode == 0


def test_phase_b_standalone_no_fallback_message(tmp_path, monkeypatch):
    monkeypatch.setitem(VARS, "PHASE_A_RC_FILE", str(tmp_path / "absent.rc"))
    monkeypatch.setitem(VARS, "PHASE_A_PID_FILE", str(tmp_path / "absent.pid"))
    r, _ = run(tmp_path, "prewarm-rust-cicd")
    assert "PREWARM FALLBACK" not in r.stdout
    assert len(lines(tmp_path, "scaffold.calls")) == 1


# ── Phase A still running when Phase B starts (the join gave up), then ends ────────────
def run_b_with_late_phase_a(tmp_path, monkeypatch, ends_at, rc, scaffolded=False):
    """Phase A is a live process (this pytest pid) with no rc file; the fake `sleep`
    writes its rc (and, for a successful Phase A, the scaffold) once the virtual clock
    reaches ends_at."""
    b, plat = fakes(tmp_path)
    pid, rcf = tmp_path / "pa.pid", tmp_path / "pa.rc"
    pid.write_text(str(os.getpid()))
    monkeypatch.setitem(VARS, "PHASE_A_PID_FILE", str(pid))
    monkeypatch.setitem(VARS, "PHASE_A_RC_FILE", str(rcf))
    done = f'touch "$FAKE_T/scaffolded"; ' if scaffolded else ""
    (b / "sleep").write_text(
        '#!/usr/bin/env bash\n'
        'C=$(cat "$FAKE_T/clock"); C=$((C + ${1%s})); echo $C > "$FAKE_T/clock"\n'
        f'if [ "$C" -ge {ends_at} ] && [ ! -s "{rcf}" ]; then {done}echo {rc} > "{rcf}"; fi\n')
    env = dict(os.environ, PATH=f"{b}:{os.environ['PATH']}", FAKE_T=str(tmp_path), HOME=str(tmp_path))
    r = subprocess.run(["bash", "-c", render("prewarm-rust-cicd", plat)], env=env,
                       capture_output=True, text=True, timeout=60, cwd=str(tmp_path))
    return r, int((tmp_path / "clock").read_text())


def test_phase_b_falls_back_when_late_phase_a_fails(tmp_path, monkeypatch):
    # Pre-review C1: Phase B used to wait PIPE_T for a pipeline nobody creates and give
    # up with no scaffold. go-task reports a failed cmd as rc=201.
    r, clock = run_b_with_late_phase_a(tmp_path, monkeypatch, ends_at=300, rc=201)
    assert "Phase A still running" in r.stdout, r.stdout
    assert "Phase A finished (rc=201)" in r.stdout, r.stdout
    assert "PREWARM FALLBACK: Phase A did not scaffold rust (rc=201" in r.stdout, r.stdout
    calls = lines(tmp_path, "scaffold.calls")
    assert len(calls) == 1 and int(calls[0].split()[0]) >= 300, calls
    assert "✓ CICDPipeline rust-cicd-pipeline ACTIVE." in r.stdout, r.stdout
    assert r.returncode == 0


def test_phase_b_no_scaffold_when_late_phase_a_succeeds(tmp_path, monkeypatch):
    r, clock = run_b_with_late_phase_a(tmp_path, monkeypatch, ends_at=300, rc=0, scaffolded=True)
    assert "Phase A finished (rc=0)" in r.stdout, r.stdout
    assert lines(tmp_path, "scaffold.calls") == []
    assert "PREWARM FALLBACK" not in r.stdout
    assert "pipeline ACTIVE" in r.stdout, r.stdout


def test_phase_b_phase_a_ok_but_nothing_visible_yet_does_not_rescaffold(tmp_path, monkeypatch):
    # rc=0 means Phase A's task completed: never submit a second one, wait instead.
    r, clock = run_b_with_late_phase_a(tmp_path, monkeypatch, ends_at=300, rc=0, scaffolded=False)
    assert lines(tmp_path, "scaffold.calls") == []
    assert "nothing will create the pipeline" not in r.stdout
    assert "waiting for CICDPipeline" in r.stdout, r.stdout
