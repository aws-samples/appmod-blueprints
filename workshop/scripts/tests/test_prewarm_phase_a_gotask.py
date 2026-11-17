"""Prewarm Phase A must scaffold under go-task's OWN shell, and fail visibly.

prewarm-rust-cicd-phase-a used to source scripts/validation/backstage-auth.sh into the
go-task cmd shell and call backstage_scaffolder there. go-task runs cmds with its built-in
POSIX interpreter (mvdan/sh), not bash, and the helper's subshell-bodied functions
(`f() ( local ...; ... )`) die there with "local: can only be used in a function" before
any HTTP call. Phase A therefore never scaffolded; its output went to /dev/null, it
exited 0 and Phase B did the work. The other prewarm tests render the cmd and run it with
bash, which is why they never saw it: the Phase A tests here run the real `task` binary.

Also covered: prewarm-rust-cicd says loudly when it falls back for a failed Phase A, and
does not scaffold a second time while Phase A is still running. Every test here runs the
rendered cmd through `task` with the real Taskfile's `set:` line (errexit, nounset,
pipefail), so unbound variables and pipefail effects show up as they do on an install.

Run:  python -m pytest workshop/scripts/tests/test_prewarm_phase_a_gotask.py -q
"""
import os
import shutil
import subprocess

import pytest

yaml = pytest.importorskip("yaml")
from test_prewarm_rust_waits import REPO, TASKFILE, VARS, fakes, lines, render  # noqa: E402

BSAUTH = os.path.join(REPO, "scripts", "validation", "backstage-auth.sh")
# The real Taskfile's shell options: go-task applies them to every cmd.
TASK_SET = yaml.safe_load(open(TASKFILE))["set"]
# First line Phase A writes to its scaffold log during the install VARS describe.
RUN = f"run: {VARS['INSTALL_START']}\n"


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
    # Like the real kubectl, the fake must die when grep closes the pipe early (SIGPIPE),
    # not swallow it with `exit 0`.
    k = (b / "kubectl").read_text()
    k2 = k.replace('cat "$FAKE_T/backstage.log" 2>/dev/null; exit 0', 'exec cat "$FAKE_T/backstage.log" 2>/dev/null')
    assert k2 != k
    (b / "kubectl").write_text(k2)
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
    r = task_run(tmp_path, b, cmd)
    return r, int((tmp_path / "clock").read_text()), log


def task_run(tmp_path, b, cmd):
    """Run a rendered cmd through the real `task` binary, with the real `set:` line."""
    d = tmp_path / "tf"
    d.mkdir()
    (d / "Taskfile.yaml").write_text(yaml.safe_dump(
        {"version": "3", "set": TASK_SET, "tasks": {"a": {"cmds": [cmd]}}}))
    env = dict(os.environ, PATH=f"{b}:{os.environ['PATH']}", FAKE_T=str(tmp_path), HOME=str(tmp_path))
    return subprocess.run([task_bin(), "-s", "-d", str(d), "a"], env=env,
                          capture_output=True, text=True, timeout=120, cwd=str(tmp_path))


def run_b(tmp_path, **at):
    """prewarm-rust-cicd (Phase B) through `task`, with the shared fakes."""
    b, plat = fakes(tmp_path, **at)
    r = task_run(tmp_path, b, render("prewarm-rust-cicd", plat))
    return r, int((tmp_path / "clock").read_text())


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


@pytest.mark.parametrize("code", ["000", "502", "504"])
def test_phase_a_post_without_answer_is_not_retried(tmp_path, code):
    # Review (L1367): rc=2 also covers HTTP 000 (no answer, e.g. the POST's 60 s
    # --max-time fired), where Backstage may already have created the task. 502/504 come
    # from CloudFront or the load balancer, so the same holds. A retry could submit a
    # second scaffold: only an error answer from Backstage is retried.
    r, _, _ = run_phase_a(tmp_path, post_code=code)
    assert len(lines(tmp_path, "post.calls")) == 1, r.stdout
    assert "scaffold failed (rc=2" in r.stdout, r.stdout
    assert "retrying in 60s" not in r.stdout
    assert r.returncode != 0


def test_phase_a_failed_task_is_not_resubmitted(tmp_path):
    # A created task that fails may already have published the repo: never POST again.
    r, _, _ = run_phase_a(tmp_path, task_status="failed")
    assert len(lines(tmp_path, "post.calls")) == 1
    assert "scaffold failed (rc=1" in r.stdout, r.stdout
    assert r.returncode != 0


@pytest.fixture
def phase_a_pid():
    """A live process whose cmdline looks like the install's Phase A launcher
    (`sh -c '... task prewarm-rust-cicd-phase-a ...'`)."""
    p = subprocess.Popen(["sh", "-c", "/bin/sleep 600; : task prewarm-rust-cicd-phase-a"])
    yield p.pid
    p.kill()
    p.wait()


# ── prewarm-rust-cicd (Phase B) ────────────────────────────────────────────────────────
def test_phase_b_fallback_is_loud(tmp_path, monkeypatch):
    rc = tmp_path / "pa.rc"
    rc.write_text("201\n")                                  # go-task exit code of a failed cmd
    monkeypatch.setitem(VARS, "PHASE_A_RC_FILE", str(rc))
    monkeypatch.setitem(VARS, "PHASE_A_PID_FILE", str(tmp_path / "pa.pid"))
    r, _ = run_b(tmp_path)
    assert "PREWARM FALLBACK: Phase A did not scaffold rust (rc=201" in r.stdout, r.stdout
    assert len(lines(tmp_path, "scaffold.calls")) == 1


def test_phase_b_no_second_scaffold_while_phase_a_runs(tmp_path, monkeypatch, phase_a_pid):
    pid = tmp_path / "pa.pid"
    pid.write_text(str(phase_a_pid))                          # a live Phase A, no rc yet
    monkeypatch.setitem(VARS, "PHASE_A_PID_FILE", str(pid))
    monkeypatch.setitem(VARS, "PHASE_A_RC_FILE", str(tmp_path / "pa.rc"))
    r, _ = run_b(tmp_path)
    assert "Phase A still running" in r.stdout, r.stdout
    assert lines(tmp_path, "scaffold.calls") == []
    assert "nothing will create the pipeline" not in r.stdout
    assert "waiting for CICDPipeline" in r.stdout
    assert r.returncode == 0


def test_phase_b_standalone_no_fallback_message(tmp_path, monkeypatch):
    monkeypatch.setitem(VARS, "PHASE_A_RC_FILE", str(tmp_path / "absent.rc"))
    monkeypatch.setitem(VARS, "PHASE_A_PID_FILE", str(tmp_path / "absent.pid"))
    r, _ = run_b(tmp_path)
    assert "PREWARM FALLBACK" not in r.stdout
    assert len(lines(tmp_path, "scaffold.calls")) == 1


# ── Phase A still running when Phase B starts (the join gave up), then ends ────────────
def run_b_with_late_phase_a(tmp_path, monkeypatch, pa_pid, ends_at, rc, scaffolded=False, repo_after=False, **at):
    """Phase A is a live launcher-like process with no rc file; the fake `sleep` writes
    its rc (and, for a successful Phase A, the scaffold) once the virtual clock reaches
    ends_at. repo_after: the GitLab project API answers 200 once the rc is written
    (Phase A failed AFTER publish:gitlab created the repo). at: passed to fakes()."""
    b, plat = fakes(tmp_path, **at)
    pid, rcf = tmp_path / "pa.pid", tmp_path / "pa.rc"
    pid.write_text(str(pa_pid))
    monkeypatch.setitem(VARS, "PHASE_A_PID_FILE", str(pid))
    monkeypatch.setitem(VARS, "PHASE_A_RC_FILE", str(rcf))
    done = f'touch "$FAKE_T/scaffolded"; ' if scaffolded else ""
    (b / "sleep").write_text(
        '#!/usr/bin/env bash\n'
        'C=$(cat "$FAKE_T/clock"); C=$((C + ${1%s})); echo $C > "$FAKE_T/clock"\n'
        f'if [ "$C" -ge {ends_at} ] && [ ! -s "{rcf}" ]; then {done}echo {rc} > "{rcf}"; fi\n')
    if repo_after:
        monkeypatch.setitem(VARS, "GIT_TOKEN", "glpat-test")
        (b / "curl").write_text(
            '#!/usr/bin/env bash\n'
            'C=$(cat "$FAKE_T/clock"); echo "$C curl $*" >> "$FAKE_T/curl.calls"\n'
            'case "$*" in *api/v4/projects/*)\n'
            f'  if [ -s "{rcf}" ]; then echo 200; else echo 404; fi; exit 0;; esac\n'
            'echo 401\n')
    r = task_run(tmp_path, b, render("prewarm-rust-cicd", plat))
    return r, int((tmp_path / "clock").read_text())


def test_phase_b_falls_back_when_late_phase_a_fails(tmp_path, monkeypatch, phase_a_pid):
    # Pre-review C1: Phase B used to wait PIPE_T for a pipeline nobody creates and give
    # up with no scaffold. go-task reports a failed cmd as rc=201.
    r, clock = run_b_with_late_phase_a(tmp_path, monkeypatch, phase_a_pid, ends_at=300, rc=201)
    assert "Phase A still running" in r.stdout, r.stdout
    assert "Phase A finished (rc=201)" in r.stdout, r.stdout
    assert "PREWARM FALLBACK: Phase A did not scaffold rust (rc=201" in r.stdout, r.stdout
    calls = lines(tmp_path, "scaffold.calls")
    assert len(calls) == 1 and int(calls[0].split()[0]) >= 300, calls
    assert "✓ CICDPipeline rust-cicd-pipeline ACTIVE." in r.stdout, r.stdout
    assert r.returncode == 0


def test_phase_b_no_scaffold_when_late_phase_a_succeeds(tmp_path, monkeypatch, phase_a_pid):
    r, clock = run_b_with_late_phase_a(tmp_path, monkeypatch, phase_a_pid, ends_at=300, rc=0, scaffolded=True)
    assert "Phase A finished (rc=0)" in r.stdout, r.stdout
    assert lines(tmp_path, "scaffold.calls") == []
    assert "PREWARM FALLBACK" not in r.stdout
    assert "pipeline ACTIVE" in r.stdout, r.stdout


def test_phase_b_phase_a_ok_but_nothing_visible_yet_does_not_rescaffold(tmp_path, monkeypatch, phase_a_pid):
    # rc=0 after Phase A created a task (its scaffold log has the "Task ID:" line):
    # never submit a second one, wait instead.
    sc = tmp_path / "pa-scaffold.log"
    sc.write_text(RUN + "Task ID: t1\n")
    monkeypatch.setitem(VARS, "PHASE_A_SCAFFOLD_LOG", str(sc))
    r, clock = run_b_with_late_phase_a(tmp_path, monkeypatch, phase_a_pid, ends_at=300, rc=0, scaffolded=False)
    assert lines(tmp_path, "scaffold.calls") == []
    assert "nothing will create the pipeline" not in r.stdout
    assert "waiting for CICDPipeline" in r.stdout, r.stdout


# ── Phase A already ended with rc=0 when Phase B starts (review L1602) ──────────────
@pytest.mark.parametrize("task_id,install_start,scaffolds", [
    (True, "1000000", 0),     # Phase A submitted a task this install: never POST again
    (False, "1000000", 1),    # rc=0 from a Phase A skip (no task created): Phase B scaffolds
    (True, "", 1),            # standalone re-run: the /tmp files are from an old install
])
def test_phase_b_phase_a_done_rc0_before_phase_b(tmp_path, monkeypatch, task_id, install_start, scaffolds):
    # Before: the rc=0 rule only ran inside the "Phase A still running" branch, so a
    # Phase A that finished before Phase B (no glpat- PAT for the repo guard, pipeline not
    # synced yet) got a second POST.
    rcf, sc = tmp_path / "pa.rc", tmp_path / "pa-scaffold.log"
    rcf.write_text("0\n")
    sc.write_text(RUN + ("Task ID: t1\n" if task_id else ""))
    monkeypatch.setitem(VARS, "PHASE_A_RC_FILE", str(rcf))
    monkeypatch.setitem(VARS, "PHASE_A_PID_FILE", str(tmp_path / "absent.pid"))
    monkeypatch.setitem(VARS, "PHASE_A_SCAFFOLD_LOG", str(sc))
    monkeypatch.setitem(VARS, "INSTALL_START", install_start)
    r, _ = run_b(tmp_path)
    assert len(lines(tmp_path, "scaffold.calls")) == scaffolds, r.stdout
    assert "PREWARM FALLBACK" not in r.stdout
    if not scaffolds:
        assert "may already have a scaffold in flight" in r.stdout, r.stdout
        assert "nothing will create the pipeline" not in r.stdout
        assert "waiting for CICDPipeline" in r.stdout, r.stdout
    assert r.returncode == 0, r.stderr


@pytest.mark.parametrize("last_status,scaffolds", [
    ("processing", 0),   # Phase A's poll timed out, the task may still run: wait for it
    ("failed", 1),       # the task ended failed: Phase B falls back (loud)
    ("cancelled", 1),
])
def test_phase_b_phase_a_task_then_nonzero_rc_no_pat(tmp_path, monkeypatch, last_status, scaffolds):
    # Pre-review r1 point 2: Phase A created a task, then ended rc=201 (poll timed out or
    # task failed), and there is no glpat- PAT for the repo guard. A task that may still
    # run must not get a second POST; one that failed still gets the fallback.
    rcf, sc = tmp_path / "pa.rc", tmp_path / "pa-scaffold.log"
    rcf.write_text("201\n")
    sc.write_text(RUN + f"Task ID: t1\n  [1] status: processing\n  [30] status: {last_status}\n")
    monkeypatch.setitem(VARS, "PHASE_A_RC_FILE", str(rcf))
    monkeypatch.setitem(VARS, "PHASE_A_PID_FILE", str(tmp_path / "absent.pid"))
    monkeypatch.setitem(VARS, "PHASE_A_SCAFFOLD_LOG", str(sc))
    monkeypatch.setitem(VARS, "GIT_TOKEN", "")
    r, _ = run_b(tmp_path)
    assert len(lines(tmp_path, "scaffold.calls")) == scaffolds, r.stdout
    if scaffolds:
        assert "PREWARM FALLBACK: Phase A did not scaffold rust (rc=201" in r.stdout, r.stdout
    else:
        assert "may already have a scaffold in flight" in r.stdout, r.stdout
        assert "waiting for CICDPipeline" in r.stdout, r.stdout
    assert r.returncode == 0, r.stderr


def test_phase_a_truncates_its_scaffold_log_at_start(tmp_path):
    # Phase B trusts the "Task ID:" line only if it comes from this Phase A run, so Phase
    # A must empty the log even when it exits before the scaffold (here: disabled).
    VARS_ENABLED = VARS["ENABLED"]
    VARS["ENABLED"] = "false"
    try:
        (tmp_path / "scaffold.log").write_text("Task ID: old\n")
        r, _, log = run_phase_a(tmp_path)
    finally:
        VARS["ENABLED"] = VARS_ENABLED
    assert "disabled" in r.stdout, r.stdout
    assert log.read_text() == RUN


@pytest.mark.parametrize("code,scaffolds", [("000", 0), ("502", 0), ("504", 0), ("500", 1)])
def test_phase_b_waits_after_unanswered_phase_a_post(tmp_path, monkeypatch, code, scaffolds):
    # Pre-review r2 point 2: Phase A does not retry a POST with no answer from Backstage
    # (000, or 502/504 from the proxy) because the task may exist. Phase B must not send
    # that second POST either. A POST Backstage refused (500) still gets the fallback.
    r, _, log = run_phase_a(tmp_path, post_code=code)
    assert r.returncode != 0 and "Task ID:" not in log.read_text(), r.stdout
    b_dir = tmp_path / "b"
    b_dir.mkdir()
    rcf = b_dir / "pa.rc"
    rcf.write_text("201\n")
    monkeypatch.setitem(VARS, "PHASE_A_RC_FILE", str(rcf))
    monkeypatch.setitem(VARS, "PHASE_A_PID_FILE", str(b_dir / "absent.pid"))
    monkeypatch.setitem(VARS, "PHASE_A_SCAFFOLD_LOG", str(log))
    r, _ = run_b(b_dir)
    assert len(lines(b_dir, "scaffold.calls")) == scaffolds, r.stdout
    if scaffolds:
        assert "PREWARM FALLBACK" in r.stdout, r.stdout
    else:
        assert "its POST got no answer from Backstage" in r.stdout, r.stdout
        assert "waiting for CICDPipeline" in r.stdout, r.stdout
    assert r.returncode == 0, r.stderr


def test_phase_b_ignores_stale_scaffold_log_phase_a_could_not_rewrite(tmp_path, monkeypatch):
    # Pre-review r2 point 1: Phase A cannot rewrite a stale log (read-only file) and
    # exits 1. Phase B must not trust that log's old "Task ID:" line: it falls back.
    if os.geteuid() == 0:
        pytest.skip("root can write a read-only file")
    log = tmp_path / "scaffold.log"
    log.write_text("run: 999\nTask ID: old\n  [30] status: processing\n")
    log.chmod(0o444)
    r, _, _ = run_phase_a(tmp_path)
    assert "cannot rewrite" in r.stdout, r.stdout
    assert r.returncode != 0
    b_dir = tmp_path / "b"
    b_dir.mkdir()
    rcf = b_dir / "pa.rc"
    rcf.write_text("201\n")
    monkeypatch.setitem(VARS, "PHASE_A_RC_FILE", str(rcf))
    monkeypatch.setitem(VARS, "PHASE_A_PID_FILE", str(b_dir / "absent.pid"))
    monkeypatch.setitem(VARS, "PHASE_A_SCAFFOLD_LOG", str(log))
    r, _ = run_b(b_dir)
    assert len(lines(b_dir, "scaffold.calls")) == 1, r.stdout
    assert "PREWARM FALLBACK" in r.stdout, r.stdout


def test_phase_a_fails_when_it_cannot_empty_its_scaffold_log(tmp_path):
    # Pre-review r1 (suspected): a stale log Phase A cannot empty (another user's file
    # in /tmp) would keep an old "Task ID:" line that stops Phase B's fallback. Phase A
    # must fail visibly instead. A directory stands in for the unwritable file.
    (tmp_path / "scaffold.log").mkdir()
    r, _, _ = run_phase_a(tmp_path)
    assert "cannot rewrite" in r.stdout, r.stdout
    assert lines(tmp_path, "post.calls") == []
    assert r.returncode != 0


# ── nits S1 / S4 ─────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("rc,install_start", [("0", "1000000"), ("201", "")])
def test_phase_b_no_fallback_message_for_ok_rc_or_standalone(tmp_path, monkeypatch, rc, install_start):
    # The rc file stays in /tmp after an install: a successful Phase A (rc 0) or a later
    # standalone re-run (no INSTALL_START) must not print PREWARM FALLBACK.
    f = tmp_path / "pa.rc"
    f.write_text(rc + "\n")
    monkeypatch.setitem(VARS, "PHASE_A_RC_FILE", str(f))
    monkeypatch.setitem(VARS, "PHASE_A_PID_FILE", str(tmp_path / "absent.pid"))
    monkeypatch.setitem(VARS, "INSTALL_START", install_start)
    r, _ = run_b(tmp_path)
    assert "PREWARM FALLBACK" not in r.stdout, r.stdout
    assert len(lines(tmp_path, "scaffold.calls")) == 1


def test_phase_a_backend_failed_exits_at_once(tmp_path):
    (tmp_path / "backstage.log").write_text("Backend startup failed\nMigrationLocked: Migration table is already locked\n")
    r, clock, _ = run_phase_a(tmp_path, bs_up_at=10_000)
    assert "Backstage backend failed to start" in r.stdout, r.stdout
    assert lines(tmp_path, "post.calls") == []
    assert r.returncode != 0
    assert clock == 0, clock


def test_phase_a_backend_failed_seen_in_large_log(tmp_path):
    # Review (L1337): under pipefail, `kubectl logs | grep -Eq` on a log over 64 KB made
    # kubectl die of SIGPIPE once grep matched early, so the `if` was false and Phase A
    # waited out its full 600 s Backstage wait.
    (tmp_path / "backstage.log").write_text(
        "Backend startup failed\nMigrationLocked: Migration table is already locked\n"
        + ("x" * 120 + "\n") * 2000)
    r, clock, _ = run_phase_a(tmp_path, bs_up_at=10_000)
    assert "Backstage backend failed to start" in r.stdout, r.stdout
    assert lines(tmp_path, "post.calls") == []
    assert r.returncode != 0
    assert clock == 0, clock


# ── pre-review #2: repo guard re-check, standalone cap, stale pid ──────────────────────
def test_phase_b_no_rescaffold_when_late_phase_a_failed_after_publishing_repo(tmp_path, monkeypatch, phase_a_pid):
    # Phase A failed (rc=201) after publish:gitlab created user1/rust-cicd: a second
    # scaffold would 500 in publish:gitlab. The re-check must see the repo and not POST.
    r, _ = run_b_with_late_phase_a(tmp_path, monkeypatch, phase_a_pid, ends_at=300, rc=201, repo_after=True)
    assert "Phase A finished (rc=201)" in r.stdout, r.stdout
    assert lines(tmp_path, "scaffold.calls") == [], r.stdout
    assert "PREWARM FALLBACK" not in r.stdout


def test_phase_b_repo_left_by_failed_phase_a_without_argo_app(tmp_path, monkeypatch, phase_a_pid):
    # Review (L1598/L1775): Phase A failed after publish:gitlab and before the Argo CD app
    # was created. The re-check sets REPO_EXISTS but never SCAFFOLD_SUBMITTED, so under
    # nounset Phase B died on "SCAFFOLD_SUBMITTED: unbound variable" and never printed
    # the delete-repo hint.
    r, _ = run_b_with_late_phase_a(tmp_path, monkeypatch, phase_a_pid, ends_at=300, rc=201,
                                   repo_after=True, cd_at=10_000_000)
    assert "unbound variable" not in r.stdout + r.stderr, r.stderr
    assert "no CICDPipeline and no Argo CD app rust-cicd" in r.stdout, r.stdout + r.stderr
    assert "delete it, then" in r.stdout
    assert lines(tmp_path, "scaffold.calls") == []
    assert r.returncode == 0, r.stderr


def test_phase_b_wait_for_phase_a_capped_without_deadline(tmp_path, monkeypatch, phase_a_pid):
    # Standalone run (no INSTALL_START): left() is 999999, the wait must still stop at 900 s.
    pid = tmp_path / "pa.pid"
    pid.write_text(str(phase_a_pid))
    monkeypatch.setitem(VARS, "PHASE_A_PID_FILE", str(pid))
    monkeypatch.setitem(VARS, "PHASE_A_RC_FILE", str(tmp_path / "pa.rc"))
    monkeypatch.setitem(VARS, "INSTALL_START", "")
    r, clock = run_b(tmp_path)
    assert "waiting up to 900s for it to finish" in r.stdout, r.stdout
    assert "still running after 900s" in r.stdout, r.stdout
    assert lines(tmp_path, "scaffold.calls") == []
    assert clock < 900 + 600 + 120, clock         # Phase A wait + PIPE_T, not ~999639 s


def test_phase_b_ignores_stale_pid_of_another_process(tmp_path, monkeypatch):
    # A pid file left by an aborted install now points at an unrelated live process
    # (here: pytest itself). It must not be treated as Phase A.
    pid = tmp_path / "pa.pid"
    pid.write_text(str(os.getpid()))
    monkeypatch.setitem(VARS, "PHASE_A_PID_FILE", str(pid))
    monkeypatch.setitem(VARS, "PHASE_A_RC_FILE", str(tmp_path / "pa.rc"))
    monkeypatch.setitem(VARS, "INSTALL_START", "")
    r, clock = run_b(tmp_path)
    assert "Phase A still running" not in r.stdout, r.stdout
    assert len(lines(tmp_path, "scaffold.calls")) == 1
