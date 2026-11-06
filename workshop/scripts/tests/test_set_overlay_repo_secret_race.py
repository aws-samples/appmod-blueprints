"""`set-overlay-repo` registers two ArgoCD credential Secrets (`argocd/fleet-config-repo`
and `argocd/gitlab-user-repo-creds`). The `argocd-gitlab-repo-creds` chart ships an
ExternalSecret with the same name for each one (creationPolicy: Owner), so ESO can create
the Secret while the task is creating it. `kubectl apply` does a GET (NotFound) and then a
CREATE; if ESO wins in between, the CREATE fails with AlreadyExists, and with errexit the
whole `task install` aborts (exit 201).

These tests run the real `set-overlay-repo` cmd under go-task (same `set:` options as the
workshop Taskfile) with fake `kubectl`, `aws`, `git` and `sleep` on PATH:

1. ESO creates the Secret between kubectl's GET and CREATE -> the task retries and passes.
2. The ExternalSecret exists and ESO creates the Secret a moment later -> the task waits for
   it and does not write it imperatively (ESO stays the single owner).
3. A real, persistent apply error is still fatal after 5 attempts (the retry must not
   swallow it).
4. The ExternalSecret exists but ESO never creates the Secret -> after the wait the task
   falls back to creating it, as before.

The run stops at the idempotent fast-path (overlay already wired), right after step 3.

Run:  python -m pytest workshop/scripts/tests/test_set_overlay_repo_secret_race.py -q
"""
import os
import re
import shutil
import subprocess

import pytest

yaml = pytest.importorskip("yaml")

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
TASKFILE = os.path.join(REPO, "workshop", "Taskfile.yaml")
TASK = shutil.which("task")
FLEET = "fleet-config-repo"
CREDS = "gitlab-user-repo-creds"
OVERLAY_URL = "https://git.example/user1/fleet-config.git"

KUBECTL = r"""#!/usr/bin/env bash
# Fake kubectl. State lives in $FAKE_STATE:
#   secret-<name>   the Secret exists
#   raced-<name>    the AlreadyExists race was already injected for <name>
# FAKE_RACE   names whose first CREATE loses the race against ESO
# FAKE_ES     names that have an ExternalSecret
# FAKE_ESO_AFTER  number of `get secret` calls after which ESO has created the Secret
# FAKE_FAIL   names whose apply always fails (Forbidden)
S="$FAKE_STATE"
echo "kubectl $*" >> "$S/calls"
args=("$@")
for ((i=0; i<${#args[@]}; i++)); do
  if [ "${args[$i]}" = get ]; then kind="${args[$((i+1))]:-}"; name="${args[$((i+2))]:-}"; fi
  if [ "${args[$i]}" = apply ]; then verb=apply; fi
done
has() { case " $1 " in *" $2 "*) return 0;; esac; return 1; }
if [ "${verb:-}" = apply ]; then
  body=$(cat)
  n=$(printf '%s\n' "$body" | sed -n 's/^ *name: *//p' | head -1)
  echo "apply $n" >> "$S/applies"
  if has "${FAKE_FAIL:-}" "$n"; then
    echo 'Error from server (Forbidden): secrets is forbidden' >&2; exit 1
  fi
  if has "${FAKE_RACE:-}" "$n" && [ ! -e "$S/raced-$n" ]; then
    touch "$S/raced-$n" "$S/secret-$n"
    echo "Error from server (AlreadyExists): error when creating \"STDIN\": secrets \"$n\" already exists" >&2
    exit 1
  fi
  touch "$S/secret-$n"; echo "secret/$n configured"; exit 0
fi
case "${kind:-}" in
  ns) exit 0 ;;
  externalsecret) has "${FAKE_ES:-}" "$name" && exit 0
                  echo "Error from server (NotFound): externalsecrets \"$name\" not found" >&2; exit 1 ;;
  secret)
    c=$(( $(cat "$S/gets-$name" 2>/dev/null || echo 0) + 1 )); echo "$c" > "$S/gets-$name"
    if has "${FAKE_ES:-}" "$name" && [ "$c" -gt "${FAKE_ESO_AFTER:-0}" ]; then touch "$S/secret-$name"; fi
    [ -e "$S/secret-$name" ] && exit 0
    echo "Error from server (NotFound): secrets \"$name\" not found" >&2; exit 1 ;;
esac
exit 0
"""

AWS = r"""#!/usr/bin/env bash
# Fake aws: get-secret-value returns a <hub>/config whose overlay is already wired, so the
# task takes its idempotent fast-path right after step 3.
case " $* " in
  *" get-secret-value "*) printf '%s\n' '{"metadata":"{\"overlay_repo_url\":\"__URL__\"}"}' ;;
esac
exit 0
"""


def overlay_cmd():
    with open(TASKFILE) as f:
        task = yaml.safe_load(f)["tasks"]["set-overlay-repo"]
    cmds = [c if isinstance(c, str) else c.get("cmd") for c in task["cmds"]]
    assert len(cmds) == 1 and isinstance(cmds[0], str)
    return cmds[0]


def run(tmp_path, **env):
    bin_ = tmp_path / "bin"
    state = tmp_path / "state"
    bin_.mkdir()
    state.mkdir()
    for name, body in {"kubectl": KUBECTL, "aws": AWS.replace("__URL__", OVERLAY_URL),
                       "git": "#!/bin/sh\nexit 0\n", "sleep": "#!/bin/sh\nexit 0\n"}.items():
        p = bin_ / name
        p.write_text(body)
        p.chmod(0o755)
    cmd = overlay_cmd()
    values = {"GIT_DOMAIN": "git.example", "GIT_USERNAME": "user1", "GIT_PASSWORD": "pw",
              "REPO": str(tmp_path), "HUB_CLUSTER_NAME": "hub", "AWS_REGION": "us-west-2",
              "OVERLAY_REPO_BASEPATH": "", "CLUSTER_PROVIDER": "kind-kro-ack"}
    names = sorted(set(re.findall(r"\{\{\s*\.(\w+)\s*\}\}", cmd)))
    vars_ = {n: values.get(n, "") for n in names}
    (tmp_path / "private").mkdir()
    taskfile = {"version": "3", "set": ["errexit", "nounset", "pipefail"], "silent": True,
                "vars": vars_, "tasks": {"set-overlay-repo": {"cmds": [cmd]}}}
    (tmp_path / "Taskfile.yml").write_text(yaml.safe_dump(taskfile, sort_keys=False, width=10000))
    full_env = dict(os.environ, PATH=f"{bin_}:{os.environ['PATH']}", FAKE_STATE=str(state), **env)
    p = subprocess.run([TASK, "set-overlay-repo"], cwd=tmp_path, env=full_env,
                       capture_output=True, text=True, timeout=120)
    applies = (state / "applies").read_text().split("\n") if (state / "applies").exists() else []
    return p, [a for a in applies if a]


pytestmark = pytest.mark.skipif(not TASK, reason="go-task not on PATH")


def test_alreadyexists_race_is_retried(tmp_path):
    p, applies = run(tmp_path, FAKE_RACE=f"{FLEET} {CREDS}")
    out = p.stdout + p.stderr
    assert p.returncode == 0, out
    assert "AlreadyExists" in out  # the race really was injected
    assert "leaving untouched (idempotent)" in out  # reached the step after the Secrets
    assert applies.count(f"apply {FLEET}") == 2 and applies.count(f"apply {CREDS}") == 2, applies


def test_eso_owned_secret_is_waited_for_not_written(tmp_path):
    p, applies = run(tmp_path, FAKE_ES=f"{FLEET} {CREDS}", FAKE_ESO_AFTER="2")
    out = p.stdout + p.stderr
    assert p.returncode == 0, out
    assert applies == [], applies  # ESO stays the only writer
    assert "leaving untouched (idempotent)" in out


def test_persistent_apply_error_is_still_fatal(tmp_path):
    p, applies = run(tmp_path, FAKE_FAIL=FLEET)
    out = p.stdout + p.stderr
    assert p.returncode != 0, out
    assert "Forbidden" in out
    assert "leaving untouched (idempotent)" not in out
    assert applies.count(f"apply {FLEET}") == 5, applies  # bounded retries, then fatal


def test_stalled_eso_falls_back_to_imperative_create(tmp_path):
    """ExternalSecret present but ESO never creates the Secret: fall back to applying it."""
    p, applies = run(tmp_path, FAKE_ES=f"{FLEET} {CREDS}", FAKE_ESO_AFTER="1000")
    out = p.stdout + p.stderr
    assert p.returncode == 0, out
    assert applies == [f"apply {FLEET}", f"apply {CREDS}"], applies
    assert "leaving untouched (idempotent)" in out


def test_no_bare_kubectl_apply_of_repo_secrets():
    """Both repo-credential Secrets go through the race-safe helper, not a bare apply."""
    pipes = re.findall(r"cat <<EOF \| (.+)", overlay_cmd())
    assert pipes == [f"register_repo_secret {FLEET}", f"register_repo_secret {CREDS}"], pipes
