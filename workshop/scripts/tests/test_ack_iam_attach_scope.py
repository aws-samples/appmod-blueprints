"""The ACK IAM identities may attach only an allowlist of AWS managed policies.

Least-privilege scoping of the AWS managed policy attach path on the identities the ACK IAM
controller reconciles under. In kind-kro-ack the IAMRoleSelectors
(gitops/addons/charts/multi-acct/templates/iam-role-selectors.yaml,
gitops/abstractions/kro/kro-clusters/templates/iam-role-selectors.yaml) route iam.services.k8s.aws
resources to `<prefix>-cluster-mgmt-iam`; a namespace no selector covers falls back to the
cluster's `<cluster>-ack-capability-role` (ManageIRSARoles), which the kind-crossplane
platform-cluster composition also builds.

This test asserts the same `DenyAttachAwsManagedPolicyOutsideAllowlist` statement, with one
canonical allowlist, on:

1. cluster-providers/common/iam/cluster-mgmt-iam-policy.json
2. the ManageIRSARoles inline policy in the eks RGD, both CEL branches
   (gitops/addons/charts/kro/resource-groups/manifests/eks/rg-eks.yaml)
3. the ManageIRSARoles RolePolicy fmt in the platform-cluster composition
   (gitops/abstractions/crossplane/platform-cluster/templates/composition.yaml)
4. the cross-account cluster-mgmt-iam role built by scripts/create-cross-account-roles.sh
5. the kind-crossplane ack-capability-flow-d-microvm RolePolicy
   (cluster-providers/kind-crossplane/claims/ack-capability-role.yaml)

It mirrors the Crossplane provider-aws-iam guard
(cluster-providers/common/iam/crossplane-provider-policy.json, test_crossplane_provider_scope.py).
Inline-policy content and customer-managed policy attach are out of scope here.

Run:  python -m pytest workshop/scripts/tests/test_ack_iam_attach_scope.py -q
"""
import fnmatch
import json
import os
import re

import pytest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
RG_EKS = os.path.join(REPO, "gitops", "addons", "charts", "kro", "resource-groups",
                      "manifests", "eks", "rg-eks.yaml")
COMPOSITION = os.path.join(REPO, "gitops", "abstractions", "crossplane", "platform-cluster",
                           "templates", "composition.yaml")
CLUSTER_MGMT_IAM = os.path.join(REPO, "cluster-providers", "common", "iam",
                                "cluster-mgmt-iam-policy.json")
# Repo-relative globs of the dirs whose iam.services.k8s.aws CRs are reconciled under an ACK
# IAM identity (cluster-mgmt-iam, or the fallback capability role): the kro RGDs, and the
# ack-pod-identity chart, whose Role template renders identities[*].managedPolicyArns into
# `policies:`, with the per-environment overlays that feed it.
ACK_RGD_DIRS = ["gitops/addons/charts/kro",
                "gitops/abstractions/kro",
                "gitops/addons/charts/ack-pod-identity",
                "gitops/overlays/environments/*/ack-pod-identities"]
ACCT = "111111111111"
ADMIN_LIKE = ["AdministratorAccess", "PowerUserAccess", "IAMFullAccess"]

CEL_VARS = {
    '" + schema.spec.aws_partition + "': "aws",
    '" + schema.spec.accountId + "': ACCT,
    '" + schema.spec.resourcePrefix + "': "peeks",
    '" + schema.spec.name + "': "peeks-hub",
    '" + schema.spec.region + "': "us-west-2",
}


# ------------------------------------------------------------------ document loaders

def _cluster_mgmt_iam_doc():
    return json.load(open(CLUSTER_MGMT_IAM))


def _rg_eks_manageirsa_docs():
    s = open(RG_EKS).read()
    for a, b in CEL_VARS.items():
        s = s.replace(a, b)
    return [json.loads(json.loads('"' + m.group(1) + '"'))
            for m in re.finditer(r'"ManageIRSARoles":\s*"((?:[^"\\]|\\.)*)"', s)]


def _composition_manageirsa_doc():
    c = open(COMPOSITION).read()
    m = re.search(r"fmt: '(\{\"Version\":\"2012-10-17\",\"Statement\":\[\{\"Effect\":\"Allow\","
                  r"\"Action\":\[\"iam:GetRole\".*?\}\]\})'", c, re.S)
    assert m, "composition ManageIRSARoles fmt not found"
    # fmt has two %s, in CombineFromComposite order: accountId, then clusterName.
    return json.loads(m.group(1) % (ACCT, "peeks-hub"))


def _microvm_rolepolicy_doc():
    import yaml
    path = os.path.join(REPO, "cluster-providers", "kind-crossplane", "claims",
                        "ack-capability-role.yaml")
    for d in yaml.safe_load_all(open(path)):
        if d and d.get("kind") == "RolePolicy" and d["metadata"]["name"] == "ack-capability-flow-d-microvm":
            return json.loads(d["spec"]["forProvider"]["policy"])
    raise AssertionError("ack-capability-flow-d-microvm RolePolicy not found")


def all_sinks():
    """(label, policy document, a role ARN governed by its Allow) for every ACK IAM identity."""
    docs = _rg_eks_manageirsa_docs()
    assert len(docs) == 2, f"expected two rg-eks CEL branches, found {len(docs)}"
    assert docs[0] == docs[1], "rg-eks ManageIRSARoles differs between CEL branches"
    return [
        ("cluster-mgmt-iam", _cluster_mgmt_iam_doc(), f"arn:aws:iam::{ACCT}:role/anything"),
        ("rg-eks capability role", docs[0], f"arn:aws:iam::{ACCT}:role/peeks-hub-x"),
        ("composition capability role", _composition_manageirsa_doc(), f"arn:aws:iam::{ACCT}:role/peeks-hub-x"),
        ("kind-crossplane microvm RolePolicy", _microvm_rolepolicy_doc(),
         f"arn:aws:iam::{ACCT}:role/x-microvm-build"),
    ]


SINKS = all_sinks()
SINK_IDS = [s[0] for s in SINKS]


def deny(doc):
    return next(s for s in doc["Statement"] if s.get("Sid") == "DenyAttachAwsManagedPolicyOutsideAllowlist")


def allowlist(doc):
    v = deny(doc)["Condition"]["ArnNotLike"]["iam:PolicyARN"]
    return v if isinstance(v, list) else [v]


# ------------------------------------------------------------------ IAM evaluation model

# shortcut: same local model as test_crossplane_provider_scope.py (Allow/Deny, wildcard Action
# and Resource, Arn*/String* operators, negated true when no value matches). fnmatch lets `*`
# cross `:`; harmless here. Not AWS's evaluator; upgrade to aws iam simulate-custom-policy live.
def _as_list(v):
    return v if isinstance(v, list) else [v]


def _cond_ok(cond, ctx):
    for op, kv in cond.items():
        neg = "Not" in op
        for key, vals in kv.items():
            v = ctx.get(key)
            hit = v is not None and any(fnmatch.fnmatchcase(v, p) for p in _as_list(vals))
            if hit == neg:
                return False
    return True


def _matches(st, action, resource, ctx):
    if not any(fnmatch.fnmatchcase(action.lower(), a.lower()) for a in _as_list(st["Action"])):
        return False
    if not any(fnmatch.fnmatchcase(resource, r) for r in _as_list(st["Resource"])):
        return False
    return _cond_ok(st.get("Condition", {}), ctx)


def allowed(doc, action, resource, ctx=None):
    ctx = ctx or {}
    sts = [s for s in doc["Statement"] if _matches(s, action, resource, ctx)]
    if any(s["Effect"] == "Deny" for s in sts):
        return False
    return any(s["Effect"] == "Allow" for s in sts)


def attach(doc, policy_arn, role):
    return allowed(doc, "iam:AttachRolePolicy", role, {"iam:PolicyARN": policy_arn})


def aws_managed(name):
    return f"arn:aws:iam::aws:policy/{name}"


# ------------------------------------------------------------------ one canonical allowlist

def test_all_sinks_share_one_allowlist():
    lists = [tuple(allowlist(doc)) for _, doc, _ in SINKS]
    assert len(set(lists)) == 1, "the three ACK IAM identities carry different allowlists"
    assert len(lists[0]) == 25, f"expected 25 allowlisted policies, got {len(lists[0])}"


def test_allowlist_entries_are_aws_managed_and_non_admin():
    for arn in allowlist(SINKS[0][1]):
        assert re.fullmatch(r"arn:\*:iam::aws:policy/(service-role/)?[\w+=,.@/-]+", arn), arn
        assert not any(arn.endswith("/" + a) for a in ADMIN_LIKE), arn


# ------------------------------------------------------------------ the deny, per sink

@pytest.mark.parametrize("label,doc,role", SINKS, ids=SINK_IDS)
def test_deny_present(label, doc, role):
    assert deny(doc)["Effect"] == "Deny"


@pytest.mark.parametrize("label,doc,role", SINKS, ids=SINK_IDS)
@pytest.mark.parametrize("name", ADMIN_LIKE)
@pytest.mark.parametrize("partition", ["aws", "aws-us-gov", "aws-cn"])
def test_admin_like_attach_denied(label, doc, role, name, partition):
    assert not attach(doc, f"arn:{partition}:iam::aws:policy/{name}", role)


@pytest.mark.parametrize("label,doc,role", SINKS, ids=SINK_IDS)
@pytest.mark.parametrize("name", ["ReadOnlyAccess", "AdministratorAccess-Amplify",
                                  "AWSLambda_FullAccess", "AmazonVPCFullAccess",
                                  "job-function/SystemAdministrator"])
def test_unlisted_aws_managed_attach_denied(label, doc, role, name):
    """Allowlist, not denylist: any AWS managed policy outside the allowlist is refused."""
    assert not attach(doc, aws_managed(name), role)


@pytest.mark.parametrize("label,doc,role", SINKS, ids=SINK_IDS)
def test_allowlisted_attach_allowed(label, doc, role):
    for arn in allowlist(doc):
        assert attach(doc, arn.replace("arn:*:", "arn:aws:"), role), arn


@pytest.mark.parametrize("label,doc,role", SINKS, ids=SINK_IDS)
def test_customer_managed_and_scoped_attach_not_denied(label, doc, role):
    """The Deny gates on ArnLike arn:*:iam::aws:policy/* (AWS managed only), so the
    customer-managed crossplane-provider-scoped policy the platform attaches is untouched."""
    scoped = f"arn:aws:iam::{ACCT}:policy/peeks-hub-crossplane-provider-scoped"
    assert attach(doc, scoped, role)


@pytest.mark.parametrize("label,doc,role", SINKS, ids=SINK_IDS)
def test_controller_keeps_the_iam_writes_it_needs(label, doc, role):
    """CreateRole / PutRolePolicy / DetachRolePolicy / GetRole on the identity's own scope must
    still work \u2014 the Deny only narrows AttachRolePolicy of AWS managed policies."""
    assert allowed(doc, "iam:CreateRole", role)
    assert allowed(doc, "iam:PutRolePolicy", role)
    assert allowed(doc, "iam:DetachRolePolicy", role, {"iam:PolicyARN": aws_managed("AdministratorAccess")})
    assert allowed(doc, "iam:GetRole", role)


def test_cluster_mgmt_iam_deny_covers_user_and_group_attach():
    """cluster-mgmt-iam holds iam:* (so it can attach to users/groups); the Deny covers all
    three attach verbs, like the Crossplane guard."""
    d = deny(_cluster_mgmt_iam_doc())
    assert set(_as_list(d["Action"])) >= {"iam:AttachRolePolicy", "iam:AttachUserPolicy", "iam:AttachGroupPolicy"}
    doc = _cluster_mgmt_iam_doc()
    assert not allowed(doc, "iam:AttachUserPolicy", f"arn:aws:iam::{ACCT}:user/x",
                       {"iam:PolicyARN": aws_managed("AdministratorAccess")})
    assert not allowed(doc, "iam:AttachGroupPolicy", f"arn:aws:iam::{ACCT}:group/x",
                       {"iam:PolicyARN": aws_managed("AdministratorAccess")})


# ------------------------------------------------------------------ coverage guard

# Every AWS managed policy attached via an ACK iam CR (a `policies:` entry or a
# RolePolicyAttachment target) must be allowlisted, or the attach is AccessDenied at install.
# The regex matches a literal partition (arn:aws:...), a wildcard (arn:*:...) and a CEL/Helm
# variable partition (arn:${...}:...) so a parameterised ARN is not missed (the earlier scanner
# only matched the literal arn:aws: form). cluster-access-policy ARNs are EKS access entries,
# not iam:AttachRolePolicy, and are excluded.
ARN = re.compile(r"arn:(?:[^:\"'\s]*|\$\{[^}]+\}):iam::aws:policy/(service-role/)?([\w+=,.@-]+)")


def _ack_rgd_roots(repo):
    import glob
    return [d for pat in ACK_RGD_DIRS for d in sorted(glob.glob(os.path.join(repo, pat)))]


def test_ack_rgd_dirs_exist():
    roots = _ack_rgd_roots(REPO)
    for pat in ACK_RGD_DIRS:
        assert any(fnmatch.fnmatchcase(os.path.relpath(r, REPO), pat) for r in roots), pat


def ack_attached_aws_managed(repo=REPO):
    names = set()
    for root in _ack_rgd_roots(repo):
        for dp, _, fs in os.walk(root):
            for fn in fs:
                if not fn.endswith((".yaml", ".yml", ".tpl")):
                    continue
                for raw in open(os.path.join(dp, fn), errors="replace"):
                    line = raw.split("#", 1)[0]
                    # The Deny statement carries the allowlist itself; scanning it would make
                    # every allowlist entry look "attached".
                    if "DenyAttachAwsManagedPolicyOutsideAllowlist" in line:
                        continue
                    if "cluster-access-policy" in line:
                        continue
                    for m in ARN.finditer(line):
                        names.add((m.group(1) or "") + m.group(2))
    return names


def test_allowlist_covers_every_ack_attached_aws_policy():
    allow = {a.split("policy/", 1)[1] for a in allowlist(SINKS[0][1])}
    attached = ack_attached_aws_managed()
    assert attached, "no AWS managed attachments found in the ACK RGD dirs \u2014 scan broke"
    missing = sorted(attached - allow)
    assert not missing, ("AWS managed policies attached via ACK IAM but not allowlisted:\n"
                         + "\n".join(missing))


def test_scanner_matches_partition_variable_form():
    """Regression for the earlier scanner blind spot: a partition-variable ARN must be seen."""
    sample = 'policyArn: "arn:${schema.spec.aws_partition}:iam::aws:policy/AmazonS3FullAccess"'
    m = ARN.search(sample.split("#", 1)[0])
    assert m and m.group(2) == "AmazonS3FullAccess"


ACK_POD_IDENTITY_VALUES = [
    "gitops/addons/charts/ack-pod-identity/values.yaml",
    "gitops/overlays/environments/dev/ack-pod-identities/values.yaml",
    "gitops/overlays/environments/prod/ack-pod-identities/values.yaml",
]


@pytest.mark.parametrize("rel", ACK_POD_IDENTITY_VALUES)
def test_scanner_sees_ack_pod_identity_managed_policy_arns(tmp_path, rel):
    """ack-pod-identity renders managedPolicyArns into the ACK Role `policies:`, so an AWS
    managed policy added there is attached by cluster-mgmt-iam and must be allowlisted. Copy the
    file into a scratch tree, add such an entry, and check the coverage scan sees it."""
    import shutil
    dst = tmp_path / rel
    dst.parent.mkdir(parents=True)
    shutil.copy(os.path.join(REPO, rel), dst)
    with open(dst, "a") as f:
        f.write("\n  zz-coverage-probe:\n    enabled: true\n    managedPolicyArns:\n"
                "      - arn:aws:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy\n")
    assert "service-role/AmazonEBSCSIDriverPolicy" in ack_attached_aws_managed(str(tmp_path))


# Allowlist entries no ACK CR in this repo attaches: shared with the Crossplane guard list or kept
# for other ACK consumers (for example OAP). Listed explicitly so a NEW unused entry fails the test.
# shortcut: some are broad (S3/EC2/RDS/Prometheus FullAccess); shrink once nothing outside this repo
# needs them, see the PR "Residual risk" section.
UNUSED_BY_THIS_REPO_ACK = {
    "AWSGrafanaAccountAdministrator", "AWSXrayReadOnlyAccess", "AmazonDynamoDBFullAccess_v2",
    "AmazonEC2ContainerRegistryReadOnly", "AmazonEC2FullAccess", "AmazonEKSWorkerNodePolicy",
    "AmazonEKS_CNI_Policy", "AmazonPrometheusFullAccess", "AmazonPrometheusQueryAccess",
    "AmazonRDSFullAccess", "AmazonS3FullAccess", "service-role/AmazonGrafanaCloudWatchAccess",
}


def test_allowlist_has_no_new_unused_entry():
    allow = {a.split("policy/", 1)[1] for a in allowlist(SINKS[0][1])}
    unused = allow - ack_attached_aws_managed()
    assert unused == UNUSED_BY_THIS_REPO_ACK, (
        f"allowlist entries not attached by any ACK CR: {sorted(unused)}")


def _run_cross_account_script(tmp_path, *, with_jq=True, policy_file=True, strip_deny=False):
    """Run create-cross-account-roles.sh --target-only against a fake `aws`; return
    (returncode, {policy-name: document}, aws-call-log)."""
    import shutil
    import subprocess
    bindir = tmp_path / "bin"
    bindir.mkdir()
    out = tmp_path / "out"
    out.mkdir()
    log = tmp_path / "calls.log"
    fake = bindir / "aws"
    fake.write_text(
        "#!/usr/bin/env bash\n"
        "echo \"$*\" >> \"$AWSLOG\"\n"
        "case \"$1 $2\" in\n"
        "  'sts get-caller-identity') echo 222222222222;;\n"
        "  'iam get-role') exit 254;;\n"
        "  'iam put-role-policy')\n"
        "    prev=; pn=; doc=\n"
        "    for a in \"$@\"; do [ \"$prev\" = --policy-name ] && pn=$a; "
        "[ \"$prev\" = --policy-document ] && doc=$a; prev=$a; done\n"
        "    printf '%s' \"$doc\" > \"$AWSOUT/$pn.json\";;\n"
        "esac\n")
    fake.chmod(0o755)
    tree = tmp_path / "tree"
    (tree / "scripts").mkdir(parents=True)
    shutil.copy(os.path.join(REPO, "scripts", "create-cross-account-roles.sh"), tree / "scripts")
    if policy_file:
        d = tree / "cluster-providers" / "common" / "iam"
        d.mkdir(parents=True)
        shutil.copy(os.path.join(REPO, "cluster-providers", "common", "iam",
                                 "cluster-mgmt-iam-policy.json"), d)
        if strip_deny:
            f = d / "cluster-mgmt-iam-policy.json"
            doc = json.loads(f.read_text())
            doc["Statement"] = [x for x in doc["Statement"] if x.get("Effect") != "Deny"]
            f.write_text(json.dumps(doc))
    path = str(bindir) + os.pathsep + os.environ["PATH"]
    if not with_jq:
        tools = tmp_path / "tools"
        tools.mkdir()
        for t in ("bash", "env", "dirname", "cat", "cut", "grep", "sed", "mkdir"):
            found = shutil.which(t)
            if found:
                os.symlink(found, tools / t)
        path = str(bindir) + os.pathsep + str(tools)
    env = {"PATH": path, "AWSLOG": str(log), "AWSOUT": str(out),
           "HUB_ACCOUNT_ID": "111111111111", "RESOURCE_PREFIX": "peeks", "HOME": str(tmp_path)}
    r = subprocess.run([shutil.which("bash") or "/bin/bash",
                        str(tree / "scripts" / "create-cross-account-roles.sh"), "--target-only"],
                       cwd=str(tmp_path), env=env, capture_output=True, text=True)
    docs = {f.name[:-5]: f.read_text() for f in out.iterdir()}
    return r.returncode, docs, log.read_text() if log.exists() else ""


def test_cross_account_iam_role_gets_the_same_deny(tmp_path):
    """The iam role created in a cross-account target account gets Allow iam:* plus the exact
    Deny statement of cluster-mgmt-iam-policy.json; the other roles keep their own documents."""
    rc, docs, _ = _run_cross_account_script(tmp_path)
    assert rc == 0, "script must complete (the rds role has no policy to put)"
    iam = json.loads(docs["iam-permissions"])
    assert iam["Statement"][0] == {"Effect": "Allow", "Action": ["iam:*"], "Resource": "*"}
    shared = json.load(open(os.path.join(REPO, "cluster-providers", "common", "iam",
                                         "cluster-mgmt-iam-policy.json")))
    want = [s for s in shared["Statement"]
            if s.get("Sid") == "DenyAttachAwsManagedPolicyOutsideAllowlist"]
    assert len(want) == 1 and iam["Statement"][1:] == want
    for svc in ("ec2", "eks", "ecr", "s3", "dynamodb", "secretsmanager"):
        assert all(s["Effect"] == "Allow"
                   for s in json.loads(docs[f"{svc}-permissions"])["Statement"])


def test_cross_account_script_fails_closed_without_jq_or_policy(tmp_path):
    for sub, kw in (("nojq", {"with_jq": False}), ("nofile", {"policy_file": False}),
                    ("nodeny", {"strip_deny": True})):
        d = tmp_path / sub
        d.mkdir()
        rc, docs, log = _run_cross_account_script(d, **kw)
        assert rc != 0
        assert "put-role-policy" not in log and not docs, sub


def _run_verify(tmp_path, doc, get_policy_denied=False):
    """Run mgmt-roles-verify.sh for the iam role against a fake aws; return (rc, stdout, stderr)."""
    import shutil
    import subprocess
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake = bindir / "aws"
    fake.write_text(
        "#!/bin/sh\n"
        "case \"$1 $2\" in\n"
        "  'iam get-role') echo peeks-cluster-mgmt-iam;;\n"
        "  'iam list-attached-role-policies') echo arn:aws:iam::111111111111:policy/peeks-cluster-mgmt-iam-scoped;;\n"
        "  'iam get-policy') [ -n \"$DENY\" ] && { echo AccessDenied >&2; exit 254; }; echo v1;;\n"
        "  'iam get-policy-version') printf '%s' \"$DOC\";;\n"
        "esac\n")
    fake.chmod(0o755)
    script = os.path.join(REPO, "cluster-providers", "common", "scripts", "mgmt-roles-verify.sh")
    env = {"PATH": str(bindir) + os.pathsep + os.environ["PATH"], "RESOURCE_PREFIX": "peeks",
           "MGMT_SERVICES": "iam", "DOC": doc, "HOME": str(tmp_path),
           "DENY": "1" if get_policy_denied else ""}
    r = subprocess.run(["sh", script], env=env, capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


def test_external_verify_warns_when_scoped_policy_has_no_deny(tmp_path):
    rc, out, err = _run_verify(tmp_path, json.dumps(
        {"Statement": [{"Effect": "Allow", "Action": "iam:*", "Resource": "*"}]}))
    assert rc == 0 and "ready" not in out
    assert "DenyAttachAwsManagedPolicyOutsideAllowlist" in err and "privileged:pre" in err


def test_external_verify_silent_when_scoped_policy_has_the_deny(tmp_path):
    shared = open(CLUSTER_MGMT_IAM).read()
    rc, out, err = _run_verify(tmp_path, shared)
    assert rc == 0 and "DenyAttachAwsManagedPolicyOutsideAllowlist" not in err


def test_external_verify_reports_unreadable_scoped_policy_separately(tmp_path):
    """A failed scoped-policy read is a missing read permission, not a missing Deny:
    re-running privileged:pre cannot clear it, so it gets its own message."""
    rc, out, err = _run_verify(tmp_path, open(CLUSTER_MGMT_IAM).read(), get_policy_denied=True)
    assert rc == 0
    assert "could not read the scoped policy" in err
    assert "iam:GetPolicy" in err and "iam:GetPolicyVersion" in err
    assert "has no DenyAttachAwsManagedPolicyOutsideAllowlist" not in err


def test_external_verify_read_set_documented():
    """The reads the verify makes are listed in the script header and the install doc."""
    script = open(os.path.join(REPO, "cluster-providers", "common", "scripts",
                               "mgmt-roles-verify.sh")).read()
    header = script.split("set -eu", 1)[0]
    doc = open(os.path.join(REPO, "docs", "install", "privileged-steps.md")).read()
    section = doc.split("## IAM the install host still needs in external mode", 1)[1]
    for action in ("GetRole", "ListAttachedRolePolicies", "GetRolePolicy", "GetPolicy",
                   "GetPolicyVersion"):
        assert action in header, action
        assert f"iam:{action}" in section, action
