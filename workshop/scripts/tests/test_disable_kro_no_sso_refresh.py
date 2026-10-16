"""`spokes:disable-kro` (workshop/Taskfile.yaml) must not sign in to Argo CD through IAM
Identity Center, and nothing a Taskfile cmd sources may be unparseable by go-task.

go-task runs every cmd in its own shell interpreter (mvdan/sh), not bash. `source` parses
the whole file first, so a file with zsh-only syntax (`${(%):-%x}`) fails before its first
line runs, and `2>/dev/null || true` hides it. That made the old SSO token refresh in
`spokes:disable-kro` dead code. It also must not come back working: the Identity Center
identity source is account-wide, so on an account with two workshop stacks the sign-in
would land on the other stack's Keycloak.

1. Static: no Taskfile cmd sources or runs the Playwright token refresh.
2. With go-task on PATH: every repo script a Taskfile cmd sources parses under go-task.
3. With go-task on PATH: the task's cmd, run verbatim under go-task against a local bare
   fleet-config repo (real git and yq; fake aws, argocd, kubectl, python3 and sleep, and an
   `rm` that only records), prunes through the kubectl fallback when the argocd CLI has no
   session, and starts no sign-in.

Run:  python -m pytest workshop/scripts/tests/test_disable_kro_no_sso_refresh.py -q
"""
import glob
import json
import os
import re
import shutil
import subprocess

import pytest

yaml = pytest.importorskip("yaml")

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
TASKFILE = os.path.join(REPO, "workshop", "Taskfile.yaml")
TASK = shutil.which("task")
SSO_REFRESH = re.compile(r"argocd-refresh-token\.sh|argocd_token_automation")
SOURCED = re.compile(r"(?:^|[\s;&|(])(?:source|\.)\s+\"?\{\{\.(?:REPO|ROOT_DIR)\}\}/([^\"\s]+)")


def taskfiles():
    return [os.path.join(REPO, "Taskfile.yaml"), TASKFILE] + sorted(
        glob.glob(os.path.join(REPO, "cluster-providers", "*", "Taskfile.yaml")))


def shell_texts(path):
    """(where, text) for every cmd and every `sh:` var of every task in a Taskfile."""
    tasks = (yaml.safe_load(open(path)) or {}).get("tasks") or {}
    rel = os.path.relpath(path, REPO)
    for name, task in tasks.items():
        if not isinstance(task, dict):
            continue
        for i, cmd in enumerate(task.get("cmds") or []):
            text = cmd.get("cmd") if isinstance(cmd, dict) else cmd
            if isinstance(text, str):
                yield f"{rel} {name}[{i}]", text
        for var, spec in (task.get("vars") or {}).items():
            if isinstance(spec, dict) and isinstance(spec.get("sh"), str):
                yield f"{rel} {name} vars.{var}", spec["sh"]


def test_no_taskfile_cmd_runs_the_sso_token_refresh():
    hits = [f"{where}: {line.strip()}"
            for path in taskfiles() for where, text in shell_texts(path)
            for line in text.splitlines()
            if SSO_REFRESH.search(line) and not line.strip().startswith("#")]
    assert not hits, "a Taskfile cmd runs the Playwright/Identity Center token refresh:\n" + "\n".join(hits)


@pytest.mark.skipif(not TASK, reason="go-task not on PATH")
def test_sourced_repo_scripts_parse_under_go_task(tmp_path):
    sourced = sorted({(m.group(1), where)
                      for path in taskfiles() for where, text in shell_texts(path)
                      for m in SOURCED.finditer(text)})
    bad = []
    for i, (rel, where) in enumerate(sourced):
        # mvdan/sh parses the whole file before running it, so a leading `return 0` makes
        # this a parse-only check: nothing in the script runs.
        probe = tmp_path / f"probe{i}.sh"
        probe.write_text("return 0\n" + open(os.path.join(REPO, rel)).read())
        (tmp_path / "Taskfile.yml").write_text(
            "version: '3'\nset: [errexit, nounset, pipefail]\n"
            f"tasks:\n  probe:\n    cmds:\n      - source {probe}\n")
        res = subprocess.run([TASK, "-s", "probe"], cwd=tmp_path, capture_output=True, text=True)
        if res.returncode:
            bad.append(f"{where} sources {rel}: {res.stderr.strip()}")
    assert not bad, "go-task cannot parse a script a Taskfile cmd sources:\n" + "\n".join(bad)


@pytest.mark.skipif(not TASK, reason="go-task not on PATH")
def test_go_task_source_rejects_zsh_only_expansion(tmp_path):
    """The mechanism behind the dead code, and test 2's parse-only premise, under go-task."""
    (tmp_path / "zsh.sh").write_text('echo RAN-ZSH\nX="${BASH_SOURCE[0]:-${(%):-%x}}"\n')
    (tmp_path / "early.sh").write_text("return 0\necho RAN-EARLY\n")
    (tmp_path / "Taskfile.yml").write_text(
        "version: '3'\nset: [errexit, nounset, pipefail]\n"
        "tasks:\n  probe:\n    cmds:\n"
        "      - |\n        source ./zsh.sh 2>/dev/null || echo SOURCE-FAILED\n"
        "        source ./early.sh\n        echo AFTER\n")
    out = subprocess.run([TASK, "-s", "probe"], cwd=tmp_path, capture_output=True, text=True).stdout
    assert out.split() == ["SOURCE-FAILED", "AFTER"]


CLUSTER = "peeks-spoke-dev"
FLEET_URL = "https://user1:test-password@git.example.test/user1/fleet-config.git"
BASE = "gitops/fleet/spoke-values/tenants/workshop/kro-clusters"

FAKES = {
    # no Argo CD session: `app sync` fails the way the CLI does without a token
    "argocd": """#!/usr/bin/env bash
echo "argocd $*" >> "$FAKE_LOG"
if [ "$1 $2" = "app sync" ]; then
  echo 'level=fatal msg="rpc error: code = Unauthenticated desc = no session information"' >&2
  exit 20
fi
exit 0
""",
    # ApplicationSet refresh annotations read back empty: both appsets have re-generated
    "kubectl": """#!/usr/bin/env bash
echo "kubectl $*" >> "$FAKE_LOG"
case " $* " in
  *" patch application "*) echo "application.argoproj.io/${5:-app} patched" ;;
esac
exit 0
""",
    "aws": '#!/usr/bin/env bash\necho "aws $*" >> "$FAKE_LOG"\nexit 0\n',
    # the token automation is a Python/Playwright script: any python3 call is a sign-in attempt
    "python3": '#!/usr/bin/env bash\necho "python3 $*" >> "$FAKE_LOG"\nexit 1\n',
    "sleep": "#!/usr/bin/env bash\nexit 0\n",
    "rm": '#!/usr/bin/env bash\necho "rm $*" >> "$FAKE_LOG"\n',
}


@pytest.mark.skipif(not TASK or not shutil.which("git") or not shutil.which("yq"),
                    reason="needs go-task, git and yq")
def test_disable_kro_prunes_via_kubectl_without_a_session(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name, text in FAKES.items():
        (bindir / name).write_text(text)
        (bindir / name).chmod(0o755)
    log = tmp_path / "calls.log"
    bare = tmp_path / "fleet-config.git"
    env = dict(
        os.environ, PATH=f"{bindir}:{os.environ['PATH']}", HOME=str(tmp_path),
        TMPDIR=str(tmp_path), FAKE_LOG=str(log),
        GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
        GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0=f"url.file://{bare}.insteadOf",
        GIT_CONFIG_VALUE_0=FLEET_URL,
        GIT_AUTHOR_NAME="test", GIT_AUTHOR_EMAIL="test@example.test",
        GIT_COMMITTER_NAME="test", GIT_COMMITTER_EMAIL="test@example.test",
    )
    env.pop("ARGOCD_AUTH_TOKEN", None)

    def git(*args, cwd=None):
        return subprocess.run(["git", *args], cwd=cwd, env=env, check=True,
                              capture_output=True, text=True).stdout

    # fleet-config as spokes:enable-kro leaves it for one spoke
    seed = tmp_path / "seed"
    git("init", "-q", "--bare", "-b", "main", str(bare))
    git("init", "-q", "-b", "main", str(seed))
    files = {
        f"{BASE}/values.yaml": f"clusters:\n  {CLUSTER}:\n    clusterName: {CLUSTER}\n",
        f"{BASE}/clusters/{CLUSTER}.json": json.dumps({"name": CLUSTER}) + "\n",
        "configs/multi-acct/values.yaml": f'clusters:\n  {CLUSTER}: "111122223333"\n',
        f"gitops/fleet/members/{CLUSTER}/values.yaml": "{}\n",
        f"overlays/clusters/{CLUSTER}/platform-manifests/values.yaml": "{}\n",
    }
    for rel, text in files.items():
        os.makedirs(os.path.dirname(seed / rel), exist_ok=True)
        (seed / rel).write_text(text)
    git("add", "-A", cwd=seed)
    git("commit", "-q", "-m", "seed", cwd=seed)
    git("push", "-q", str(bare), "main", cwd=seed)

    # {{.REPO}} is a scratch dir whose scripts/ is this checkout's, so on a Taskfile that
    # still sources scripts/argocd-refresh-token.sh the real file is what go-task reads.
    repo = tmp_path / "repo"
    (repo / "private").mkdir(parents=True)
    os.symlink(os.path.join(REPO, "scripts"), repo / "scripts")

    cmd = yaml.safe_load(open(TASKFILE))["tasks"]["spokes:disable-kro"]["cmds"][0]
    taskfile = {
        "version": "3", "set": ["errexit", "nounset", "pipefail"],
        "vars": {"CLUSTER": CLUSTER, "GIT_USERNAME": "user1", "GIT_PASSWORD": "test-password",
                 "GIT_DOMAIN": "git.example.test", "REPO": str(repo),
                 "HUB_CLUSTER_NAME": "peeks-hub", "AWS_REGION": "us-west-2",
                 "C_STEP": "", "C_OK": "", "C_ERR": "", "C_INFO": "", "C_RESET": ""},
        "tasks": {"disable": {"cmds": [cmd]}},
    }
    (tmp_path / "Taskfile.yml").write_text(yaml.safe_dump(taskfile, sort_keys=False))
    res = subprocess.run([TASK, "-s", "disable"], cwd=tmp_path, env=env,
                         capture_output=True, text=True, timeout=120)
    out = res.stdout + res.stderr
    calls = log.read_text().splitlines()

    assert res.returncode == 0, out
    assert f"argocd app sync clusters-kro-{CLUSTER} --prune --timeout 600" in calls
    assert "Falling back to kubectl patch" in out
    assert any(c.startswith(f"kubectl --kubeconfig {repo}/private/hub-kubeconfig patch application "
                            f"clusters-kro-{CLUSTER} -n argocd") and '"prune":true' in c for c in calls), calls
    assert f"De-registered {CLUSTER} from Argo CD" in out
    assert not [c for c in calls if c.startswith("python3")], "an SSO sign-in was started"
    # post-prune cleanup ran: spec and CARM mapping removed in Git, marker and member removed
    for rel in (f"{BASE}/values.yaml", "configs/multi-acct/values.yaml"):
        assert CLUSTER not in git("show", f"main:{rel}", cwd=bare), rel
    assert any(c.startswith("rm -f ") and c.endswith(f"{BASE}/clusters/{CLUSTER}.json") for c in calls), calls
    assert any(c.startswith("rm -rf ") and c.endswith(f"gitops/fleet/members/{CLUSTER}") for c in calls), calls
