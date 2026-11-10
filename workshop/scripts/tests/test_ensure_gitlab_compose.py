"""workshop/scripts/ensure-gitlab-compose.sh with fake docker/curl/aws on PATH.

Proves (mocked, no network, no root, no real docker):
  - compose plugin present and GitLab running: no-op (no download, no up -d);
  - compose missing + GitHub ok: plugin installed (sha256 verified), GitLab started;
  - compose missing + GitHub down + S3 ok (s3-first): installed from the S3 mirror;
  - sha256 mismatch is refused (rc 10, plugin not installed);
  - `docker compose up -d` failing propagates (rc 12);
  - PEEKS_TOOLS_SOURCE=s3-only never calls curl; without bucket vars it fails explicitly;
  - container never healthy: bounded, warning only (rc 0);
  - background launcher / waiter rc propagation, extracted from the real Taskfiles and run with a
    real go-task (skipped when `task` is absent).

Run:  python -m pytest workshop/scripts/tests/test_ensure_gitlab_compose.py -q
"""
import hashlib
import os
import re
import shutil
import stat
import subprocess

import pytest
import yaml

SCRIPT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "ensure-gitlab-compose.sh"))
GOOD = b"GOOD\n"
GOOD_SHA = hashlib.sha256(GOOD).hexdigest()

FAKE_DOCKER = r"""#!/bin/bash
echo "docker $*" >> "$MOCK/calls.log"
if [ "$1" = inspect ] && [ "$4" = gitlab-gitlab-1 ]; then cat "$MOCK/gl_health" 2>/dev/null || exit 1; exit 0; fi
if [ "$1" = inspect ]; then cat "$MOCK/health" 2>/dev/null || echo healthy; exit 0; fi
[ "$1" = compose ] || exit 1
grep -qx GOOD "$PLUGIN_DIR/docker-compose" 2>/dev/null || { echo "docker: 'compose' is not a docker command." >&2; exit 1; }
shift
case "$*" in
  version) echo "Docker Compose version v2.27.1" ;;
  *"ps -q --status running"*) [ -f "$MOCK/running" ] && echo abc123 ;;
  *"ps -q"*) echo abc123 ;;
  *"up -d"*) [ "${UP_FAIL:-}" = 1 ] && exit 1; touch "$MOCK/running" ;;
esac
"""

# CURL_MODE: ok | bad (wrong content) | fail (HTTP 504)
FAKE_CURL = r"""#!/bin/bash
echo "curl $*" >> "$MOCK/calls.log"
out=""; while [ $# -gt 0 ]; do [ "$1" = -o ] && { out=$2; shift; }; shift; done
case "$CURL_MODE" in ok) echo GOOD > "$out" ;; bad) echo BAD > "$out" ;; *) exit 22 ;; esac
"""

# aws s3 cp <uri> <dest>; S3_MODE: ok | fail
FAKE_AWS = r"""#!/bin/bash
echo "aws $*" >> "$MOCK/calls.log"
[ "$S3_MODE" = ok ] && { echo GOOD > "$4"; exit 0; }
exit 1
"""


def _exe(path, body):
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


@pytest.fixture
def env(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for n, b in (("docker", FAKE_DOCKER), ("curl", FAKE_CURL), ("aws", FAKE_AWS)):
        _exe(bindir / n, b)
    mock = tmp_path / "mock"
    mock.mkdir()
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    gl = tmp_path / "gitlab"
    gl.mkdir()
    (gl / "docker-compose.yml").write_text("services: {}\n")
    e = {
        "PATH": f"{bindir}:/usr/bin:/bin", "HOME": str(tmp_path), "MOCK": str(mock),
        "PLUGIN_DIR": str(plugins), "GITLAB_HOME": str(gl), "COMPOSE_SHA256": GOOD_SHA,
        "BACKOFF_BASE": "0", "ATTEMPTS": "3", "HEALTH_TIMEOUT": "0", "HEALTH_INTERVAL": "0",
        "CURL_MODE": "ok", "S3_MODE": "fail",
    }
    return e, mock, plugins


def run(e):
    return subprocess.run(["bash", SCRIPT], env=e, capture_output=True, text=True)


def calls(mock):
    p = mock / "calls.log"
    return p.read_text() if p.exists() else ""


def n_calls(mock, tool):
    return sum(1 for l in calls(mock).splitlines() if l.startswith(tool + " "))


def test_present_and_running_is_noop(env):
    e, mock, plugins = env
    (plugins / "docker-compose").write_bytes(GOOD)
    (mock / "running").touch()
    r = run(e)
    assert r.returncode == 0, r.stderr
    c = calls(mock)
    assert n_calls(mock, "curl") == 0 and n_calls(mock, "aws") == 0 and "up -d" not in c


def test_missing_github_ok_installs_and_starts(env):
    e, mock, plugins = env
    r = run(e)
    assert r.returncode == 0, r.stderr
    assert (plugins / "docker-compose").read_bytes() == GOOD
    assert "up -d" in calls(mock)


def test_missing_github_down_s3_first_ok(env):
    e, mock, plugins = env
    e.update(CURL_MODE="fail", S3_MODE="ok", PEEKS_TOOLS_SOURCE="s3-first",
             ASSETS_BUCKET_NAME="bkt", ASSETS_BUCKET_PREFIX="pfx")
    r = run(e)
    assert r.returncode == 0, r.stderr
    c = calls(mock)
    assert "s3://bkt/pfx/tools/v1/docker-compose-v2.27.1-linux-x86_64" in c
    assert n_calls(mock, "curl") == 0  # S3 succeeded first, GitHub untouched


def test_github_down_no_s3_fails_explicitly(env):
    e, mock, plugins = env
    e["CURL_MODE"] = "fail"
    r = run(e)
    assert r.returncode == 10
    assert "PEEKS_PRECONDITION_FAILED" in r.stderr
    assert not (plugins / "docker-compose").exists()
    assert n_calls(mock, "curl") == 3  # ATTEMPTS


def test_sha_mismatch_refused(env):
    e, mock, plugins = env
    e["CURL_MODE"] = "bad"
    r = run(e)
    assert r.returncode == 10
    assert not (plugins / "docker-compose").exists()
    assert list(plugins.glob("*.part.*")) == []


def test_up_failure_propagates(env):
    e, mock, plugins = env
    (plugins / "docker-compose").write_bytes(GOOD)
    e["UP_FAIL"] = "1"
    r = run(e)
    assert r.returncode == 12
    assert "PEEKS_PRECONDITION_FAILED" in r.stderr


def test_s3_only_never_calls_curl(env):
    e, mock, plugins = env
    e.update(PEEKS_TOOLS_SOURCE="s3-only", S3_MODE="ok", CURL_MODE="ok",
             ASSETS_BUCKET_NAME="bkt", ASSETS_BUCKET_PREFIX="pfx/")
    r = run(e)
    assert r.returncode == 0, r.stderr
    assert n_calls(mock, "curl") == 0
    assert "github.com" not in calls(mock)


def test_s3_only_s3_down_never_falls_back_to_github(env):
    e, mock, plugins = env
    e.update(PEEKS_TOOLS_SOURCE="s3-only", S3_MODE="fail", CURL_MODE="ok", ASSETS_BUCKET_NAME="bkt")
    r = run(e)
    assert r.returncode == 10
    assert n_calls(mock, "curl") == 0


def test_s3_only_without_bucket_vars_fails_explicitly(env):
    e, mock, plugins = env
    e.update(PEEKS_TOOLS_SOURCE="s3-only", CURL_MODE="ok")
    r = run(e)
    assert r.returncode == 10
    assert "ASSETS_BUCKET_NAME not set" in r.stderr
    assert n_calls(mock, "curl") == 0


def test_never_healthy_is_only_a_warning(env):
    e, mock, plugins = env
    (plugins / "docker-compose").write_bytes(GOOD)
    (mock / "health").write_text("starting\n")
    r = run(e)
    assert r.returncode == 0
    assert "WARNING: GitLab container not healthy" in r.stderr


def test_logs_resolved_gitlab_home(env):
    e, mock, plugins = env
    (plugins / "docker-compose").write_bytes(GOOD)
    (mock / "running").touch()
    assert f"GITLAB_HOME={e['GITLAB_HOME']}" in run(e).stderr


def test_compose_file_missing_rc11(env):
    e, mock, plugins = env
    (plugins / "docker-compose").write_bytes(GOOD)
    os.remove(os.path.join(e["GITLAB_HOME"], "docker-compose.yml"))
    r = run(e)
    assert r.returncode == 11
    assert "PEEKS_PRECONDITION_FAILED" in r.stderr


def test_unknown_source_rc10(env):
    e, mock, plugins = env
    e["PEEKS_TOOLS_SOURCE"] = "bogus"
    r = run(e)
    assert r.returncode == 10
    assert "unknown PEEKS_TOOLS_SOURCE" in r.stderr


URI = "s3://bkt/{}tools/v1/docker-compose-v2.27.1-linux-x86_64"


@pytest.mark.parametrize("prefix,expected", [("pfx/", "pfx/"), ("pfx", "pfx/"), ("", "")])
def test_s3_uri_prefix_normalisation(env, prefix, expected):
    e, mock, plugins = env
    e.update(PEEKS_TOOLS_SOURCE="s3-only", S3_MODE="ok", ASSETS_BUCKET_NAME="bkt",
             ASSETS_BUCKET_PREFIX=prefix)
    assert run(e).returncode == 0
    uris = [l.split()[3] for l in calls(mock).splitlines() if l.startswith("aws s3 cp")]
    assert uris and set(uris) == {URI.format(expected)}


def test_s3_first_falls_back_to_github(env):
    e, mock, plugins = env
    e.update(PEEKS_TOOLS_SOURCE="s3-first", S3_MODE="fail", CURL_MODE="ok",
             ASSETS_BUCKET_NAME="bkt", ASSETS_BUCKET_PREFIX="pfx")
    r = run(e)
    assert r.returncode == 0, r.stderr
    assert n_calls(mock, "aws") == 3 and n_calls(mock, "curl") == 1
    assert (plugins / "docker-compose").read_bytes() == GOOD


def test_real_sha_pin_is_enforced(env):
    # COMPOSE_SHA256 NOT overridden: the fake GOOD payload must be refused by the real pin,
    # and the pin must be the value published by docker/compose for v2.27.1.
    e, mock, plugins = env
    del e["COMPOSE_SHA256"]
    r = run(e)
    assert r.returncode == 10
    assert not (plugins / "docker-compose").exists()
    src = open(SCRIPT).read()
    assert "ddc876fe2a89d5b7ea455146b0975bfe52904eecba9b192193377d6f99d69ad9" in src


# ---- background launcher / waiter, extracted from the real Taskfiles ------------------------
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
REAL_TASK = shutil.which("task")


def _cmd_block(path, task, needle):
    with open(os.path.join(ROOT, path)) as f:
        cmds = yaml.safe_load(f)["tasks"][task]["cmds"]
    return next(c for c in cmds if isinstance(c, str) and needle in c)


def _prep(block, d):
    block = block.replace("/tmp/gitlab-init", f"{d}/gitlab-init")
    return re.sub(r"\{\{\.[A-Z_]+\}\}", "", block)


def _stub_task(d, rc, log_line):
    bindir = d / "stubbin"
    bindir.mkdir()
    # like go-task: a failing cmd exits 201 unless `-x` is given
    _exe(bindir / "task", f"#!/bin/bash\necho '{log_line}'\nsleep 1\n[ \"$1\" = -x ] || [ {rc} -eq 0 ] || exit 201\nexit {rc}\n")
    return bindir


def _run_taskfile(d, blocks, extra_path=None):
    # Same task run for launcher and waiter, like workshop:install: go-task reaps background
    # jobs when the run that started them ends.
    tf = d / "Taskfile.yaml"
    tf.write_text(yaml.safe_dump({"version": "3", "tasks": {"t": {"cmds": blocks}}}))
    env = {"PATH": f"{extra_path or ''}:/usr/bin:/bin", "HOME": str(d)}
    return subprocess.run([REAL_TASK, "-d", str(d), "t"], env=env, capture_output=True,
                          text=True, timeout=60)


@pytest.mark.skipif(REAL_TASK is None, reason="go-task not installed")
@pytest.mark.parametrize("rc", [0, 10])
def test_launcher_waiter_rc_propagation(tmp_path, rc):
    launch = _prep(_cmd_block("workshop/Taskfile.yaml", "install", "gitlab-init.pid"), tmp_path)
    wait = _prep(_cmd_block("cluster-providers/kind-kro-ack/Taskfile.yaml",
                            "hub:wait-for-gitlab-init", "PID_FILE="), tmp_path)
    stub = _stub_task(tmp_path, rc, "PEEKS_PRECONDITION_FAILED: boom" if rc else "fine")
    w = _run_taskfile(tmp_path, [launch, wait], str(stub))
    assert (tmp_path / "gitlab-init.rc").read_text().strip() == str(rc)
    if rc:
        assert w.returncode != 0
        assert "PEEKS_PRECONDITION_FAILED: boom" in w.stdout + w.stderr
        assert "background job failed (exit 10" in w.stdout
    else:
        assert w.returncode == 0, w.stdout + w.stderr
        assert "background job complete" in w.stdout


@pytest.mark.skipif(REAL_TASK is None, reason="go-task not installed")
def test_waiter_without_rc_file_keeps_old_behaviour(tmp_path):
    wait = _prep(_cmd_block("cluster-providers/kind-kro-ack/Taskfile.yaml",
                            "hub:wait-for-gitlab-init", "PID_FILE="), tmp_path)
    (tmp_path / "gitlab-init.pid").write_text("999999\n")  # dead pid, no .rc file
    w = _run_taskfile(tmp_path, [wait])
    assert w.returncode == 0, w.stdout + w.stderr
    assert "background job complete" in w.stdout


def test_init_ec2_runs_ensure_script_first():
    with open(os.path.join(ROOT, "workshop/Taskfile.yaml")) as f:
        cmds = yaml.safe_load(f)["tasks"]["gitlab:init-ec2"]["cmds"]
    real = [str(c) for c in cmds if "{{.MARK}}" not in str(c)]
    assert "ensure-gitlab-compose.sh" in real[0]


def test_healthy_gitlab_exits_0_without_plugin_or_compose_file(env):
    e, mock, plugins = env
    (mock / "gl_health").write_text("healthy\n")  # plugin absent, curl would fail
    e.update(CURL_MODE="fail", GITLAB_HOME=str(mock / "nope"))
    r = run(e)
    assert r.returncode == 0, r.stderr
    assert n_calls(mock, "curl") == 0 and "up -d" not in calls(mock)


def test_no_docker_fails_10_without_download(env):
    e, mock, plugins = env
    (mock.parent / "bin" / "docker").unlink()
    e["PATH"] = str(mock.parent / "bin") + ":/nonexistent"
    r = subprocess.run(["/bin/bash", SCRIPT], env=e, capture_output=True, text=True)
    assert r.returncode == 10 and "docker is not installed" in r.stderr
    assert n_calls(mock, "curl") == 0


@pytest.mark.skipif(REAL_TASK is None, reason="go-task not installed")
def test_waiter_stale_virtual_pid_without_rc_fails_fast(tmp_path):
    wait = _prep(_cmd_block("cluster-providers/kind-kro-ack/Taskfile.yaml",
                            "hub:wait-for-gitlab-init", "PID_FILE="), tmp_path)
    for n in ("gitlab-init.pid", "gitlab-init.log"):
        f = tmp_path / n
        f.write_text("g1\n" if n.endswith("pid") else "old\n")
        os.utime(f, (1, 1))  # ancient
    w = _run_taskfile(tmp_path, [wait])
    assert w.returncode != 0
    assert "left no exit code" in w.stdout + w.stderr
    assert "background job complete" not in w.stdout


@pytest.mark.skipif(REAL_TASK is None, reason="go-task not installed")
def test_secret_put_failure_is_not_fatal_under_go_task(tmp_path):
    with open(os.path.join(ROOT, "workshop/Taskfile.yaml")) as f:
        cmds = yaml.safe_load(f)["tasks"]["gitlab:init-ec2"]["cmds"]
    blk = next(c for c in cmds if isinstance(c, str) and "put-secret-value" in c and "USER1_PAT" in c)
    # both put-secret-value ... && printf lines must carry a `|| printf` warning
    assert blk.count("put-secret-value") == 2 and blk.count("Could not update") == 2
    bindir = tmp_path / "b"
    bindir.mkdir()
    _exe(bindir / "aws", "#!/bin/sh\nexit 1\n")
    shell = "ISOK=1\n" + "\n".join(
        l for l in ("if true; then", "  if true; then",
                    "    aws secretsmanager put-secret-value >/dev/null 2>&1 && \\",
                    "      printf 'ok\\n' || \\",
                    "      printf 'Could not update\\n'", "  fi", "fi", "echo AFTER"))
    w = _run_taskfile(tmp_path, [shell], str(bindir))
    assert w.returncode == 0 and "AFTER" in w.stdout


# ---- review fixes: github-first, quiet-job threshold, non-precondition exits -----------------
def test_github_first_is_accepted(env):
    # the exact default PEEKS exports; the old script answered rc 10 "unknown PEEKS_TOOLS_SOURCE"
    e, mock, plugins = env
    e["PEEKS_TOOLS_SOURCE"] = "github-first"
    r = run(e)
    assert r.returncode == 0, r.stderr
    assert (plugins / "docker-compose").exists() and n_calls(mock, "curl") >= 1


def test_github_first_falls_back_to_s3(env):
    e, mock, plugins = env
    e.update(PEEKS_TOOLS_SOURCE="github-first", CURL_MODE="fail", S3_MODE="ok", ASSETS_BUCKET_NAME="bkt")
    r = run(e)
    assert r.returncode == 0, r.stderr
    assert n_calls(mock, "curl") >= 1 and n_calls(mock, "aws") >= 1


def test_unset_source_is_github_first(env):
    e, mock, plugins = env
    e.update(CURL_MODE="fail", S3_MODE="ok", ASSETS_BUCKET_NAME="bkt")
    e.pop("PEEKS_TOOLS_SOURCE", None)
    assert run(e).returncode == 0


def test_health_wait_prints_heartbeat(env):
    e, mock, plugins = env
    (mock / "health").write_text("starting\n")
    e.update(HEALTH_TIMEOUT="3", HEALTH_INTERVAL="1", HEARTBEAT="1")
    (plugins / "docker-compose").write_text("GOOD\n")
    r = run(e)
    assert r.returncode == 0 and "still waiting for GitLab to be healthy" in r.stderr


def _waiter(tmp_path):
    return _prep(_cmd_block("cluster-providers/kind-kro-ack/Taskfile.yaml",
                            "hub:wait-for-gitlab-init", "PID_FILE="), tmp_path)


def _aged(tmp_path, age):
    import time
    for n, c in (("gitlab-init.pid", "g1\n"), ("gitlab-init.log", "quiet\n")):
        f = tmp_path / n
        f.write_text(c)
        t = time.time() - age
        os.utime(f, (t, t))


@pytest.mark.skipif(REAL_TASK is None, reason="go-task not installed")
def test_quiet_but_alive_job_is_not_stale(tmp_path):
    # log silent for 1000 s (< the 1200 s sign_in wait): the job finishes with rc 0 a few seconds later
    _aged(tmp_path, 1000)
    wait = _waiter(tmp_path)
    shell = f"( sleep 5; echo 0 > {tmp_path}/gitlab-init.rc ) > /dev/null 2>&1 < /dev/null &\n" + wait
    w = _run_taskfile(tmp_path, [shell])
    assert w.returncode == 0, w.stdout + w.stderr
    assert "left no exit code" not in w.stdout and "background job complete" in w.stdout


@pytest.mark.skipif(REAL_TASK is None, reason="go-task not installed")
def test_timeout_message_differs_from_stale(tmp_path):
    import time
    _aged(tmp_path, 0)
    w = _run_taskfile(tmp_path, [f"export BG_JOB_WAIT_TIMEOUT=3\ntouch {tmp_path}/gitlab-init.log\n" + _waiter(tmp_path)])
    assert w.returncode != 0
    assert "still running after 3s" in w.stdout and "stale pid file" not in w.stdout


def _rc_case(tmp_path, rc, log):
    (tmp_path / "gitlab-init.pid").write_text("999999\n")
    (tmp_path / "gitlab-init.rc").write_text(rc)
    (tmp_path / "gitlab-init.log").write_text(log)
    return _run_taskfile(tmp_path, [_waiter(tmp_path)])


@pytest.mark.skipif(REAL_TASK is None, reason="go-task not installed")
def test_non_precondition_failure_stays_non_fatal(tmp_path):
    # before this PR any exit of gitlab:init-ec2 was ignored; only precondition failures may abort
    w = _rc_case(tmp_path, "7\n", "some ruby error\n")
    assert w.returncode == 0, w.stdout + w.stderr
    assert "exited 7 without a precondition failure" in w.stdout


@pytest.mark.skipif(REAL_TASK is None, reason="go-task not installed")
def test_precondition_failure_is_fatal(tmp_path):
    w = _rc_case(tmp_path, "12\n", "PEEKS_PRECONDITION_FAILED: up -d failed\n")
    assert w.returncode != 0 and "background job failed (exit 12" in w.stdout


@pytest.mark.skipif(REAL_TASK is None, reason="go-task not installed")
def test_empty_rc_file_is_not_success(tmp_path):
    w = _rc_case(tmp_path, "", "PEEKS_PRECONDITION_FAILED: x\n")
    assert w.returncode != 0 and "background job failed (exit 1" in w.stdout


@pytest.mark.skipif(REAL_TASK is None, reason="go-task not installed")
def test_waiter_removes_pid_file(tmp_path):
    w = _rc_case(tmp_path, "0\n", "ok\n")
    assert w.returncode == 0 and not (tmp_path / "gitlab-init.pid").exists()


def test_init_ec2_sign_in_wait_prints_heartbeat():
    with open(os.path.join(ROOT, "workshop/Taskfile.yaml")) as f:
        cmds = yaml.safe_load(f)["tasks"]["gitlab:init-ec2"]["cmds"]
    blk = next(c for c in cmds if isinstance(c, str) and "users/sign_in" in c)
    assert "still waiting for GitLab sign_in" in blk
