"""The Crossplane provider identity cannot hand out AdministratorAccess, and crossplane-base
no longer asks it to.

Follow-up to the scoped <cluster>-crossplane-provider policy. That policy keeps iam:* on
role/* and policy/*, so on its own provider-aws-iam could attach any AWS managed policy,
AdministratorAccess included, to any role. Two changes:

(c) crossplane-base attaches a per-provider managed policy (values.yaml providers.<p>.policyArns)
    to each provider role, not AdministratorAccess.
(a) common/iam/crossplane-provider-policy.json (and its rg-eks inline copy) denies
    iam:AttachRolePolicy of any AWS managed policy outside an explicit allowlist (iam:PolicyARN),
    and denies CreatePolicyVersion / SetDefaultPolicyVersion on the provider's own
    *-crossplane-provider-scoped policy.

Not closed, and pinned below as still allowed so a reader sees the gap: customer-managed
policies (CreatePolicy + attach), inline PutRolePolicy, CreatePolicyVersion on other
policies, PassRole, eks:*.

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
# boundaries, NotAction or IfExists. Upgrade to `aws iam simulate-custom-policy` in a live test.
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
    st = next(s for s in doc["Statement"] if s.get("Sid") == "DenyAttachAwsManagedPolicyOutsideAllowlist")
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


@pytest.mark.parametrize("name", ["peeks-hub-crossplane-provider-scoped",
                                  "peeks-spoke-dev-crossplane-provider-scoped",
                                  "pfx-hub-crossplane-provider-scoped"])
@pytest.mark.parametrize("action", ["iam:CreatePolicyVersion", "iam:SetDefaultPolicyVersion"])
def test_own_scoped_policy_cannot_be_rewritten(name, action):
    assert not allowed(load_doc(), action, f"arn:aws:iam::{ACCT}:policy/{name}")


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


def test_deny_statements_only_narrow():
    doc = load_doc()
    denies = [s for s in doc["Statement"] if s["Effect"] == "Deny"]
    assert {s["Sid"] for s in denies} == {"DenyAttachAwsManagedPolicyOutsideAllowlist", "DenyRewriteOwnScopedPolicy"}
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


def crossplane_iam_units():
    roots = [os.path.join(REPO, "gitops", "addons", "charts"), os.path.join(REPO, "gitops", "abstractions", "crossplane")]
    units = []
    for root in roots:
        for name in sorted(os.listdir(root)):
            d = os.path.join(root, name)
            if not os.path.isdir(d):
                continue
            files = [os.path.join(dp, f) for dp, _, fs in os.walk(d) for f in fs if f.endswith((".yaml", ".yml", ".tpl"))]
            texts = {f: open(f).read() for f in files}
            if any(XP_IAM.search(t) for t in texts.values()):
                units.append((os.path.relpath(d, REPO), texts))
    return units


def test_allowlist_covers_every_crossplane_attached_aws_policy():
    allow = {a.split("policy/", 1)[1] for a in allowlist(load_doc())}
    units = crossplane_iam_units()
    names = {u for u, _ in units}
    assert "gitops/addons/charts/crossplane-base" in names and "gitops/addons/charts/karpenter" in names, names
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
