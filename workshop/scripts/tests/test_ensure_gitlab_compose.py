"""workshop/scripts/ensure-gitlab-compose.sh with fake docker/curl/aws on PATH.

Proves (mocked, no network, no root, no real docker):
  - compose plugin present and GitLab running: no-op (no download, no up -d);
  - compose missing + GitHub ok: plugin installed (sha256 verified), GitLab started;
  - compose missing + GitHub down + S3 ok (s3-first): installed from the S3 mirror;
  - sha256 mismatch is refused (rc 10, plugin not installed);
  - `docker compose up -d` failing propagates (rc 12);
  - PEEKS_TOOLS_SOURCE=s3-only never calls curl; without bucket vars it fails explicitly;
  - container never healthy: bounded, rc 13.

Run:  python -m pytest workshop/scripts/tests/test_ensure_gitlab_compose.py -q
"""
import hashlib
import os
import stat
import subprocess

import pytest

SCRIPT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "ensure-gitlab-compose.sh"))
GOOD = b"GOOD\n"
GOOD_SHA = hashlib.sha256(GOOD).hexdigest()

FAKE_DOCKER = r"""#!/bin/bash
echo "docker $*" >> "$MOCK/calls.log"
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


def test_never_healthy_times_out(env):
    e, mock, plugins = env
    (plugins / "docker-compose").write_bytes(GOOD)
    (mock / "health").write_text("starting\n")
    r = run(e)
    assert r.returncode == 13
    assert "not healthy" in r.stderr
