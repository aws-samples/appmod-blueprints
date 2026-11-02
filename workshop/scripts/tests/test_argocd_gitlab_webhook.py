"""workshop/scripts/argocd-gitlab-webhook.sh with fake aws/kubectl/curl on PATH.

Proves (mocked, no network, no cluster):
  (a) reuse: a non-empty webhook.gitlab.secret already in the Secret is used as the hook
      token and the Secret is NOT patched; BOTH hooks are created (Application and
      ApplicationSet receivers) with that token and SSL verify on;
  (a2) empty/absent key: a token is generated and ONLY that key is merge-patched, with a
      warning, and the hooks use the generated token;
  (a3) idempotent: existing hooks (matched by URL) are PUT-updated, never duplicated;
  (a4) ARGOCD_APPSET_WEBHOOK=0 opts out of the ApplicationSet hook;
  (b) every failure only warns and exits 0;
  (c) neither the webhook token nor the GitLab PAT appears in stdout/stderr or argv.

Run:  python -m pytest workshop/scripts/tests/test_argocd_gitlab_webhook.py -q
"""
import json
import os
import shutil
import stat
import subprocess

import pytest

HERE = os.path.dirname(__file__)
SCRIPT = os.path.abspath(os.path.join(HERE, "..", "argocd-gitlab-webhook.sh"))
SERVER = "https://argocd-abc123.eks-capabilities.us-west-2.amazonaws.com"
PAT = "glpat-SECRETPATVALUE0123"
EXISTING = "capability-original-value-0123456789"
EXISTING_B64 = __import__("base64").b64encode(EXISTING.encode()).decode()

FAKE_AWS = """#!/usr/bin/env bash
echo "aws $*" >> "$MOCK/calls.log"
[ "${FAIL_AWS:-}" = 1 ] && exit 254
[ "${AWS_EMPTY:-}" = 1 ] && { echo None; exit 0; }
echo "%s"
""" % SERVER

FAKE_KUBECTL = """#!/usr/bin/env bash
echo "kubectl $*" >> "$MOCK/calls.log"
case "$*" in
  *"get secret"*)
    [ "${FAIL_GET:-}" = 1 ] && exit 1
    cat "$MOCK/secret.json"; exit 0 ;;
esac
[ "${FAIL_KUBECTL:-}" = 1 ] && exit 1
while [ $# -gt 0 ]; do
  if [ "$1" = "--patch-file" ]; then cp "$2" "$MOCK/patch.json"; fi
  shift
done
exit 0
"""

FAKE_CURL = r"""#!/usr/bin/env bash
echo "curl $*" >> "$MOCK/calls.log"
method=GET; body=""; url=""
while [ $# -gt 0 ]; do
  case "$1" in
    -X) method="$2"; shift ;;
    -K) cp "$2" "$MOCK/last.cfg"
        body=$(sed -E 's/^data-urlencode = "(.*)"$/\1/' "$2" | jq -Rn '[inputs|capture("^(?<k>[^=]+)=(?<v>.*)$")|{(.k):.v}]|add|
          with_entries(.value |= (if .=="true" then true elif .=="false" then false else . end))' -c)
        shift ;;
    http*) url="$1" ;;
  esac
  shift
done
if [ "$method" = GET ]; then
  [ "${FAIL_LIST:-}" = 1 ] && exit 22
  cat "$MOCK/hooks.json"; exit 0
fi
[ "${FAIL_WRITE:-}" = 1 ] && exit 22
printf '%s %s %s\n' "$method" "$url" "$body" >> "$MOCK/writes.log"
exit 0
"""


def _mk(path, text):
    with open(path, "w") as f:
        f.write(text)
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)


@pytest.fixture()
def env(tmp_path):
    if not shutil.which("jq"):
        pytest.skip("jq required")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    mock = tmp_path / "mock"
    mock.mkdir()
    _mk(bindir / "aws", FAKE_AWS)
    _mk(bindir / "kubectl", FAKE_KUBECTL)
    _mk(bindir / "curl", FAKE_CURL)
    (mock / "hooks.json").write_text("[]")
    (mock / "secret.json").write_text(json.dumps({"data": {"webhook.gitlab.secret": EXISTING_B64}}))
    e = {
        "PATH": f"{bindir}:{os.environ['PATH']}",
        "MOCK": str(mock),
        "HUB_CLUSTER_NAME": "peeks-hub",
        "AWS_REGION": "us-west-2",
        "GIT_DOMAIN": "git.example.invalid",
        "GIT_USERNAME": "user1",
        "GITLAB_TOKEN": PAT,
    }
    return e, mock


def run(e, **extra):
    p = subprocess.run(["bash", SCRIPT], env={**e, **extra}, capture_output=True, text=True)
    return p


def writes(mock):
    f = mock / "writes.log"
    return f.read_text().splitlines() if f.exists() else []


def _bodies(mock):
    return [json.loads(x.split(" ", 2)[2]) for x in writes(mock)]


def test_reuses_existing_secret_value_and_does_not_patch(env):
    e, mock = env
    p = run(e)
    assert p.returncode == 0
    calls = (mock / "calls.log").read_text()
    assert "patch secret" not in calls
    assert not (mock / "patch.json").exists()
    w = writes(mock)
    assert len(w) == 2
    assert all(x.startswith("POST https://git.example.invalid/api/v4/projects/user1%2Ffleet-config/hooks ") for x in w)
    bodies = _bodies(mock)
    assert {b["url"] for b in bodies} == {SERVER + "/api/webhook", SERVER + "/api/applicationset/webhook"}
    for b in bodies:
        assert b["token"] == EXISTING
        assert b["push_events"] is True and b["enable_ssl_verification"] is True
    assert "describe-capability --cluster-name peeks-hub --capability-name argocd" in calls
    out = p.stdout + p.stderr
    assert "reusing" in out and "⚠" not in out
    # (c) no secret in output or argv
    for s in (EXISTING, PAT):
        assert s not in out + calls


@pytest.mark.parametrize("data", [{}, {"webhook.gitlab.secret": ""}])
def test_empty_or_absent_key_generates_and_patches_only_that_key(env, data):
    e, mock = env
    (mock / "secret.json").write_text(json.dumps({"data": data}))
    p = run(e)
    assert p.returncode == 0
    patch = json.loads((mock / "patch.json").read_text())
    assert list(patch["stringData"].keys()) == ["webhook.gitlab.secret"]
    tok = patch["stringData"]["webhook.gitlab.secret"]
    assert len(tok) == 64
    assert "patch secret argocd-webhook-creds-secret --type merge" in (mock / "calls.log").read_text()
    assert len(writes(mock)) == 2
    assert all(b["token"] == tok for b in _bodies(mock))
    out = p.stdout + p.stderr
    assert "may keep rejecting" in out
    assert tok not in out + (mock / "calls.log").read_text()
    assert PAT not in out


def test_appset_opt_out(env):
    e, mock = env
    p = run(e, ARGOCD_APPSET_WEBHOOK="0")
    assert p.returncode == 0
    w = writes(mock)
    assert len(w) == 1
    assert json.loads(w[0].split(" ", 2)[2])["url"] == SERVER + "/api/webhook"


def test_rerun_updates_existing_hooks_without_duplicates(env):
    e, mock = env
    (mock / "hooks.json").write_text(json.dumps([
        {"id": 7, "url": SERVER + "/api/webhook"},
        {"id": 9, "url": SERVER + "/api/applicationset/webhook"},
        {"id": 3, "url": "https://other.example/hook"},
    ]))
    p = run(e)
    assert p.returncode == 0
    w = writes(mock)
    assert len(w) == 2 and all(x.startswith("PUT ") for x in w)
    assert any(x.split()[1].endswith("/hooks/7") for x in w)
    assert any(x.split()[1].endswith("/hooks/9") for x in w)


@pytest.mark.parametrize("extra", [
    {"FAIL_AWS": "1"},
    {"AWS_EMPTY": "1"},
    {"FAIL_KUBECTL": "1", "EMPTY": "1"},
    {"FAIL_LIST": "1"},
    {"FAIL_WRITE": "1"},
    {"GITLAB_TOKEN": ""},
    {"GIT_DOMAIN": ""},
    {"HUB_CLUSTER_NAME": ""},
])
def test_every_failure_only_warns_and_exits_zero(env, extra):
    e, mock = env
    if extra.pop("EMPTY", None):
        (mock / "secret.json").write_text(json.dumps({"data": {}}))
    p = run(e, **extra)
    assert p.returncode == 0
    out = p.stdout + p.stderr
    assert PAT not in out
    if "FAIL_WRITE" not in extra:
        assert "⚠ argocd webhook" in out
    else:
        assert out.count("⚠ argocd webhook") == 2
    if (mock / "patch.json").exists():
        tok = json.loads((mock / "patch.json").read_text())["stringData"]["webhook.gitlab.secret"]
        assert tok not in out


def test_patch_failure_skips_gitlab_hooks(env):
    e, mock = env
    (mock / "secret.json").write_text(json.dumps({"data": {}}))
    run(e, FAIL_KUBECTL="1")
    assert writes(mock) == []


def test_missing_tool_warns_and_exits_zero(env, tmp_path):
    e, _ = env
    # PATH with only the fakes, no jq
    only = tmp_path / "only"
    only.mkdir()
    for n in ("aws", "kubectl", "curl"):
        os.symlink(os.path.join(e["PATH"].split(":")[0], n), only / n)
    for n in ("bash", "mktemp", "chmod", "rm", "head", "od", "tr", "printf", "cat", "dirname"):
        w = shutil.which(n)
        if w:
            os.symlink(w, only / n)
    p = subprocess.run([shutil.which("bash"), SCRIPT], env={**e, "PATH": str(only)}, capture_output=True, text=True)
    assert p.returncode == 0
    assert "jq not found" in p.stdout
