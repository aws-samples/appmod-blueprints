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
if [ -n "${FAKE_DENY:-}" ] && [ "$2" = "$FAKE_DENY" ]; then
  case " $* " in *" ${FAKE_DENY_ROLE:-} "*|*"${FAKE_DENY_ROLE:-}"*)
    echo "An error occurred (AccessDenied) when calling the $2 operation: denied" >&2; exit 254 ;; esac; fi
case "$1 $2" in
  "sts get-caller-identity")
    case "$*" in *Account*) echo 111122223333 ;; *) echo "arn:aws:sts::111122223333:assumed-role/Runner/s" ;; esac ;;
  "iam get-role"|"iam get-role-policy")
    for r in ${FAKE_ABSENT_ROLES:-}; do case " $* " in *" $r "*)
      echo "An error occurred (NoSuchEntity) when calling the GetRole operation: not found" >&2; exit 254 ;; esac; done
    if [ "$2" = get-role-policy ] && [ -n "${FAKE_NO_INLINE:-}" ]; then
      echo "An error occurred (NoSuchEntity) when calling the GetRolePolicy operation: not found" >&2; exit 254; fi
    case "${FAKE_ROLES:-present}" in
      present) echo ok ;;
      expired) echo "An error occurred (ExpiredToken) when calling the GetRole operation: The security token included in the request is expired" >&2; exit 254 ;;
      *) echo "An error occurred (NoSuchEntity) when calling the GetRole operation: not found" >&2; exit 254 ;;
    esac ;;
  "iam list-attached-role-policies")
    [ "${FAKE_ROLES:-present}" = present ] || exit 254
    printf '%s\t' $FAKE_ALL_POLICIES; echo ;;
  "eks describe-cluster")
    [ "${FAKE_HUB:-gone}" = live ] && { echo ACTIVE; exit 0; }
    echo "An error occurred (ResourceNotFoundException) when calling the DescribeCluster operation: No cluster found" >&2; exit 254 ;;
  "eks describe-capability")
    [ -n "${FAKE_CAP_ARN:-}" ] && { echo "$FAKE_CAP_ARN"; exit 0; }
    echo "An error occurred (ResourceNotFoundException) when calling the DescribeCapability operation: not found" >&2; exit 254 ;;
  "eks list-clusters") echo "" ;;
  *) echo ok ;;
esac
"""
FAKE_FAIL = "#!/usr/bin/env bash\necho \"$(basename \"$0\") $*\" >> \"$FAKE_AWS_LOG\"\nexit 7\n"


def _config(provider, mode=None, hub_iam=None):
    iam = f", iam: {hub_iam}" if hub_iam else ""
    c = f"""clusterProvider: {provider}
resourcePrefix: acme
aws: {{region: us-west-2, accountId: "111122223333"}}
hub: {{clusterName: acme-hub{iam}}}
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
# <hub>-crossplane-provider has its own scoped policy (kind-kro-ack)
SCOPED_XP = "arn:aws:iam::111122223333:policy/acme-hub-crossplane-provider-scoped"
ALL_POLICIES.append(SCOPED_XP)


@pytest.fixture
def repo(tmp_path):
    """A copy of the parts of the repo the Taskfiles load, as <tmp>/repo."""
    r = tmp_path / "repo"
    r.mkdir()
    shutil.copy(os.path.join(REPO, "Taskfile.yaml"), r / "Taskfile.yaml")
    shutil.copytree(os.path.join(REPO, "cluster-providers"), r / "cluster-providers")
    # managed-policy.sh has its own tests (test_install_no_admin_managed_policies.py); here the
    # fake aws cannot answer its get-policy-version, so it is replaced by a logging stub.
    stub = r / "cluster-providers" / "common" / "iam" / "managed-policy.sh"
    stub.write_text('#!/bin/sh\necho "managed-policy.sh $*" >> "$FAKE_AWS_LOG"\n')
    (r / "scripts").mkdir()
    shutil.copy(os.path.join(REPO, "scripts", "install-timing.sh"), r / "scripts" / "install-timing.sh")
    shutil.copytree(os.path.join(REPO, "gitops", "addons", "registry"), r / "gitops" / "addons" / "registry")
    (r / "workshop").mkdir()
    shutil.copy(os.path.join(REPO, "workshop", "Taskfile.yaml"), r / "workshop" / "Taskfile.yaml")
    return r


def _run(tmp_path, repo, provider, args, mode=None, roles="present", cwd=None, env_extra=None, fakes=(),
         hub_iam=None):
    (repo / "config.local.yaml").write_text(_config(provider, mode, hub_iam))
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    for name, body in (("aws", FAKE_AWS), ("curl", FAKE_FAIL), ("kind", FAKE_FAIL)) + tuple(fakes):
        (bindir / name).write_text(body)
        (bindir / name).chmod(0o755)
    log = tmp_path / "calls.log"
    log.write_text("")
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", FAKE_AWS_LOG=str(log),
               FAKE_ROLES=roles, FAKE_ALL_POLICIES=" ".join(ALL_POLICIES), HOME=str(tmp_path),
               INSTALL_TIMING_LOG=str(tmp_path / "timing.log"))
    for k in ("AWS_PROFILE", "AWS_CONFIG_FILE", "AWS_DEFAULT_PROFILE", "KUBECONFIG"):
        env.pop(k, None)
    env.update(env_extra or {})
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
    ("arn:aws:iam::111122223333:policy/acme-cluster-mgmt-iam-scoped-52e27e9d", True),  # after a document change
    ("arn:aws:iam::111122223333:policy/acme-cluster-mgmt-iam-scoped-other", False),
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


def _inline_pairs_verify(text):
    """[(service, policy name)] the verify script checks as inline policies."""
    m = re.search(r"^for pair in ([a-z0-9:\- ]+); do", text, re.M)
    return sorted(tuple(p.split(":", 1)) for p in m.group(1).split())


def _inline_pairs_apply(block):
    """[(service, policy name)] apply puts on $EKS_ROLE / $RDS_ROLE."""
    roles = dict(re.findall(r'^\s+([A-Z]+_ROLE)="\{\{\.RESOURCE_PREFIX\}\}-cluster-mgmt-([a-z0-9]+)"', block, re.M))
    puts = re.findall(r'put-role-policy --role-name "\$([A-Z]+_ROLE)" --policy-name ([A-Za-z0-9\-]+)', block)
    return sorted((roles[var], name) for var, name in puts)


def _apply_block(text):
    block = text[text.index("hub:create-mgmt-roles:apply:"):]
    return block[:block.index("cluster-mgmt roles ready")]


def test_verify_lists_match_providers():
    """The verify script's role/policy lists, managed AND inline, must match what apply creates."""
    verify = open(VERIFY_SH).read()
    want = _expected_policies(verify)
    want_inline = _inline_pairs_verify(verify)
    assert sorted(want) == sorted(SERVICES)
    assert want_inline == [("eks", "eks-access-management"), ("rds", "rds-kms")]
    for provider in PROVIDERS:
        text = open(os.path.join(REPO, "cluster-providers", provider, "Taskfile.yaml")).read()
        block = _apply_block(text)
        pol = block[block.index("get_policies() {"):block.index("        }\n", block.index("get_policies() {"))]
        assert _expected_policies(pol) == want, provider
        assert _inline_pairs_apply(block) == want_inline, provider
        assert re.search(r"for service in " + " ".join(SERVICES) + r"; do", text), provider


def test_drift_check_catches_an_inline_policy_rename(tmp_path):
    """Renaming rds-kms in one provider's apply must break the drift check (review #1296)."""
    p = os.path.join(REPO, "cluster-providers", "kind-kro-ack", "Taskfile.yaml")
    renamed = open(p).read().replace("--policy-name rds-kms", "--policy-name rds-kms-v2", 1)
    assert _inline_pairs_apply(_apply_block(renamed)) != _inline_pairs_verify(open(VERIFY_SH).read())


# ── review #1296: unknown values, early verify, read errors, other host roles ──

UNKNOWN = "extrenal"


@pytest.mark.parametrize("args", [["install"], ["install:hub"], ["install:complete"], ["privileged:pre"],
                                  ["privileged:post"], ["kind-kro-ack:hub:create-mgmt-roles"],
                                  ["kind-kro-ack:hub:crossplane-provider-role"], ["kind-kro-ack:ray:roles"]])
def test_unknown_mode_is_refused_before_any_write(tmp_path, repo, args):
    res, calls = _run(tmp_path, repo, "kind-kro-ack", args, mode=UNKNOWN, roles="absent")
    assert res.returncode != 0, res.stdout
    assert "must be inline or external" in res.stderr or "must not set privilegedSteps" in res.stderr, res.stderr
    assert not (_verbs(calls, "iam") & IAM_WRITES), calls
    assert not any(c[0] == "kind" for c in calls)


@pytest.mark.parametrize("provider", PROVIDERS)
def test_crossplane_provider_unknown_mode_refused(tmp_path, repo, provider):
    res, calls = _run(tmp_path, repo, provider, [f"{provider}:hub:create-mgmt-roles"], mode=UNKNOWN, roles="absent")
    assert res.returncode != 0 and "must be inline or external" in res.stderr
    assert not (_verbs(calls, "iam") & IAM_WRITES), calls


@pytest.mark.parametrize("entry", ["install", "install:hub"])
def test_external_install_verifies_before_kind(tmp_path, repo, entry):
    res, calls = _run(tmp_path, repo, "kind-kro-ack", [entry], mode="external", roles="absent")
    assert res.returncode != 0 and "not ready" in res.stderr, res.stdout + res.stderr
    assert "acme-hub-crossplane-provider" in res.stderr and "acme-ray-worker-role" in res.stderr
    assert not any(c[0] == "kind" for c in calls), "install must stop before kind:create"
    assert not (_verbs(calls, "iam") & IAM_WRITES)


@pytest.mark.parametrize("provider", PROVIDERS)
def test_verify_reports_read_errors_not_missing_roles(tmp_path, repo, provider):
    res, calls = _run(tmp_path, repo, provider, [f"{provider}:privileged:verify"], mode="external", roles="expired")
    assert res.returncode != 0
    assert "ExpiredToken" in res.stderr and "could not read" in res.stderr, res.stderr
    assert "not ready" not in res.stderr and "privileged:pre" not in res.stderr, res.stderr


def test_role_check_reports_read_errors(tmp_path, repo):
    res, _ = _run(tmp_path, repo, "kind-kro-ack", ["kind-kro-ack:ray:roles"], mode="external", roles="expired")
    assert res.returncode != 0 and "ExpiredToken" in res.stderr and "do not exist" not in res.stderr


def test_kro_ack_privileged_pre_creates_every_host_role(tmp_path, repo):
    res, calls = _run(tmp_path, repo, "kind-kro-ack", ["privileged:pre"], roles="absent")
    assert res.returncode == 0, res.stdout + res.stderr
    created = {c[c.index("--role-name") + 1] for c in calls if c[:2] == ["iam", "create-role"]}
    assert {"acme-hub-crossplane-provider", "acme-model-prestage-role", "acme-ray-worker-role"} <= created
    assert not any(c[0] == "eks" and c[1] == "create-pod-identity-association" for c in calls)


@pytest.mark.parametrize("task,roles", [
    ("kind-kro-ack:hub:crossplane-provider-role", ["acme-hub-crossplane-provider"]),
    ("kind-kro-ack:ray:roles", ["acme-model-prestage-role", "acme-ray-worker-role"]),
    ("kind-crossplane:ray:roles", ["acme-model-prestage-role", "acme-ray-worker-role"]),
])
def test_external_mode_other_host_roles_only_read(tmp_path, repo, task, roles):
    provider = task.split(":", 1)[0]
    res, calls = _run(tmp_path, repo, provider, [task], mode="external")
    assert res.returncode == 0, res.stdout + res.stderr
    assert not (_verbs(calls, "iam") & IAM_WRITES), calls
    res, calls = _run(tmp_path, repo, provider, [task], mode="external", roles="absent")
    assert res.returncode != 0 and all(r in res.stderr for r in roles) and "privileged:pre" in res.stderr
    assert not (_verbs(calls, "iam") & IAM_WRITES), calls
    res, calls = _run(tmp_path, repo, provider, [task], roles="absent")
    assert res.returncode == 0, res.stdout + res.stderr
    assert {c[c.index("--role-name") + 1] for c in calls if c[:2] == ["iam", "create-role"]} == set(roles)


def test_bootstrap_crossplane_identity_makes_no_iam_write():
    text = open(os.path.join(REPO, "cluster-providers", "kind-kro-ack", "Taskfile.yaml")).read()
    block = text[text.index("  hub:bootstrap-crossplane-identity:"):]
    block = block[:block.index("\n  # ──")]
    assert not re.search(r"aws iam (create-role|attach-role-policy|put-role-policy)", block)
    dag = text[:text.index("  hub:bootstrap-crossplane-identity:")]
    assert dag.index("task: hub:crossplane-provider-role") < dag.index("task: hub:bootstrap-crossplane-identity")


def test_crossplane_pre_never_writes_an_empty_role_arn(tmp_path, repo):
    res, calls = _run(tmp_path, repo, "kind-crossplane", ["privileged:pre"], roles="absent")
    assert res.returncode == 0, res.stdout + res.stderr
    raw = (tmp_path / "calls.log").read_text()
    assert "create-role --role-name acme-cluster-mgmt-iam" in raw
    assert ':role/"' not in raw and "role/acme-hub-ACKCapabilityRole" in raw, raw
    # before the hub: the ack-assume-role put is skipped, privileged:post applies it
    assert not [c for c in calls if c[:2] == ["iam", "put-role-policy"] and "ack-assume-role" in c]
    assert "applied once the hub exists" in res.stdout


@pytest.mark.parametrize("entry", ["kind-crossplane:hub:create-mgmt-roles", "privileged:post"])
def test_crossplane_ack_assume_put_fails_when_hub_exists(tmp_path, repo, entry):
    env = {"FAKE_CAP_ARN": "arn:aws:iam::111122223333:role/acme-hub-ACKCapabilityRole",
           "FAKE_DENY": "put-role-policy", "FAKE_DENY_ROLE": "acme-hub-ACKCapabilityRole"}
    res, calls = _run(tmp_path, repo, "kind-crossplane", [entry], env_extra=env)
    assert res.returncode != 0, res.stdout
    assert "AccessDenied" in res.stderr and "roles ready" not in res.stdout
    res, calls = _run(tmp_path, repo, "kind-crossplane", [entry],
                      env_extra={"FAKE_CAP_ARN": env["FAKE_CAP_ARN"]})
    assert res.returncode == 0, res.stdout + res.stderr
    puts = [c for c in calls if c[:2] == ["iam", "put-role-policy"] and "ack-assume-role" in c]
    assert puts and puts[0][puts[0].index("--role-name") + 1] == "acme-hub-ACKCapabilityRole"


def test_crossplane_ack_capability_read_error_fails(tmp_path, repo):
    res, _ = _run(tmp_path, repo, "kind-crossplane", ["kind-crossplane:hub:create-mgmt-roles"],
                  env_extra={"FAKE_DENY": "describe-capability"})
    assert res.returncode != 0 and "cannot read the hub ACK capability" in res.stdout + res.stderr


def test_verify_inline_policy_read_error_is_not_missing(tmp_path, repo):
    res, _ = _run(tmp_path, repo, "kind-kro-ack", ["kind-kro-ack:privileged:verify"], mode="external",
                  env_extra={"FAKE_DENY": "get-role-policy"})
    assert res.returncode != 0
    assert "could not read" in res.stderr and "AccessDenied" in res.stderr
    assert "not ready" not in res.stderr, res.stderr


def test_external_mode_unsupported_provider_is_named(tmp_path, repo):
    res, calls = _run(tmp_path, repo, "terraform", ["install"], mode="external")
    assert res.returncode != 0 and "supported by the kind-kro-ack and kind-crossplane providers only" in res.stderr
    assert not (_verbs(calls, "iam") & IAM_WRITES)


def test_install_codebuild_is_an_alias_of_install_external(tmp_path, repo):
    for entry in ("install:external", "install:codebuild"):
        res, _ = _run(tmp_path, repo, "kind-kro-ack", [entry])
        assert res.returncode != 0 and "needs privilegedSteps: external" in res.stderr, entry


def test_workshop_install_codebuild_says_the_key_persists(tmp_path, repo):
    res, _ = _run(tmp_path, repo, "kind-kro-ack", ["install:codebuild"], roles="absent", cwd=repo / "workshop")
    assert "stay external until the key is removed" in res.stdout


FAKE_PY = "#!/usr/bin/env bash\necho \"python3 $*\" >> \"$FAKE_AWS_LOG\"\n"
PRE_ROLES = {
    "kind-kro-ack": {f"acme-cluster-mgmt-{s}" for s in SERVICES}
    | {"acme-hub-crossplane-provider", "acme-model-prestage-role", "acme-ray-worker-role"},
    "kind-crossplane": {f"acme-cluster-mgmt-{s}" for s in SERVICES}
    | {"acme-model-prestage-role", "acme-ray-worker-role"},
}


@pytest.mark.parametrize("provider", PROVIDERS)
def test_privileged_destroy_deletes_what_pre_created(tmp_path, repo, provider):
    res, calls = _run(tmp_path, repo, provider, ["privileged:destroy"], fakes=(("python3", FAKE_PY),))
    assert res.returncode == 0, res.stdout + res.stderr
    deleted = {c[c.index("--role-name") + 1] for c in calls if c[:2] == ["iam", "delete-role"]}
    assert deleted == PRE_ROLES[provider]
    assert any(c[0] == "python3" and "sweep-log-deliveries.py" in c[1] and "--strict" in c for c in calls)


FAKE_PY_FAIL = "#!/usr/bin/env bash\necho \"python3 $*\" >> \"$FAKE_AWS_LOG\"\nexit 1\n"


def test_privileged_destroy_fails_when_a_delivery_delete_fails(tmp_path, repo):
    res, calls = _run(tmp_path, repo, "kind-kro-ack", ["privileged:destroy"], fakes=(("python3", FAKE_PY_FAIL),))
    assert res.returncode != 0
    deleted = {c[c.index("--role-name") + 1] for c in calls if c[:2] == ["iam", "delete-role"]}
    assert deleted == PRE_ROLES["kind-kro-ack"], "the role deletes still run after a delivery failure"


def test_privileged_destroy_sweeps_deliveries_even_if_a_role_fails(tmp_path, repo):
    res, calls = _run(tmp_path, repo, "kind-kro-ack", ["privileged:destroy"], env_extra={"FAKE_DENY": "delete-role"},
                      fakes=(("python3", FAKE_PY),))
    assert res.returncode != 0
    assert any(c[0] == "python3" for c in calls)


def test_sweep_log_deliveries_strict_fails_on_a_failed_delete():
    import importlib.util
    path = os.path.join(REPO, "scripts", "sweep-log-deliveries.py")
    spec = importlib.util.spec_from_file_location("sweep_log_deliveries_cli", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    sl = mod.sl

    class Eks:
        pass

    class Logs:
        pass

    orig = (sl.cluster_inventory, sl.sweep_log_deliveries)
    try:
        sl.cluster_inventory = lambda eks: {}

        def fake_sweep(logs, gone, dry_run=False, failures=None):
            failures.append("delivery d-1")
            return ["d-1"], [], [], 0
        sl.sweep_log_deliveries = fake_sweep
        import io
        args = ["acme", "us-west-2", "acme-hub"]
        assert mod.main(args, eks=Eks(), logs=Logs(), out=io.StringIO()) == 0
        assert mod.main(args + ["--strict"], eks=Eks(), logs=Logs(), out=io.StringIO()) == 1
    finally:
        sl.cluster_inventory, sl.sweep_log_deliveries = orig


@pytest.mark.parametrize("provider", PROVIDERS)
def test_privileged_destroy_refuses_while_hub_exists(tmp_path, repo, provider):
    res, calls = _run(tmp_path, repo, provider, ["privileged:destroy"], env_extra={"FAKE_HUB": "live"},
                      fakes=(("python3", FAKE_PY),))
    assert res.returncode != 0 and "still exists" in res.stderr
    # the kind-kro-ack external destroy leaves the hub: the refusal names how to delete it
    assert "privilegedSteps: external does not delete the hub" in res.stderr
    assert not any(c[:2] == ["iam", "delete-role"] for c in calls)


def test_privileged_steps_doc_matches_the_kro_ack_external_destroy():
    """The doc must not promise AWS deletes the kind-kro-ack destroy skips under external."""
    doc = open(os.path.join(REPO, "docs", "install", "privileged-steps.md")).read()
    kro = open(os.path.join(REPO, "cluster-providers", "kind-kro-ack", "Taskfile.yaml")).read()
    assert 'if [ "{{.AWS_DELETES}}" = external ]; then' in kro, "the Kubernetes-only destroy moved: update this test"
    assert "Teardown: `task destroy` still deletes" not in doc
    teardown = doc[doc.index("- Teardown, `kind-kro-ack`"):doc.index("- Teardown, `kind-crossplane`")]
    assert "only tears down Kubernetes" in teardown and "hub EKS cluster" in teardown
    assert "| After `task destroy` | `task privileged:destroy`" not in doc


def test_privileged_destroy_reports_a_role_it_could_not_delete(tmp_path, repo):
    res, calls = _run(tmp_path, repo, "kind-kro-ack", ["privileged:destroy"], env_extra={"FAKE_DENY": "delete-role"},
                      fakes=(("python3", FAKE_PY),))
    assert res.returncode != 0
    assert "not deleted" in res.stderr and "acme-hub-crossplane-provider" in res.stderr and "AccessDenied" in res.stderr


def test_privileged_destroy_refuses_external_config(tmp_path, repo):
    res, calls = _run(tmp_path, repo, "kind-kro-ack", ["privileged:destroy"], mode="external",
                      fakes=(("python3", FAKE_PY),))
    assert res.returncode != 0 and "must not set privilegedSteps" in res.stderr
    assert not any(c[:2] == ["iam", "delete-role"] for c in calls)


def test_kro_ack_destroy_6b_records_a_role_it_could_not_delete(tmp_path):
    """Run the real 6b delete-role snippet with a fake aws: AccessDenied is recorded, NoSuchEntity is not."""
    text = open(os.path.join(REPO, "cluster-providers", "kind-kro-ack", "Taskfile.yaml")).read()
    block = text[text.index("# 6b. ALL remaining"):text.index("# 6b2. Shared fixed-name roles")]
    start = block.index('echo "  deleting IAM role $ROLE"')
    snippet = block[start:block.rindex("done")]
    awserr = re.search(r"^\s*(awserr\(\) \{.*\})$", text, re.M).group(1)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "aws").write_text("#!/bin/sh\necho \"$FAKE_ERR\" >&2\nexit 254\n")
    (bindir / "aws").chmod(0o755)
    for err, recorded in (("An error occurred (AccessDenied) when calling DeleteRole: no", True),
                          ("An error occurred (NoSuchEntity) when calling DeleteRole: gone", False)):
        failed = tmp_path / "failed"
        failed.write_text("")
        script = f'set -eu\n{awserr}\nFAILED="{failed}"\nROLE=acme-x\n{snippet}\n'
        r = subprocess.run(["sh", "-c", script], env=dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}",
                                                         FAKE_ERR=err), capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        assert ("iam-delete-role(6b)" in failed.read_text()) is recorded, (err, r.stdout)
        assert ("not deleted (AccessDenied)" in r.stdout) is recorded


@pytest.mark.parametrize("entry", ["kind-kro-ack:hub:create-mgmt-roles", "privileged:post"])
def test_kro_ack_ack_assume_put_fails_when_hub_exists(tmp_path, repo, entry):
    env = {"FAKE_CAP_ARN": "arn:aws:iam::111122223333:role/acme-hub-ack-capability-role",
           "FAKE_DENY": "put-role-policy", "FAKE_DENY_ROLE": "acme-hub-ack-capability-role"}
    res, _ = _run(tmp_path, repo, "kind-kro-ack", [entry], env_extra=env)
    assert res.returncode != 0, res.stdout
    assert "AccessDenied" in res.stderr and "roles ready" not in res.stdout
    res, calls = _run(tmp_path, repo, "kind-kro-ack", [entry], env_extra={"FAKE_CAP_ARN": env["FAKE_CAP_ARN"]})
    assert res.returncode == 0, res.stdout + res.stderr
    puts = [c for c in calls if c[:2] == ["iam", "put-role-policy"] and "ack-assume-role" in c]
    assert puts and puts[0][puts[0].index("--role-name") + 1] == "acme-hub-ack-capability-role"


def test_kro_ack_ack_assume_put_skipped_before_the_hub(tmp_path, repo):
    res, calls = _run(tmp_path, repo, "kind-kro-ack", ["privileged:pre"], roles="absent")
    assert res.returncode == 0, res.stdout + res.stderr
    assert not [c for c in calls if c[:2] == ["iam", "put-role-policy"] and "ack-assume-role" in c]
    assert "ack-assume-role is applied once the hub is up" in res.stdout


def test_role_check_without_arguments_is_an_error():
    r = subprocess.run(["sh", os.path.join(REPO, "cluster-providers", "common", "scripts", "iam-role-check.sh")],
                       capture_output=True, text=True)
    assert r.returncode == 2 and "usage" in r.stderr


def test_workshop_install_codebuild_names_supported_providers(tmp_path, repo):
    res, calls = _run(tmp_path, repo, "terraform", ["install:codebuild"], cwd=repo / "workshop")
    assert res.returncode != 0 and "kind-kro-ack and kind-crossplane providers only" in res.stderr
    assert not (_verbs(calls, "iam") & IAM_WRITES)

# Bring-your-own roles (hub.iam.*, kind-kro-ack) in the runner flow.
BYO_XP = '{crossplaneProviderRoleArn: "arn:aws:iam::111122223333:role/byo-xp"}'


def test_external_verify_with_byo_crossplane_role(tmp_path, repo):
    """privileged:pre does not create <hub>-crossplane-provider for a BYO role, so the
    host's verify must check the BYO role instead."""
    env = {"FAKE_ABSENT_ROLES": "acme-hub-crossplane-provider"}
    res, calls = _run(tmp_path, repo, "kind-kro-ack", ["kind-kro-ack:privileged:verify"], mode="external",
                      env_extra=env, hub_iam=BYO_XP)
    assert res.returncode == 0, res.stdout + res.stderr
    roles = [c[c.index("--role-name") + 1] for c in calls if c[:2] == ["iam", "get-role"]]
    assert "byo-xp" in roles and "acme-hub-crossplane-provider" not in roles
    # control: without the BYO key the missing default role fails
    res, _ = _run(tmp_path, repo, "kind-kro-ack", ["kind-kro-ack:privileged:verify"], mode="external", env_extra=env)
    assert res.returncode != 0 and "role:acme-hub-crossplane-provider" in res.stderr


def test_external_crossplane_role_verify_with_byo_checks_it_exists(tmp_path, repo):
    res, _ = _run(tmp_path, repo, "kind-kro-ack", ["kind-kro-ack:hub:crossplane-provider-role"], mode="external",
                  env_extra={"FAKE_ABSENT_ROLES": "byo-xp"}, hub_iam=BYO_XP)
    assert res.returncode != 0 and "byo-xp" in res.stderr


@pytest.mark.parametrize("task", ["kind-kro-ack:privileged:verify", "kind-kro-ack:hub:crossplane-provider-role"])
def test_external_verify_wants_the_crossplane_scoped_policy(tmp_path, repo, task):
    """A hub whose runner did not run privileged:pre from this revision (no scoped policy on
    <hub>-crossplane-provider) is refused; a leftover AdministratorAccess is reported."""
    no_scoped = " ".join(a for a in ALL_POLICIES if a != SCOPED_XP)
    res, _ = _run(tmp_path, repo, "kind-kro-ack", [task], mode="external",
                  env_extra={"FAKE_ALL_POLICIES": no_scoped})
    assert res.returncode != 0
    assert "policy:acme-hub-crossplane-provider:acme-hub-crossplane-provider-scoped" in res.stderr
    admin = " ".join(ALL_POLICIES + ["arn:aws:iam::aws:policy/AdministratorAccess"])
    res, _ = _run(tmp_path, repo, "kind-kro-ack", [task], mode="external", env_extra={"FAKE_ALL_POLICIES": admin})
    assert res.returncode == 0, res.stdout + res.stderr
    assert "acme-hub-crossplane-provider still has AdministratorAccess" in res.stderr


def test_external_verify_warns_on_leftover_iam_full_access(tmp_path, repo):
    pols = " ".join(ALL_POLICIES + ["arn:aws:iam::aws:policy/IAMFullAccess"])
    res, _ = _run(tmp_path, repo, "kind-kro-ack", ["kind-kro-ack:hub:create-mgmt-roles"], mode="external",
                  env_extra={"FAKE_ALL_POLICIES": pols})
    assert res.returncode == 0, res.stdout + res.stderr
    assert "acme-cluster-mgmt-iam still has IAMFullAccess" in res.stderr


@pytest.mark.parametrize("task", ["kind-kro-ack:privileged:verify", "kind-kro-ack:hub:create-mgmt-roles"])
def test_external_verify_byo_cluster_mgmt_role_existence_only(tmp_path, repo, task):
    """A BYO cluster-mgmt role gets no policy from the inline path, so external verify
    (the root install runs privileged:verify first) only checks that it exists."""
    byo = '{clusterMgmtRoleArns: {iam: "arn:aws:iam::111122223333:role/acme-cluster-mgmt-iam"}}'
    no_scoped = " ".join(a for a in ALL_POLICIES if a != SCOPED_IAM)
    res, calls = _run(tmp_path, repo, "kind-kro-ack", [task], mode="external",
                      env_extra={"FAKE_ALL_POLICIES": no_scoped}, hub_iam=byo)
    assert res.returncode == 0, res.stdout + res.stderr
    assert any(c[:2] == ["iam", "get-role"] and "acme-cluster-mgmt-iam" in c for c in calls)
    # control: without the BYO key the missing scoped policy fails
    res, _ = _run(tmp_path, repo, "kind-kro-ack", [task], mode="external",
                  env_extra={"FAKE_ALL_POLICIES": no_scoped})
    assert res.returncode != 0 and "acme-cluster-mgmt-iam-scoped" in res.stderr


@pytest.mark.parametrize("task", ["kind-kro-ack:privileged:verify", "kind-kro-ack:hub:create-mgmt-roles"])
def test_external_verify_byo_role_needs_no_inline_policy(tmp_path, repo, task):
    """The inline policies (eks-access-management, rds-kms) are not required on a BYO role."""
    byo = ('{clusterMgmtRoleArns: {eks: "arn:aws:iam::111122223333:role/acme-cluster-mgmt-eks", '
           'rds: "arn:aws:iam::111122223333:role/acme-cluster-mgmt-rds"}}')
    res, _ = _run(tmp_path, repo, "kind-kro-ack", [task], mode="external",
                  env_extra={"FAKE_NO_INLINE": "1"}, hub_iam=byo)
    assert res.returncode == 0, res.stdout + res.stderr
    # control: the repo-created roles need them
    res, _ = _run(tmp_path, repo, "kind-kro-ack", [task], mode="external", env_extra={"FAKE_NO_INLINE": "1"})
    assert res.returncode != 0 and "inline:acme-cluster-mgmt-eks:eks-access-management" in res.stderr


@pytest.mark.parametrize("provider,hint", [("kind-kro-ack", "re-run task privileged:pre"),
                                           ("kind-crossplane", "detach it manually")])
def test_external_verify_legacy_hint_matches_provider(tmp_path, repo, provider, hint):
    """kind-crossplane's privileged:pre does not detach IAMFullAccess, so its verify must not
    send the operator there."""
    pols = " ".join(ALL_POLICIES + ["arn:aws:iam::aws:policy/IAMFullAccess"])
    res, _ = _run(tmp_path, repo, provider, [f"{provider}:privileged:verify"], mode="external",
                  env_extra={"FAKE_ALL_POLICIES": pols})
    assert res.returncode == 0, res.stdout + res.stderr
    assert "acme-cluster-mgmt-iam still has IAMFullAccess" in res.stderr and hint in res.stderr


def test_privileged_destroy_keeps_byo_roles(tmp_path, repo):
    byo = ('{crossplaneProviderRoleArn: "arn:aws:iam::111122223333:role/acme-hub-crossplane-provider", '
           'clusterMgmtRoleArns: {iam: "arn:aws:iam::111122223333:role/acme-cluster-mgmt-iam"}}')
    res, calls = _run(tmp_path, repo, "kind-kro-ack", ["privileged:destroy"], fakes=(("python3", FAKE_PY),),
                      hub_iam=byo)
    assert res.returncode == 0, res.stdout + res.stderr
    deleted = {c[c.index("--role-name") + 1] for c in calls if c[:2] == ["iam", "delete-role"]}
    assert deleted == PRE_ROLES["kind-kro-ack"] - {"acme-hub-crossplane-provider", "acme-cluster-mgmt-iam"}
    assert "skip role acme-cluster-mgmt-iam (bring-your-own" in res.stdout
    touched = {c[4] for c in calls if c[:1] == ["managed-policy.sh"]}
    assert "acme-cluster-mgmt-iam" not in touched and "acme-hub-crossplane-provider" not in touched


@pytest.mark.parametrize("provider", PROVIDERS)
def test_privileged_destroy_deletes_scoped_policies(tmp_path, repo, provider):
    res, calls = _run(tmp_path, repo, provider, ["privileged:destroy"], fakes=(("python3", FAKE_PY),))
    assert res.returncode == 0, res.stdout + res.stderr
    deletes = {c[4] for c in calls if c[:2] == ["managed-policy.sh", "delete"]}
    assert deletes == PRE_ROLES[provider]
    assert all(c[2:4] == ["111122223333", "acme"] for c in calls if c[:2] == ["managed-policy.sh", "delete"])


def test_privileged_destroy_scoped_policy_failure_keeps_the_role(tmp_path, repo):
    """A failed scoped-policy delete is reported and that role is not deleted (deleting it
    would leave its policy behind with nothing pointing at it)."""
    fail_stub = '#!/bin/sh\necho "managed-policy.sh $*" >> "$FAKE_AWS_LOG"\n[ "$4" = acme-cluster-mgmt-iam ] && { echo boom >&2; exit 1; }\nexit 0\n'
    (repo / "cluster-providers" / "common" / "iam" / "managed-policy.sh").write_text(fail_stub)
    res, calls = _run(tmp_path, repo, "kind-kro-ack", ["privileged:destroy"], fakes=(("python3", FAKE_PY),))
    assert res.returncode != 0
    assert "acme-cluster-mgmt-iam (scoped policy)" in res.stderr
    deleted = {c[c.index("--role-name") + 1] for c in calls if c[:2] == ["iam", "delete-role"]}
    assert "acme-cluster-mgmt-iam" not in deleted and "acme-cluster-mgmt-ec2" in deleted


def test_privileged_destroy_deletes_the_scoped_policy_of_a_role_already_gone(tmp_path, repo):
    """A role the host already deleted (6b) may have left its scoped policy: delete it too."""
    res, calls = _run(tmp_path, repo, "kind-kro-ack", ["privileged:destroy"], fakes=(("python3", FAKE_PY),),
                      env_extra={"FAKE_ABSENT_ROLES": "acme-cluster-mgmt-iam"})
    assert res.returncode == 0, res.stdout + res.stderr
    assert "acme-cluster-mgmt-iam already gone" in res.stdout
    assert ["managed-policy.sh", "delete", "111122223333", "acme", "acme-cluster-mgmt-iam"] in calls
    deleted = {c[c.index("--role-name") + 1] for c in calls if c[:2] == ["iam", "delete-role"]}
    assert "acme-cluster-mgmt-iam" not in deleted
