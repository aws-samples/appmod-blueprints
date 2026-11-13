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
2. the two policy files are valid, grant no "*" action and no iam:* on "*", and the rg-eks
   crossplane-provider inline policy is the same document;
3. behaviour (fake `aws` on PATH, REAL Taskfile blocks under go-task): default path, legacy
   detach, BYO path and BYO validation, for both tasks.

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
IAM_DIR = os.path.join(REPO, "cluster-providers", "common", "iam")
RG_EKS = os.path.join(REPO, "gitops", "addons", "charts", "kro", "resource-groups", "manifests", "eks", "rg-eks.yaml")
TASK = shutil.which("task")
ACCT = "111111111111"
needs_task = pytest.mark.skipif(not (TASK and shutil.which("yq")), reason="go-task/yq not on PATH")

ADMIN_ARN = re.compile(r"arn:aws[\w-]*:iam::aws:policy/(AdministratorAccess|PowerUserAccess|IAMFullAccess)\b")

# Files run (or rendered with the installing principal's creds) by `task install`.
# Not here, on purpose: cluster-providers/terraform (iam.tf, not the install path of
# kind-kro-ack/kind-crossplane) and scripts/create-cross-account-roles.sh (manual
# multi-account helper run with the TARGET account's creds).
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


# ------------------------------------------------------------------ 3. behaviour

FAKE_AWS = r"""#!/bin/sh
echo "aws $*" >> "$FAKE_LOG"
case "$1 $2" in
  "iam get-role")
    for r in $FAKE_EXISTING_ROLES; do [ "$r" = "$4" ] && exit 0; done
    echo "NoSuchEntity" >&2; exit 254 ;;
  "iam list-attached-role-policies") echo "${FAKE_ATTACHED:-}"; exit 0 ;;
  "eks list-pod-identity-associations") echo "None"; exit 0 ;;
esac
exit 0
"""


def block(task, index):
    with open(KRO) as f:
        cmd = yaml.safe_load(f)["tasks"][task]["cmds"][index]
    return cmd["cmd"] if isinstance(cmd, dict) else cmd


def harness(tmp_path, config=""):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "aws").write_text(FAKE_AWS)
    (bin_dir / "aws").chmod(0o755)
    cfg = tmp_path / "config.local.yaml"
    cfg.write_text(config or "hub:\n  clusterName: hub\n")
    tf = {
        "version": "3",
        "set": ["errexit", "nounset", "pipefail"],
        "silent": True,
        "vars": {
            "CONFIG_FILE": str(cfg), "AWS_ACCOUNT_ID": ACCT, "AWS_REGION": "us-west-2",
            "HUB_CLUSTER_NAME": "hub", "RESOURCE_PREFIX": "pfx", "IAM_POLICY_DIR": IAM_DIR,
            "ACK_CAPABILITY_ROLE": "hub-ack-capability-role",
            "CROSSPLANE_PROVIDER_ROLE_ARN": "",
            **{c: "" for c in ("C_INFO", "C_OK", "C_STEP", "C_ERR", "C_WARN", "C_RESET")},
        },
        "tasks": {
            "bootstrap": {"cmds": [block("hub:bootstrap-crossplane-identity", 1)]},
            "mgmt": {"cmds": [block("hub:create-mgmt-roles", 1)]},
        },
    }
    (tmp_path / "Taskfile.yml").write_text(yaml.safe_dump(tf, sort_keys=False))
    return bin_dir


def run(tmp_path, bin_dir, task, *task_vars, existing="", attached=""):
    env = {k: v for k, v in os.environ.items() if not k.startswith("AWS_")}
    env.update(PATH=f"{bin_dir}:{os.environ['PATH']}", FAKE_LOG=str(tmp_path / "calls.log"),
               FAKE_EXISTING_ROLES=existing, FAKE_ATTACHED=attached)
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


@pytest.mark.skipif(not shutil.which("shellcheck"), reason="shellcheck not on PATH")
@pytest.mark.parametrize("task,index", [("hub:bootstrap-crossplane-identity", 1), ("hub:create-mgmt-roles", 1)])
def test_blocks_shellcheck(tmp_path, task, index):
    # go-task templates are not shell; replace them with a plain word first.
    body = re.sub(r"\{\{[^}]*\}\}", "X", block(task, index))
    p = tmp_path / "b.sh"
    p.write_text("#!/bin/bash\n" + body)
    r = subprocess.run(["shellcheck", "-S", "error", str(p)], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout
