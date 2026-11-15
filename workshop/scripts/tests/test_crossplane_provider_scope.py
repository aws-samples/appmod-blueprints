"""The Crossplane provider identity cannot hand out AdministratorAccess, and crossplane-base
no longer asks it to.

Follow-up to the scoped <cluster>-crossplane-provider policy. That policy keeps iam:* on
role/* and policy/*, so on its own provider-aws-iam could attach any AWS managed policy,
AdministratorAccess included, to any role. Two changes:

(c) crossplane-base attaches a per-provider managed policy (values.yaml providers.<p>.policyArns)
    to each provider role, not AdministratorAccess.
(a) common/iam/crossplane-provider-policy.json (and its rg-eks inline copy) denies
    iam:AttachRolePolicy of any AWS managed policy outside an explicit allowlist (iam:PolicyARN),
    and denies editing or deleting the provider scoped policies (*-crossplane-provider-scoped,
    *ProviderRole-scoped).

The privilege ceiling is unchanged. Pinned below as still allowed so a reader sees the gap:
customer-managed policies (CreatePolicy + attach), inline PutRolePolicy, CreatePolicyVersion
on other policies, UpdateAssumeRolePolicy, CreateRole, the boundary operations, PassRole, eks:*,
and detaching the scoped policy.

kind-crossplane: its hub iam/eks provider roles come from a direct render of crossplane-base
in crossplane:claims (and the same render in destroy). Those renders are tested here too.

Run:  python -m pytest workshop/scripts/tests/test_crossplane_provider_scope.py -q
"""
import copy
import fnmatch
import json
import os
import re
import shutil
import subprocess

import pytest

yaml = pytest.importorskip("yaml")

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
POLICY = os.path.join(REPO, "cluster-providers", "common", "iam", "crossplane-provider-policy.json")
CHART = os.path.join(REPO, "gitops", "addons", "charts", "crossplane-base")
REGISTRY = os.path.join(REPO, "gitops", "addons", "registry", "platform.yaml")
ACCT = "111111111111"
ROLE = f"arn:aws:iam::{ACCT}:role/peeks-hub-CrossplaneEC2ProviderRole"
ADMIN_LIKE = ["AdministratorAccess", "PowerUserAccess", "IAMFullAccess"]


def load_doc():
    with open(POLICY) as f:
        return json.load(f)


def as_list(v):
    return v if isinstance(v, list) else [v]


# shortcut: a model of IAM evaluation for this one document (Allow/Deny, wildcard Action and
# Resource, the Arn*/String* condition operators it uses, AND across operators, OR across
# values, negated operators true when no value matches). Not AWS's evaluator: no SCPs,
# boundaries, NotAction or IfExists. fnmatch on whole ARNs lets `*` cross `:`, unlike ArnLike;
# harmless for the patterns in this document. Upgrade to `aws iam simulate-custom-policy` in a
# live test.
def _cond_ok(cond, ctx):
    for op, kv in cond.items():
        neg = "Not" in op
        for key, vals in kv.items():
            v = ctx.get(key)
            hit = v is not None and any(fnmatch.fnmatchcase(v, p) for p in as_list(vals))
            if hit == neg:
                return False
    return True


def _matches(st, action, resource, ctx):
    if not any(fnmatch.fnmatchcase(action.lower(), a.lower()) for a in as_list(st["Action"])):
        return False
    if not any(fnmatch.fnmatchcase(resource, r) for r in as_list(st["Resource"])):
        return False
    return _cond_ok(st.get("Condition", {}), ctx)


def allowed(doc, action, resource, ctx=None):
    ctx = ctx or {}
    sts = [s for s in doc["Statement"] if _matches(s, action, resource, ctx)]
    if any(s["Effect"] == "Deny" for s in sts):
        return False
    return any(s["Effect"] == "Allow" for s in sts)


def attach(doc, policy_arn, role=ROLE):
    return allowed(doc, "iam:AttachRolePolicy", role, {"iam:PolicyARN": policy_arn})


def aws_managed(name):
    return f"arn:aws:iam::aws:policy/{name}"


def allowlist(doc):
    st = next(x for x in doc["Statement"] if x.get("Sid") == "DenyAttachAwsManagedPolicyOutsideAllowlist")
    return as_list(st["Condition"]["ArnNotLike"]["iam:PolicyARN"])


# ------------------------------------------------------------------ evaluator self-check

def test_model_without_the_deny_allows_admin_attach():
    """The scoped policy before this change: iam:* on role/* lets AdministratorAccess through."""
    doc = load_doc()
    doc["Statement"] = [s for s in doc["Statement"] if s["Effect"] == "Allow"]
    assert attach(doc, aws_managed("AdministratorAccess"))
    assert not allowed(doc, "s3:PutObject", "arn:aws:s3:::b/k")


# ------------------------------------------------------------------ (a) the policy

@pytest.mark.parametrize("name", ADMIN_LIKE)
@pytest.mark.parametrize("partition", ["aws", "aws-us-gov", "aws-cn"])
def test_admin_like_attach_denied(name, partition):
    doc = load_doc()
    assert not attach(doc, f"arn:{partition}:iam::aws:policy/{name}")
    # On its own role too (self-escalation).
    own = f"arn:aws:iam::{ACCT}:role/peeks-hub-crossplane-provider"
    assert not attach(doc, f"arn:{partition}:iam::aws:policy/{name}", role=own)


@pytest.mark.parametrize("name", ["ReadOnlyAccess", "AmazonEC2FullAccessX", "job-function/SystemAdministrator",
                                  "AmazonDynamoDBFullAccess", "AWSLambda_FullAccess"])
def test_unlisted_aws_managed_attach_denied(name):
    """Allowlist, not denylist: any other AWS managed policy is refused, exact name only."""
    assert not attach(load_doc(), aws_managed(name))


def test_allowlisted_attach_allowed():
    doc = load_doc()
    for arn in allowlist(doc):
        assert attach(doc, arn.replace("arn:*:", "arn:aws:")), arn


def test_detach_admin_still_allowed():
    """Detach is not conditioned: upgrades must be able to remove AdministratorAccess."""
    assert allowed(load_doc(), "iam:DetachRolePolicy", ROLE, {"iam:PolicyARN": aws_managed("AdministratorAccess")})


MANAGED_POLICY_SH = os.path.join(REPO, "cluster-providers", "common", "iam", "managed-policy.sh")


def scoped_name(prefix, role):
    """The policy name managed-policy.sh gives <role> (its own `name` subcommand)."""
    return subprocess.run(["sh", MANAGED_POLICY_SH, "name", prefix, role], capture_output=True,
                          text=True, check=True).stdout.strip()


# Every role that carries this document: hub (kind-kro-ack hub:bootstrap-crossplane-identity),
# kro-ack spoke (rg-eks, "<spoke>-crossplane-provider-scoped", no prefix added) and the
# spokes:seed-provider-identity roles of both cluster providers.
OWN_POLICIES = [
    ("peeks", "peeks-hub-crossplane-provider"),
    ("peeks", "acme-hub-crossplane-provider"),
    ("peeks", "peeks-spoke-dev-CrossplaneIAMProviderRole"),
    ("peeks", "peeks-spoke-dev-CrossplaneEKSProviderRole"),
    ("peeks", "acme-spoke1-CrossplaneIAMProviderRole"),
    ("", "spoke1-CrossplaneEKSProviderRole"),
]


@pytest.mark.parametrize("prefix,role", OWN_POLICIES)
@pytest.mark.parametrize("action", ["iam:CreatePolicyVersion", "iam:SetDefaultPolicyVersion",
                                    "iam:DeletePolicyVersion", "iam:DeletePolicy"])
def test_provider_scoped_policies_cannot_be_changed(prefix, role, action):
    doc = load_doc()
    for name in (scoped_name(prefix, role), role + "-scoped"):  # managed-policy.sh / rg-eks
        assert not allowed(doc, action, f"arn:aws:iam::{ACCT}:policy/{name}"), name


def test_scoped_name_matches_script():
    assert scoped_name("peeks", "peeks-hub-crossplane-provider") == "peeks-hub-crossplane-provider-scoped"
    assert scoped_name("peeks", "acme-spoke1-CrossplaneIAMProviderRole") == "peeks-acme-spoke1-CrossplaneIAMProviderRole-scoped"


def test_known_gaps_still_open():
    """Not closed by this change (see the PR description). If one flips, update the docs."""
    doc = load_doc()
    cust = f"arn:aws:iam::{ACCT}:policy/peeks-anything"
    assert allowed(doc, "iam:CreatePolicy", cust)
    assert attach(doc, cust)
    assert allowed(doc, "iam:CreatePolicyVersion", cust)
    assert allowed(doc, "iam:PutRolePolicy", ROLE)
    assert allowed(doc, "iam:PassRole", ROLE)
    assert allowed(doc, "eks:CreateAccessEntry", f"arn:aws:eks:us-west-2:{ACCT}:cluster/any")
    assert allowed(doc, "iam:UpdateAssumeRolePolicy", f"arn:aws:iam::{ACCT}:role/any-admin-role")
    assert allowed(doc, "iam:CreateRole", ROLE)
    assert allowed(doc, "iam:PutRolePermissionsBoundary", ROLE)
    assert allowed(doc, "iam:DeleteRolePermissionsBoundary", ROLE)
    own = f"arn:aws:iam::{ACCT}:policy/peeks-hub-crossplane-provider-scoped"
    own_role = f"arn:aws:iam::{ACCT}:role/peeks-hub-crossplane-provider"
    assert allowed(doc, "iam:DetachRolePolicy", own_role, {"iam:PolicyARN": own})


def test_deny_statements_only_narrow():
    doc = load_doc()
    denies = [s for s in doc["Statement"] if s["Effect"] == "Deny"]
    assert {x["Sid"] for x in denies} == {"DenyAttachAwsManagedPolicyOutsideAllowlist", "DenyChangeProviderScopedPolicies"}
    for arn in allowlist(doc):
        assert re.fullmatch(r"arn:\*:iam::aws:policy/[\w+=,.@/-]+", arn), arn
        assert not any(arn.endswith("/" + a) for a in ADMIN_LIKE), arn
    assert len(json.dumps(doc, separators=(",", ":"))) < 6144, "managed policy size limit"


# ------------------------------------------------------------------ allowlist covers the repo

# Charts and compositions whose AWS managed policy attachments are made in-cluster by
# provider-aws-iam (Crossplane iam.aws[.m].upbound.io). Every AWS managed ARN they attach
# must be in the allowlist, or the attach is AccessDenied at runtime.
XP_IAM = re.compile(r"iam\.aws(\.m)?\.upbound\.io")
ARN = re.compile(r"arn:aws:iam::aws:policy/([\w+=,.@/-]+)")
# Attachments the deny refuses on purpose. crossplane-pod-identity is the kind-crossplane hub
# addon that bootstraps the spoke iam/eks provider roles (provider NotIn [kro-ack]); it is
# blocked only if the hub provider-aws-iam runs with this scoped document (to validate live).
KNOWN_DENIED = {("gitops/addons/charts/crossplane-pod-identity", "AdministratorAccess")}


SCAN_ROOTS = ["gitops/addons/charts", "gitops/abstractions", "gitops/overlays", "platform",
              "cluster-providers/kind-crossplane/claims"]
SCAN_EXT = (".yaml", ".yml", ".tpl", ".cue", ".json")


def crossplane_iam_units():
    """(unit, {file: text}) per first-level directory (or loose file) under SCAN_ROOTS that
    uses Crossplane IAM. A unit is the scope in which an ARN counts as Crossplane-attached."""
    units = []
    for rel in SCAN_ROOTS:
        root = os.path.join(REPO, rel)
        for name in sorted(os.listdir(root)):
            d = os.path.join(root, name)
            if os.path.isdir(d):
                files = [os.path.join(dp, f) for dp, _, fs in os.walk(d) for f in fs if f.endswith(SCAN_EXT)]
            elif name.endswith(SCAN_EXT):
                files = [d]
            else:
                continue
            texts = {f: open(f, errors="replace").read() for f in files}
            if any(XP_IAM.search(t) for t in texts.values()):
                units.append((os.path.relpath(d, REPO), texts))
    return units


def test_allowlist_covers_every_crossplane_attached_aws_policy():
    allow = {a.split("policy/", 1)[1] for a in allowlist(load_doc())}
    units = crossplane_iam_units()
    names = {u for u, _ in units}
    assert {"gitops/addons/charts/crossplane-base", "gitops/addons/charts/karpenter",
            "gitops/abstractions/crossplane"} <= names, names
    missing = []
    for unit, texts in units:
        if unit == "gitops/addons/charts/kro":  # ACK RGDs (iam.services.k8s.aws), another identity
            continue
        for path, text in texts.items():
            for line in text.splitlines():
                if line.strip().startswith(("#", "//")):
                    continue
                for n in ARN.findall(line):
                    if n not in allow and (unit, n) not in KNOWN_DENIED:
                        missing.append(f"{os.path.relpath(path, REPO)}: {n}")
    assert not missing, "AWS managed policies attached by provider-aws-iam but not allowlisted:\n" + "\n".join(missing)


def test_kro_chart_attaches_through_ack_not_crossplane():
    """The kro chart is skipped above because its IAM is ACK. Fail if that stops being true."""
    unit = dict(crossplane_iam_units()).get("gitops/addons/charts/kro", {})
    for path, text in unit.items():
        if ARN.search(text):
            assert not XP_IAM.search(text), f"{path}: Crossplane IAM next to an AWS managed ARN"


# ------------------------------------------------------------------ (c) crossplane-base render

def registry_values():
    """crossplane-base valuesObject from the addon registry, ArgoCD templating stubbed."""
    with open(REGISTRY) as f:
        vals = copy.deepcopy(yaml.safe_load(f)["crossplane-base"]["valuesObject"])

    def stub(v):
        if isinstance(v, dict):
            return {k: stub(x) for k, x in v.items()}
        if isinstance(v, list):
            return [stub(x) for x in v]
        return "stub" if isinstance(v, str) and "{{" in v else v
    vals = stub(vals)
    vals["aws"] = {"region": "us-west-2", "clusterName": "peeks-hub", "accountId": ACCT}
    return vals


def render(tmp_path, vals):
    if not shutil.which("helm"):
        pytest.skip("helm not available")
    f = tmp_path / "values.yaml"
    f.write_text(yaml.safe_dump(vals))
    return subprocess.run(["helm", "template", "t", CHART, "-f", str(f)], capture_output=True, text=True)


def docs_of(out, kind):
    return [d for d in yaml.safe_load_all(out) if d and d.get("kind") == kind]


def test_registry_render_has_no_admin_and_one_scoped_policy_per_provider(tmp_path):
    vals = registry_values()
    r = render(tmp_path, vals)
    assert r.returncode == 0, r.stderr
    for name in ADMIN_LIKE:
        assert f"policy/{name}" not in r.stdout
    roles = {d["metadata"]["name"] for d in docs_of(r.stdout, "Role") if d["apiVersion"].startswith("iam.aws.")}
    atts = docs_of(r.stdout, "RolePolicyAttachment")
    # The registry enables these five with createIdentity: true (iam/eks are false).
    assert roles == {f"{p}-provider-role" for p in ("ec2", "rds", "dynamodb", "amp", "grafana")}
    allow = {a.replace("arn:*:", "arn:aws:") for a in allowlist(load_doc())}
    by_role = {}
    for a in atts:
        fp = a["spec"]["forProvider"]
        assert fp["policyArn"] in allow, fp
        assert not a["metadata"]["name"].endswith("-admin-attachment")
        by_role.setdefault(fp["roleRef"]["name"], []).append(fp["policyArn"])
    assert set(by_role) == roles
    assert by_role["ec2-provider-role"] == [aws_managed("AmazonEC2FullAccess")]
    assert by_role["amp-provider-role"] == [aws_managed("AmazonPrometheusFullAccess")]


def test_render_fails_when_provider_has_no_policy(tmp_path):
    vals = registry_values()
    vals["providers"]["ec2"]["policyArns"] = []
    r = render(tmp_path, vals)
    assert r.returncode != 0 and "providers.ec2 has createIdentity but no policyArns" in r.stderr


def test_every_chart_default_policy_is_allowlisted():
    with open(os.path.join(CHART, "values.yaml")) as f:
        provs = yaml.safe_load(f)["providers"]
    allow = {a.replace("arn:*:", "arn:aws:") for a in allowlist(load_doc())}
    for name, p in provs.items():
        if p.get("roleName") and str(p.get("createIdentity", True)).lower() != "false":
            assert p.get("policyArns"), name
            assert set(p["policyArns"]) <= allow, (name, p["policyArns"])
    assert str(provs["iam"]["createIdentity"]).lower() == "false"
    assert str(provs["eks"]["createIdentity"]).lower() == "false"


# ------------------------------------------------------------------ kind-crossplane direct renders

KC = os.path.join(REPO, "cluster-providers", "kind-crossplane", "Taskfile.yaml")


def kind_crossplane_render_cmd(task):
    """The `helm template crossplane-base ...` command of a kind-crossplane task, vars stubbed."""
    with open(KC) as f:
        cmds = yaml.safe_load(f)["tasks"][task]["cmds"]
    texts = [c if isinstance(c, str) else c.get("cmd", "") for c in cmds]
    hit = [t for t in texts if "helm template crossplane-base" in t]
    assert len(hit) == 1, (task, len(hit))
    cmd = hit[0].replace("\\\n", " ")
    cmd = cmd[cmd.index("helm template crossplane-base"):cmd.index("|")]
    for var, val in {"{{.GITOPS_ROOT}}": os.path.join(REPO, "gitops"), "{{.AWS_REGION}}": "us-west-2",
                     "{{.HUB_CLUSTER_NAME}}": "hub1", "{{.AWS_ACCOUNT_ID}}": ACCT}.items():
        cmd = cmd.replace(var, val)
    assert "{{" not in cmd, cmd
    return cmd


def run_render(cmd):
    if not shutil.which("helm"):
        pytest.skip("helm not available")
    r = subprocess.run(["sh", "-c", cmd], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return list(d for d in yaml.safe_load_all(r.stdout) if d)


@pytest.mark.parametrize("task", ["crossplane:claims", "destroy"])
def test_kind_crossplane_bootstrap_render_keeps_hub_iam_eks_identity(task):
    """kind-crossplane has no other source for the hub provider-aws-iam/eks identity: the
    chart defaults them to createIdentity: false, so both renders must enable them."""
    docs = run_render(kind_crossplane_render_cmd(task))
    roles = {d["metadata"]["annotations"].get("crossplane.io/external-name") for d in docs
             if d["kind"] == "Role" and d["apiVersion"].startswith("iam.aws.")}
    assert {"hub1-CrossplaneIAMProviderRole", "hub1-CrossplaneEKSProviderRole"} <= roles, roles
    pias = {d["spec"]["forProvider"]["serviceAccount"] for d in docs if d["kind"] == "PodIdentityAssociation"}
    assert {"provider-aws-iam", "provider-aws-eks"} <= pias, pias
    atts = {d["spec"]["forProvider"]["roleRef"]["name"] for d in docs if d["kind"] == "RolePolicyAttachment"}
    assert {"iam-provider-role", "eks-provider-role"} <= atts, atts


def test_kind_crossplane_destroy_matches_install_render():
    """destroy deletes what crossplane:claims created (plus family/ec2), so no role is left."""
    ins = {(d["kind"], d["metadata"]["name"]) for d in run_render(kind_crossplane_render_cmd("crossplane:claims"))}
    des = {(d["kind"], d["metadata"]["name"]) for d in run_render(kind_crossplane_render_cmd("destroy"))}
    assert ins <= des, ins - des


def test_kind_crossplane_destroy_deletes_legacy_admin_attachments():
    """Hubs installed before the attachments were renamed keep <name>-provider-admin-attachment;
    destroy must delete those too, or the role delete hits DeleteConflict."""
    with open(KC) as f:
        cmds = yaml.safe_load(f)["tasks"]["destroy"]["cmds"]
    text = next(c["cmd"] for c in cmds if isinstance(c, dict) and "helm template crossplane-base" in c.get("cmd", ""))
    assert re.search(r'for P in iam eks ec2; do\s+kubectl delete rolepolicyattachments\.iam\.aws\.upbound\.io '
                     r'"\$P-provider-admin-attachment"', text), text


def test_attachment_names_follow_the_policy_not_the_index(tmp_path):
    vals = registry_values()
    vals["providers"]["ec2"]["policyArns"] = [aws_managed("AmazonS3FullAccess"), aws_managed("AmazonEC2FullAccess")]
    r = render(tmp_path, vals)
    assert r.returncode == 0, r.stderr
    names = {a["metadata"]["name"] for a in docs_of(r.stdout, "RolePolicyAttachment")
             if a["spec"]["forProvider"]["roleRef"]["name"] == "ec2-provider-role"}
    assert names == {"ec2-provider-amazons3fullaccess", "ec2-provider-amazonec2fullaccess"}, names


# ------------------------------------------------------------------ grafana: EC2 reads for a VPC workspace

GRAFANA_EC2_READ = ["ec2:DescribeSubnets", "ec2:DescribeSecurityGroups", "ec2:DescribeVpcs"]
WRITE_OR_ESCALATE = ["iam:CreateRole", "iam:PutRolePolicy", "iam:AttachRolePolicy", "iam:PassRole",
                     "sts:AssumeRole", "ec2:CreateVpc", "ec2:CreateSecurityGroup", "ec2:DeleteSubnet",
                     "ec2:ModifyVpcAttribute", "ec2:AuthorizeSecurityGroupIngress", "ec2:RunInstances"]


def grafana_inline_doc(tmp_path):
    """The inline policy document(s) crossplane-base puts on the Grafana provider role, as one
    policy. The managed AWSGrafanaAccountAdministrator (grafana:*, iam:PassRole to grafana)
    has no ec2:*: AMG CreateWorkspace with a VPC then fails 403 'Access denied when fetching EC2
    subnet details' (CloudTrail: ec2:DescribeSubnets refused)."""
    r = render(tmp_path, registry_values())
    assert r.returncode == 0, r.stderr
    pols = [d for d in docs_of(r.stdout, "RolePolicy") if d["spec"]["forProvider"]["roleRef"]["name"] == "grafana-provider-role"]
    assert len(pols) == 1, "grafana-provider-role needs exactly one inline policy for the EC2 reads"
    return json.loads(pols[0]["spec"]["forProvider"]["policy"])


def test_grafana_role_can_describe_vpc_for_workspace(tmp_path):
    doc = grafana_inline_doc(tmp_path)
    for a in GRAFANA_EC2_READ:
        assert allowed(doc, a, "*"), a


def test_grafana_inline_policy_is_only_those_ec2_reads(tmp_path):
    doc = grafana_inline_doc(tmp_path)
    for st in doc["Statement"]:
        assert st["Effect"] == "Allow" and "Condition" not in st
        assert sorted(as_list(st["Action"])) == sorted(GRAFANA_EC2_READ)
        assert as_list(st["Resource"]) == ["*"]
    for a in WRITE_OR_ESCALATE:
        assert not allowed(doc, a, "*"), a
        assert not allowed(doc, a, ROLE), a


def test_only_grafana_gets_an_inline_policy(tmp_path):
    r = render(tmp_path, registry_values())
    assert r.returncode == 0, r.stderr
    assert {d["spec"]["forProvider"]["roleRef"]["name"] for d in docs_of(r.stdout, "RolePolicy")} == {"grafana-provider-role"}


def test_grafana_inline_policy_keeps_managed_policy_attached(tmp_path):
    r = render(tmp_path, registry_values())
    atts = [a["spec"]["forProvider"]["policyArn"] for a in docs_of(r.stdout, "RolePolicyAttachment")
            if a["spec"]["forProvider"]["roleRef"]["name"] == "grafana-provider-role"]
    assert atts == [aws_managed("AWSGrafanaAccountAdministrator")]
