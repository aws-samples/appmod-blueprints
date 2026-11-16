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
    for svc, arns in re.findall(r"^\s+([a-z0-9]+)\) echo \"([^\"]+)\";;", text, re.M):
        out[svc] = arns.split()
    return out


ALL_POLICIES = sorted({a for v in _expected_policies(open(VERIFY_SH).read()).values() for a in v})


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


def _run(tmp_path, repo, provider, args, mode=None, roles="present", cwd=None, env_extra=None, fakes=()):
    (repo / "config.local.yaml").write_text(_config(provider, mode))
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
    assert not any(c[:2] == ["iam", "delete-role"] for c in calls)


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