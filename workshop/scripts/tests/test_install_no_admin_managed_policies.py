"""`task install` attaches no admin-like AWS managed policy.

A consumer (e.g. the PEEKS workshop) wants to deny, on the role that runs `task install`,
iam:AttachRolePolicy of AdministratorAccess / PowerUserAccess / IAMFullAccess (iam:PolicyARN
condition). That only works if the install never attaches them itself. The two places that did:

* hub:bootstrap-crossplane-identity / spokes:seed-provider-identity -> AdministratorAccess on
  the Crossplane provider-aws-iam/eks role. Now: customer-managed <role>-scoped policy with the
  document common/iam/crossplane-provider-policy.json.
* hub:create-mgmt-roles -> IAMFullAccess on <prefix>-cluster-mgmt-iam. Now: customer-managed
  <prefix>-cluster-mgmt-iam-scoped with common/iam/cluster-mgmt-iam-policy.json.

Customer-managed, not inline, and no CreatePolicyVersion: the consumer may grant
CreatePolicy/AttachRolePolicy/DeletePolicy on <prefix>-* but neither iam:PutRolePolicy on these
roles nor iam:CreatePolicyVersion. common/iam/managed-policy.sh creates, recreates on drift and
attaches the policy, and removes the inline policy an earlier version of the install wrote.
Plus the bring-your-own option (hub.iam.*): a set ARN is used as is, nothing is created.

What these tests pin:
1. static: no admin-like managed policy ARN outside comments/detach calls in the install path;
2. the two policy files are valid, grant no "*" action and no iam:* on "*"; the rg-eks
   crossplane-provider role attaches only the ACK Policy node with the same document and the
   <role>-scoped name, and that node stays spoke-only (gated on provider == "kro-ack", which
   hub:claim never sets);
3. behaviour, against a stateful fake `aws` on PATH: managed-policy.sh alone (create, identical
   = attach only, drift = detach/prune/delete/create/attach in that order, legacy inline
   removal, fatal errors, convergence after a failure inside the recreate window, delete);
   the REAL Taskfile blocks under go-task (default, legacy detach, upgrade from inline, re-run
   on the roles a failed run left, BYO, fatal policy errors, seed tasks of both providers);
   kind-kro-ack destroy step 6b deletes the scoped policies before their roles;
4. config.schema.json hub.iam rejects unknown keys; shellcheck on the blocks and the script.

Run:  python -m pytest workshop/scripts/tests/test_install_no_admin_managed_policies.py -q
"""
import json
import os
import re
import shutil
import subprocess
import sys

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
    nodes = {r["id"]: r for r in rgd["spec"]["resources"]}
    role, pol = nodes["crossplaneProviderRole"], nodes["crossplaneProviderPolicy"]
    spec = role["template"]["spec"]
    # Only the scoped customer-managed policy node, no inline policy, no AWS managed ARN.
    assert spec["policies"] == ["${crossplaneProviderPolicy.status.ackResourceMetadata.arn}"], spec
    assert "inlinePolicies" not in spec, spec
    assert pol["template"]["kind"] == "Policy"
    assert pol["includeWhen"] == role["includeWhen"], "policy and role must render together"
    # Same <role>-scoped name rule as managed-policy.sh, so it matches policy/<prefix>-*.
    assert pol["template"]["spec"]["name"] == spec["name"] + "-scoped"
    assert json.loads(pol["template"]["spec"]["policyDocument"]) == load_policy("crossplane-provider-policy.json")


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

# Stateful fake `aws`: IAM roles, customer-managed policies (versions + default document),
# attachments and inline policies live in a JSON state file, so the real Taskfile blocks and
# managed-policy.sh run against something that behaves like IAM (NoSuchEntity,
# DeleteConflict, EntityAlreadyExists). Every call is logged. Failure switch:
# FAKE_FAIL="<op>:<target> ..." -> AccessDenied when the op's role name or policy name is
# <target>. FAKE_ATTACHED: extra AWS-managed ARNs listed as attached to every role (legacy).
FAKE_AWS = r'''#!__PY__
import json, os, sys
args = sys.argv[1:]
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write("aws " + " ".join(args) + "\n")
svc, op = (args + ["", ""])[:2]
opt = {}
i = 2
while i < len(args):
    if args[i].startswith("--"):
        opt[args[i][2:]] = args[i + 1] if i + 1 < len(args) else ""
        i += 2
    else:
        i += 1
if svc != "iam":
    if (svc, op) == ("eks", "list-pod-identity-associations"):
        print("None")
    elif (svc, op) == ("eks", "describe-cluster"):
        print("ACTIVE")
    sys.exit(0)
import fcntl
path = os.environ["FAKE_STATE"]
lock = open(path + ".lock", "w")
fcntl.flock(lock, fcntl.LOCK_EX)  # the mgmt block runs 8 role creations in parallel
st = json.load(open(path)) if os.path.exists(path) else {}
roles = st.setdefault("roles", [])
pols = st.setdefault("policies", {})
att = st.setdefault("attached", {})
inl = st.setdefault("inline", {})
role = opt.get("role-name", "")
pname = opt.get("policy-name") or opt.get("policy-arn", "").rsplit("/", 1)[-1]

def save():
    json.dump(st, open(path, "w"))

def err(code):
    sys.stderr.write(f"An error occurred ({code}) when calling the {op} operation: fake\n")
    sys.exit(254)

for spec in os.environ.get("FAKE_FAIL", "").split():
    o, _, target = spec.partition(":")
    if o == op and target in (role, pname):
        err("AccessDenied")
legacy = os.environ.get("FAKE_ATTACHED", "").split()

def managed(arn):
    return ":iam::aws:policy/" not in arn

if op == "list-roles":
    print("\t".join(roles))
elif op == "list-policies":
    print("\t".join(f"arn:aws:iam::{os.environ.get('FAKE_ACCT', '111111111111')}:policy/{n}" for n in pols))
elif op == "get-role":
    if role not in roles:
        err("NoSuchEntity")
elif op == "create-role":
    roles.append(role); save()
elif op == "put-role-policy":
    inl.setdefault(role, []).append(pname); save()
elif op == "delete-role-policy":
    if pname not in inl.get(role, []):
        err("NoSuchEntity")
    inl[role].remove(pname); save()
elif op == "list-role-policies":
    print("\t".join(inl.get(role, [])))
elif op == "list-attached-role-policies":
    print("\t".join(legacy + att.get(role, [])))
elif op == "attach-role-policy":
    arn = opt["policy-arn"]
    if role not in roles or (managed(arn) and pname not in pols):
        err("NoSuchEntity")
    if arn not in att.setdefault(role, []):
        att[role].append(arn)
    save()
elif op == "detach-role-policy":
    arn = opt["policy-arn"]
    if arn in legacy:
        sys.exit(0)
    if arn not in att.get(role, []):
        err("NoSuchEntity")
    att[role].remove(arn); save()
elif op == "get-policy":
    if pname not in pols:
        err("NoSuchEntity")
    print(pols[pname]["default"])
elif op == "get-policy-version":
    if pname not in pols:
        err("NoSuchEntity")
    raw = os.environ.get("FAKE_RAW_VERSION")
    print(raw if raw is not None else json.dumps(pols[pname]["docs"][opt["version-id"]]))
elif op == "list-policy-versions":
    if pname not in pols:
        err("NoSuchEntity")
    print("\t".join(v for v in pols[pname]["docs"] if v != pols[pname]["default"]))
elif op == "delete-policy-version":
    if pname not in pols or opt["version-id"] not in pols[pname]["docs"]:
        err("NoSuchEntity")
    if opt["version-id"] == pols[pname]["default"]:
        err("DeleteConflict")
    del pols[pname]["docs"][opt["version-id"]]; save()
elif op == "delete-policy":
    if pname not in pols:
        err("NoSuchEntity")
    if any(opt["policy-arn"] in a for a in att.values()) or len(pols[pname]["docs"]) > 1:
        err("DeleteConflict")
    del pols[pname]; save()
elif op == "create-policy":
    if pname in pols:
        err("EntityAlreadyExists")
    doc = json.load(open(opt["policy-document"][len("file://"):]))
    pols[pname] = {"default": "v1", "docs": {"v1": doc}}; save()
elif op == "create-policy-version":
    err("AccessDenied")  # the consumer (PEEKS) does not grant it: never called
'''.replace("__PY__", sys.executable)


def block(task, index, taskfile=KRO):
    with open(taskfile) as f:
        cmd = yaml.safe_load(f)["tasks"][task]["cmds"][index]
    return cmd["cmd"] if isinstance(cmd, dict) else cmd


def kro_var(name):
    with open(KRO) as f:
        return yaml.safe_load(f)["vars"][name]


def destroy_index():
    """The destroy cmd that holds step 6 (extended sweep, role loop 6b)."""
    with open(KRO) as f:
        cmds = yaml.safe_load(f)["tasks"]["destroy"]["cmds"]
    idx = [i for i, c in enumerate(cmds) if isinstance(c, dict) and "6b. ALL remaining" in c.get("cmd", "")]
    assert len(idx) == 1, idx
    return idx[0]


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
        # destroy step 6, with its own task vars; python3 is a no-op stub here (the
        # sweep helpers it runs would call AWS) and the destroy deadline is off.
        with open(KRO) as f:
            dvars = yaml.safe_load(f)["tasks"]["destroy"]["vars"]
        tf["tasks"]["sweep"] = {
            "vars": {"DL_FN": dvars["DL_FN"], "DESTROY_DEADLINE": "0", "HUB_VPC_ID": "",
                     "DESTROY_KEEP_DATA": "false"},
            "cmds": [block("destroy", destroy_index())],
        }
        (tmp_path / "private").mkdir()
    (tmp_path / "Taskfile.yml").write_text(yaml.safe_dump(tf, sort_keys=False))
    return bin_dir


def seed_state(tmp_path, roles=(), policies=None, attached=None, inline=None):
    """policies: {name: document | [doc_v1, doc_v2, ...]} (the last one is the default)."""
    pols = {}
    for name, docs in (policies or {}).items():
        docs = docs if isinstance(docs, list) else [docs]
        pols[name] = {"default": f"v{len(docs)}", "docs": {f"v{i + 1}": d for i, d in enumerate(docs)}}
    st = {"roles": list(roles), "policies": pols, "attached": attached or {}, "inline": inline or {}}
    (tmp_path / "state.json").write_text(json.dumps(st))


def state(tmp_path):
    return json.loads((tmp_path / "state.json").read_text())


def run(tmp_path, bin_dir, task, *task_vars, existing="", attached="", fail="", stub_python=False):
    if not (tmp_path / "state.json").exists():
        seed_state(tmp_path, roles=existing.split())
    path = f"{bin_dir}:{os.environ['PATH']}"
    if stub_python:
        stub = tmp_path / "stubpy"
        stub.mkdir(exist_ok=True)
        (stub / "python3").write_text("#!/bin/sh\nexit 0\n")
        (stub / "python3").chmod(0o755)
        path = f"{stub}:{path}"
    env = {k: v for k, v in os.environ.items() if not k.startswith("AWS_")}
    env.update(PATH=path, FAKE_LOG=str(tmp_path / "calls.log"), FAKE_STATE=str(tmp_path / "state.json"),
               FAKE_ATTACHED=attached, FAKE_FAIL=fail)
    r = subprocess.run([TASK, "-d", str(tmp_path), task, *task_vars], env=env,
                       capture_output=True, text=True, timeout=120)
    log = (tmp_path / "calls.log").read_text() if (tmp_path / "calls.log").exists() else ""
    return r, r.stdout + r.stderr, log.splitlines()


def calls_of(log, verb):
    return [c for c in log if f"aws iam {verb} " in c]


def arn(name):
    return f"arn:aws:iam::{ACCT}:policy/{name}"


XP_DOC = load_policy("crossplane-provider-policy.json")
MGMT_DOC = load_policy("cluster-mgmt-iam-policy.json")
HUB_POL = "pfx-hub-crossplane-provider-scoped"
MGMT_POL = "pfx-cluster-mgmt-iam-scoped"


def test_no_create_policy_version_and_no_inline_put_in_changed_blocks():
    """The consumer (PEEKS) grants CreatePolicy/DeletePolicy on policy/<prefix>-* but neither
    iam:CreatePolicyVersion nor iam:PutRolePolicy on these roles."""
    with open(os.path.join(IAM_DIR, "managed-policy.sh")) as f:
        assert "create-policy-version" not in f.read()
    for taskfile, task, index in BLOCKS:
        body = block(task, index, taskfile)
        assert "managed-policy.sh\" ensure" in body, (task, taskfile)
        for line in logical_lines_of(body):
            if "put-role-policy" in line and not line.strip().startswith("#"):
                assert not re.search(r"--policy-name (cluster-mgmt-iam|crossplane-provider)-scoped", line), line


def logical_lines_of(text):
    return text.replace("\\\n", " ").splitlines()


BLOCKS = [(KRO, "hub:bootstrap-crossplane-identity", 1), (KRO, "hub:create-mgmt-roles", 1),
          (KRO, "spokes:seed-provider-identity", 0),
          (XP, "hub:create-mgmt-roles", 1), (XP, "spokes:seed-provider-identity", 0)]


# managed-policy.sh on its own (same fake aws, no go-task)

MP = os.path.join(IAM_DIR, "managed-policy.sh")


def mp(tmp_path, *args, fail="", raw_version=None):
    bin_dir = tmp_path / "bin"
    if not bin_dir.exists():
        bin_dir.mkdir()
        (bin_dir / "aws").write_text(FAKE_AWS)
        (bin_dir / "aws").chmod(0o755)
    env = {k: v for k, v in os.environ.items() if not k.startswith("AWS_")}
    env.update(PATH=f"{bin_dir}:{os.environ['PATH']}", FAKE_LOG=str(tmp_path / "calls.log"),
               FAKE_STATE=str(tmp_path / "state.json"), FAKE_FAIL=fail, FAKE_ATTACHED="")
    if raw_version is not None:
        env["FAKE_RAW_VERSION"] = raw_version
    r = subprocess.run(["sh", MP, *args], env=env, capture_output=True, text=True, timeout=60)
    log = (tmp_path / "calls.log").read_text().splitlines() if (tmp_path / "calls.log").exists() else []
    return r, r.stdout + r.stderr, log


DOC_FILE = os.path.join(IAM_DIR, "crossplane-provider-policy.json")


@pytest.mark.parametrize("prefix,role,name", [
    ("pfx", "pfx-hub-crossplane-provider", "pfx-hub-crossplane-provider-scoped"),
    ("pfx", "hub-crossplane-provider", "pfx-hub-crossplane-provider-scoped"),
    ("", "hub-crossplane-provider", "hub-crossplane-provider-scoped"),
    ("pfx", "pfx-cluster-mgmt-iam", "pfx-cluster-mgmt-iam-scoped"),
])
def test_mp_name_always_carries_the_prefix(tmp_path, prefix, role, name):
    r, out, _ = mp(tmp_path, "name", prefix, role)
    assert r.returncode == 0 and out.strip() == name, out


def test_mp_create_when_absent(tmp_path):
    seed_state(tmp_path, roles=["pfx-r"])
    r, out, log = mp(tmp_path, "ensure", ACCT, "pfx", "pfx-r", DOC_FILE)
    assert r.returncode == 0, out
    s = state(tmp_path)
    assert s["policies"]["pfx-r-scoped"]["docs"] == {"v1": XP_DOC}
    assert s["attached"]["pfx-r"] == [arn("pfx-r-scoped")]
    assert not calls_of(log, "create-policy-version")


def test_mp_identical_is_attach_only(tmp_path):
    seed_state(tmp_path, roles=["pfx-r"], policies={"pfx-r-scoped": XP_DOC},
               attached={"pfx-r": [arn("pfx-r-scoped")]})
    r, out, log = mp(tmp_path, "ensure", ACCT, "pfx", "pfx-r", DOC_FILE)
    assert r.returncode == 0, out
    for verb in ("create-policy", "delete-policy", "delete-policy-version", "detach-role-policy"):
        assert not calls_of(log, verb), (verb, log)
    assert len(calls_of(log, "attach-role-policy")) == 1
    assert state(tmp_path)["policies"]["pfx-r-scoped"]["docs"] == {"v1": XP_DOC}


def test_mp_identical_but_detached_is_reattached(tmp_path):
    seed_state(tmp_path, roles=["pfx-r"], policies={"pfx-r-scoped": XP_DOC})
    r, out, log = mp(tmp_path, "ensure", ACCT, "pfx", "pfx-r", DOC_FILE)
    assert r.returncode == 0, out
    assert not calls_of(log, "create-policy")
    assert state(tmp_path)["attached"]["pfx-r"] == [arn("pfx-r-scoped")]


def test_mp_drift_recreates_in_order_without_create_policy_version(tmp_path):
    old = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "s3:*", "Resource": "*"}]}
    seed_state(tmp_path, roles=["pfx-r"], policies={"pfx-r-scoped": [old, old, old]},
               attached={"pfx-r": [arn("pfx-r-scoped")]})
    r, out, log = mp(tmp_path, "ensure", ACCT, "pfx", "pfx-r", DOC_FILE)
    assert r.returncode == 0, out
    ops = [c.split()[2] for c in log if c.split()[2] in (
        "detach-role-policy", "delete-policy-version", "delete-policy", "create-policy", "attach-role-policy")]
    assert ops == ["detach-role-policy", "delete-policy-version", "delete-policy-version",
                   "delete-policy", "create-policy", "attach-role-policy"], ops
    s = state(tmp_path)
    assert s["policies"]["pfx-r-scoped"]["docs"] == {"v1": XP_DOC}
    assert s["attached"]["pfx-r"] == [arn("pfx-r-scoped")]
    assert not calls_of(log, "create-policy-version")


def test_mp_document_compare_ignores_key_order(tmp_path):
    reordered = json.loads(json.dumps(XP_DOC))
    reordered = {"Statement": reordered["Statement"], "Version": reordered["Version"]}
    seed_state(tmp_path, roles=["pfx-r"], policies={"pfx-r-scoped": reordered},
               attached={"pfx-r": [arn("pfx-r-scoped")]})
    r, out, log = mp(tmp_path, "ensure", ACCT, "pfx", "pfx-r", DOC_FILE)
    assert r.returncode == 0, out
    assert not calls_of(log, "delete-policy"), log


@pytest.mark.parametrize("raw", ["{bad", "", '"%7Bbad"'])
def test_mp_unparseable_document_is_fatal_and_deletes_nothing(tmp_path, raw):
    """A document that cannot be compared is an error, never "drift": drift deletes the policy."""
    seed_state(tmp_path, roles=["pfx-r"], policies={"pfx-r-scoped": XP_DOC},
               attached={"pfx-r": [arn("pfx-r-scoped")]})
    r, out, log = mp(tmp_path, "ensure", ACCT, "pfx", "pfx-r", DOC_FILE, raw_version=raw)
    assert r.returncode != 0 and "cannot compare" in out, out
    for verb in ("detach-role-policy", "delete-policy", "delete-policy-version", "create-policy"):
        assert not calls_of(log, verb), (verb, log)
    assert state(tmp_path)["policies"]["pfx-r-scoped"]["docs"] == {"v1": XP_DOC}


def test_mp_invalid_desired_document_is_fatal_before_any_aws_call(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{bad")
    seed_state(tmp_path, roles=["pfx-r"], policies={"pfx-r-scoped": XP_DOC},
               attached={"pfx-r": [arn("pfx-r-scoped")]})
    r, out, log = mp(tmp_path, "ensure", ACCT, "pfx", "pfx-r", str(bad))
    assert r.returncode != 0 and "is not readable JSON" in out, out
    assert log == [], log
    assert state(tmp_path)["policies"]["pfx-r-scoped"]["docs"] == {"v1": XP_DOC}


def test_mp_removes_legacy_inline_and_tolerates_its_absence(tmp_path):
    seed_state(tmp_path, roles=["pfx-r", "pfx-s"], inline={"pfx-r": ["crossplane-provider-scoped", "other"]})
    r, out, _ = mp(tmp_path, "ensure", ACCT, "pfx", "pfx-r", DOC_FILE, "crossplane-provider-scoped")
    assert r.returncode == 0, out
    assert state(tmp_path)["inline"]["pfx-r"] == ["other"]
    r, out, _ = mp(tmp_path, "ensure", ACCT, "pfx", "pfx-s", DOC_FILE, "crossplane-provider-scoped")
    assert r.returncode == 0, out  # NoSuchEntity on the legacy inline = nothing to do


@pytest.mark.parametrize("fail", [
    "get-policy:pfx-r-scoped", "create-policy:pfx-r-scoped", "attach-role-policy:pfx-r",
    "delete-role-policy:pfx-r",
])
def test_mp_errors_are_fatal(tmp_path, fail):
    seed_state(tmp_path, roles=["pfx-r"], inline={"pfx-r": ["crossplane-provider-scoped"]})
    r, out, _ = mp(tmp_path, "ensure", ACCT, "pfx", "pfx-r", DOC_FILE, "crossplane-provider-scoped", fail=fail)
    assert r.returncode != 0, out
    # the failing call itself is reported (not a later call failing because of it)
    assert f"ERROR: aws iam {fail.split(':')[0]} failed" in out and "AccessDenied" in out, out


def test_mp_missing_role_is_fatal(tmp_path):
    seed_state(tmp_path)
    r, out, _ = mp(tmp_path, "ensure", ACCT, "pfx", "pfx-r", DOC_FILE)
    assert r.returncode != 0, out


def test_mp_failure_in_the_recreate_window_converges_on_rerun(tmp_path):
    old = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "s3:*", "Resource": "*"}]}
    seed_state(tmp_path, roles=["pfx-r"], policies={"pfx-r-scoped": old},
               attached={"pfx-r": [arn("pfx-r-scoped")]})
    r, out, _ = mp(tmp_path, "ensure", ACCT, "pfx", "pfx-r", DOC_FILE, fail="create-policy:pfx-r-scoped")
    assert r.returncode != 0, out
    assert "pfx-r-scoped" not in state(tmp_path)["policies"]  # inside the window: no policy
    r, out, _ = mp(tmp_path, "ensure", ACCT, "pfx", "pfx-r", DOC_FILE)
    assert r.returncode == 0, out
    s = state(tmp_path)
    assert s["policies"]["pfx-r-scoped"]["docs"] == {"v1": XP_DOC}
    assert s["attached"]["pfx-r"] == [arn("pfx-r-scoped")]


def test_mp_delete_detaches_prunes_versions_and_deletes(tmp_path):
    seed_state(tmp_path, roles=["pfx-r"], policies={"pfx-r-scoped": [XP_DOC, XP_DOC, XP_DOC]},
               attached={"pfx-r": [arn("pfx-r-scoped")]})
    r, out, log = mp(tmp_path, "delete", ACCT, "pfx", "pfx-r")
    assert r.returncode == 0, out
    assert state(tmp_path)["policies"] == {}
    assert state(tmp_path)["attached"]["pfx-r"] == []
    assert len(calls_of(log, "delete-policy-version")) == 2


def test_mp_delete_absent_is_a_noop(tmp_path):
    seed_state(tmp_path, roles=["pfx-r"])
    r, out, log = mp(tmp_path, "delete", ACCT, "pfx", "pfx-r")
    assert r.returncode == 0, out
    assert not calls_of(log, "delete-policy")


def test_mp_delete_refuses_a_policy_attached_elsewhere(tmp_path):
    seed_state(tmp_path, roles=["pfx-r", "other"], policies={"pfx-r-scoped": XP_DOC},
               attached={"pfx-r": [arn("pfx-r-scoped")], "other": [arn("pfx-r-scoped")]})
    r, out, _ = mp(tmp_path, "delete", ACCT, "pfx", "pfx-r")
    assert r.returncode != 0 and "DeleteConflict" in out, out
    assert state(tmp_path)["attached"]["other"] == [arn("pfx-r-scoped")]


# The real Taskfile blocks under go-task

@needs_task
def test_bootstrap_default_creates_managed_policy_and_no_admin(tmp_path):
    b = harness(tmp_path)
    r, out, log = run(tmp_path, b, "bootstrap")
    assert r.returncode == 0, out
    assert calls_of(log, "create-role"), log
    attaches = calls_of(log, "attach-role-policy")
    assert not [a for a in attaches if ADMIN_ARN.search(a)], attaches
    assert not calls_of(log, "put-role-policy"), log
    s = state(tmp_path)
    assert s["policies"][HUB_POL]["docs"] == {"v1": XP_DOC}
    assert s["attached"]["hub-crossplane-provider"] == [arn(HUB_POL)]
    pia = [c for c in log if "create-pod-identity-association" in c]
    assert len(pia) == 2 and all("role/hub-crossplane-provider" in c for c in pia), pia


@needs_task
def test_bootstrap_detaches_legacy_administrator_access(tmp_path):
    b = harness(tmp_path)
    r, out, log = run(tmp_path, b, "bootstrap", existing="hub-crossplane-provider",
                      attached="arn:aws:iam::aws:policy/AdministratorAccess")
    assert r.returncode == 0, out
    assert not calls_of(log, "create-role")
    det = [d for d in calls_of(log, "detach-role-policy") if "policy/AdministratorAccess" in d]
    assert len(det) == 1, log


@needs_task
def test_bootstrap_upgrade_from_inline_converges(tmp_path):
    """Re-run on a role an earlier version of this PR gave an inline policy."""
    b = harness(tmp_path)
    seed_state(tmp_path, roles=["hub-crossplane-provider"],
               inline={"hub-crossplane-provider": ["crossplane-provider-scoped"]})
    r, out, log = run(tmp_path, b, "bootstrap")
    assert r.returncode == 0, out
    s = state(tmp_path)
    assert s["inline"]["hub-crossplane-provider"] == []
    assert s["attached"]["hub-crossplane-provider"] == [arn(HUB_POL)]


@needs_task
def test_bootstrap_byo_role_is_used_as_is(tmp_path):
    b = harness(tmp_path)
    byo = f"arn:aws:iam::{ACCT}:role/cfn-crossplane"
    r, out, log = run(tmp_path, b, "bootstrap", f"CROSSPLANE_PROVIDER_ROLE_ARN={byo}", existing="cfn-crossplane")
    assert r.returncode == 0, out
    for verb in ("create-role", "put-role-policy", "attach-role-policy", "detach-role-policy",
                 "create-policy", "get-policy"):
        assert not calls_of(log, verb), (verb, log)
    pia = [c for c in log if "create-pod-identity-association" in c]
    assert len(pia) == 2 and all(byo in c for c in pia), pia


@needs_task
@pytest.mark.parametrize("byo,existing,msg", [
    ("arn:aws:iam::222222222222:role/cfn-crossplane", "cfn-crossplane", "is not an IAM role ARN in account"),
    (f"arn:aws:iam::{ACCT}:role/missing", "", "does not exist"),
])
def test_bootstrap_byo_role_is_validated(tmp_path, byo, existing, msg):
    b = harness(tmp_path)
    r, out, log = run(tmp_path, b, "bootstrap", f"CROSSPLANE_PROVIDER_ROLE_ARN={byo}", existing=existing)
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
    assert any("AmazonS3FullAccess" in a for a in attaches)  # other services unchanged
    s = state(tmp_path)
    assert s["attached"]["pfx-cluster-mgmt-iam"] == [arn(MGMT_POL)], s["attached"]
    assert s["policies"][MGMT_POL]["docs"] == {"v1": MGMT_DOC}
    assert not [p for p in calls_of(log, "put-role-policy") if "pfx-cluster-mgmt-iam " in p + " "], log


@needs_task
def test_mgmt_rerun_on_existing_roles_without_policy_converges(tmp_path):
    """A failed earlier run left the 8 roles with no scoped policy: the re-run creates it."""
    b = harness(tmp_path)
    roles = [f"pfx-cluster-mgmt-{s}" for s in ("ec2", "eks", "iam", "ecr", "s3", "dynamodb", "secretsmanager", "rds")]
    seed_state(tmp_path, roles=roles)
    r, out, log = run(tmp_path, b, "mgmt")
    assert r.returncode == 0, out
    assert not calls_of(log, "create-role"), log
    assert state(tmp_path)["attached"]["pfx-cluster-mgmt-iam"] == [arn(MGMT_POL)]
    # and a second run is a no-op for the policy
    r, out, log2 = run(tmp_path, b, "mgmt")
    assert r.returncode == 0, out
    new = log2[len(log):]
    assert not calls_of(new, "create-policy") and not calls_of(new, "delete-policy"), new


@needs_task
def test_mgmt_detaches_legacy_iam_full_access(tmp_path):
    b = harness(tmp_path)
    r, out, log = run(tmp_path, b, "mgmt", existing="pfx-cluster-mgmt-iam",
                      attached="arn:aws:iam::aws:policy/IAMFullAccess")
    assert r.returncode == 0, out
    det = [d for d in calls_of(log, "detach-role-policy") if "IAMFullAccess" in d]
    assert len(det) == 1 and "pfx-cluster-mgmt-iam" in det[0], log


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
    assert not calls_of(log, "create-policy"), log
    assert len(calls_of(log, "create-role")) == 6, log
    # rds is not BYO here, so its inline KMS policy is still put
    assert [p for p in calls_of(log, "put-role-policy") if "pfx-cluster-mgmt-rds" in p]


@needs_task
@pytest.mark.parametrize("byo,existing,msg", [
    (f"arn:aws:iam::{ACCT}:role/cfn-iam", "cfn-iam", "must be arn:aws:iam::"),
    (f"arn:aws:iam::{ACCT}:role/pfx-cluster-mgmt-iam", "", "does not exist"),
])
def test_mgmt_byo_roles_are_validated(tmp_path, byo, existing, msg):
    cfg = f"hub:\n  clusterName: hub\n  iam:\n    clusterMgmtRoleArns:\n      iam: {byo}\n"
    b = harness(tmp_path, cfg)
    r, out, log = run(tmp_path, b, "mgmt", existing=existing)
    assert r.returncode != 0 and msg in out, out
    assert not calls_of(log, "create-role"), log


@needs_task
@pytest.mark.parametrize("fail", [f"create-policy:{HUB_POL}", "attach-role-policy:hub-crossplane-provider"])
def test_bootstrap_policy_failure_is_fatal(tmp_path, fail):
    b = harness(tmp_path)
    r, out, log = run(tmp_path, b, "bootstrap", fail=fail)
    assert r.returncode != 0, out
    assert not [c for c in log if "create-pod-identity-association" in c], log


@needs_task
def test_bootstrap_byo_role_read_from_config(tmp_path):
    """The real `sh: yq` global var reads hub.iam.crossplaneProviderRoleArn from config.local.yaml."""
    byo = f"arn:aws:iam::{ACCT}:role/cfn-crossplane"
    cfg = f"hub:\n  clusterName: hub\n  iam:\n    crossplaneProviderRoleArn: {byo}\n"
    b = harness(tmp_path, cfg, real_byo_var=True)
    r, out, log = run(tmp_path, b, "bootstrap", existing="cfn-crossplane")
    assert r.returncode == 0, out
    assert not calls_of(log, "create-role") and not calls_of(log, "create-policy"), log
    pia = [c for c in log if "create-pod-identity-association" in c]
    assert len(pia) == 2 and all(byo in c for c in pia), pia


@needs_task
@pytest.mark.parametrize("fail", [f"create-policy:{MGMT_POL}", "attach-role-policy:pfx-cluster-mgmt-iam",
                                  "delete-role-policy:pfx-cluster-mgmt-iam"])
def test_mgmt_policy_failure_is_fatal(tmp_path, fail):
    b = harness(tmp_path)
    seed_state(tmp_path, inline={"pfx-cluster-mgmt-iam": ["cluster-mgmt-iam-scoped"]})
    r, out, log = run(tmp_path, b, "mgmt", fail=fail)
    assert r.returncode != 0, out


SPOKE_ROLES = ["spoke1-CrossplaneEKSProviderRole", "spoke1-CrossplaneIAMProviderRole"]


@needs_task
@pytest.mark.parametrize("taskfile", [KRO, XP])
def test_seed_provider_identity_creates_managed_policies(tmp_path, taskfile):
    b = harness(tmp_path, taskfile=taskfile)
    r, out, log = run(tmp_path, b, "seed")
    assert r.returncode == 0, out
    assert not calls_of(log, "put-role-policy"), log
    s = state(tmp_path)
    for role in SPOKE_ROLES:
        assert s["attached"][role] == [arn(f"pfx-{role}-scoped")], s["attached"]
        assert s["policies"][f"pfx-{role}-scoped"]["docs"] == {"v1": XP_DOC}
    assert not [c for c in log if "--role-name hub-" in c], log  # the hub is excluded


@needs_task
@pytest.mark.parametrize("taskfile", [KRO, XP])
def test_seed_provider_identity_policy_failure_is_fatal(tmp_path, taskfile):
    b = harness(tmp_path, taskfile=taskfile)
    r, out, log = run(tmp_path, b, "seed", fail="create-policy:pfx-spoke1-CrossplaneIAMProviderRole-scoped")
    assert r.returncode != 0, out
    assert not [c for c in log if "create-pod-identity-association" in c], log


@needs_task
def test_kind_crossplane_mgmt_creates_managed_policy_and_no_admin(tmp_path):
    b = harness(tmp_path, taskfile=XP)
    seed_state(tmp_path, inline={"pfx-cluster-mgmt-iam": ["cluster-mgmt-iam-scoped"]})
    r, out, log = run(tmp_path, b, "mgmt")
    assert r.returncode == 0, out
    attaches = calls_of(log, "attach-role-policy")
    assert not [a for a in attaches if ADMIN_ARN.search(a)], attaches
    s = state(tmp_path)
    assert s["attached"]["pfx-cluster-mgmt-iam"] == [arn(MGMT_POL)]
    assert s["inline"]["pfx-cluster-mgmt-iam"] == []  # legacy inline removed


@needs_task
def test_kind_crossplane_mgmt_policy_failure_is_fatal(tmp_path):
    b = harness(tmp_path, taskfile=XP)
    r, out, log = run(tmp_path, b, "mgmt", fail=f"create-policy:{MGMT_POL}")
    assert r.returncode != 0, out


# Teardown: kind-kro-ack destroy step 6b deletes the scoped managed policies of the roles
# it deletes (detach, non-default versions, delete), before the role itself.

@needs_task
def test_destroy_sweep_deletes_scoped_managed_policies(tmp_path):
    b = harness(tmp_path)
    roles = ["pfx-cluster-mgmt-iam", "pfx-hub-crossplane-provider", "pfx-spoke1-CrossplaneIAMProviderRole"]
    pols = {f"{r}-scoped": [XP_DOC, XP_DOC] for r in roles}
    seed_state(tmp_path, roles=roles, policies=pols, attached={r: [arn(f"{r}-scoped")] for r in roles})
    r, out, log = run(tmp_path, b, "sweep", stub_python=True)
    assert r.returncode == 0, out
    s = state(tmp_path)
    assert s["policies"] == {}, s["policies"]
    for role in roles:
        assert s["attached"][role] == []
        order = [c.split()[2] for c in log if (f"policy/{role}-scoped" in c) or (f"--role-name {role}" in c and " delete-role " in c + " ")]
        assert "delete-policy" in order and order.index("delete-policy") < order.index("delete-role"), order
        assert order.index("delete-policy-version") < order.index("delete-policy"), order
    assert "iam-scoped-policy(6b)" not in ((tmp_path / "private" / "destroy-sweep-failures").read_text()
                                           if (tmp_path / "private" / "destroy-sweep-failures").exists() else "")


@needs_task
def test_destroy_sweep_records_a_failed_scoped_policy_delete(tmp_path):
    b = harness(tmp_path)
    seed_state(tmp_path, roles=["pfx-cluster-mgmt-iam"], policies={MGMT_POL: MGMT_DOC},
               attached={"pfx-cluster-mgmt-iam": [arn(MGMT_POL)]})
    r, out, log = run(tmp_path, b, "sweep", stub_python=True, fail=f"delete-policy:{MGMT_POL}")
    assert "could not delete the scoped managed policy of pfx-cluster-mgmt-iam" in out, out
    assert "iam-scoped-policy(6b)" in (tmp_path / "private" / "destroy-sweep-failures").read_text()


def test_destroy_role_loop_deletes_the_scoped_policy_before_the_role():
    body = block("destroy", destroy_index())
    sixb = body[body.index("6b. ALL remaining"):body.index("6b2.")]
    assert sixb.index('managed-policy.sh" delete') < sixb.index("aws iam delete-role --role-name"), sixb


@needs_task
def test_kind_crossplane_seed_upgrade_from_inline(tmp_path):
    b = harness(tmp_path, taskfile=XP)
    seed_state(tmp_path, roles=SPOKE_ROLES, inline={r: ["crossplane-provider-scoped"] for r in SPOKE_ROLES})
    r, out, log = run(tmp_path, b, "seed")
    assert r.returncode == 0, out
    assert all(state(tmp_path)["inline"][r] == [] for r in SPOKE_ROLES)


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


@pytest.mark.skipif(not shutil.which("shellcheck"), reason="shellcheck not on PATH")
def test_managed_policy_script_shellcheck():
    r = subprocess.run(["shellcheck", "-s", "sh", MP], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout
