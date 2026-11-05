"""Hermetic tests: `hub:pivot` never exposes the overlay credential (#1033 follow-up).

The overlay PAT (argocd/fleet-config-repo) used by kind-kro-ack `hub:pivot` to probe, clone
and push the consumer's overlay repo must never be on a git command line (ps-visible), never
be written to the clone's .git/config, and never reach a credential helper. All of that is
now done by cluster-providers/kind-kro-ack/scripts/pivot-overlay-git.sh, via GIT_ASKPASS.

`git` is a fake on PATH. It logs every argv, checks that GIT_ASKPASS returns the password,
and serves https://overlay.test/... from a local bare repo through the real git binary.
No network.

Run:  python -m pytest workshop/scripts/tests/test_hub_pivot_overlay_credential.py -q
"""
import json
import os
import re
import shutil
import stat
import subprocess
import sys

import pytest

yaml = pytest.importorskip("yaml")

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
TASKFILE = os.environ.get("PIVOT_TASKFILE") or os.path.join(
    REPO, "cluster-providers", "kind-kro-ack", "Taskfile.yaml")
SCRIPT = os.path.join(REPO, "cluster-providers", "kind-kro-ack", "scripts", "pivot-overlay-git.sh")
REAL_GIT = shutil.which("git")
SECRET = "glpat-S3CR3T-do-not-leak-0123456789"
URL = "https://overlay.test/team/fleet-config.git"

pytestmark = pytest.mark.skipif(REAL_GIT is None, reason="git not installed")

FAKE_GIT = r'''#!{python} -I
import json, os, subprocess, sys
REAL, LOG, BARE, URL = {real!r}, os.environ["FAKE_GIT_LOG"], os.environ["FAKE_GIT_BARE"], {url!r}
SNAP = os.environ["FAKE_GIT_SNAP"]
argv = sys.argv[1:]
with open(LOG, "a") as f:
    f.write(json.dumps({{"argv": argv, "askpass": os.environ.get("GIT_ASKPASS", "")}}) + "\n")

# Global options, then the subcommand.
cfg, i = [], 0
while i < len(argv) and argv[i] == "-c":
    cfg.append(argv[i + 1]); i += 2
sub, rest = (argv[i], argv[i + 1:]) if i < len(argv) else ("", [])

def real(args, **kw):
    return subprocess.run([REAL] + args, **kw).returncode

def authed():
    """Emulate an https remote: git asks GIT_ASKPASS for the password."""
    if os.environ.get("FAKE_GIT_DOWN"):
        return False
    ap = os.environ.get("GIT_ASKPASS")
    if not ap:
        return False
    user = next((c.split("=", 1)[1] for c in cfg if c.startswith("credential.username=")), "")
    pw = subprocess.run([ap, "Password for 'https://%s@overlay.test': " % user],
                        capture_output=True, text=True).stdout.rstrip("\n")
    return user == os.environ["FAKE_GIT_USER"] and pw == os.environ["FAKE_GIT_PASS"]

if sub in ("ls-remote", "clone", "push") and URL not in " ".join(rest) and sub != "push":
    sys.exit(128)
if sub == "ls-remote":
    sys.exit(0 if authed() and real(["ls-remote", BARE], stdout=subprocess.DEVNULL) == 0 else 128)
if sub == "clone":
    if not authed():
        sys.exit(128)
    dest = rest[-1]
    rc = real(["clone"] + [BARE if a == URL else a for a in rest])
    if rc == 0:  # what a real https clone records: the URL it was given
        real(["-C", dest, "remote", "set-url", "origin", URL])
    sys.exit(rc)
if sub == "push":
    remote = rest[0]
    url = subprocess.run([REAL, "remote", "get-url", remote], capture_output=True, text=True).stdout.strip() \
        if not remote.startswith("https://") else remote
    gd = subprocess.run([REAL, "rev-parse", "--git-dir"], capture_output=True, text=True).stdout.strip()
    with open(os.path.join(gd, "config")) as s, open(SNAP, "w") as d:
        d.write(s.read())
    if url != URL or not authed() or os.environ.get("FAKE_GIT_PUSH_FAIL"):
        sys.exit(1)
    sys.exit(real(["push", BARE] + rest[1:]))
sys.exit(real(argv))
'''


@pytest.fixture
def env(tmp_path):
    bare = tmp_path / "bare.git"
    seed = tmp_path / "seed"
    g = lambda *a, **kw: subprocess.run([REAL_GIT] + list(a), check=True, capture_output=True, **kw)
    g("init", "-q", "--bare", "-b", "main", str(bare))
    g("init", "-q", "-b", "main", str(seed))
    (seed / "README.md").write_text("overlay\n")
    g("-C", str(seed), "add", "-A")
    g("-C", str(seed), "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init")
    g("-C", str(seed), "push", "-q", str(bare), "main")

    bindir = tmp_path / "bin"; bindir.mkdir()
    fake = bindir / "git"
    fake.write_text(FAKE_GIT.format(python=sys.executable, real=REAL_GIT, url=URL))
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    tmpdir = tmp_path / "tmp"; tmpdir.mkdir()
    home = tmp_path / "home"; home.mkdir()
    # A user-level `store` helper: must NOT receive the PAT.
    (home / ".gitconfig").write_text("[credential]\n\thelper = store\n")

    e = {
        "PATH": f"{bindir}:{os.environ['PATH']}",
        "HOME": str(home), "TMPDIR": str(tmpdir),
        "GIT_CONFIG_NOSYSTEM": "1",
        "FAKE_GIT_LOG": str(tmp_path / "git.log"),
        "FAKE_GIT_BARE": str(bare),
        "FAKE_GIT_SNAP": str(tmp_path / "clone-config.snapshot"),
        "FAKE_GIT_USER": "x-access-token", "FAKE_GIT_PASS": SECRET,
        "OVERLAY_GIT_PASSWORD": SECRET,
    }
    manifest = tmp_path / "hub-instance.yaml"
    manifest.write_text("apiVersion: kro.run/v1alpha1\nkind: EksCluster\nmetadata:\n  name: acme-hub\n")
    return {"env": e, "tmp": tmp_path, "bare": bare, "manifest": manifest, "home": home,
            "tmpdir": tmpdir}


def run(ctx, *args, **extra):
    e = dict(ctx["env"]); e.update(extra)
    return subprocess.run(["bash", SCRIPT] + list(args), env=e, capture_output=True, text=True)


def git_calls(ctx):
    p = ctx["tmp"] / "git.log"
    return [json.loads(l) for l in p.read_text().splitlines()] if p.exists() else []


def assert_no_leak(ctx, res):
    for call in git_calls(ctx):
        assert not any(SECRET in a for a in call["argv"]), call["argv"]
        if set(call["argv"]) & {"ls-remote", "clone", "push"}:
            # Every authenticated call: helpers cleared (no store/cache of the PAT) + askpass.
            assert "credential.helper=" in call["argv"], call["argv"]
            assert call["askpass"], call["argv"]
    assert SECRET not in res.stdout + res.stderr
    # Nothing on disk holds the secret: no askpass leftover, no helper store, no clone.
    assert list(ctx["tmpdir"].iterdir()) == [], list(ctx["tmpdir"].iterdir())
    assert not (ctx["home"] / ".git-credentials").exists()
    for root, _, files in os.walk(ctx["tmp"]):
        for f in files:
            with open(os.path.join(root, f), "rb") as fh:
                assert SECRET.encode() not in fh.read(), os.path.join(root, f)


def test_probe_ok_uses_askpass_and_no_secret_in_argv(env):
    res = run(env, "probe", URL)
    assert res.returncode == 0, res.stderr
    calls = git_calls(env)
    assert [c["argv"][-2:] for c in calls] == [["ls-remote", URL]]
    a = calls[0]["argv"]
    assert "credential.helper=" in a and "credential.username=x-access-token" in a
    assert calls[0]["askpass"]
    assert_no_leak(env, res)


def test_probe_custom_username(env):
    res = run(env, "probe", URL, OVERLAY_GIT_USERNAME="oauth2", FAKE_GIT_USER="oauth2")
    assert res.returncode == 0, res.stderr
    assert "credential.username=oauth2" in git_calls(env)[0]["argv"]
    assert_no_leak(env, res)


def test_probe_wrong_credential_fails(env):
    res = run(env, "probe", URL, FAKE_GIT_PASS="something-else")
    assert res.returncode != 0
    assert_no_leak(env, res)


def test_publish_commits_and_pushes_without_leaking(env):
    res = run(env, "publish", URL, "main", "self-adoption/hub", str(env["manifest"]),
              "acme-hub.yaml", "[#1033] GitOps-assert hub acme-hub EksCluster (self-adoption)")
    assert res.returncode == 0, res.stderr
    subs = [next(a for a in c["argv"] if not a.startswith("-") and "=" not in a) for c in git_calls(env)]
    assert subs[0] == "ls-remote" and "clone" in subs and subs[-1] == "push"
    push = git_calls(env)[-1]["argv"]
    assert push[-2:] == ["origin", "HEAD:main"]
    # The clone's .git/config (snapshot at push time) carries no credential.
    cfg = (env["tmp"] / "clone-config.snapshot").read_text()
    assert SECRET not in cfg
    assert re.search(r"url = " + re.escape(URL) + r"\s*$", cfg, re.M), cfg
    assert "credential" not in cfg
    # The manifest landed at the exact path on the exact branch, with the same message.
    show = subprocess.run([REAL_GIT, "--git-dir", str(env["bare"]), "show", "main:self-adoption/hub/acme-hub.yaml"],
                          capture_output=True, text=True)
    assert show.returncode == 0 and "name: acme-hub" in show.stdout
    log = subprocess.run([REAL_GIT, "--git-dir", str(env["bare"]), "log", "-1", "--format=%s|%an|%ae", "main"],
                         capture_output=True, text=True).stdout.strip()
    assert log == "[#1033] GitOps-assert hub acme-hub EksCluster (self-adoption)|peeks-pivot|pivot@peeks.local"
    assert_no_leak(env, res)


def test_publish_honours_basepath(env):
    res = run(env, "publish", URL, "main", "gitops/self-adoption/hub", str(env["manifest"]),
              "acme-hub.yaml", "msg")
    assert res.returncode == 0, res.stderr
    show = subprocess.run([REAL_GIT, "--git-dir", str(env["bare"]), "show",
                           "main:gitops/self-adoption/hub/acme-hub.yaml"], capture_output=True)
    assert show.returncode == 0
    assert_no_leak(env, res)


def test_publish_push_failure_is_reported(env):
    res = run(env, "publish", URL, "main", "self-adoption/hub", str(env["manifest"]),
              "acme-hub.yaml", "msg", FAKE_GIT_PUSH_FAIL="1")
    assert res.returncode != 0
    assert_no_leak(env, res)


def test_publish_unreachable_never_clones(env):
    res = run(env, "publish", URL, "main", "self-adoption/hub", str(env["manifest"]),
              "acme-hub.yaml", "msg", FAKE_GIT_DOWN="1")
    assert res.returncode != 0
    assert [c["argv"][-2] for c in git_calls(env)] == ["ls-remote"]
    assert_no_leak(env, res)


def test_publish_missing_branch_fails(env):
    res = run(env, "publish", URL, "nope", "self-adoption/hub", str(env["manifest"]), "acme-hub.yaml", "msg")
    assert res.returncode != 0
    assert_no_leak(env, res)


@pytest.mark.parametrize("bad", ["https://x-access-token:%s@overlay.test/r.git" % SECRET,
                                 "https://%s@overlay.test/r.git" % SECRET, "http://overlay.test/r.git"])
def test_refuses_credentialed_or_plain_http_url(env, bad):
    res = run(env, "probe", bad)
    assert res.returncode == 2
    assert git_calls(env) == []


def test_requires_password_in_env(env):
    res = run(env, "probe", URL, OVERLAY_GIT_PASSWORD="")
    assert res.returncode == 2 and git_calls(env) == []


# --- Taskfile wiring (static) ------------------------------------------------------------

def _pivot_script():
    doc = yaml.safe_load(open(TASKFILE))
    cmds = doc["tasks"]["hub:pivot"]["cmds"]
    return "\n".join(c if isinstance(c, str) else c.get("cmd", "") for c in cmds)


def test_taskfile_never_builds_a_credentialed_url():
    s = _pivot_script()
    assert not re.search(r"\$\{?REPO_PASS\}?@", s)
    assert not re.search(r"https://\$\{?REPO_USER\}?:", s)
    assert "PUSH_URL" not in s


def test_taskfile_git_calls_all_go_through_the_helper():
    s = _pivot_script()
    assert not re.search(r"\bgit\s+(ls-remote|clone|push)\b", s), "direct overlay git call left in hub:pivot"
    calls = re.findall(r"OVERLAY_GIT_PASSWORD=\"\$REPO_PASS\"[^\n]*\\\n\s*bash '[^']*pivot-overlay-git\.sh' (probe|publish)", s)
    assert calls == ["probe", "publish"], calls
    # Same branch / path / message as before the change.
    assert 'REL_DIR="self-adoption/hub"' in s
    assert '"$OVERLAY_REV" "$REL_DIR" "$WORK/hub-instance.yaml" "$HUB.yaml"' in s
    assert '"[#1033] GitOps-assert hub $HUB EksCluster (self-adoption)"' in s
