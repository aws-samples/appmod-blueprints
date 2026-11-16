"""Hermetic go-task tests for the privileged-step offload (config.yaml `privilegedSteps`).

`privilegedSteps: external` moves the install steps that call AWS write APIs directly
(cluster-mgmt IAM roles, EKS capability log delivery) out of `task install` and into a
separate privileged runner (`task privileged:pre` / `task privileged:post`, run by the
CloudFormation InstallOffload CodeBuild project). These tests run the REAL go-task on a
copy of the repo's Taskfiles, with fake `aws` / `curl` / `kind` on PATH that record their
calls. No AWS, no network, no IMDS.

Run:  python -m pytest workshop/scripts/tests/test_privileged_offload.py -q
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
VERIFY_SH = os.path.join(REPO, "cluster-providers", "common", "scripts", "mgmt-roles-verify.sh")
PROVIDERS = ["kind-kro-ack", "kind-crossplane"]
SERVICES = "ec2 eks iam ecr s3 dynamodb secretsmanager rds".split()
IAM_WRITES = {"create-role", "update-assume-role-policy", "attach-role-policy", "put-role-policy"}
LOGS_WRITES = {"put-resource-policy", "put-delivery-source", "put-delivery-destination", "create-delivery"}

FAKE_AWS = r"""#!/usr/bin/env bash
echo "$*" >> "$FAKE_AWS_LOG"
# like the real CLI: an empty --role-name is a validation error
prev=""; for a in "$@"; do
  if [ "$prev" = "--role-name" ] && [ -z "$a" ]; then echo "empty --role-name" >&2; exit 252; fi
  prev="$a"; done
case "$1 $2" in
  "sts get-caller-identity")
    case "$*" in *Account*) echo 111122223333 ;; *) echo "arn:aws:sts::111122223333:assumed-role/Runner/s" ;; esac ;;
  "iam get-role"|"iam get-role-policy")
    [ "${FAKE_ROLES:-present}" = present ] || { echo "NoSuchEntity" >&2; exit 254; }
    echo ok ;;
  "iam get-policy") echo "NoSuchEntity" >&2; exit 254 ;;  # scoped policy absent: managed-policy.sh creates it
  "iam list-attached-role-policies")
    [ "${FAKE_ROLES:-present}" = present ] || exit 254
    printf '%s\t' $FAKE_ALL_POLICIES; echo ;;
  "eks describe-capability"|"eks describe-cluster") exit 254 ;;
  "eks list-clusters") echo "" ;;
  *) echo ok ;;
esac
"""
FAKE_FAIL = "#!/usr/bin/env bash\necho \"$(basename \"$0\") $*\" >> \"$FAKE_AWS_LOG\"\nexit 7\n"


def _config(provider, mode=None):
    c = f"""clusterProvider: {provider}
resourcePrefix: acme
aws: {{region: us-west-2, accountId: "111122223333"}}
hub: {{clusterName: acme-hub}}
repo: {{url: https://example.invalid/repo, revision: main, basepath: gitops/addons/}}
identityCenter: {{instanceArn: "", region: us-west-2}}
"""
    return c + (f"privilegedSteps: {mode}\n" if mode else "")


def _expected_policies(text):
    """{service: [policy arns]} from a get_policies()/expected_policies() case block."""
    out = {}
    for svc, arns in re.findall(r"^\s+([a-z0-9]+)\) echo \"([^\"]*)\";;", text, re.M):
        out[svc] = arns.split()
    return out


ALL_POLICIES = sorted({a for v in _expected_policies(open(VERIFY_SH).read()).values() for a in v})
# cluster-mgmt-iam has the customer-managed scoped policy instead of IAMFullAccess
SCOPED_IAM = "arn:aws:iam::111122223333:policy/acme-cluster-mgmt-iam-scoped"
ALL_POLICIES.append(SCOPED_IAM)


@pytest.fixture
def repo(tmp_path):
    """A copy of the parts of the repo the Taskfiles load, as <tmp>/repo."""
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


def _run(tmp_path, repo, provider, args, mode=None, roles="present", cwd=None):
    (repo / "config.local.yaml").write_text(_config(provider, mode))
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    for name, body in (("aws", FAKE_AWS), ("curl", FAKE_FAIL), ("kind", FAKE_FAIL)):
        (bindir / name).write_text(body)
        (bindir / name).chmod(0o755)
    log = tmp_path / "calls.log"
    log.write_text("")
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", FAKE_AWS_LOG=str(log),
               FAKE_ROLES=roles, FAKE_ALL_POLICIES=" ".join(ALL_POLICIES), HOME=str(tmp_path),
               INSTALL_TIMING_LOG=str(tmp_path / "timing.log"))
    for k in ("AWS_PROFILE", "AWS_CONFIG_FILE", "AWS_DEFAULT_PROFILE", "KUBECONFIG"):
        env.pop(k, None)
    res = subprocess.run([TASK, "-d", str(cwd or repo), *args], env=env, capture_output=True,
                         text=True, timeout=180)
    calls = [line.split() for line in log.read_text().splitlines() if line.strip()]
    return res, calls


def _verbs(calls, service):
    return {c[1] for c in calls if len(c) > 1 and c[0] == service}


@pytest.mark.parametrize("provider", PROVIDERS)
def test_external_mode_only_reads_iam(tmp_path, repo, provider):
    res, calls = _run(tmp_path, repo, provider, [f"{provider}:hub:create-mgmt-roles"], mode="external")
    assert res.returncode == 0, res.stdout + res.stderr
    assert "verified read-only" in res.stdout
    assert not (_verbs(calls, "iam") & IAM_WRITES), calls
    gets = [c for c in calls if c[:2] == ["iam", "get-role"]]
    assert len(gets) == len(SERVICES)


@pytest.mark.parametrize("attached,ok", [
    ("arn:aws:iam::aws:policy/IAMFullAccess", False),  # old admin-like policy is not enough
    ("arn:aws:iam::111122223333:policy/acme-cluster-mgmt-iam-scoped", True),
])
def test_verify_wants_the_scoped_iam_policy(tmp_path, attached, ok):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "aws").write_text(FAKE_AWS)
    (bindir / "aws").chmod(0o755)
    others = [a for a in ALL_POLICIES if a != SCOPED_IAM]
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", FAKE_AWS_LOG=str(tmp_path / "l"),
               FAKE_ROLES="present", FAKE_ALL_POLICIES=" ".join(others + [attached]), RESOURCE_PREFIX="acme")
    res = subprocess.run(["sh", VERIFY_SH], env=env, capture_output=True, text=True, timeout=60)
    assert (res.returncode == 0) is ok, res.stdout + res.stderr
    if not ok:
        assert "policy:acme-cluster-mgmt-iam:acme-cluster-mgmt-iam-scoped" in res.stderr


@pytest.mark.parametrize("provider", PROVIDERS)
def test_external_mode_missing_roles_fails_without_writing(tmp_path, repo, provider):
    res, calls = _run(tmp_path, repo, provider, [f"{provider}:hub:create-mgmt-roles"],
                      mode="external", roles="absent")
    assert res.returncode != 0
    assert "acme-cluster-mgmt-iam" in res.stderr and "privileged:pre" in res.stderr
    assert not (_verbs(calls, "iam") & IAM_WRITES), calls


@pytest.mark.parametrize("provider", PROVIDERS)
def test_default_mode_still_creates_roles(tmp_path, repo, provider):
    res, calls = _run(tmp_path, repo, provider, [f"{provider}:hub:create-mgmt-roles"], roles="absent")
    assert res.returncode == 0, res.stdout + res.stderr
    created = sorted(c[c.index("--role-name") + 1] for c in calls if c[:2] == ["iam", "create-role"])
    assert created == sorted(f"acme-cluster-mgmt-{s}" for s in SERVICES)


@pytest.mark.parametrize("provider", PROVIDERS)
def test_privileged_pre_creates_roles_and_refuses_external_config(tmp_path, repo, provider):
    # before the hub exists (describe-capability fails): roles created, rc 0 on both providers
    res, calls = _run(tmp_path, repo, provider, ["privileged:pre"], roles="absent")
    assert res.returncode == 0, res.stdout + res.stderr
    assert "create-role" in _verbs(calls, "iam")
    res, calls = _run(tmp_path, repo, provider, ["privileged:pre"], mode="external")
    assert res.returncode != 0 and "must not set privilegedSteps" in res.stderr
    assert not (_verbs(calls, "iam") & IAM_WRITES)


def test_privileged_post_enables_capability_logs(tmp_path, repo):
    res, calls = _run(tmp_path, repo, "kind-kro-ack", ["privileged:post"])
    assert res.returncode == 0, res.stdout + res.stderr
    assert "put-resource-policy" in _verbs(calls, "logs")


def test_root_install_codebuild_requires_external(tmp_path, repo):
    res, calls = _run(tmp_path, repo, "kind-kro-ack", ["install:codebuild"])
    assert res.returncode != 0 and "needs privilegedSteps: external" in res.stderr
    assert not (_verbs(calls, "iam") & IAM_WRITES)
    assert not any(c[0] == "kind" for c in calls)


def test_root_install_codebuild_stops_before_kind_when_pre_did_not_run(tmp_path, repo):
    res, calls = _run(tmp_path, repo, "kind-kro-ack", ["install:codebuild"], mode="external", roles="absent")
    assert res.returncode != 0 and "not ready" in res.stderr
    assert not any(c[0] == "kind" for c in calls), "install must stop before kind:create"
    assert not (_verbs(calls, "iam") & IAM_WRITES)


def _stub_provider_install_complete(repo):
    p = repo / "cluster-providers" / "kind-kro-ack" / "Taskfile.yaml"
    text = p.read_text()
    new, n = re.subn(r"(?ms)^  install:complete:\n.*?(?=^  install:post-sync:)",
                     "  install:complete:\n    cmds:\n      - echo provider-complete-stub\n\n", text)
    assert n == 1
    p.write_text(new)


@pytest.mark.parametrize("mode,expect_logs", [("external", False), (None, True)])
def test_install_complete_capability_logs_follow_mode(tmp_path, repo, mode, expect_logs):
    _stub_provider_install_complete(repo)
    res, calls = _run(tmp_path, repo, "kind-kro-ack", ["install:complete"], mode=mode)
    assert res.returncode == 0, res.stdout + res.stderr
    assert "provider-complete-stub" in res.stdout
    assert bool(_verbs(calls, "logs") & LOGS_WRITES) is expect_logs, calls
    if not expect_logs:
        assert "skipped (privilegedSteps=external)" in res.stdout


def test_workshop_install_codebuild_sets_external_and_fails_fast(tmp_path, repo):
    res, calls = _run(tmp_path, repo, "kind-kro-ack", ["install:codebuild"], roles="absent",
                      cwd=repo / "workshop")
    assert "privilegedSteps: external" in (repo / "config.local.yaml").read_text()
    assert res.returncode != 0 and "not ready" in res.stderr
    assert not any(c[0] == "kind" for c in calls), "workshop install must stop before kind:create"
    assert not (_verbs(calls, "iam") & IAM_WRITES)


def test_verify_lists_match_providers():
    """The verify script's role/policy lists must match what apply creates."""
    want = _expected_policies(open(VERIFY_SH).read())
    assert sorted(want) == sorted(SERVICES)
    for provider in PROVIDERS:
        text = open(os.path.join(REPO, "cluster-providers", provider, "Taskfile.yaml")).read()
        block = text[text.index("hub:create-mgmt-roles:apply:"):]
        block = block[block.index("get_policies() {"):block.index("        }\n", block.index("get_policies() {"))]
        assert _expected_policies(block) == want, provider
        assert re.search(r"for service in " + " ".join(SERVICES) + r"; do", text), provider
