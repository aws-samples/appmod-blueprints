"""Hermetic tests for the prewarm-rust-cicd hardening against a Backstage whose backend
failed to start (MigrationLocked on a duplicated knex lock row) or whose catalog is not
serving the template yet.

1. backstage_scaffolder (scripts/validation/backstage-auth.sh) fails at once when POST
   /api/scaffolder/v2/tasks is not 2xx or returns no id, printing the HTTP code and the
   error body. It used to poll tasks/null 30x10 s.
2. backstage_template_status reads the template from the catalog WITH the token and
   follows redirects: an unauthenticated 401 (scaffolder) or 302 (catalog) answers on a
   broken backend too.
3. The prewarm gate requires that authenticated read to return 200, retries 3x60 s when
   it does not, and stops with the "restart Backstage (and dedupe the knex lock row)"
   hint when the backend log shows the startup failed. A scaffold POST refused with
   503/404 gets the same 3x60 s retries.

Run:  python -m pytest workshop/scripts/tests/test_prewarm_rust_r7.py -q
"""
import os
import subprocess

import pytest

pytest.importorskip("yaml")
from test_prewarm_rust_waits import REPO, fakes, lines, render  # noqa: E402

BSAUTH = os.path.join(REPO, "scripts", "validation", "backstage-auth.sh")
HINT = "restart Backstage (and dedupe the knex lock row"
FAILED_LOG = ("Backend startup failed\n"
              "MigrationLockError: Plugin 'proxy' startup failed; caused by MigrationLocked: "
              "Migration table is already locked\n")


# ── prewarm-rust-cicd gate and POST retries ────────────────────────────────────────────
def run_task(tmp_path, template_status=None, scaffold=None, backend_log=None):
    """template_status / scaffold: bash bodies replacing the default fakes. The fake
    curl still answers 401 on the unauthenticated scaffolder probe, as a broken backend does."""
    b, plat = fakes(tmp_path)
    helper = plat / "scripts" / "validation" / "backstage-auth.sh"
    text = helper.read_text()
    if scaffold is not None:
        text += ('backstage_scaffolder() {\n'
                 '  C=$(cat "$FAKE_T/clock"); echo "$C scaffold" >> "$FAKE_T/scaffold.calls"\n'
                 f'{scaffold}\n}}\n')
    if template_status is not None:
        text += ('backstage_template_status() {\n'
                 '  C=$(cat "$FAKE_T/clock"); echo "$C template" >> "$FAKE_T/template.calls"\n'
                 f'{template_status}\n}}\n')
    helper.write_text(text)
    if backend_log is not None:
        (tmp_path / "backstage.log").write_text(backend_log)
    env = dict(os.environ, PATH=f"{b}:{os.environ['PATH']}", FAKE_T=str(tmp_path), HOME=str(tmp_path))
    r = subprocess.run(["bash", "-c", render("prewarm-rust-cicd", plat)], env=env,
                       capture_output=True, text=True, timeout=60, cwd=str(tmp_path))
    return r, int((tmp_path / "clock").read_text())


def test_gate_401_alone_is_not_enough_backend_failed(tmp_path):
    # Broken bucket-B Backstage: 401 on the scaffolder probe, 503 on the catalog,
    # MigrationLocked in the log. Before: the gate passed and the scaffold ran.
    r, clock = run_task(tmp_path, template_status="  echo 503", backend_log=FAILED_LOG)
    assert r.returncode == 0
    assert HINT in r.stdout, r.stdout
    assert "HTTP 503" in r.stdout
    assert lines(tmp_path, "scaffold.calls") == []
    assert "waiting for CICDPipeline" not in r.stdout
    assert len(lines(tmp_path, "template.calls")) == 1      # no retry on a failed startup
    assert clock == 0, clock


def test_gate_template_late_then_served(tmp_path):
    # Catalog still ingesting: 404 twice, then 200 -> scaffold after two 60 s retries.
    body = ('  N=$(wc -l < "$FAKE_T/template.calls")\n'
            '  if [ "$N" -ge 3 ]; then echo 200; else echo 404; fi')
    r, clock = run_task(tmp_path, template_status=body)
    assert "catalog template read returned HTTP 404 — retrying in 60s (1/3)" in r.stdout, r.stdout
    assert "(2/3)" in r.stdout and "(3/3)" not in r.stdout
    assert "scaffolder task completed" in r.stdout
    assert "✓ CICDPipeline rust-cicd-pipeline ACTIVE." in r.stdout, r.stdout
    assert len(lines(tmp_path, "template.calls")) == 3
    assert clock == 120, clock


def test_gate_template_never_served_is_bounded(tmp_path):
    r, clock = run_task(tmp_path, template_status="  echo 404")
    assert "not served by the Backstage catalog (authenticated read: HTTP 404, 4 tries)" in r.stdout, r.stdout
    assert lines(tmp_path, "scaffold.calls") == []
    assert "waiting for CICDPipeline" not in r.stdout
    assert len(lines(tmp_path, "template.calls")) == 4
    assert clock == 180, clock


def test_gate_backend_fails_during_retries(tmp_path):
    # First read 503 with a clean log, the backend then logs the failure: stop with the hint.
    body = ('  echo "Backend startup failed" > "$FAKE_T/backstage.log"; echo 503')
    r, clock = run_task(tmp_path, template_status=body)
    assert HINT in r.stdout, r.stdout
    assert lines(tmp_path, "scaffold.calls") == []
    assert clock == 0


POST_503 = ('  echo "backstage_scaffolder: POST https://cf.example/backstage/api/scaffolder/v2/tasks '
            'returned HTTP 503: {\\"error\\":{\\"name\\":\\"ServiceUnavailableError\\"}}" >&2; return 2')


def test_post_503_retries_three_times_then_stops(tmp_path):
    r, clock = run_task(tmp_path, scaffold=POST_503)
    assert "returned HTTP 503" in r.stdout and "ServiceUnavailableError" in r.stdout, r.stdout
    for i in (1, 2, 3):
        assert f"scaffold POST returned HTTP 503 — retrying in 60s ({i}/3)" in r.stdout, r.stdout
    assert "scaffold POST still HTTP 503 after 3 retries" in r.stdout
    assert "waiting for CICDPipeline" not in r.stdout
    assert len(lines(tmp_path, "scaffold.calls")) == 4
    assert clock == 180, clock


def test_post_404_then_success(tmp_path):
    body = ('  if [ -f "$FAKE_T/tried" ]; then touch "$FAKE_T/scaffolded"; return 0; fi\n'
            '  touch "$FAKE_T/tried"\n'
            '  echo "backstage_scaffolder: POST x returned HTTP 404: {\\"error\\":{\\"name\\":\\"NotFoundError\\"}}" >&2; return 2')
    r, clock = run_task(tmp_path, scaffold=body)
    assert "scaffold POST returned HTTP 404 — retrying in 60s (1/3)" in r.stdout, r.stdout
    assert "✓ CICDPipeline rust-cicd-pipeline ACTIVE." in r.stdout, r.stdout
    assert len(lines(tmp_path, "scaffold.calls")) == 2
    assert clock == 60, clock


def test_post_refused_with_backend_failed_gives_restart_hint(tmp_path):
    # Template read was 200 (cached catalog) but the backend log shows the failure by
    # the time the POST is refused: no retry, the restart hint.
    body = ('  echo "MigrationLocked" > "$FAKE_T/backstage.log"\n' + POST_503)
    r, clock = run_task(tmp_path, scaffold=body)
    assert HINT in r.stdout, r.stdout
    assert len(lines(tmp_path, "scaffold.calls")) == 1
    assert "retrying" not in r.stdout
    assert clock == 0


# ── backstage-auth.sh helpers ──────────────────────────────────────────────────────────
def helper_env(tmp_path, post_code, post_body, task_status="completed"):
    """Fake curl: POST tasks -> post_body + post_code (as -w '\\n%{http_code}' prints it);
    GET tasks/<id> -> {"status": task_status}; catalog GET -> 200 with -L, 302 without."""
    b = tmp_path / "bin"
    b.mkdir()
    (tmp_path / "post_body").write_text(post_body)
    (b / "curl").write_text(
        '#!/usr/bin/env bash\n'
        'printf "%s\\n" "$*" >> "$FAKE_T/curl.calls"\n'
        'case "$*" in\n'
        f'  *"-X POST"*"/api/scaffolder/v2/tasks"*) cat "$FAKE_T/post_body"; printf "\\n{post_code}";;\n'
        f'  *"/api/scaffolder/v2/tasks/"*) printf \'{{"status":"{task_status}"}}\';;\n'
        '  *"/api/catalog/entities/by-name/template/"*)\n'
        '     case "$*" in *-sLk*) printf 200;; *) printf 302;; esac;;\n'
        '  *) printf 000;;\n'
        'esac\n')
    (b / "sleep").write_text('#!/usr/bin/env bash\necho "sleep $*" >> "$FAKE_T/sleep.calls"\n')
    for f in ("curl", "sleep"):
        os.chmod(b / f, 0o755)
    return dict(os.environ, PATH=f"{b}:{os.environ['PATH']}", FAKE_T=str(tmp_path), HOME=str(tmp_path),
                BACKSTAGE_URL="https://cf.example/backstage", USER1_PASSWORD="pw")


def call_helper(tmp_path, env, expr):
    script = f'. "{BSAUTH}" >/dev/null 2>&1; backstage_get_token() {{ echo tok; }}; {expr}'
    return subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True,
                          timeout=60, cwd=str(tmp_path))


@pytest.mark.parametrize("code,body", [
    ("503", '{"error":{"name":"ServiceUnavailableError","message":"Service Unavailable"}}'),
    ("404", '{"error":{"name":"NotFoundError","message":"template not found"}}'),
    ("201", '{"id":null}'),
])
def test_scaffolder_fails_fast_on_refused_post(tmp_path, code, body):
    env = helper_env(tmp_path, code, body)
    r = call_helper(tmp_path, env, 'backstage_scaffolder "template:default/cicd-pipeline-gitops" \'{"appname":"rust"}\'')
    assert r.returncode == 2, (r.returncode, r.stderr)
    assert f"returned HTTP {code}:" in r.stderr, r.stderr
    assert body in r.stderr, r.stderr
    calls = lines(tmp_path, "curl.calls")
    assert not any("/tasks/null" in c for c in calls), calls     # before: 30 polls of tasks/null
    assert lines(tmp_path, "sleep.calls") == []


def test_scaffolder_success_path_unchanged(tmp_path):
    env = helper_env(tmp_path, "201", '{"id":"abc-123"}')
    r = call_helper(tmp_path, env, 'backstage_scaffolder "template:default/cicd-pipeline-gitops" \'{"appname":"rust"}\'')
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "abc-123"
    assert any("/api/scaffolder/v2/tasks/abc-123" in c for c in lines(tmp_path, "curl.calls"))


def test_scaffolder_failed_task_still_returns_1(tmp_path):
    env = helper_env(tmp_path, "201", '{"id":"abc-123"}', task_status="failed")
    r = call_helper(tmp_path, env, 'backstage_scaffolder "t" \'{}\'')
    assert r.returncode == 1


def test_template_status_is_authenticated_and_follows_redirects(tmp_path):
    env = helper_env(tmp_path, "201", "{}")
    r = call_helper(tmp_path, env, "backstage_template_status cicd-pipeline-gitops")
    assert r.stdout.strip() == "200", (r.stdout, r.stderr)
    call = [c for c in lines(tmp_path, "curl.calls") if "/api/catalog/" in c][-1]
    assert "-sLk" in call
    assert "Authorization: Bearer tok" in call
    assert call.endswith("/backstage/api/catalog/entities/by-name/template/default/cicd-pipeline-gitops")


def test_template_status_000_when_curl_fails(tmp_path):
    env = helper_env(tmp_path, "201", "{}")
    (tmp_path / "bin" / "curl").write_text("#!/usr/bin/env bash\nexit 7\n")
    r = call_helper(tmp_path, env, "backstage_template_status")
    assert r.stdout.strip() == "000"
