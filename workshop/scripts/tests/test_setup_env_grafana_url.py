"""GRAFANA_URL ends up as the Amazon Managed Grafana (AMG) endpoint even when AMG is created
after `setup-env` (workshop/Taskfile.yaml) has finished waiting for it.

v0.5.0-rc2 (remote install): setup-env's 18 x 10 s wait for `<prefix>-observability` ended at
10:09:35 and the hub created AMG at 10:10:46, so the IDE kept the AMG console fallback for good.
setup-env now writes that fallback, then keeps polling in the background
(workshop/scripts/resolve-grafana-url.sh) and rewrites GRAFANA_URL once AMG exists. It still
never writes a CloudFront /grafana path (no in-cluster Grafana: that path is a 404).

`aws` and `sleep` are fakes on PATH: `aws grafana list-workspaces` answers None until its
FAKE_AMG_AFTER-th call, then the workspace id; `sleep` returns at once, so the 1 h background
poll runs in well under a second. setup-env's cmd is read verbatim from the Taskfile, its go-task
variables filled in, and run with bash; one test runs go-task itself on a copy of the Taskfile
(skipped if go-task, yq or jq is not on PATH), which checks that the background poll survives
go-task's shell. No AWS, no network.

Run:  python -m pytest workshop/scripts/tests/test_setup_env_grafana_url.py -q
"""
import os
import re
import shutil
import subprocess
import time

import pytest

yaml = pytest.importorskip("yaml")
if not shutil.which("bash"):
    pytest.skip("bash not available", allow_module_level=True)

WORKSHOP = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
TASKFILE = os.path.join(WORKSHOP, "Taskfile.yaml")
RESOLVER = os.path.join(WORKSHOP, "scripts", "resolve-grafana-url.sh")
TASK = shutil.which("task")
TEMPLATE_VAR = re.compile(r'\{\{\s*\.([A-Z0-9_]+)\s*(?:\|\s*default\s+"([^"]*)"\s*)?\}\}')
CF = "d111111abcdef8.cloudfront.net"
AMG_HOST = "g-0123456789.grafana-workspace.us-west-2.amazonaws.com"
AMG_URL = f'export GRAFANA_URL="https://{AMG_HOST}"'
CONSOLE_URL = ('export GRAFANA_URL="https://us-west-2.console.aws.amazon.com/grafana/home'
               '?region=us-west-2#/workspaces"')
FAKE_AWS = """echo "aws $*" >> "$FAKE_LOG"
if [ "$1" = grafana ] && [ -n "${FAKE_AWS_ERROR:-}" ]; then echo "$FAKE_AWS_ERROR" >&2; exit 254; fi
case "$1 $2" in
  "grafana list-workspaces")
    n=$(( $(cat "$FAKE_COUNT" 2>/dev/null || echo 0) + 1 )); echo "$n" > "$FAKE_COUNT"
    if [ "$n" -ge "$FAKE_AMG_AFTER" ]; then echo "g-0123456789"; else echo "None"; fi ;;
  "grafana describe-workspace") echo "${FAKE_ENDPOINT:-g-0123456789.grafana-workspace.us-west-2.amazonaws.com}" ;;
  "eks describe-capability") echo "https://argocd-0123abcd.example.com" ;;
  "cloudfront list-distributions") echo "d111111abcdef8.cloudfront.net" ;;
  "secretsmanager get-secret-value")
    echo '{"user_password":"not-a-real-password","keycloak_admin_password":"not-a-real-admin"}' ;;
  *) echo "unexpected aws call: $*" >&2; exit 1 ;;
esac"""
# Returns at once, except after setup-env's own 18 polls (the background poll) when
# FAKE_BG_SLEEP is set: a slow background poll shows that setup-env does not wait for it.
FAKE_SLEEP = """echo "sleep $*" >> "$FAKE_LOG"
if [ -n "${FAKE_BG_SLEEP:-}" ] && [ "$(cat "$FAKE_COUNT" 2>/dev/null || echo 0)" -gt 18 ]; then
  /bin/sleep "$FAKE_BG_SLEEP"
fi"""
SETUP_ENV_VARS = {"C_OK": "", "C_INFO": "", "C_RESET": "", "CF_DOMAIN": CF, "GIT_DOMAIN_VAR": "",
                  "ARGOCD_URL": "https://argocd-0123abcd.example.com",
                  "USER_PASSWORD": "not-a-real-password", "KC_ADMIN_PASSWORD": "not-a-real-admin",
                  "AWS_REGION": "us-west-2", "AWS_ACCOUNT_ID": "111122223333",
                  "RESOURCE_PREFIX": "acme", "HUB_CLUSTER_NAME": "acme-hub", "ROOT_DIR": WORKSHOP}
CONFIG = """aws: {region: us-west-2, accountId: "111122223333"}
hub: {clusterName: acme-hub}
domain: d111111abcdef8.cloudfront.net
resourcePrefix: acme
"""


def _env(tmp_path, amg_after, **extra):
    bindir, home = tmp_path / "bin", tmp_path / "home"
    bindir.mkdir(exist_ok=True)
    (home / ".bashrc.d").mkdir(parents=True, exist_ok=True)
    for name, body in (("aws", FAKE_AWS), ("sleep", FAKE_SLEEP)):
        (bindir / name).write_text("#!/usr/bin/env bash\n" + body + "\n")
        (bindir / name).chmod(0o755)
    log = tmp_path / "calls.log"
    log.write_text("")
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", HOME=str(home),
               FAKE_LOG=str(log), FAKE_COUNT=str(tmp_path / "count"),
               FAKE_AMG_AFTER=str(amg_after), **extra)
    return env, log, home / ".bashrc.d" / "platform.sh"


def _setup_env_script(**task_vars):
    """setup-env's cmd, verbatim from the Taskfile, with its go-task variables filled in."""
    (block,) = yaml.safe_load(open(TASKFILE))["tasks"]["setup-env"]["cmds"]
    values = dict(SETUP_ENV_VARS, **task_vars)

    def fill(m):
        name, default = m.group(1), m.group(2)
        return values[name] if name in values else (default if default is not None else "")

    script = TEMPLATE_VAR.sub(fill, block)
    assert "{{" not in script, re.findall(r"\{\{[^}]*\}\}", script)
    return script


def _run_setup_env(tmp_path, amg_after):
    env, log, platform_sh = _env(tmp_path, amg_after)
    (tmp_path / "run.sh").write_text(_setup_env_script())
    res = subprocess.run(["bash", str(tmp_path / "run.sh")], env=env, capture_output=True,
                         text=True, timeout=60)
    assert res.returncode == 0, res.stderr
    return res, log, platform_sh


def _grafana_lines(platform_sh):
    return re.findall(r"^export GRAFANA_URL=.*$", platform_sh.read_text(), re.M)


def _polls(log):
    return sum(c.startswith("aws grafana list-workspaces") for c in log.read_text().splitlines())


def _wait_for(cond, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.2)
    return cond()


def test_amg_created_after_the_wait_is_written_later(tmp_path):
    # AMG shows up on poll 25: after setup-env's own 18 polls (the rc2 timing)
    res, log, platform_sh = _run_setup_env(tmp_path, amg_after=25)
    assert "corrected in the background" in res.stdout, res.stdout
    assert _wait_for(lambda: _grafana_lines(platform_sh) == [AMG_URL]), _grafana_lines(platform_sh)
    assert _polls(log) == 25
    assert f"{CF}/grafana" not in platform_sh.read_text()
    # every other variable setup-env wrote is still there
    out = platform_sh.read_text()
    for name in ("BACKSTAGE_URL", "ARGOCD_URL", "GIT_TOKEN", "KEYCLOAK_ADMIN_PASSWORD"):
        assert f"export {name}=" in out, name


def test_amg_already_there_is_written_at_once_with_no_background_poll(tmp_path):
    res, log, platform_sh = _run_setup_env(tmp_path, amg_after=1)
    assert _grafana_lines(platform_sh) == [AMG_URL]
    assert "corrected in the background" not in res.stdout
    time.sleep(1)
    assert _polls(log) == 1


def test_amg_found_during_the_wait_needs_no_background_poll(tmp_path):
    res, log, platform_sh = _run_setup_env(tmp_path, amg_after=10)
    assert _grafana_lines(platform_sh) == [AMG_URL]
    assert "corrected in the background" not in res.stdout
    time.sleep(1)
    assert _polls(log) == 10


def test_amg_never_created_keeps_the_console_fallback_and_never_cf_grafana(tmp_path):
    _, log, platform_sh = _run_setup_env(tmp_path, amg_after=10**6)
    assert _grafana_lines(platform_sh) == [CONSOLE_URL]
    # the background poll gives up after its 360 polls (sleep is a no-op here)
    assert _wait_for(lambda: _polls(log) == 18 + 360), _polls(log)
    time.sleep(0.5)
    assert _polls(log) == 18 + 360
    assert _grafana_lines(platform_sh) == [CONSOLE_URL]
    assert "/grafana\"" not in platform_sh.read_text().replace("/grafana/home", "")


def test_setup_env_rerun_keeps_one_grafana_line(tmp_path):
    _run_setup_env(tmp_path, amg_after=1)
    _run_setup_env(tmp_path, amg_after=1)
    assert _grafana_lines(tmp_path / "home" / ".bashrc.d" / "platform.sh") == [AMG_URL]


# ---------------------------------------------------------------- the resolver on its own
def _resolve(tmp_path, amg_after, tries, content=None, **extra):
    env, log, platform_sh = _env(tmp_path, amg_after, **extra)
    if content is not None:
        platform_sh.write_text(content)
    res = subprocess.run(["sh", RESOLVER, str(platform_sh), "us-west-2", "acme", str(tries), "10"],
                         env=env, capture_output=True, text=True, timeout=60)
    return res, log, platform_sh


def test_resolver_replaces_the_fallback_in_place(tmp_path):
    before = f'export A="1"\n{CONSOLE_URL}\nexport B="2"\n'
    res, log, platform_sh = _resolve(tmp_path, amg_after=3, tries=5, content=before)
    assert res.returncode == 0, res.stderr
    assert platform_sh.read_text() == f'export A="1"\n{AMG_URL}\nexport B="2"\n'
    # sleeps only between polls
    assert log.read_text().count("sleep 10") == 2


def test_resolver_gives_up_after_its_tries_and_leaves_the_file_alone(tmp_path):
    res, log, platform_sh = _resolve(tmp_path, amg_after=10**6, tries=4, content=CONSOLE_URL + "\n")
    assert res.returncode == 1
    assert _polls(log) == 4 and log.read_text().count("sleep 10") == 3
    assert platform_sh.read_text() == CONSOLE_URL + "\n"


def test_resolver_rejects_an_endpoint_that_is_not_a_hostname(tmp_path):
    res, _, platform_sh = _resolve(tmp_path, amg_after=1, tries=2, content=CONSOLE_URL + "\n",
                                   FAKE_ENDPOINT='x|y";touch /tmp/pwn')
    assert res.returncode == 1
    assert platform_sh.read_text() == CONSOLE_URL + "\n"


def test_resolver_reports_aws_errors_instead_of_hiding_them(tmp_path):
    # expired credentials must not look like "AMG not created yet" in the log
    err = "An error occurred (ExpiredTokenException) when calling the ListWorkspaces operation"
    res, _, platform_sh = _resolve(tmp_path, amg_after=1, tries=2, content=CONSOLE_URL + "\n",
                                   FAKE_AWS_ERROR=err)
    assert res.returncode == 1
    assert res.stderr.count("ExpiredTokenException") == 2, res.stderr
    assert platform_sh.read_text() == CONSOLE_URL + "\n"


# ---------------------------------------------------------------- under go-task
@pytest.mark.skipif(not (TASK and shutil.which("yq") and shutil.which("jq")),
                    reason="needs go-task, yq and jq on PATH")
def test_background_poll_survives_go_task(tmp_path):
    ws = tmp_path / "workshop"
    (ws / "scripts").mkdir(parents=True)
    shutil.copy(TASKFILE, ws / "Taskfile.yaml")
    shutil.copy(RESOLVER, ws / "scripts" / "resolve-grafana-url.sh")
    (tmp_path / "config.local.yaml").write_text(CONFIG)
    env, log, platform_sh = _env(tmp_path, amg_after=25, FAKE_BG_SLEEP="1")
    t0 = time.time()
    res = subprocess.run([TASK, "-d", str(ws), "setup-env"], env=env, capture_output=True,
                         text=True, timeout=120)
    took = time.time() - t0
    assert res.returncode == 0, res.stdout + res.stderr
    assert "corrected in the background" in res.stdout, res.stdout + res.stderr
    # go-task returned (and closed its stdout/stderr) while the background poll still had about
    # 6 s of sleeps to go: the poll is detached and holds none of the caller's fds
    assert took < 5, took
    assert _grafana_lines(platform_sh) == [CONSOLE_URL]
    assert _wait_for(lambda: _grafana_lines(platform_sh) == [AMG_URL]), (
        _grafana_lines(platform_sh), res.stdout, res.stderr)


@pytest.mark.skipif(not (TASK and shutil.which("yq") and shutil.which("jq") and shutil.which("script")),
                    reason="needs go-task, yq, jq and util-linux script on PATH")
def test_background_poll_survives_the_terminal_closing(tmp_path):
    # `task setup-env` run by hand in an IDE terminal: the terminal (here a pty from `script`)
    # closes when task exits and sends SIGHUP to its session. The poll must be in its own
    # session (setsid) to keep running.
    ws = tmp_path / "workshop"
    (ws / "scripts").mkdir(parents=True)
    shutil.copy(TASKFILE, ws / "Taskfile.yaml")
    shutil.copy(RESOLVER, ws / "scripts" / "resolve-grafana-url.sh")
    (tmp_path / "config.local.yaml").write_text(CONFIG)
    env, log, platform_sh = _env(tmp_path, amg_after=25, FAKE_BG_SLEEP="1")
    out = tmp_path / "terminal.out"
    # stdin stays open (an idle terminal) until task has exited: with stdin at EOF, `script`
    # tears the pty down while task is still running, which is not what a user does.
    with open(out, "w") as fh:
        p = subprocess.Popen(["script", "-qec", f"{TASK} -d {ws} setup-env", "/dev/null"],
                             env=env, stdin=subprocess.PIPE, stdout=fh, stderr=subprocess.STDOUT)
        try:
            rc = p.wait(timeout=120)
        finally:
            p.stdin.close()
    assert rc == 0, out.read_text()
    assert "corrected in the background" in out.read_text(), out.read_text()
    assert _wait_for(lambda: _grafana_lines(platform_sh) == [AMG_URL]), (
        _grafana_lines(platform_sh), _polls(log))
    assert _polls(log) == 25
