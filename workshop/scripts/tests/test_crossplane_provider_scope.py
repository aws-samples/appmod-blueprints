"""The Crossplane provider identity cannot hand out AdministratorAccess, and crossplane-base
no longer asks it to.

Follow-up to the scoped <cluster>-crossplane-provider policy, which keeps the IAM writes on
roles and policies that the Crossplane IAM provider needs. Two changes:

(c) crossplane-base attaches a per-provider managed policy (values.yaml providers.<p>.policyArns)
    to each provider role, not AdministratorAccess.
(a) common/iam/crossplane-provider-policy.json (and its rg-eks inline copy) denies
    iam:AttachRolePolicy of any AWS managed policy outside an explicit allowlist (iam:PolicyARN),
    and denies editing or deleting the provider scoped policies (*-crossplane-provider-scoped,
    *ProviderRole-scoped, and their *-scoped-<sha8> second names).

This is least-privilege scoping of the AWS managed policy path, not a permissions boundary.

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
    # On its own role too.
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


@pytest.mark.parametrize("prefix,role", OWN_POLICIES)
@pytest.mark.parametrize("action", ["iam:CreatePolicyVersion", "iam:SetDefaultPolicyVersion",
                                    "iam:DeletePolicyVersion", "iam:DeletePolicy"])
def test_provider_scoped_policies_under_the_second_name_cannot_be_changed(prefix, role, action):
    """After a document change managed-policy.sh names the policy <base>-<sha8>: the Deny must
    cover that name too, or the first install after an upgrade moves it out of the Deny."""
    import hashlib
    doc = load_doc()
    sha8 = hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:8]
    for name in (scoped_name(prefix, role), role + "-scoped"):
        assert not allowed(doc, action, f"arn:aws:iam::{ACCT}:policy/{name}-{sha8}"), name


def test_scoped_name_matches_script():
    assert scoped_name("peeks", "peeks-hub-crossplane-provider") == "peeks-hub-crossplane-provider-scoped"
    assert scoped_name("peeks", "acme-spoke1-CrossplaneIAMProviderRole") == "peeks-acme-spoke1-CrossplaneIAMProviderRole-scoped"


def test_controllers_keep_the_iam_writes_they_need():
    """The Crossplane IAM provider creates roles and customer-managed policies for the addons
    and apps, attaches them and passes roles; an upgrade detaches the older attachments. The
    Deny statements must not break that."""
    doc = load_doc()
    cust = f"arn:aws:iam::{ACCT}:policy/peeks-anything"
    assert allowed(doc, "iam:CreatePolicy", cust)
    assert attach(doc, cust)
    assert allowed(doc, "iam:CreateRole", ROLE)
    assert allowed(doc, "iam:PassRole", ROLE)
    assert allowed(doc, "eks:CreatePodIdentityAssociation", f"arn:aws:eks:us-west-2:{ACCT}:cluster/any")
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

# DescribeSubnets and DescribeDhcpOptions: proven needed (CloudTrail UnauthorizedOperation, caller
# grafana.amazonaws.com). The rest are read-only and not proven.
GRAFANA_EC2_READ = ["ec2:DescribeSubnets", "ec2:DescribeDhcpOptions", "ec2:DescribeSecurityGroups",
                    "ec2:DescribeVpcs", "ec2:DescribeVpcAttribute", "ec2:DescribeNetworkInterfaces",
                    "ec2:DescribeAvailabilityZones"]
WRITE_ACTIONS = ["iam:CreateRole", "iam:PutRolePolicy", "iam:AttachRolePolicy", "iam:PassRole",
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


SLR_ARN = f"arn:aws:iam::{ACCT}:role/aws-service-role/grafana.amazonaws.com/AWSServiceRoleForAmazonGrafana"
SLR_RESOURCE = "arn:aws:iam::*:role/aws-service-role/grafana.amazonaws.com/*"


def test_grafana_inline_policy_is_only_those_ec2_reads_and_the_scoped_slr(tmp_path):
    doc = grafana_inline_doc(tmp_path)
    sts = doc["Statement"]
    reads = [s for s in sts if "iam:CreateServiceLinkedRole" not in as_list(s["Action"])]
    slr = [s for s in sts if "iam:CreateServiceLinkedRole" in as_list(s["Action"])]
    assert len(reads) == 1 and len(slr) == 1 and len(sts) == 2
    st = reads[0]
    assert st["Effect"] == "Allow" and "Condition" not in st
    assert sorted(as_list(st["Action"])) == sorted(GRAFANA_EC2_READ)
    assert as_list(st["Resource"]) == ["*"]
    for a in WRITE_ACTIONS:
        assert not allowed(doc, a, "*"), a
        assert not allowed(doc, a, ROLE), a


def test_grafana_can_create_only_its_own_service_linked_role(tmp_path):
    # AMG CreateWorkspace with a VPC creates the service-linked role with the caller's rights:
    # 403 "You do not have permissions to create a service-linked role" without this statement.
    doc = grafana_inline_doc(tmp_path)
    ctx = {"iam:AWSServiceName": "grafana.amazonaws.com"}
    assert allowed(doc, "iam:CreateServiceLinkedRole", SLR_ARN, ctx)
    # another service's SLR, or a mismatched service name, stays denied
    assert not allowed(doc, "iam:CreateServiceLinkedRole", SLR_ARN, {"iam:AWSServiceName": "ec2.amazonaws.com"})
    assert not allowed(doc, "iam:CreateServiceLinkedRole", SLR_ARN)
    other = f"arn:aws:iam::{ACCT}:role/aws-service-role/eks.amazonaws.com/AWSServiceRoleForAmazonEKS"
    assert not allowed(doc, "iam:CreateServiceLinkedRole", other, {"iam:AWSServiceName": "eks.amazonaws.com"})
    assert not allowed(doc, "iam:CreateServiceLinkedRole", other, ctx)
    assert not allowed(doc, "iam:CreateServiceLinkedRole", ROLE, ctx)


def test_grafana_slr_statement_is_scoped_and_the_only_iam_action(tmp_path):
    doc = grafana_inline_doc(tmp_path)
    slr = [s for s in doc["Statement"] if "iam:CreateServiceLinkedRole" in as_list(s["Action"])]
    assert len(slr) == 1
    st = slr[0]
    assert st["Effect"] == "Allow"
    assert as_list(st["Action"]) == ["iam:CreateServiceLinkedRole"]
    assert as_list(st["Resource"]) == [SLR_RESOURCE]
    assert st["Condition"] == {"StringEquals": {"iam:AWSServiceName": "grafana.amazonaws.com"}}
    iam_actions = [a for s in doc["Statement"] for a in as_list(s["Action"]) if a.lower().startswith("iam:")]
    assert iam_actions == ["iam:CreateServiceLinkedRole"], iam_actions


def test_only_grafana_and_amp_get_an_inline_policy(tmp_path):
    r = render(tmp_path, registry_values())
    assert r.returncode == 0, r.stderr
    assert {d["spec"]["forProvider"]["roleRef"]["name"] for d in docs_of(r.stdout, "RolePolicy")} == {
        "grafana-provider-role", "amp-provider-role"}


def test_grafana_inline_policy_keeps_managed_policy_attached(tmp_path):
    r = render(tmp_path, registry_values())
    atts = [a["spec"]["forProvider"]["policyArn"] for a in docs_of(r.stdout, "RolePolicyAttachment")
            if a["spec"]["forProvider"]["roleRef"]["name"] == "grafana-provider-role"]
    assert atts == [aws_managed("AWSGrafanaAccountAdministrator")]


# ------------------------------------------------------------------ claims: legacy attachments

FAKE_KUBECTL = r'''#!/bin/sh
# Fake kubectl for the legacy-attachment step: one file per MR holds its deletionPolicy.
# STATE/ignore_patch makes patch a no-op (an MR that never takes the policy).
echo "kubectl $*" >> "$STATE/log"
verb=$1; shift
name=$2   # $1 is the resource type
case $verb in
  get)
    [ -f "$STATE/get_fail" ] && { echo "error: You must be logged in (ExpiredToken)" >&2; exit 1; }
    if [ ! -f "$STATE/mr/$name" ]; then
      case " $* " in
        *" --ignore-not-found "*) exit 0 ;;   # empty output, like kubectl
        *) echo "Error from server (NotFound): $name not found" >&2; exit 1 ;;
      esac
    fi
    case " $* " in
      *jsonpath*) cat "$STATE/mr/$name" ;;
      *) echo "rolepolicyattachment.iam.aws.upbound.io/$name" ;;
    esac ;;
  patch)
    # Apply the deletionPolicy the patch actually sends (not a fixed value), so a wrong
    # payload is caught.
    if [ ! -f "$STATE/ignore_patch" ]; then
      pol=$(printf '%s\n' "$*" | sed -n 's/.*"deletionPolicy":"\([A-Za-z]*\)".*/\1/p')
      echo "${pol:-unset}" > "$STATE/mr/$name"
    fi ;;
  delete)
    echo "delete $name policy=$(cat "$STATE/mr/$name")" >> "$STATE/events"
    rm -f "$STATE/mr/$name" ;;
esac
'''


def legacy_step_script():
    with open(KC) as f:
        cmds = yaml.safe_load(f)["tasks"]["crossplane:claims"]["cmds"]
    texts = [c if isinstance(c, str) else c.get("cmd", "") for c in cmds]
    idx = [i for i, t in enumerate(texts) if "provider-admin-attachment" in t]
    assert len(idx) == 1, idx
    render = [i for i, t in enumerate(texts) if "helm template crossplane-base" in t]
    assert len(render) == 1 and idx[0] < render[0], "legacy MRs must be gone before the new render is applied"
    return texts[idx[0]]


def run_legacy_step(tmp_path, existing, ignore_patch=False, get_fail=False):
    state = tmp_path / "state"
    (state / "mr").mkdir(parents=True, exist_ok=True)
    for n in existing:
        (state / "mr" / n).write_text("Delete\n")
    if ignore_patch:
        (state / "ignore_patch").write_text("")
    if get_fail:
        (state / "get_fail").write_text("")
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    k = bindir / "kubectl"
    k.write_text(FAKE_KUBECTL)
    k.chmod(0o755)
    for tool in ("sleep",):  # no real waiting in the tests
        s = bindir / tool
        s.write_text("#!/bin/sh\nexit 0\n")
        s.chmod(0o755)
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", STATE=str(state))
    r = subprocess.run(["sh", "-e", "-c", legacy_step_script()], capture_output=True, text=True, env=env)
    ev = state / "events"
    return r, (ev.read_text().splitlines() if ev.exists() else []), (state / "log").read_text()


LEGACY = ["iam-provider-admin-attachment", "eks-provider-admin-attachment"]


def test_legacy_step_is_a_noop_on_a_fresh_cluster(tmp_path):
    r, events, log = run_legacy_step(tmp_path, [])
    assert r.returncode == 0, r.stderr
    assert events == [] and "patch" not in log and "delete" not in log


def test_legacy_step_orphans_before_deleting_on_an_existing_cluster(tmp_path):
    r, events, log = run_legacy_step(tmp_path, LEGACY)
    assert r.returncode == 0, r.stderr
    assert events == [f"delete {n} policy=Orphan" for n in LEGACY], events
    assert "--wait=true" in log


def test_legacy_step_rerun_is_a_noop(tmp_path):
    r, events, _ = run_legacy_step(tmp_path, LEGACY)
    assert r.returncode == 0 and len(events) == 2
    # second pass on the SAME state: the MRs are gone, nothing is patched or deleted again
    (tmp_path / "state" / "events").unlink()
    (tmp_path / "state" / "log").unlink()
    r2, events2, log2 = run_legacy_step(tmp_path, [])
    assert r2.returncode == 0 and events2 == [] and "patch" not in log2 and "delete" not in log2


def test_legacy_step_aborts_when_kubectl_get_fails(tmp_path):
    """Only NotFound means absent: an expired token must not be read as 'nothing to do'."""
    r, events, log = run_legacy_step(tmp_path, LEGACY, get_fail=True)
    assert r.returncode != 0
    assert events == [] and "patch" not in log and "delete" not in log


def test_legacy_step_only_touches_one_when_only_one_exists(tmp_path):
    r, events, _ = run_legacy_step(tmp_path, LEGACY[:1])
    assert r.returncode == 0, r.stderr
    assert events == [f"delete {LEGACY[0]} policy=Orphan"]


def test_legacy_step_never_deletes_an_mr_that_did_not_take_orphan(tmp_path):
    r, events, _ = run_legacy_step(tmp_path, LEGACY, ignore_patch=True)
    assert r.returncode != 0
    assert events == [], "deleting without Orphan would detach AdministratorAccess"


# ------------------------------------------------------------------ user/group attach, rg-eks copy

RG_EKS = os.path.join(REPO, "gitops", "addons", "charts", "kro", "resource-groups", "manifests", "eks", "rg-eks.yaml")
ATTACH_ACTIONS = ["iam:AttachRolePolicy", "iam:AttachUserPolicy", "iam:AttachGroupPolicy"]
RESOURCE_FOR = {"iam:AttachRolePolicy": ROLE,
                "iam:AttachUserPolicy": f"arn:aws:iam::{ACCT}:user/u",
                "iam:AttachGroupPolicy": f"arn:aws:iam::{ACCT}:group/g"}


def with_blanket_allow(doc):
    """The same document next to a role that keeps AdministratorAccess (seeded spokes): the
    Deny alone has to hold."""
    d = copy.deepcopy(doc)
    d["Statement"].append({"Effect": "Allow", "Action": "*", "Resource": "*"})
    return d


@pytest.mark.parametrize("action", ATTACH_ACTIONS)
@pytest.mark.parametrize("name", ADMIN_LIKE)
def test_admin_like_attach_denied_for_role_user_and_group(action, name):
    doc = with_blanket_allow(load_doc())
    assert not allowed(doc, action, RESOURCE_FOR[action], {"iam:PolicyARN": aws_managed(name)})


@pytest.mark.parametrize("action", ATTACH_ACTIONS)
def test_allowlisted_attach_stays_allowed_for_role_user_and_group(action):
    doc = with_blanket_allow(load_doc())
    assert allowed(doc, action, RESOURCE_FOR[action], {"iam:PolicyARN": aws_managed("AmazonS3FullAccess")})


def rg_eks_policy_documents():
    with open(RG_EKS) as f:
        text = f.read()
    docs = []
    for m in re.finditer(r"policyDocument: '(\{.*\})'\s*$", text, re.M):
        docs.append(json.loads(m.group(1)))
    return docs


def test_rg_eks_inline_copy_equals_the_policy_file():
    """The kro-ack spoke carries the same document inline; the two must not drift."""
    docs = [d for d in rg_eks_policy_documents()
            if any(s.get("Sid") == "DenyAttachAwsManagedPolicyOutsideAllowlist" for s in d["Statement"])]
    assert len(docs) == 1, len(docs)
    assert docs[0] == load_doc()


# ------------------------------------------------------------------ amp: scraper access entry

# AMP CreateScraper creates an EKS access entry for the scraper's service-linked role with the
# CALLER's rights. AmazonPrometheusFullAccess has no eks:CreateAccessEntry, so CreateScraper is
# 403 (CloudTrail errorCode AccessDenied on CreateScraper). The scraper principal is AWSServiceRoleForAmazonPrometheusScraper_<id>,
# generated by AMP at create time (AMP docs: roleArn only known from describe-scraper), so the
# entry cannot be pre-created by another principal.
SCRAPER_SLR = (f"arn:aws:iam::{ACCT}:role/aws-service-role/scraper.aps.amazonaws.com/"
               "AWSServiceRoleForAmazonPrometheusScraper_1234abcd-56ef-7")
SCRAPER_SLR_NOPATH = f"arn:aws:iam::{ACCT}:role/AWSServiceRoleForAmazonPrometheusScraper_1234abcd-56ef-7"
CLUSTER = f"arn:aws:eks:us-west-2:{ACCT}:cluster/peeks-spoke-dev"
EKS_ADMIN = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"
SCRAPER_NAME = "AWSServiceRoleForAmazonPrometheusScraper_1234abcd-56ef-7"


def amp_inline_doc(tmp_path, vals=None):
    r = render(tmp_path, vals or registry_values())
    assert r.returncode == 0, r.stderr
    pols = [d for d in docs_of(r.stdout, "RolePolicy") if d["spec"]["forProvider"]["roleRef"]["name"] == "amp-provider-role"]
    assert len(pols) == 1, "amp-provider-role needs one inline policy for the scraper access entry"
    return json.loads(pols[0]["spec"]["forProvider"]["policy"])


def entry(cluster, principal_name, acct=ACCT):
    return f"arn:aws:eks:us-west-2:{acct}:access-entry/{cluster}/role/{acct}/{principal_name}/uuid-1"


@pytest.mark.parametrize("principal", [SCRAPER_SLR])
@pytest.mark.parametrize("cluster", ["peeks-hub", "peeks-spoke-dev", "my-hub", "team-a-prod"])
def test_amp_can_create_access_entry_for_its_scraper_role_on_any_cluster_here(tmp_path, principal, cluster):
    # The hub name comes from the consumer's hub.clusterName and need not share the spokes' prefix.
    doc = amp_inline_doc(tmp_path)
    arn = f"arn:aws:eks:us-west-2:{ACCT}:cluster/{cluster}"
    assert allowed(doc, "eks:CreateAccessEntry", arn, {"eks:principalArn": principal})


# The exact principal AMP CreateScraper sends to eks:CreateAccessEntry, from CloudTrail on a v0.5
# install (requestParameters.principalArn, invokedBy aps.amazonaws.com): a probe name that "can't
# exist", under the service-linked-role path. Cluster names are the hub and both spokes.
SCRAPER_PROBE = (f"arn:aws:iam::{ACCT}:role/aws-service-role/scraper.aps.amazonaws.com/"
                 "AWSServiceRoleForAmazonPrometheusScraper_Th1s_C@nt_3x1st")


@pytest.mark.parametrize("cluster", ["peeks-hub", "peeks-spoke-dev", "peeks-spoke-prod"])
def test_amp_allows_the_principal_amp_actually_sends(tmp_path, cluster):
    doc = amp_inline_doc(tmp_path)
    arn = f"arn:aws:eks:us-west-2:{ACCT}:cluster/{cluster}"
    assert allowed(doc, "eks:CreateAccessEntry", arn, {"eks:principalArn": SCRAPER_PROBE})


@pytest.mark.parametrize("principal", [
    f"arn:aws:iam::{ACCT}:role/WSParticipantRole",
    f"arn:aws:iam::{ACCT}:role/peeks-hub-CrossplaneAMPProviderRole",
    f"arn:aws:iam::{ACCT}:role/AWSServiceRoleForAmazonPrometheusScraperX",
    f"arn:aws:iam::{ACCT}:role/aws-service-role/other.amazonaws.com/AWSServiceRoleForAmazonPrometheusScraper_1",
    "arn:aws:iam::222222222222:role/AWSServiceRoleForAmazonPrometheusScraper_1",
    f"arn:aws:iam::{ACCT}:user/AWSServiceRoleForAmazonPrometheusScraper_1",
    # Customer roles whose PATH imitates the scraper role (IAM StringLike * also matches "/").
    f"arn:aws:iam::{ACCT}:role/AWSServiceRoleForAmazonPrometheusScraper_x/Evil",
    f"arn:aws:iam::{ACCT}:role/aws-service-role/scraper.aps.amazonaws.com/AWSServiceRoleForAmazonPrometheusScraper_x/Evil",
    # The no-path spelling is not what AMP sends (CloudTrail) and is not granted.
    SCRAPER_SLR_NOPATH,
])
def test_amp_cannot_create_access_entry_for_any_other_principal(tmp_path, principal):
    doc = amp_inline_doc(tmp_path)
    assert not allowed(doc, "eks:CreateAccessEntry", CLUSTER, {"eks:principalArn": principal})


def test_amp_access_entry_is_limited_to_this_account_and_region(tmp_path):
    doc = amp_inline_doc(tmp_path)
    ctx = {"eks:principalArn": SCRAPER_SLR}
    assert not allowed(doc, "eks:CreateAccessEntry", f"arn:aws:eks:eu-west-1:{ACCT}:cluster/peeks-hub", ctx)
    assert not allowed(doc, "eks:CreateAccessEntry", "arn:aws:eks:us-west-2:222222222222:cluster/peeks-hub", ctx)
    assert not allowed(doc, "eks:CreateAccessEntry", CLUSTER)  # no principal in the request context


def test_amp_cannot_associate_any_access_policy(tmp_path):
    # No access-policy association is granted, so no entry can be given an EKS access policy
    # (cluster admin included) through this role. Whether AMP needs one is not proven. The
    # entry's Kubernetes groups are not bounded (in-cluster RBAC decides what they grant).
    doc = amp_inline_doc(tmp_path)
    for name in (SCRAPER_NAME, "WSParticipantRole", "peeks-hub-CrossplaneAMPProviderRole", "Admin"):
        e = entry("peeks-hub", name)
        for a in ("eks:AssociateAccessPolicy", "eks:DisassociateAccessPolicy", "eks:UpdateAccessEntry"):
            assert not allowed(doc, a, e, {"eks:policyArn": EKS_ADMIN}), (a, name)


def test_amp_can_describe_and_delete_only_scraper_entries(tmp_path):
    doc = amp_inline_doc(tmp_path)
    for cluster in ("peeks-spoke-dev", "my-hub"):
        e = entry(cluster, SCRAPER_NAME)
        for a in ("eks:DescribeAccessEntry", "eks:DeleteAccessEntry"):
            assert allowed(doc, a, e), (a, cluster)
    for name in ("WSParticipantRole", "Admin", "AWSServiceRoleForAmazonPrometheusScraperX"):
        assert not allowed(doc, "eks:DeleteAccessEntry", entry("peeks-hub", name)), name
    assert not allowed(doc, "eks:DeleteAccessEntry", entry("peeks-hub", SCRAPER_NAME, acct="222222222222"))


def test_amp_inline_policy_adds_only_scoped_eks_allows(tmp_path):
    doc = amp_inline_doc(tmp_path)
    assert all(s["Effect"] == "Allow" for s in doc["Statement"])
    assert all(a.startswith("eks:") for s in doc["Statement"] for a in as_list(s["Action"]))
    for a in WRITE_ACTIONS + ["eks:CreateCluster", "eks:DeleteCluster", "eks:UpdateClusterConfig"]:
        for res in ("*", CLUSTER, ROLE):
            assert not allowed(doc, a, res, {"eks:principalArn": SCRAPER_SLR}), (a, res)


def test_crossplane_base_renders_without_a_resource_prefix(tmp_path):
    # The amp policy must not depend on resourcePrefix: an empty one must not fail the whole
    # crossplane-base render (every provider of the chart).
    vals = registry_values()
    vals.pop("resourcePrefix", None)
    r = render(tmp_path, vals)
    assert r.returncode == 0, r.stderr
    assert len(docs_of(r.stdout, "Provider")) >= 2


def test_amp_managed_policy_stays_attached(tmp_path):
    r = render(tmp_path, registry_values())
    atts = [a["spec"]["forProvider"]["policyArn"] for a in docs_of(r.stdout, "RolePolicyAttachment")
            if a["spec"]["forProvider"]["roleRef"]["name"] == "amp-provider-role"]
    assert atts == [aws_managed("AmazonPrometheusFullAccess")]
