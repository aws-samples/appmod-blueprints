"""Hermetic go-task tests for the reduced-IDE-role mode (v0.5 integration branch).

Two config.yaml keys, on top of `privilegedSteps: external` (see test_privileged_offload.py):

* `aws.installRoleArn`: on an EC2 host the install runs as this role (an `install` profile
  that assumes it from the instance role), so the instance role needs no IAM write. Teardown
  on the host (PLATFORM_SKIP_INSTALL_ROLE=true) stays on the instance role.
* `privilegedSteps: external` on `destroy`: Kubernetes-only teardown, the direct AWS deletes
  are left to the stack sweep.

The real go-task runs on a copy of the Taskfiles with a fake `aws` / `curl` / `kind` on PATH.
`curl` succeeds here so the EC2 branch (generated private/aws-config) is taken. No AWS, no IMDS.

Run:  python -m pytest workshop/scripts/tests/test_reduced_ide.py -q
"""
import json
import os
import re
import shutil
import subprocess

import pytest
import yaml

TASK = shutil.which("task")
if not TASK:
    pytest.skip("go-task not on PATH", allow_module_level=True)

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
ROLE = "arn:aws:iam::111122223333:role/acme-kind-install"
VERIFY_SH = os.path.join(REPO, "cluster-providers", "common", "scripts", "mgmt-roles-verify.sh")
ALL_POLICIES = sorted(set(re.findall(r"arn:aws:iam::aws:policy/[A-Za-z0-9]+", open(VERIFY_SH).read())))
SCOPED_IAM = "arn:aws:iam::111122223333:policy/acme-cluster-mgmt-iam-scoped"
ALL_POLICIES.append(SCOPED_IAM)
IDE_ROLE = "arn:aws:iam::111122223333:role/acme-ide"
PROVIDERS = ["kind-kro-ack", "kind-crossplane"]
ALL_PROVIDER_FILES = ["kind-kro-ack", "kind-crossplane", "terraform"]

# Records the profile and config the CLI would see, then answers like a bare fake.
FAKE_AWS = r"""#!/usr/bin/env bash
echo "PROFILE=${AWS_PROFILE:-} CFG=${AWS_CONFIG_FILE:-} :: $*" >> "$FAKE_AWS_LOG"
case "$1 $2" in
  "sts get-caller-identity") echo 111122223333 ;;
  "iam get-role"|"iam get-role-policy") echo ok ;;
  "iam get-policy") echo "NoSuchEntity" >&2; exit 254 ;;  # scoped policy absent: managed-policy.sh creates it
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


def _config(provider, install_role=None, mode=None, session_name=None):
    # json.dumps: a YAML double-quoted scalar with JSON escapes, so "\n" stays a real newline
    sn = f', installRoleSessionName: {json.dumps(session_name)}' if session_name is not None else ""
    c = f"""clusterProvider: {provider}
resourcePrefix: acme
aws: {{region: us-west-2, accountId: "111122223333"{f', installRoleArn: "{install_role}", ideRoleArn: "{IDE_ROLE}"' if install_role else ''}{sn}}}
hub: {{clusterName: acme-hub}}
repo: {{url: https://example.invalid/repo, revision: main, basepath: gitops/addons/}}
identityCenter: {{instanceArn: "", region: us-west-2}}
"""
    return c + (f"privilegedSteps: {mode}\n" if mode else "")


def _run(tmp_path, repo, provider, args, install_role=None, mode=None, ide_only=False, session_name=None, env_extra=None):
    (repo / "config.local.yaml").write_text(_config(provider, install_role, mode, session_name))
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    for name, body in (("aws", FAKE_AWS), ("curl", FAKE_OK), ("kind", FAKE_FAIL)):
        (bindir / name).write_text(body)
        (bindir / name).chmod(0o755)
    log = tmp_path / "calls.log"
    log.write_text("")
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", FAKE_AWS_LOG=str(log),
               HOME=str(tmp_path), FAKE_ALL_POLICIES=" ".join(ALL_POLICIES), INSTALL_TIMING_LOG=str(tmp_path / "timing.log"))
    for k in ("AWS_PROFILE", "AWS_CONFIG_FILE", "AWS_DEFAULT_PROFILE", "KUBECONFIG", "PLATFORM_SKIP_INSTALL_ROLE"):
        env.pop(k, None)
    if ide_only:
        env["PLATFORM_SKIP_INSTALL_ROLE"] = "true"
    env.update(env_extra or {})
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
    assert "aws.installRoleArn" in text and "PLATFORM_SKIP_INSTALL_ROLE" in text and "[profile install]" in text


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


def test_destroy_external_names_what_is_left_for_the_sweep(tmp_path, repo):
    # a privilegedSteps=external user without a stack sweep (install:codebuild) must be told
    # which cluster is still there, not only "complete"
    _echo_commands(repo)
    res, _ = _run(tmp_path, repo, "kind-kro-ack", ["kind-kro-ack:destroy", "--dry"], mode="external")
    assert "If no stack sweep runs after this" in res.stderr, res.stderr[-600:]
    assert "EKS cluster" in res.stderr and "remain" in res.stderr


def test_schema_documents_that_external_changes_destroy():
    import json
    d = json.load(open(os.path.join(REPO, "config.schema.json")))["properties"]["privilegedSteps"]["description"]
    assert "destroy" in d.lower() and "sweep" in d.lower()


def test_schema_install_role_is_not_claimed_for_kind_acks():
    import json
    d = json.load(open(os.path.join(REPO, "config.schema.json")))["properties"]["aws"]["properties"]["installRoleArn"]["description"]
    assert "ACK controllers in the kind bootstrap cluster keep the instance role" in d


def test_workshop_destroy_passes_ide_only_when_external():
    text = open(os.path.join(REPO, "workshop", "Taskfile.yaml")).read()
    assert "export PLATFORM_SKIP_INSTALL_ROLE=true" in text
    assert re.search(r"privilegedSteps // \"inline\"' \{\{\.CONFIG_FILE\}\} 2>/dev/null \|\| true\)\" = external", text)
    assert text.index("export PLATFORM_SKIP_INSTALL_ROLE=true") < text.index("task {{.PROVIDER}}:destroy HUB_DELETE_WAIT")


def test_hub_seed_also_admits_the_ide_role():
    text = open(os.path.join(REPO, "cluster-providers", "kind-kro-ack", "Taskfile.yaml")).read()
    assert "aws.ideRoleArn" in text
    assert text.count('--principal-arn "$IDE_ROLE"') == 2


# ---------------------------------------------------------------- privilegedSteps: enum and scope

@pytest.mark.parametrize("args", [
    ["kind-kro-ack:hub:create-mgmt-roles"], ["kind-crossplane:hub:create-mgmt-roles"],
    ["kind-kro-ack:destroy"], ["install:complete"], ["install"],
])
def test_unknown_privileged_steps_value_is_refused_not_read_as_inline(tmp_path, repo, args):
    provider = "kind-crossplane" if args[0].startswith("kind-crossplane") else "kind-kro-ack"
    res, log = _run(tmp_path, repo, provider, args, mode="External")  # a typo of external
    assert res.returncode != 0
    assert "must be inline or external" in res.stderr, res.stderr[-600:]
    assert not re.search(r"\biam (create|attach|put|update|delete)|eks delete|delete-secret", log), log


def test_workshop_destroy_refuses_an_unknown_value_before_draining(tmp_path, repo):
    res, log = _run(tmp_path, repo, "kind-kro-ack", ["-d", str(repo / "workshop"), "destroy"], mode="externl")
    assert res.returncode != 0 and "must be inline or external" in res.stderr, res.stderr[-600:]
    assert "delete" not in log, log


@pytest.mark.parametrize("mode", ["inline", None])
def test_known_values_pass_the_check(tmp_path, repo, mode):
    res, _ = _run(tmp_path, repo, "kind-kro-ack", ["kind-kro-ack:hub:create-mgmt-roles"], mode=mode)
    assert "must be inline or external" not in res.stderr


def test_destroy_external_lists_every_skipped_aws_step(tmp_path, repo):
    _echo_commands(repo)
    res, _ = _run(tmp_path, repo, "kind-kro-ack", ["kind-kro-ack:destroy", "--dry"], mode="external")
    for what in ("EKS capabilities", "ALBs", "Ray resources", "ECR repositories", "CloudFront",
                 "AMP workspaces", "OIDC providers", "log groups", "VPCs", "security groups"):
        assert what in res.stderr, what


def test_schema_scopes_the_kubernetes_only_destroy_to_kind_kro_ack():
    import json
    d = json.load(open(os.path.join(REPO, "config.schema.json")))["properties"]["privilegedSteps"]["description"]
    assert "With clusterProvider kind-kro-ack, task destroy then only tears down Kubernetes" in d
    assert "other providers have no Kubernetes-only destroy" in d


WS_DESTROY = yaml.safe_load(open(os.path.join(REPO, "workshop", "Taskfile.yaml")))["tasks"]["destroy"]["cmds"]
PHASE3 = [c["cmd"] for c in WS_DESTROY if isinstance(c, dict) and "PLATFORM_SKIP_INSTALL_ROLE" in c.get("cmd", "")][0]


@pytest.mark.parametrize("provider,mode,ide_only,notice", [
    ("kind-crossplane", "external", "true", True),
    ("terraform", "external", "true", True),
    ("kind-kro-ack", "external", "true", False),
    ("kind-crossplane", None, "", False),
])
def test_workshop_destroy_says_when_external_is_not_kubernetes_only(tmp_path, provider, mode, ide_only, notice):
    cfg = tmp_path / "config.local.yaml"
    cfg.write_text(f"clusterProvider: {provider}\n" + (f"privilegedSteps: {mode}\n" if mode else ""))
    (tmp_path / "bin").mkdir()
    for name, body in (("aws", "#!/bin/sh\nexit 254\n"),
                       ("task", '#!/bin/sh\necho "task $* ide_only=${PLATFORM_SKIP_INSTALL_ROLE:-}" > "$OUT"\n')):
        (tmp_path / "bin" / name).write_text(body)
        (tmp_path / "bin" / name).chmod(0o755)
    block = re.sub(r"\{\{\.C_[A-Z]+\}\}", "", PHASE3)
    block = (block.replace("{{.CONFIG_FILE}}", str(cfg)).replace("{{.PROVIDER}}", provider)
             .replace("{{.PLATFORM_DIR}}", str(tmp_path)).replace("{{.DESTROY_DEADLINE_FILE}}", str(tmp_path / "dl"))
             .replace('{{.HUB_DELETE_WAIT | default ""}}', "true"))
    block = re.sub(r"\{\{\.[A-Z_]+\}\}", "x", block)
    env = {k: v for k, v in os.environ.items() if k != "PLATFORM_SKIP_INSTALL_ROLE"}
    env.update(PATH=f"{tmp_path / 'bin'}:{os.environ['PATH']}", OUT=str(tmp_path / "out"))
    r = subprocess.run(["bash", "-c", block], env=env, capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    assert ("only the kind-kro-ack destroy is Kubernetes-only" in r.stdout) is notice, r.stdout
    assert (tmp_path / "out").read_text().strip().endswith(f"ide_only={ide_only}")


# ---------------------------------------------------------------- neutral provider inputs

ALL_PROVIDERS = ["kind-kro-ack", "kind-crossplane", "terraform"]


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("session_name,want", [
    ("peeks-install", "peeks-install"),        # what the workshop's create-config.sh writes
    (None, "platform-install"),                # neutral default for any other consumer
    ("bad name\nrole_arn = x", "platform-install"),  # never written into the file as is
    ("ok\ncredential_process = /bin/false", "platform-install"),  # one valid line is not enough
    ("a", "platform-install"),                 # shorter than the IAM minimum (2)
    ("x" * 65, "platform-install"),            # longer than the IAM maximum (64)
    ("x" * 64, "x" * 64),
])
def test_install_profile_session_name_comes_from_config(tmp_path, repo, provider, session_name, want):
    res, _ = _run(tmp_path, repo, provider, [f"{provider}:hub:create-mgmt-roles"],
                  install_role=ROLE, mode="external", session_name=session_name)
    assert res.returncode == 0, res.stdout + res.stderr
    cfg = (repo / "private" / "aws-config").read_text()
    assert f"role_session_name = {want}\n" in cfg, cfg
    assert cfg.count("role_arn = ") == 1
    assert "credential_process" not in cfg and "/bin/false" not in cfg


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("value,skipped", [("true", True), ("", False), ("false", False)])
def test_skip_install_role_variable(tmp_path, repo, provider, value, skipped):
    res, log = _run(tmp_path, repo, provider, [f"{provider}:hub:create-mgmt-roles"], install_role=ROLE,
                    mode="external", env_extra={"PLATFORM_SKIP_INSTALL_ROLE": value})
    assert res.returncode == 0, res.stdout + res.stderr
    assert ("[profile install]" in (repo / "private" / "aws-config").read_text()) is (not skipped)
    assert ("PROFILE=install" in log) is (not skipped)


def test_no_consumer_name_left_in_the_providers():
    for p in ALL_PROVIDERS:
        text = open(os.path.join(REPO, "cluster-providers", p, "Taskfile.yaml")).read()
        assert "PEEKS_AWS_IDE_ONLY" not in text and "peeks-install" not in text, p


def test_workshop_sets_its_session_name_and_skip_variable():
    cc = open(os.path.join(REPO, "workshop", "create-config.sh")).read()
    assert "installRoleSessionName: \"peeks-install\"" in cc
    ws = open(os.path.join(REPO, "workshop", "Taskfile.yaml")).read()
    assert "export PLATFORM_SKIP_INSTALL_ROLE=true" in ws



@pytest.mark.parametrize("session_name,want", [
    ("peeks-install", "peeks-install"),
    ("ok\ncredential_process = /bin/false", "platform-install"),
])
def test_terraform_provider_writes_the_same_install_profile(tmp_path, repo, session_name, want):
    """terraform has its own copy of the profile code: run it (its vars resolve before any cmd)."""
    _run(tmp_path, repo, "terraform", ["terraform:validate"], install_role=ROLE, mode="external",
         session_name=session_name)
    cfg = (repo / "private" / "aws-config").read_text()
    assert f"role_session_name = {want}\n" in cfg and "credential_process" not in cfg, cfg


@pytest.mark.parametrize("value,skipped", [("true", True), ("", False)])
def test_terraform_provider_honours_the_skip_variable(tmp_path, repo, value, skipped):
    _run(tmp_path, repo, "terraform", ["terraform:validate"], install_role=ROLE, mode="external",
         env_extra={"PLATFORM_SKIP_INSTALL_ROLE": value})
    assert ("[profile install]" in (repo / "private" / "aws-config").read_text()) is (not skipped)
