"""Hermetic tests for `spokes:enable-crossplane` (workshop/Taskfile.yaml): enabling a spoke
adds its entry to the overlay's crossplane-clusters/values.yaml and keeps every other one.

The task's shell block is read verbatim from the Taskfile, its go-task variables are filled
in, and it runs with bash against a local bare git repo seeded with gitops/fleet, as the
workshop seeds fleet-config. git and yq are real; the fleet-config https URL is redirected to
the bare repo with url.<base>.insteadOf. `aws` is a fake, and `rm` only records its
arguments, so the task's own cleanup of its temp clone never runs. No AWS, no network.

Run:  python -m pytest workshop/scripts/tests/test_enable_crossplane_values.py -q
"""
import os
import re
import shutil
import subprocess

import pytest

yaml = pytest.importorskip("yaml")
for _tool in ("bash", "git", "yq"):
    if not shutil.which(_tool):
        pytest.skip(f"{_tool} not available", allow_module_level=True)

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
TASKFILE = os.path.join(REPO, "workshop", "Taskfile.yaml")
OVERLAY = "gitops/fleet/spoke-values/tenants/workshop/crossplane-clusters/values.yaml"
FLEET_URL = "https://user1:test-password@git.example.test/user1/fleet-config.git"

FAKE_AWS = """#!/usr/bin/env bash
# the task's only AWS call: the IDE SharedRole lookup (--query already applied)
[ "$1 $2" = "iam list-roles" ] && { echo '["ws-PEEKSSharedRole-1"]'; exit 0; }
echo "unexpected aws call: $*" >&2; exit 1
"""
FAKE_RM = '#!/usr/bin/env bash\necho "rm $*" >> "$FAKE_RM_LOG"\n'

TASK_VARS = {
    "GIT_USERNAME": "user1", "GIT_PASSWORD": "test-password", "GIT_DOMAIN": "git.example.test",
    "AWS_ACCOUNT_ID": "111122223333", "K8S_VERSION": "1.35", "RESOURCE_PREFIX": "peeks",
    "C_STEP": "", "C_OK": "", "C_ERR": "", "C_INFO": "", "C_RESET": "",
}


def _script(cluster, config_file):
    body = yaml.safe_load(open(TASKFILE))["tasks"]["spokes:enable-crossplane"]["cmds"][0]
    values = dict(TASK_VARS, CLUSTER=cluster, CONFIG_FILE=config_file)
    out = re.sub(r"\{\{\.([A-Z0-9_]+)\}\}", lambda m: values[m.group(1)], body)
    assert "{{" not in out, re.findall(r"\{\{[^}]*\}\}", out)
    # go-task runs every cmd under the Taskfile's `set: [errexit, nounset, pipefail]`
    return "set -euo pipefail\n" + out


@pytest.fixture
def fleet(tmp_path):
    """A seeded bare fleet-config repo, and run(cluster) that enables a spoke against it."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name, text in (("aws", FAKE_AWS), ("rm", FAKE_RM)):
        (bindir / name).write_text(text)
        (bindir / name).chmod(0o755)
    (tmp_path / "home").mkdir()
    (tmp_path / "tmp").mkdir()
    config = tmp_path / "config.local.yaml"
    config.write_text('adminRoleName: "ParticipantRole"\n')
    bare = tmp_path / "fleet-config.git"
    env = dict(
        os.environ, PATH=f"{bindir}:{os.environ['PATH']}", HOME=str(tmp_path / "home"),
        TMPDIR=str(tmp_path / "tmp"), FAKE_RM_LOG=str(tmp_path / "rm.log"),
        GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
        GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0=f"url.file://{bare}.insteadOf",
        GIT_CONFIG_VALUE_0=FLEET_URL,
        GIT_AUTHOR_NAME="test", GIT_AUTHOR_EMAIL="test@example.test",
        GIT_COMMITTER_NAME="test", GIT_COMMITTER_EMAIL="test@example.test",
    )

    def git(*args, cwd=None):
        return subprocess.run(["git", *args], cwd=cwd, env=env, check=True,
                              capture_output=True, text=True).stdout

    seed = tmp_path / "seed"
    git("init", "-q", "--bare", "-b", "main", str(bare))
    git("init", "-q", "-b", "main", str(seed))
    shutil.copytree(os.path.join(REPO, "gitops", "fleet"), seed / "gitops" / "fleet")
    git("add", "-A", cwd=seed)
    git("commit", "-q", "-m", "seed", cwd=seed)
    git("push", "-q", str(bare), "main", cwd=seed)

    class Fleet:
        def run(self, cluster):
            script = tmp_path / f"enable-{cluster}.sh"
            script.write_text(_script(cluster, str(config)))
            res = subprocess.run(["bash", str(script)], env=env, cwd=tmp_path,
                                 capture_output=True, text=True, timeout=120)
            assert res.returncode == 0, res.stdout + res.stderr
            return res.stdout

        def clusters(self):
            return yaml.safe_load(git("show", f"main:{OVERLAY}", cwd=bare))["clusters"] or {}

        def commits(self):
            return int(git("rev-list", "--count", "main", cwd=bare))

        def edit_overlay(self, text, message):
            """Commit a hand edit of the overlay file, as a user would."""
            work = tmp_path / "edit"
            git("clone", "-q", FLEET_URL, str(work))
            (work / OVERLAY).write_text(text)
            git("commit", "-q", "-am", message, cwd=work)
            git("push", "-q", cwd=work)

    return Fleet()


def test_enabling_prod_after_dev_keeps_dev(fleet):
    fleet.run("peeks-spoke-dev")
    dev = fleet.clusters()["peeks-spoke-dev"]
    assert dev["clusterName"] == "peeks-spoke-dev"
    assert dev["kubernetesVersion"] == "1.35" and dev["accountId"] == "111122223333"
    assert dev["adminRoleArn"].endswith(":role/ParticipantRole")
    assert dev["adminInstanceRoleArn"].endswith(":role/ws-PEEKSSharedRole-1")

    fleet.run("peeks-spoke-prod")  # the order `task install` uses
    clusters = fleet.clusters()
    assert sorted(clusters) == ["peeks-spoke-dev", "peeks-spoke-prod"]
    assert clusters["peeks-spoke-dev"] == dev
    assert clusters["peeks-spoke-prod"]["vpcCidr"] != dev["vpcCidr"]


def test_rerun_is_idempotent(fleet):
    fleet.run("peeks-spoke-dev")
    fleet.run("peeks-spoke-prod")
    before, commits = fleet.clusters(), fleet.commits()
    for cluster in ("peeks-spoke-dev", "peeks-spoke-prod"):  # re-run of `task install`
        assert "already enabled (idempotent)" in fleet.run(cluster)
    assert fleet.clusters() == before
    assert fleet.commits() == commits


def test_keeps_hand_written_entries(fleet):
    fleet.edit_overlay(
        "# team clusters\nclusters:\n  team-a:\n    clusterName: team-a\n"
        '    vpcCidr: "10.50.0.0/16"\n', "add team-a by hand")
    fleet.run("peeks-spoke-dev")
    clusters = fleet.clusters()
    assert sorted(clusters) == ["peeks-spoke-dev", "team-a"]
    assert clusters["team-a"] == {"clusterName": "team-a", "vpcCidr": "10.50.0.0/16"}
