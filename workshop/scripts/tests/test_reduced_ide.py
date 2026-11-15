"""Hermetic go-task tests for the reduced-IDE-role mode (v0.5 integration branch).

Two config.yaml keys, on top of `privilegedSteps: external` (see test_privileged_offload.py):

* `aws.installRoleArn`: on an EC2 host the install runs as this role (an `install` profile
  that assumes it from the instance role), so the instance role needs no IAM write. Teardown
  on the host (PEEKS_AWS_IDE_ONLY=true) stays on the instance role.
* `privilegedSteps: external` on `destroy`: Kubernetes-only teardown, the direct AWS deletes
  are left to the stack sweep.

The real go-task runs on a copy of the Taskfiles with a fake `aws` / `curl` / `kind` on PATH.
`curl` succeeds here so the EC2 branch (generated private/aws-config) is taken. No AWS, no IMDS.

Run:  python -m pytest workshop/scripts/tests/test_reduced_ide.py -q
"""
import os
import re
import shutil
import subprocess

import pytest

TASK = shutil.which("task")
if not TASK:
    pytest.skip("go-task not on PATH", allow_module_level=True)

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
ROLE = "arn:aws:iam::111122223333:role/acme-kind-install"
VERIFY_SH = os.path.join(REPO, "cluster-providers", "common", "scripts", "mgmt-roles-verify.sh")
ALL_POLICIES = sorted(set(re.findall(r"arn:aws:iam::aws:policy/[A-Za-z0-9]+", open(VERIFY_SH).read())))
IDE_ROLE = "arn:aws:iam::111122223333:role/acme-ide"
PROVIDERS = ["kind-kro-ack", "kind-crossplane"]
ALL_PROVIDER_FILES = ["kind-kro-ack", "kind-crossplane", "terraform"]

# Records the profile and config the CLI would see, then answers like a bare fake.
FAKE_AWS = r"""#!/usr/bin/env bash
echo "PROFILE=${AWS_PROFILE:-} CFG=${AWS_CONFIG_FILE:-} :: $*" >> "$FAKE_AWS_LOG"
case "$1 $2" in
  "sts get-caller-identity") echo 111122223333 ;;
  "iam get-role"|"iam get-role-policy") echo ok ;;
  "iam list-attached-role-policies") printf '%s\t' $FAKE_ALL_POLICIES; echo ;;
  "eks describe-capability"|"eks describe-cluster") exit 254 ;;
  *) echo ok ;;
esac
"""
FAKE_OK = "#!/usr/bin/env bash\nexit 0\n"
FAKE_FAIL = "#!/usr/bin/env bash\nexit 7\n"


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    shutil.copy(os.path.join(REPO, "Taskfile.yaml"), r / "Taskfile.yaml")
    shutil.copytree(os.path.join(REPO, "cluster-providers"), r / "cluster-providers")
    (r / "scripts").mkdir()
    shutil.copy(os.path.join(REPO, "scripts", "install-timing.sh"), r / "scripts" / "install-timing.sh")
    shutil.copytree(os.path.join(REPO, "gitops", "addons", "registry"), r / "gitops" / "addons" / "registry")
    (r / "workshop").mkdir()
    shutil.copy(os.path.join(REPO, "workshop", "Taskfile.yaml"), r / "workshop" / "Taskfile.yaml")
    return r


def _config(provider, install_role=None, mode=None):
    c = f"""clusterProvider: {provider}
resourcePrefix: acme
aws: {{region: us-west-2, accountId: "111122223333"{f', installRoleArn: "{install_role}", ideRoleArn: "{IDE_ROLE}"' if install_role else ''}}}
hub: {{clusterName: acme-hub}}
repo: {{url: https://example.invalid/repo, revision: main, basepath: gitops/addons/}}
identityCenter: {{instanceArn: "", region: us-west-2}}
"""
    return c + (f"privilegedSteps: {mode}\n" if mode else "")


def _run(tmp_path, repo, provider, args, install_role=None, mode=None, ide_only=False):
    (repo / "config.local.yaml").write_text(_config(provider, install_role, mode))
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    for name, body in (("aws", FAKE_AWS), ("curl", FAKE_OK), ("kind", FAKE_FAIL)):
        (bindir / name).write_text(body)
        (bindir / name).chmod(0o755)
    log = tmp_path / "calls.log"
    log.write_text("")
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", FAKE_AWS_LOG=str(log),
               HOME=str(tmp_path), FAKE_ALL_POLICIES=" ".join(ALL_POLICIES), INSTALL_TIMING_LOG=str(tmp_path / "timing.log"))
    for k in ("AWS_PROFILE", "AWS_CONFIG_FILE", "AWS_DEFAULT_PROFILE", "KUBECONFIG", "PEEKS_AWS_IDE_ONLY"):
        env.pop(k, None)
    if ide_only:
        env["PEEKS_AWS_IDE_ONLY"] = "true"
    res = subprocess.run([TASK, "-d", str(repo), *args], env=env, capture_output=True, text=True, timeout=180)
    return res, log.read_text()


@pytest.mark.parametrize("provider", PROVIDERS)
def test_install_role_profile_is_generated_and_used(tmp_path, repo, provider):
    res, log = _run(tmp_path, repo, provider, [f"{provider}:hub:create-mgmt-roles"],
                    install_role=ROLE, mode="external")
    assert res.returncode == 0, res.stdout + res.stderr
    cfg = (repo / "private" / "aws-config").read_text()
    assert "[default]" in cfg and "[profile install]" in cfg
    assert f"role_arn = {ROLE}" in cfg and "credential_source = Ec2InstanceMetadata" in cfg
    iam_lines = [line for line in log.splitlines() if " :: iam " in line]
    assert iam_lines and all(line.startswith("PROFILE=install ") for line in iam_lines), log


@pytest.mark.parametrize("provider", PROVIDERS)
def test_ide_only_teardown_stays_on_instance_role(tmp_path, repo, provider):
    res, log = _run(tmp_path, repo, provider, [f"{provider}:hub:create-mgmt-roles"],
                    install_role=ROLE, mode="external", ide_only=True)
    assert res.returncode == 0, res.stdout + res.stderr
    assert "[profile install]" not in (repo / "private" / "aws-config").read_text()
    assert "PROFILE=install" not in log and "PROFILE=default" in log


@pytest.mark.parametrize("provider", PROVIDERS)
def test_without_install_role_nothing_changes(tmp_path, repo, provider):
    res, log = _run(tmp_path, repo, provider, [f"{provider}:hub:create-mgmt-roles"], mode="external")
    assert res.returncode == 0, res.stdout + res.stderr
    assert (repo / "private" / "aws-config").read_text() == "[default]\ncredential_source = Ec2InstanceMetadata\n"
    assert "PROFILE=install" not in log


@pytest.mark.parametrize("name", ALL_PROVIDER_FILES)
def test_every_provider_resolves_the_profile_the_same_way(name):
    """go-task broadcasts each provider's env to its siblings: the three must agree."""
    text = open(os.path.join(REPO, "cluster-providers", name, "Taskfile.yaml")).read()
    assert "aws.installRoleArn" in text and "PEEKS_AWS_IDE_ONLY" in text and "[profile install]" in text


def _echo_commands(repo):
    """--dry prints nothing under `silent: true`; the copy under test is made to echo."""
    p = repo / "cluster-providers" / "kind-kro-ack" / "Taskfile.yaml"
    p.write_text(p.read_text().replace("silent: true", "silent: false", 1))


DELETE_RE = re.compile(r"^\s*(?!#).*aws (eks delete-(capability|cluster)|secretsmanager delete-secret|iam delete-role)", re.M)


@pytest.mark.parametrize("mode,deletes", [("external", False), (None, True)])
def test_destroy_aws_deletes_follow_mode(tmp_path, repo, mode, deletes):
    _echo_commands(repo)
    res, _ = _run(tmp_path, repo, "kind-kro-ack", ["kind-kro-ack:destroy", "--dry"], mode=mode)
    assert res.returncode == 0, res.stdout + res.stderr
    assert bool(DELETE_RE.search(res.stderr)) is deletes, mode
    # what stays in both modes: the Kubernetes teardown and the hub inventory
    assert "hub:destroy-addons" in res.stderr
    if mode == "external":
        assert "left to the stack sweep" in res.stderr


def test_destroy_external_final_check_does_not_need_the_hub_gone(tmp_path, repo):
    _echo_commands(repo)
    res, _ = _run(tmp_path, repo, "kind-kro-ack", ["kind-kro-ack:destroy", "--dry"], mode="external")
    assert 'if [ "external" = external ]' in res.stderr and "Kubernetes teardown complete" in res.stderr


def test_workshop_destroy_passes_ide_only_when_external():
    text = open(os.path.join(REPO, "workshop", "Taskfile.yaml")).read()
    assert "export PEEKS_AWS_IDE_ONLY=true" in text
    assert re.search(r"privilegedSteps // \"inline\"' \{\{\.CONFIG_FILE\}\} 2>/dev/null \|\| true\)\" = external", text)
    assert text.index("export PEEKS_AWS_IDE_ONLY=true") < text.index("task {{.PROVIDER}}:destroy HUB_DELETE_WAIT")


def test_hub_seed_also_admits_the_ide_role():
    text = open(os.path.join(REPO, "cluster-providers", "kind-kro-ack", "Taskfile.yaml")).read()
    assert "aws.ideRoleArn" in text
    assert text.count('--principal-arn "$IDE_ROLE"') == 2
