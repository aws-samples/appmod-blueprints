"""Prewarm Phase A keeps its pid, exit code and log in a private directory per install run.

The install launched Phase A in the background with fixed paths (/tmp/prewarm-phase-a.pid,
.rc and .log), and the join and Phase B read them back. A second install started on the
same host while the first was running removed the first one's pid and rc files, wrote its
own, and both runs then read whichever exit code was written last (#1328).

Each run of `install` and `install:ide` now gets its own `mktemp -d` directory from a task
var (each cmd runs in its own shell, so a shell variable cannot carry it), and the
launcher, the join and Phase B all use that run's value. These tests pin that:

1. the files are written under a mode-0700 `$TMPDIR/prewarm-phase-a.*` directory, as
   0600 files, a new directory per run, removed when the install ends with Phase A rc 0;
2. two overlapping runs each read their OWN exit code, in the join and in Phase B: a
   barrier in the fake Phase A holds both until both have been launched, so the overlap is
   certain, and one run exits 7 while the other exits 0 two seconds later;
3. when `mktemp -d` fails, returns nothing or returns a regular file, Phase A is not
   started, nothing is written, and the install goes on;
4. the directory is removed even when the install fails before or after the launch, and
   kept (with its log, path printed) when Phase A failed or is still running; Phase A's
   stderr is in that log;
5. a TMPDIR that contains a space, a single or double quote, `$`, a backtick, `%` or a
   backslash works: the launcher, the join, the defer and the REAL Phase B all parse and
   run, and Phase B reads this run's pid and rc and prints this run's log path;
6. no fixed /tmp/prewarm-phase-a.{pid,rc,log} path is left, and a standalone Phase B gets
   no Phase A files by default;
7. when the mktemp on PATH prints an existing directory, the defer does not remove it;
8. with TMPDIR unset, the directory is created under /tmp.

The commands under test are taken from the real Taskfile (the PHASE_A_DIR var, the defer,
the launcher, the join and the Phase B call, in their real order) and run with the real
`task` binary and the real `set:` line. In most tests Phase B is replaced by a probe that
prints the Phase A paths it is given and reads the exit code through them; the
`test_real_phase_b_*` tests run the real prewarm-rust-cicd task instead, with fake aws and
kubectl, up to its PREWARM FALLBACK line. The inner `task prewarm-rust-cicd-phase-a` is a
fake on PATH; `sleep` is shortened.

Run:  python -m pytest workshop/scripts/tests/test_prewarm_phase_a_tmpdir.py -q
"""
import os
import re
import shutil
import subprocess
import sys
import time

import pytest

yaml = pytest.importorskip("yaml")
if not sys.platform.startswith("linux"):
    pytest.skip("the join polls /proc (Linux)", allow_module_level=True)

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
TASKFILE = os.path.join(REPO, "workshop", "Taskfile.yaml")
REAL = yaml.safe_load(open(TASKFILE))
TASKS = ["install", "install:ide"]
REAL_MKTEMP = shutil.which("mktemp")
DIR_RE = r"prewarm-phase-a\.[A-Za-z0-9]{6}"


def task_bin():
    t = os.environ.get("TASK_BIN") or shutil.which("task") or shutil.which("go-task")
    if not t:
        pytest.skip("go-task binary not available (set TASK_BIN)")
    return t


# The inner `task prewarm-rust-cicd-phase-a` of the launcher. Its stdout is the log the
# wrapper opened: it records that path and the modes, then waits on the barrier.
FAKE_PHASE_A = r'''#!/usr/bin/env bash
run="${FAKE_RUN:-x}"
log=$(readlink "/proc/$$/fd/1")
d=$(dirname "$log")
printf '%s\t%s\t%s\t%s\n' "$log" "$(stat -c %a "$d")" "$(stat -c %a "$log")" \
  "$(stat -c %a "$d/prewarm-phase-a.pid" 2>/dev/null)" >> "$FAKE_T/phase-a.$run"
echo "fake Phase A run $run: $*"
[ -n "${FAKE_STDERR:-}" ] && echo "$FAKE_STDERR" >&2
: > "$FAKE_T/ready.$run"
if [ -n "${FAKE_BARRIER:-}" ]; then
  i=0
  while [ "$(ls "$FAKE_T" | grep -c '^ready\.')" -lt "$FAKE_BARRIER" ] && [ $i -lt 400 ]; do
    /bin/sleep 0.05; i=$((i + 1))
  done
fi
if [ -n "${FAKE_HOLD:-}" ]; then
  i=0
  while [ ! -e "$FAKE_T/release" ] && [ $i -lt 1200 ]; do /bin/sleep 0.05; i=$((i + 1)); done
fi
[ -n "${FAKE_DELAY:-}" ] && /bin/sleep "$FAKE_DELAY"
exit "${FAKE_RC:-0}"
'''

FAKE_SLEEP = '#!/usr/bin/env bash\nexec /bin/sleep 0.05\n'

FAKE_MKTEMP = '''#!/usr/bin/env bash
case " $* " in
  *" -d "*)
    case "${FAKE_MKTEMP:-}" in
      fail) exit 1 ;;
      empty) exit 0 ;;
      file) : > "$FAKE_T/not-a-dir"; echo "$FAKE_T/not-a-dir"; exit 0 ;;
      existing) echo "$FAKE_T/victim"; exit 0 ;;
      # Record the template, then create the directory under $FAKE_T, not in the real /tmp.
      redirect) echo "$*" > "$FAKE_T/mktemp.args"; mkdir -p "$FAKE_T/redir"
                exec "%s" -d "$FAKE_T/redir/${2##*/}" ;;
    esac ;;
esac
exec "%s" "$@"
''' % (REAL_MKTEMP, REAL_MKTEMP)

# Fakes for the real prewarm-rust-cicd (Phase B): no pipeline, no image, every kubectl
# check passes. With no Backstage helper under PLATFORM_DIR, Phase B stops right after
# its PREWARM FALLBACK line, so the real cmd is parsed and run up to there.
FAKE_AWS = '#!/usr/bin/env bash\ncase "$*" in *list-images*) echo 0;; esac\nexit 0\n'
FAKE_KUBECTL = '#!/usr/bin/env bash\nexit 0\n'


def pick(task, real_b=False):
    """The Phase A cmds of a real install task, in their real order. Phase B is a probe,
    or with real_b the real prewarm-rust-cicd call."""
    out, kinds = [], []
    for c in REAL["tasks"][task]["cmds"]:
        if isinstance(c, dict) and "defer" in c and "PHASE_A_DIR" in str(c["defer"]):
            out.append(c); kinds.append("defer")
        elif isinstance(c, str) and "task prewarm-rust-cicd-phase-a" in c:
            out.append(c); kinds.append("launch")
        elif isinstance(c, dict) and "prewarm-phase-a.rc" in str(c.get("cmd", "")):
            out.append(c); kinds.append("join")
        elif isinstance(c, dict) and c.get("task") == "prewarm-rust-cicd":
            out.append(c if real_b else {"task": "probe-b", "vars": c.get("vars", {})}); kinds.append("b")
    return out, kinds


def real_b_globals(tmp_path):
    """Root vars the real prewarm-rust-cicd reads. Paths point at nothing under tmp_path."""
    return {"AWS_REGION": "r", "CLOUDFRONT_DOMAIN": "cf.example", "DOMAIN": "", "HUB_CLUSTER_NAME": "hub",
            "RESOURCE_PREFIX": "p", "CONFIG_FILE": str(tmp_path / "none.yaml"), "REPO": str(tmp_path / "repo"),
            "PLATFORM_DIR": str(tmp_path / "plat"), "PHASE_A_SCAFFOLD_LOG": str(tmp_path / "scaffold.log")}


def build(tmp_path, task, fail_before_launch=False, fail_at_end=False, budget="6600", settle=True, real_b=False):
    cmds, kinds = pick(task, real_b)
    if settle:
        # Stands in for wait-for-spokes (minutes) between the launch and the join: the
        # wrapper has written its pid by then. Without it the join can read the pid file
        # before the background shell writes it.
        cmds.insert(kinds.index("join"), 'i=0; while [ ! -e "$FAKE_T/ready.$FAKE_RUN" ] && [ $i -lt 400 ]; '
                                          'do /bin/sleep 0.02; i=$((i + 1)); done')
    if fail_before_launch:
        cmds.insert(kinds.index("launch"), "exit 3")
    if fail_at_end:
        cmds.append("exit 3")
    real_vars = REAL["tasks"][task]["vars"]
    b_vars = REAL["tasks"]["prewarm-rust-cicd"]["vars"]
    probe = {
        "vars": {k: b_vars[k] for k in ("PHASE_A_PID_FILE", "PHASE_A_RC_FILE", "PHASE_A_LOG") if k in b_vars},
        # Read the files the way prewarm-rust-cicd does: the paths in double quotes.
        "cmds": ['printf "B pid_file=[%s] rc_file=[%s] log=[%s] rc=[%s]\\n" "{{.PHASE_A_PID_FILE}}" '
                 '"{{.PHASE_A_RC_FILE}}" "{{.PHASE_A_LOG}}" "$(cat "{{.PHASE_A_RC_FILE}}" 2>/dev/null || echo none)"'],
    }
    tf = {
        "version": "3", "set": REAL["set"], "silent": True,
        "vars": {"MARK": ":", "C_INFO": "", "C_ERR": "", "C_RESET": "", "C_STEP": "", "C_OK": ""},
        "tasks": {
            "run": {"vars": {"INSTALL_START": {"sh": "date +%s"}, "INSTALL_BUDGET_SEC": budget,
                             "PHASE_A_DIR": real_vars.get("PHASE_A_DIR", "")},
                    "cmds": cmds},
            "probe-b": probe,
        },
    }
    if real_b:
        # The real Phase B task, unchanged: its vars, its cmds, go-task's own templating.
        tf["tasks"]["prewarm-rust-cicd"] = REAL["tasks"]["prewarm-rust-cicd"]
        tf["vars"].update(real_b_globals(tmp_path))
    d = tmp_path / "tf"
    d.mkdir(exist_ok=True)
    (d / "Taskfile.yaml").write_text(yaml.safe_dump(tf, sort_keys=False))
    return d, kinds


def setup(tmp_path, tmpdir_name="tmp", mktemp_mode=None):
    """tmpdir_name None: TMPDIR is removed from the environment."""
    b = tmp_path / "bin"
    b.mkdir()
    for name, body in (("task", FAKE_PHASE_A), ("sleep", FAKE_SLEEP), ("mktemp", FAKE_MKTEMP),
                       ("aws", FAKE_AWS), ("kubectl", FAKE_KUBECTL)):
        (b / name).write_text(body)
        os.chmod(b / name, 0o755)
    env = dict(os.environ, PATH=f"{b}:{os.environ['PATH']}", FAKE_T=str(tmp_path), HOME=str(tmp_path),
               PREWARM_RUST_CICD="true")
    td = None
    if tmpdir_name is None:
        env.pop("TMPDIR", None)
    else:
        td = tmp_path / tmpdir_name
        td.mkdir()
        env["TMPDIR"] = str(td)
    env.pop("PHASE_A_DIR", None)
    if mktemp_mode:
        env["FAKE_MKTEMP"] = mktemp_mode
    return env, td


def start(d, env, **extra):
    return subprocess.Popen([task_bin(), "-d", str(d), "run"], env=dict(env, **extra),
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def run(d, env, **extra):
    p = start(d, env, **extra)
    out, _ = p.communicate(timeout=120)
    return p.returncode, out


def joined_rc(out):
    """The exit code the join reported, for both install flavours."""
    m = re.search(r"prewarm Phase A(?: joined after \d+s \(rc=(\d+)| exited rc=(\d+)|: rc=(\w+))", out)
    assert m, out
    return next(g for g in m.groups() if g is not None)


def probe(out):
    m = re.search(r"B pid_file=\[(.*?)\] rc_file=\[(.*?)\] log=\[(.*?)\] rc=\[(.*?)\]", out)
    assert m, out
    return m.groups()


def records(tmp_path, run_id):
    p = tmp_path / f"phase-a.{run_id}"
    return [line.split("\t") for line in p.read_text().splitlines()] if p.exists() else []


def test_launcher_join_defer_and_phase_b_are_all_found():
    for task in TASKS:
        assert pick(task)[1] == ["defer", "launch", "join", "b"], task


def test_no_fixed_tmp_paths_left_and_standalone_phase_b_gets_none(tmp_path):
    text = open(TASKFILE).read()
    assert not re.search(r"/tmp/prewarm-phase-a\.(pid|rc|log)\b", text)
    for k in ("PHASE_A_PID_FILE", "PHASE_A_RC_FILE"):
        assert REAL["tasks"]["prewarm-rust-cicd"]["vars"][k] == "{{.%s | default \"\"}}" % k
    env, _ = setup(tmp_path)
    d, _ = build(tmp_path, "install")
    r = subprocess.run([task_bin(), "-d", str(d), "probe-b"], env=env, capture_output=True, text=True, timeout=60)
    assert probe(r.stdout)[:2] == ("", "") and probe(r.stdout)[3] == "none", r.stdout + r.stderr


@pytest.mark.parametrize("task", TASKS)
def test_private_dir_per_run_and_removed_after_rc0(tmp_path, task):
    env, td = setup(tmp_path)
    d, _ = build(tmp_path, task)
    dirs = []
    for n in ("1", "2"):
        rc, out = run(d, env, FAKE_RUN=n)
        assert rc == 0, out
        assert joined_rc(out) == "0", out
        (log, dmode, lmode, pmode), = records(tmp_path, n)
        assert re.fullmatch(re.escape(str(td)) + "/" + DIR_RE + "/prewarm-phase-a.log", log), log
        assert (dmode, lmode, pmode) == ("700", "600", "600"), (log, dmode, lmode, pmode)
        pid_f, rc_f, log_f, b_rc = probe(out)
        assert (pid_f, rc_f, log_f) == tuple(os.path.dirname(log) + "/prewarm-phase-a." + s for s in ("pid", "rc", "log"))
        assert b_rc == "0"
        if task == "install":
            assert f"started in background (log: {log})" in out, out
        dirs.append(os.path.dirname(log))
        assert os.listdir(td) == [], f"run {n} left {os.listdir(td)}"
    assert dirs[0] != dirs[1], "two runs shared one directory"


@pytest.mark.parametrize("task", TASKS)
def test_overlapping_runs_each_read_their_own_exit_code(tmp_path, task):
    env, td = setup(tmp_path)
    d, _ = build(tmp_path, task)
    a = start(d, env, FAKE_RUN="A", FAKE_RC="0", FAKE_DELAY="2", FAKE_BARRIER="2")
    b = start(d, env, FAKE_RUN="B", FAKE_RC="7", FAKE_BARRIER="2")
    out_a, _ = a.communicate(timeout=120)
    out_b, _ = b.communicate(timeout=120)
    assert (a.returncode, b.returncode) == (0, 0), out_a + out_b
    assert (joined_rc(out_a), joined_rc(out_b)) == ("0", "7"), (out_a, out_b)
    pa, pb = probe(out_a), probe(out_b)
    assert (pa[3], pb[3]) == ("0", "7"), (out_a, out_b)
    log_a, log_b = records(tmp_path, "A")[0][0], records(tmp_path, "B")[0][0]
    assert os.path.dirname(log_a) != os.path.dirname(log_b)
    assert pa[1] == os.path.dirname(log_a) + "/prewarm-phase-a.rc"
    assert pb[1] == os.path.dirname(log_b) + "/prewarm-phase-a.rc"
    # A ended with rc 0: removed. B failed: kept, with B's log only.
    assert os.listdir(td) == [os.path.basename(os.path.dirname(log_b))], os.listdir(td)
    kept = open(log_b).read()
    assert "fake Phase A run B" in kept and "run A" not in kept, kept
    assert f"its log is kept: {log_b}" in out_b, out_b


@pytest.mark.parametrize("mode", ["fail", "empty", "file"])
@pytest.mark.parametrize("task", TASKS)
def test_mktemp_failure_does_not_start_phase_a(tmp_path, task, mode):
    env, td = setup(tmp_path, mktemp_mode=mode)
    d, _ = build(tmp_path, task, settle=False)
    rc, out = run(d, env, FAKE_RUN="m")
    assert rc == 0, out
    assert "prewarm Phase A not started: could not create its temporary directory" in out, out
    assert not (tmp_path / "ready.m").exists(), "Phase A ran without a directory"
    assert "left no exit status" in out or joined_rc(out) == "none", out
    pid_f, rc_f, _, b_rc = probe(out)
    assert b_rc == "none", out
    if mode != "file":           # a regular file: Phase B gets paths under it, finds nothing
        assert (pid_f, rc_f) == ("", ""), out
    assert os.listdir(td) == []
    left = sorted(p for p in os.listdir(tmp_path) if p not in ("bin", "tf", "tmp"))
    assert left == (["not-a-dir"] if mode == "file" else []), left
    if mode == "file":
        assert (tmp_path / "not-a-dir").read_text() == "", "wrote through the returned file"


@pytest.mark.parametrize("where", ["before_launch", "at_end"])
@pytest.mark.parametrize("task", TASKS)
def test_dir_removed_when_install_fails(tmp_path, task, where):
    env, td = setup(tmp_path)
    d, _ = build(tmp_path, task, fail_before_launch=(where == "before_launch"), fail_at_end=(where == "at_end"))
    rc, out = run(d, env, FAKE_RUN="f")
    assert rc != 0, out
    if where == "at_end":
        assert joined_rc(out) == "0", out
    assert os.listdir(td) == [], f"left {os.listdir(td)}"


@pytest.mark.parametrize("task", TASKS)
def test_failed_phase_a_keeps_its_log(tmp_path, task):
    env, td = setup(tmp_path)
    d, _ = build(tmp_path, task)
    rc, out = run(d, env, FAKE_RUN="k", FAKE_RC="5")
    assert rc == 0, out
    assert joined_rc(out) == "5"
    log = records(tmp_path, "k")[0][0]
    assert f"its log is kept: {log}" in out, out
    assert "fake Phase A run k" in open(log).read()
    assert oct(os.stat(os.path.dirname(log)).st_mode & 0o777) == "0o700"
    assert oct(os.stat(log).st_mode & 0o777) == "0o600"


@pytest.mark.parametrize("task", TASKS)
def test_phase_a_stderr_goes_to_its_kept_log(tmp_path, task):
    # The wrapper sends stderr to the log too: the launcher's own redirect is /dev/null,
    # so without the wrapper's 2>&1 Phase A's errors would be lost from the kept log.
    env, _ = setup(tmp_path)
    d, _ = build(tmp_path, task)
    rc, out = run(d, env, FAKE_RUN="e", FAKE_RC="5", FAKE_STDERR="fake Phase A error on stderr")
    assert rc == 0, out
    log = records(tmp_path, "e")[0][0]
    assert f"its log is kept: {log}" in out, out
    assert "fake Phase A error on stderr" in open(log).read(), open(log).read()


@pytest.mark.parametrize("task", TASKS)
def test_still_running_phase_a_keeps_its_dir(tmp_path, task):
    env, td = setup(tmp_path)
    d, _ = build(tmp_path, task, budget="420")      # install: no join budget left at all
    rc, out = run(d, env, FAKE_RUN="h", FAKE_HOLD="1")
    try:
        assert rc == 0, out
        assert "still running" in out or "rc=none" in out, out
        log = records(tmp_path, "h")[0][0]
        assert f"its log is kept: {log}" in out, out
        assert os.path.isfile(log)
    finally:
        # Let the fake Phase A end, so it does not outlive the test.
        (tmp_path / "release").touch()
        for _ in range(100):
            if not any(f.startswith("ready.") for f in os.listdir(tmp_path)):
                break
            if all(os.path.exists(os.path.join(td, e, "prewarm-phase-a.rc")) for e in os.listdir(td)):
                break
            time.sleep(0.05)


@pytest.mark.parametrize("name", ["with space", "a'b"])
@pytest.mark.parametrize("task", TASKS)
def test_tmpdir_with_space_or_quote(tmp_path, task, name):
    env, td = setup(tmp_path, tmpdir_name=name)
    d, _ = build(tmp_path, task)
    rc, out = run(d, env, FAKE_RUN="q")
    assert rc == 0, out
    assert joined_rc(out) == "0", out
    log = records(tmp_path, "q")[0][0]
    assert log.startswith(str(td) + "/"), log
    assert probe(out)[3] == "0", out
    assert os.listdir(td) == [], f"left {os.listdir(td)}"


# ── The REAL Phase B, with this run's paths under an odd TMPDIR ────────────────────────
# The probe above does not parse prewarm-rust-cicd. These tests run the real task, with
# go-task's own templating: a path pasted into its shell text (in a printf format or in
# "...") makes go-task refuse to parse the whole cmd, and Phase B is then skipped
# silently (its call has ignore_error: true).
ODD_NAMES = ["with space", "a'b", 'a"b', "a$x`y`%s\\z"]


@pytest.mark.parametrize("name", ODD_NAMES)
@pytest.mark.parametrize("task", TASKS)
def test_real_phase_b_runs_with_odd_tmpdir(tmp_path, task, name):
    env, td = setup(tmp_path, tmpdir_name=name)
    d, _ = build(tmp_path, task, real_b=True)
    rc, out = run(d, env, FAKE_RUN="r", FAKE_RC="5")
    assert rc == 0, out
    log = records(tmp_path, "r")[0][0]
    assert log.startswith(str(td) + "/"), log
    # Phase B read this run's rc through PHASE_A_RC_FILE and printed this run's log path.
    assert (f"PREWARM FALLBACK: Phase A did not scaffold rust (rc=5, see {log} and "
            f"{tmp_path / 'scaffold.log'})") in out, out
    assert "backstage-auth.sh not found — skipping prewarm" in out, out
    assert "✓ prewarm-rust-cicd done." in out, out
    assert f"its log is kept: {log}" in out, out


@pytest.mark.parametrize("name", ODD_NAMES)
def test_real_phase_b_waits_on_this_runs_pid_with_odd_tmpdir(tmp_path, name):
    env, _ = setup(tmp_path)
    pa = tmp_path / name / "prewarm-phase-a.AbC123"
    pa.mkdir(parents=True)
    # A live process whose cmdline looks like the launcher; it writes rc 5 after 1 s.
    p = subprocess.Popen(["sh", "-c", '/bin/sleep 1; echo 5 > "$1/prewarm-phase-a.rc"; : task prewarm-rust-cicd-phase-a',
                          "_", str(pa)])
    try:
        (pa / "prewarm-phase-a.pid").write_text(str(p.pid))
        b_vars = {"INSTALL_START": str(int(time.time())), "INSTALL_BUDGET_SEC": "6600",
                  "PHASE_A_PID_FILE": str(pa / "prewarm-phase-a.pid"), "PHASE_A_RC_FILE": str(pa / "prewarm-phase-a.rc"),
                  "PHASE_A_LOG": str(pa / "prewarm-phase-a.log")}
        tf = {"version": "3", "set": REAL["set"], "silent": True,
              "vars": {"MARK": ":", "C_INFO": "", "C_ERR": "", "C_RESET": "", "C_STEP": "", "C_OK": "",
                       **real_b_globals(tmp_path)},
              "tasks": {"run": {"cmds": [{"task": "prewarm-rust-cicd", "vars": b_vars}]},
                        "prewarm-rust-cicd": REAL["tasks"]["prewarm-rust-cicd"]}}
        d = tmp_path / "tf"
        d.mkdir()
        (d / "Taskfile.yaml").write_text(yaml.safe_dump(tf, sort_keys=False))
        rc, out = run(d, env)
    finally:
        p.kill()
        p.wait()
    assert rc == 0, out
    assert f"prewarm Phase A still running (pid {p.pid})" in out, out
    assert "prewarm Phase A finished (rc=5)" in out, out
    assert (f"PREWARM FALLBACK: Phase A did not scaffold rust (rc=5, see {pa / 'prewarm-phase-a.log'} and "
            f"{tmp_path / 'scaffold.log'})") in out, out
    assert "✓ prewarm-rust-cicd done." in out, out


# ── The name check in front of the defer's rm -rf ──────────────────────────────────────
@pytest.mark.parametrize("task", TASKS)
def test_defer_never_removes_a_directory_mktemp_did_not_create(tmp_path, task):
    # PHASE_A_DIR cannot be overridden, but its value is whatever the mktemp on PATH
    # prints. Here it prints an existing user directory: only the name check keeps the
    # defer's rm -rf off it.
    env, td = setup(tmp_path, mktemp_mode="existing")
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "keep.txt").write_text("user data")
    d, _ = build(tmp_path, task)
    rc, out = run(d, env, FAKE_RUN="v")
    assert rc == 0, out
    assert joined_rc(out) == "0", out
    assert (victim / "keep.txt").exists(), "the defer removed a directory mktemp did not create: " + out
    assert (victim / "keep.txt").read_text() == "user data"


# ── TMPDIR unset: the /tmp default ─────────────────────────────────────────────────────
@pytest.mark.parametrize("task", TASKS)
def test_tmpdir_unset_defaults_to_tmp(tmp_path, task):
    # The fake mktemp records the template it is given and creates the directory under
    # tmp_path instead, so nothing is written to the real /tmp.
    env, _ = setup(tmp_path, tmpdir_name=None, mktemp_mode="redirect")
    assert "TMPDIR" not in env
    d, _ = build(tmp_path, task)
    rc, out = run(d, env, FAKE_RUN="u")
    assert rc == 0, out
    assert (tmp_path / "mktemp.args").read_text().split() == ["-d", "/tmp/prewarm-phase-a.XXXXXX"]
    assert joined_rc(out) == "0", out
    log = records(tmp_path, "u")[0][0]
    assert re.fullmatch(re.escape(str(tmp_path / "redir")) + "/" + DIR_RE + "/prewarm-phase-a.log", log), log
    assert os.listdir(tmp_path / "redir") == [], "the directory was not removed after rc 0"
