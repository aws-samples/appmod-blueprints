"""`task install` attaches no admin-like AWS managed policy.

A consumer (e.g. the PEEKS workshop) wants to deny, on the role that runs `task install`,
iam:AttachRolePolicy of AdministratorAccess / PowerUserAccess / IAMFullAccess (iam:PolicyARN
condition). That only works if the install never attaches them itself. The two places that did:

* hub:bootstrap-crossplane-identity / spokes:seed-provider-identity -> AdministratorAccess on
  the Crossplane provider-aws-iam/eks role. Now: inline common/iam/crossplane-provider-policy.json.
* hub:create-mgmt-roles -> IAMFullAccess on <prefix>-cluster-mgmt-iam. Now: inline
  common/iam/cluster-mgmt-iam-policy.json.

Plus the bring-your-own option (hub.iam.*): a set ARN is used as is, nothing is created or put.

What these tests pin:
1. static: no admin-like managed policy ARN outside comments/detach calls in the install path;
2. the two policy files are valid, grant no "*" action and no iam:* on "*", the rg-eks
   crossplane-provider inline policy is the same document, and that rg-eks node stays
   spoke-only (gated on provider == "kro-ack", which hub:claim never sets);
3. behaviour (fake `aws` on PATH, REAL Taskfile blocks under go-task): default path, legacy
   detach, BYO path (CLI var and the real config.local.yaml read), BYO validation, a failing
   inline put stops the task, and spokes:seed-provider-identity puts the scoped policy;
   the kind-crossplane hub:create-mgmt-roles and spokes:seed-provider-identity blocks too;
4. config.schema.json hub.iam rejects unknown keys (a typo is not silently ignored).

Run:  python -m pytest workshop/scripts/tests/test_install_no_admin_managed_policies.py -q
"""
import json
import os
import re
import shutil
import subprocess

import pytest

yaml = pytest.importorskip("yaml")

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
KRO = os.path.join(REPO, "cluster-providers", "kind-kro-ack", "Taskfile.yaml")
XP = os.path.join(REPO, "cluster-providers", "kind-crossplane", "Taskfile.yaml")
SCHEMA = os.path.join(REPO, "config.schema.json")
IAM_DIR = os.path.join(REPO, "cluster-providers", "common", "iam")
RG_EKS = os.path.join(REPO, "gitops", "addons", "charts", "kro", "resource-groups", "manifests", "eks", "rg-eks.yaml")
TASK = shutil.which("task")
ACCT = "111111111111"
needs_task = pytest.mark.skipif(not (TASK and shutil.which("yq")), reason="go-task/yq not on PATH")

ADMIN_ARN = re.compile(r"arn:aws[\w-]*:iam::aws:policy/(AdministratorAccess|PowerUserAccess|IAMFullAccess)\b")

# Files run (or rendered with the installing principal's creds) by `task install`.
# Not here, on purpose: cluster-providers/terraform (iam.tf, not the install path of
# kind-kro-ack/kind-crossplane) and scripts/create-cross-account-roles.sh (manual
# multi-account helper run with the TARGET account's creds). In-cluster attachments made by
# provider-aws-iam (crossplane-base, crossplane-pod-identity charts) are not the installing
# principal's and are out of scope too.
INSTALL_PATH = [
    "Taskfile.yaml",
    "workshop/Taskfile.yaml",
    "cluster-providers/kind-kro-ack/Taskfile.yaml",
    "cluster-providers/kind-crossplane/Taskfile.yaml",
    "cluster-providers/common/Taskfile.ray.yaml",
    "gitops/addons/charts/kro/resource-groups/manifests/eks/rg-eks.yaml",
]


def logical_lines(path):
    """Lines with shell backslash continuations joined, so a split command is one line."""
    with open(path) as f:
        text = f.read()
    return text.replace("\\\n", " ").splitlines()


# ------------------------------------------------------------------ 1. static

@pytest.mark.parametrize("rel", INSTALL_PATH)
def test_no_admin_like_managed_policy_in_install_path(rel):
    path = os.path.join(REPO, rel)
    if not os.path.exists(path):
        pytest.skip(f"{rel} absent")
    bad = []
    for line in logical_lines(path):
        if not ADMIN_ARN.search(line):
            continue
        s = line.strip()
        if s.startswith("#") or "detach-role-policy" in s:
            continue
        bad.append(s[:200])
    assert not bad, f"admin-like managed policy still attached in {rel}:\n" + "\n".join(bad)


def test_scan_catches_an_attach():
    """Self-check of the scan: a joined attach line is flagged, a detach or comment is not."""
    sample = "aws iam attach-role-policy --role-name r \\\n  --policy-arn arn:aws:iam::aws:policy/AdministratorAccess"
    joined = sample.replace("\\\n", " ")
    assert ADMIN_ARN.search(joined) and "detach-role-policy" not in joined
    assert ADMIN_ARN.search("arn:aws-us-gov:iam::aws:policy/IAMFullAccess")
    assert not ADMIN_ARN.search("arn:aws:iam::aws:policy/IAMReadOnlyAccess")


# ------------------------------------------------------------------ 2. policies

def load_policy(name):
    with open(os.path.join(IAM_DIR, name)) as f:
        return json.load(f)


def as_list(v):
    return v if isinstance(v, list) else [v]


@pytest.mark.parametrize("name", ["crossplane-provider-policy.json", "cluster-mgmt-iam-policy.json"])
def test_policy_is_scoped(name):
    doc = load_policy(name)
    assert doc["Version"] == "2012-10-17"
    for st in doc["Statement"]:
        assert st["Effect"] == "Allow"
        actions, resources = as_list(st["Action"]), as_list(st["Resource"])
        assert "*" not in actions, st
        if "iam:*" in actions:
            assert "*" not in resources, st
            # IAM write is limited to roles, policies, instance profiles and OIDC providers:
            # no users, groups, access keys, SAML providers or account settings.
            for r in resources:
                assert re.fullmatch(r"arn:\*:iam::\*:(role|policy|instance-profile|oidc-provider)/\*", r), r
        if resources == ["*"]:
            for a in actions:
                assert a in ("iam:Get*", "iam:List*", "eks:*", "ec2:Describe*", "sts:GetCallerIdentity"), a


def test_cluster_mgmt_iam_policy_has_no_non_iam_service():
    doc = load_policy("cluster-mgmt-iam-policy.json")
    for st in doc["Statement"]:
        for a in as_list(st["Action"]):
            assert a.startswith("iam:") or a == "sts:GetCallerIdentity", a


def test_rg_eks_crossplane_provider_role_uses_the_same_policy():
    with open(RG_EKS) as f:
        rgd = yaml.safe_load(f)
    node = next(r for r in rgd["spec"]["resources"] if r["id"] == "crossplaneProviderRole")
    spec = node["template"]["spec"]
    assert "policies" not in spec, "the crossplane-provider role must not attach managed policies"
    inline = json.loads(spec["inlinePolicies"]["crossplane-provider-scoped"])
    assert inline == load_policy("crossplane-provider-policy.json")


def test_rg_eks_crossplane_provider_role_not_rendered_for_hub():
    """The rg-eks crossplaneProviderRole node is for kro-ack spokes, never the hub.

    It is gated on spec.provider == "kro-ack", and the hub instance written by hub:claim
    sets no spec.provider (default ""). If either drifts, the hub would get an ACK-managed
    <hub>-crossplane-provider role with the same name as the bootstrap role.
    """
    with open(RG_EKS) as f:
        rgd = yaml.safe_load(f)
    node = next(r for r in rgd["spec"]["resources"] if r["id"] == "crossplaneProviderRole")
    gate = " ".join(node.get("includeWhen", []))
    assert re.search(r'schema\.spec\.provider\s*==\s*"kro-ack"', gate), gate
    with open(KRO) as f:
        claim = yaml.safe_load(f)["tasks"]["hub:claim"]["cmds"]
    heredocs = [c for c in claim if isinstance(c, str) and "kind: $KIND" in c]
    assert len(heredocs) == 1, "hub:claim instance heredoc not found"
    m = re.search(r"cat <<EOF.*?\n(.*?)\nEOF\b", heredocs[0], re.S)
    assert m, "hub:claim heredoc body not found"
    assert not re.search(r"^\s*provider\s*:", m.group(1), re.M), "hub:claim must not set spec.provider"


# ------------------------------------------------------------------ 3. behaviour

FAKE_AWS = r"""#!/bin/sh
echo "aws $*" >> "$FAKE_LOG"
case "$1 $2" in
  "iam get-role")
    for r in $FAKE_EXISTING_ROLES; do [ "$r" = "$4" ] && exit 0; done
    echo "NoSuchEntity" >&2; exit 254 ;;
  "iam put-role-policy")
    # failure switch: fail the put on one role (--role-name is $4)
    if [ -n "${FAKE_FAIL_PUT_ROLE:-}" ] && [ "$4" = "$FAKE_FAIL_PUT_ROLE" ]; then
      echo "AccessDenied" >&2; exit 254
    fi
    exit 0 ;;
  "iam list-attached-role-policies") echo "${FAKE_ATTACHED:-}"; exit 0 ;;
  "eks list-pod-identity-associations") echo "None"; exit 0 ;;
  "eks describe-cluster") echo "ACTIVE"; exit 0 ;;
esac
exit 0
"""


def block(task, index, taskfile=KRO):
    with open(taskfile) as f:
        cmd = yaml.safe_load(f)["tasks"][task]["cmds"][index]
    return cmd["cmd"] if isinstance(cmd, dict) else cmd


def kro_var(name):
    with open(KRO) as f:
        return yaml.safe_load(f)["vars"][name]


def harness(tmp_path, config="", real_byo_var=False, taskfile=KRO):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "aws").write_text(FAKE_AWS)
    (bin_dir / "aws").chmod(0o755)
    cfg = tmp_path / "config.local.yaml"
    cfg.write_text(config or "hub:\n  clusterName: hub\n")
    gitops = tmp_path / "gitops"
    for member in ("hub", "spoke1"):
        (gitops / "fleet" / "members" / member).mkdir(parents=True)
    tf = {
        "version": "3",
        "set": ["errexit", "nounset", "pipefail"],
        "silent": True,
        "vars": {
            "CONFIG_FILE": str(cfg), "AWS_ACCOUNT_ID": ACCT, "AWS_REGION": "us-west-2",
            "HUB_CLUSTER_NAME": "hub", "RESOURCE_PREFIX": "pfx", "IAM_POLICY_DIR": IAM_DIR,
            "GITOPS_ROOT": str(gitops),
            "ACK_CAPABILITY_ROLE": "hub-ack-capability-role",
            # real_byo_var: the provider's own `sh: yq ...` read of config.local.yaml
            "CROSSPLANE_PROVIDER_ROLE_ARN": kro_var("CROSSPLANE_PROVIDER_ROLE_ARN") if real_byo_var else "",
            **{c: "" for c in ("C_INFO", "C_OK", "C_STEP", "C_ERR", "C_WARN", "C_RESET")},
        },
        "tasks": {
            "mgmt": {"cmds": [block("hub:create-mgmt-roles", 1, taskfile)]},
            "seed": {"cmds": [block("spokes:seed-provider-identity", 0, taskfile)]},
        },
    }
    if taskfile == KRO:  # kind-crossplane has no hub:bootstrap-crossplane-identity
        tf["tasks"]["bootstrap"] = {"cmds": [block("hub:bootstrap-crossplane-identity", 1)]}
    (tmp_path / "Taskfile.yml").write_text(yaml.safe_dump(tf, sort_keys=False))
    return bin_dir


def run(tmp_path, bin_dir, task, *task_vars, existing="", attached="", fail_put_role=""):
    env = {k: v for k, v in os.environ.items() if not k.startswith("AWS_")}
    env.update(PATH=f"{bin_dir}:{os.environ['PATH']}", FAKE_LOG=str(tmp_path / "calls.log"),
               FAKE_EXISTING_ROLES=existing, FAKE_ATTACHED=attached, FAKE_FAIL_PUT_ROLE=fail_put_role)
    r = subprocess.run([TASK, "-d", str(tmp_path), task, *task_vars], env=env,
                       capture_output=True, text=True, timeout=60)
    log = (tmp_path / "calls.log").read_text() if (tmp_path / "calls.log").exists() else ""
    return r, r.stdout + r.stderr, log.splitlines()


def calls_of(log, verb):
    return [c for c in log if f"aws iam {verb} " in c]


@needs_task
def test_bootstrap_default_puts_scoped_policy_and_attaches_nothing(tmp_path):
    b = harness(tmp_path)
    r, out, log = run(tmp_path, b, "bootstrap")
    assert r.returncode == 0, out
    assert calls_of(log, "create-role"), log
    assert not calls_of(log, "attach-role-policy"), log
    puts = calls_of(log, "put-role-policy")
    assert len(puts) == 1 and "--role-name hub-crossplane-provider" in puts[0]
    assert f"file://{IAM_DIR}/crossplane-provider-policy.json" in puts[0]
    assert not calls_of(log, "detach-role-policy"), log  # nothing attached -> nothing to detach
    pia = [c for c in log if "create-pod-identity-association" in c]
    assert len(pia) == 2 and all(f"role/hub-crossplane-provider" in c for c in pia), pia


@needs_task
def test_bootstrap_detaches_legacy_administrator_access(tmp_path):
    b = harness(tmp_path)
    r, out, log = run(tmp_path, b, "bootstrap", existing="hub-crossplane-provider",
                      attached="arn:aws:iam::aws:policy/AdministratorAccess")
    assert r.returncode == 0, out
    assert not calls_of(log, "create-role")
    det = calls_of(log, "detach-role-policy")
    assert len(det) == 1 and "policy/AdministratorAccess" in det[0], log


@needs_task
def test_bootstrap_byo_role_is_used_as_is(tmp_path):
    b = harness(tmp_path)
    arn = f"arn:aws:iam::{ACCT}:role/cfn-crossplane"
    r, out, log = run(tmp_path, b, "bootstrap", f"CROSSPLANE_PROVIDER_ROLE_ARN={arn}", existing="cfn-crossplane")
    assert r.returncode == 0, out
    for verb in ("create-role", "put-role-policy", "attach-role-policy", "detach-role-policy"):
        assert not calls_of(log, verb), (verb, log)
    pia = [c for c in log if "create-pod-identity-association" in c]
    assert len(pia) == 2 and all(arn in c for c in pia), pia


@needs_task
@pytest.mark.parametrize("arn,existing,msg", [
    ("arn:aws:iam::222222222222:role/cfn-crossplane", "cfn-crossplane", "is not an IAM role ARN in account"),
    (f"arn:aws:iam::{ACCT}:role/missing", "", "does not exist"),
])
def test_bootstrap_byo_role_is_validated(tmp_path, arn, existing, msg):
    b = harness(tmp_path)
    r, out, log = run(tmp_path, b, "bootstrap", f"CROSSPLANE_PROVIDER_ROLE_ARN={arn}", existing=existing)
    assert r.returncode != 0 and msg in out, out
    assert not [c for c in log if "create-pod-identity-association" in c]


@needs_task
def test_mgmt_default_no_iam_full_access(tmp_path):
    b = harness(tmp_path)
    r, out, log = run(tmp_path, b, "mgmt")
    assert r.returncode == 0, out
    created = calls_of(log, "create-role")
    assert len(created) == 8, created
    attaches = calls_of(log, "attach-role-policy")
    assert attaches and not [a for a in attaches if ADMIN_ARN.search(a)], attaches
    assert not [a for a in attaches if "pfx-cluster-mgmt-iam " in a + " "], attaches
    assert any("AmazonS3FullAccess" in a for a in attaches)  # other services unchanged
    puts = [p for p in calls_of(log, "put-role-policy") if "--role-name pfx-cluster-mgmt-iam " in p]
    assert len(puts) == 1 and f"file://{IAM_DIR}/cluster-mgmt-iam-policy.json" in puts[0], log


@needs_task
def test_mgmt_detaches_legacy_iam_full_access(tmp_path):
    b = harness(tmp_path)
    r, out, log = run(tmp_path, b, "mgmt", existing="pfx-cluster-mgmt-iam",
                      attached="arn:aws:iam::aws:policy/IAMFullAccess")
    assert r.returncode == 0, out
    det = calls_of(log, "detach-role-policy")
    assert len(det) == 1 and "pfx-cluster-mgmt-iam" in det[0] and "IAMFullAccess" in det[0], log


@needs_task
def test_mgmt_byo_roles_are_used_as_is(tmp_path):
    cfg = ("hub:\n  clusterName: hub\n  iam:\n    clusterMgmtRoleArns:\n"
           f"      iam: arn:aws:iam::{ACCT}:role/pfx-cluster-mgmt-iam\n"
           f"      eks: arn:aws:iam::{ACCT}:role/pfx-cluster-mgmt-eks\n")
    b = harness(tmp_path, cfg)
    r, out, log = run(tmp_path, b, "mgmt", existing="pfx-cluster-mgmt-iam pfx-cluster-mgmt-eks")
    assert r.returncode == 0, out
    touched = [c for c in log if re.search(r"--role-name pfx-cluster-mgmt-(iam|eks) ", c + " ")
               and " get-role " not in c and "list-attached" not in c]
    assert not touched, touched
    assert len(calls_of(log, "create-role")) == 6, log
    # rds is not BYO here, so its inline KMS policy is still put
    assert [p for p in calls_of(log, "put-role-policy") if "pfx-cluster-mgmt-rds" in p]


@needs_task
@pytest.mark.parametrize("arn,existing,msg", [
    (f"arn:aws:iam::{ACCT}:role/cfn-iam", "cfn-iam", "must be arn:aws:iam::"),
    (f"arn:aws:iam::{ACCT}:role/pfx-cluster-mgmt-iam", "", "does not exist"),
])
def test_mgmt_byo_roles_are_validated(tmp_path, arn, existing, msg):
    cfg = f"hub:\n  clusterName: hub\n  iam:\n    clusterMgmtRoleArns:\n      iam: {arn}\n"
    b = harness(tmp_path, cfg)
    r, out, log = run(tmp_path, b, "mgmt", existing=existing)
    assert r.returncode != 0 and msg in out, out
    assert not calls_of(log, "create-role"), log


@needs_task
def test_bootstrap_put_failure_is_fatal(tmp_path):
    b = harness(tmp_path)
    r, out, log = run(tmp_path, b, "bootstrap", fail_put_role="hub-crossplane-provider")
    assert r.returncode != 0, out
    assert calls_of(log, "put-role-policy"), log
    assert not [c for c in log if "create-pod-identity-association" in c], log


@needs_task
def test_bootstrap_byo_role_read_from_config(tmp_path):
    """The real `sh: yq` global var reads hub.iam.crossplaneProviderRoleArn from config.local.yaml."""
    arn = f"arn:aws:iam::{ACCT}:role/cfn-crossplane"
    cfg = f"hub:\n  clusterName: hub\n  iam:\n    crossplaneProviderRoleArn: {arn}\n"
    b = harness(tmp_path, cfg, real_byo_var=True)
    r, out, log = run(tmp_path, b, "bootstrap", existing="cfn-crossplane")
    assert r.returncode == 0, out
    assert not calls_of(log, "create-role") and not calls_of(log, "put-role-policy"), log
    pia = [c for c in log if "create-pod-identity-association" in c]
    assert len(pia) == 2 and all(arn in c for c in pia), pia


@needs_task
def test_mgmt_put_failure_is_fatal(tmp_path):
    b = harness(tmp_path)
    r, out, log = run(tmp_path, b, "mgmt", fail_put_role="pfx-cluster-mgmt-iam")
    assert r.returncode != 0, out
    assert [p for p in calls_of(log, "put-role-policy") if "pfx-cluster-mgmt-iam " in p + " "], log


@needs_task
def test_seed_provider_identity_puts_scoped_policy(tmp_path):
    b = harness(tmp_path)
    r, out, log = run(tmp_path, b, "seed")
    assert r.returncode == 0, out
    assert not calls_of(log, "attach-role-policy"), log
    puts = calls_of(log, "put-role-policy")
    roles = sorted(re.search(r"--role-name (\S+)", p).group(1) for p in puts)
    assert roles == ["spoke1-CrossplaneEKSProviderRole", "spoke1-CrossplaneIAMProviderRole"], puts
    assert all(f"file://{IAM_DIR}/crossplane-provider-policy.json" in p for p in puts), puts
    assert os.path.isfile(os.path.join(IAM_DIR, "crossplane-provider-policy.json"))
    assert not [c for c in log if "--role-name hub-" in c], log  # the hub is excluded


@needs_task
def test_seed_provider_identity_put_failure_is_fatal(tmp_path):
    b = harness(tmp_path)
    r, out, log = run(tmp_path, b, "seed", fail_put_role="spoke1-CrossplaneIAMProviderRole")
    assert r.returncode != 0, out
    assert not [c for c in log if "create-pod-identity-association" in c], log


# kind-crossplane: same blocks, same fake aws (no BYO, no detach there).

@needs_task
def test_kind_crossplane_mgmt_puts_scoped_policy_and_no_admin(tmp_path):
    b = harness(tmp_path, taskfile=XP)
    r, out, log = run(tmp_path, b, "mgmt")
    assert r.returncode == 0, out
    attaches = calls_of(log, "attach-role-policy")
    assert not [a for a in attaches if ADMIN_ARN.search(a)], attaches
    assert not [a for a in attaches if "pfx-cluster-mgmt-iam " in a + " "], attaches
    puts = [p for p in calls_of(log, "put-role-policy") if "--role-name pfx-cluster-mgmt-iam " in p]
    assert len(puts) == 1 and f"file://{IAM_DIR}/cluster-mgmt-iam-policy.json" in puts[0], log


@needs_task
def test_kind_crossplane_mgmt_put_failure_is_fatal(tmp_path):
    b = harness(tmp_path, taskfile=XP)
    r, out, log = run(tmp_path, b, "mgmt", fail_put_role="pfx-cluster-mgmt-iam")
    assert r.returncode != 0, out


@needs_task
def test_kind_crossplane_seed_puts_scoped_policy(tmp_path):
    b = harness(tmp_path, taskfile=XP)
    r, out, log = run(tmp_path, b, "seed")
    assert r.returncode == 0, out
    assert not calls_of(log, "attach-role-policy"), log
    puts = calls_of(log, "put-role-policy")
    roles = sorted(re.search(r"--role-name (\S+)", p).group(1) for p in puts)
    assert roles == ["spoke1-CrossplaneEKSProviderRole", "spoke1-CrossplaneIAMProviderRole"], puts
    assert all(f"file://{IAM_DIR}/crossplane-provider-policy.json" in p for p in puts), puts


@needs_task
def test_kind_crossplane_seed_put_failure_is_fatal(tmp_path):
    b = harness(tmp_path, taskfile=XP)
    r, out, log = run(tmp_path, b, "seed", fail_put_role="spoke1-CrossplaneIAMProviderRole")
    assert r.returncode != 0, out


# ------------------------------------------------------------------ 4. config schema

def test_schema_hub_iam_rejects_unknown_keys():
    jsonschema = pytest.importorskip("jsonschema")
    with open(SCHEMA) as f:
        iam = json.load(f)["properties"]["hub"]["properties"]["iam"]
    jsonschema.validate({"crossplaneProviderRoleArn": "", "clusterMgmtRoleArns": {"iam": "x"}}, iam)
    for bad in ({"crossplaneProviderRoleARN": "x"}, {"clusterMgmtRoleArns": {"iamm": "x"}}):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(bad, iam)


@pytest.mark.skipif(not shutil.which("shellcheck"), reason="shellcheck not on PATH")
@pytest.mark.parametrize("taskfile,task,index", [
    (KRO, "hub:bootstrap-crossplane-identity", 1), (KRO, "hub:create-mgmt-roles", 1),
    (KRO, "spokes:seed-provider-identity", 0),
    (XP, "hub:create-mgmt-roles", 1), (XP, "spokes:seed-provider-identity", 0)])
def test_blocks_shellcheck(tmp_path, taskfile, task, index):
    # go-task templates are not shell; replace them with a plain word first.
    body = re.sub(r"\{\{[^}]*\}\}", "X", block(task, index, taskfile))
    p = tmp_path / "b.sh"
    p.write_text("#!/bin/bash\n" + body)
    r = subprocess.run(["shellcheck", "-S", "error", str(p)], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout
