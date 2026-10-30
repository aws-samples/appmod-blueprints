"""Hermetic tests for kind-kro-ack `task destroy` step 6 (extended AWS sweep): a delete
that fails is not reported as done.

The step-6 cmd is read verbatim from cluster-providers/kind-kro-ack/Taskfile.yaml and run
under go-task's own interpreter with the Taskfile's `set:` options (bash with
`set -euo pipefail` if go-task is not on PATH). `aws` is a fake on PATH that answers the
list/describe calls from a fixture with --query applied by jmespath, as the AWS CLI does,
and fails the deletes the fixture denies the way the CLI does (exit 254, "An error
occurred (AccessDeniedException) when calling the ... operation: ..." on stderr), or
fails them without an AWS error code, as when the endpoint is unreachable. No AWS, no
network.

Run:  python -m pytest workshop/scripts/tests/test_destroy_step6_report.py -q
Set DESTROY_TASKFILE=<path> to run the same checks against another Taskfile.
"""
import json
import os
import re
import shutil
import subprocess
import sys

import pytest

yaml = pytest.importorskip("yaml")
jmespath = pytest.importorskip("jmespath")  # ships with botocore, which the sweep needs

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
TASKFILE = os.environ.get("DESTROY_TASKFILE") or os.path.join(
    REPO, "cluster-providers", "kind-kro-ack", "Taskfile.yaml")
TASK = shutil.which("task")
ACCT, REGION, PREFIX = "111122223333", "us-west-2", "acme"
HUB = f"{PREFIX}-hub"
OIDC = f"oidc.eks.{REGION}.amazonaws.com/id/"

FIXTURE = {
    "secrets": [f"arn:aws:secretsmanager:{REGION}:{ACCT}:secret:{PREFIX}-ok-AbCdEf",
                f"arn:aws:secretsmanager:{REGION}:{ACCT}:secret:{PREFIX}-denied-GhIjKl",
                f"arn:aws:secretsmanager:{REGION}:{ACCT}:secret:{PREFIX}-unreachable-MnOpQr"],
    "workspaces": [{"alias": f"{PREFIX}-observability-amp", "workspaceId": "ws-ok"},
                   {"alias": f"{PREFIX}-other-amp", "workspaceId": "ws-denied"}],
    "dbs": ["devlake-ok", "devlake-denied"],
    "oidc": ["OKOKOK", "DENIEDDENIED", "CAPSPOKE", "FOREIGNUNTAGGED", "FOREIGNOTHERSTACK",
             "FOREIGNCAPPREFIX", "FOREIGNCAPSIBLING"],
    # Owner tag per provider (6f only deletes this stack's own). A plain string is the ACK
    # services.k8s.aws/namespace tag (rg-eks oidcProvider); a dict gives the tags as is, e.g.
    # eks:kubernetes-namespace, which the EKS managed ACK capability sets on spoke providers.
    # The FOREIGNCAP* ones carry that tag with a value that is only a prefix of, or shares a
    # prefix with, this stack's names: an exact cluster-name match is required.
    "oidc_tags": {"OKOKOK": HUB, "DENIEDDENIED": f"{PREFIX}-spoke-dev",
                  "CAPSPOKE": {"eks:kubernetes-namespace": f"{PREFIX}-spoke-prod",
                               "eks:kubernetes-resource-name": f"{PREFIX}-spoke-prod-oidc"},
                  "FOREIGNOTHERSTACK": "other-hub",
                  "FOREIGNCAPPREFIX": {"eks:kubernetes-namespace": PREFIX},
                  "FOREIGNCAPSIBLING": {"eks:kubernetes-namespace": f"{PREFIX}-b-hub"}},
    # AMP scrapers of this stack's hub and dev spoke (6ei): one delete allowed, one denied.
    "scrapers": [{"scraperId": "s-okok", "source": {"eksConfiguration": {
                      "clusterArn": f"arn:aws:eks:{REGION}:{ACCT}:cluster/{PREFIX}-hub"}}},
                 {"scraperId": "s-denied", "source": {"eksConfiguration": {
                      "clusterArn": f"arn:aws:eks:{REGION}:{ACCT}:cluster/{PREFIX}-spoke-dev"}}}],
    "log_groups": [f"/aws/eks/{HUB}/cluster", f"/aws/eks/{HUB}/capability/kro",
                   f"/aws/eks/{PREFIX}-spoke-dev/cluster", f"/aws/eks/{PREFIX}-spoke-prod/cluster"],
    # Denied deletes: one of each kind, and three of the four log groups.
    "deny": [f"{PREFIX}-denied", "ws-denied", "devlake-denied", "DENIEDDENIED", "s-denied",
             f"/aws/eks/{HUB}/cluster", f"/aws/eks/{HUB}/capability/kro",
             f"/aws/eks/{PREFIX}-spoke-dev/cluster"],
    # A delete that fails without an AWS error code (no "An error occurred (...)").
    "unreachable": [f"{PREFIX}-unreachable"],
}
DENIED = [FIXTURE["secrets"][1], "ws-denied", "devlake-denied", "DENIEDDENIED", "s-denied",
          *FIXTURE["log_groups"][:3]]
ALLOWED = [FIXTURE["secrets"][0], "ws-ok", "devlake-ok", "OKOKOK", "CAPSPOKE", "s-okok",
           FIXTURE["log_groups"][3]]
UNREACHABLE = FIXTURE["secrets"][2]
FOREIGN_OIDC = ["FOREIGNUNTAGGED", "FOREIGNOTHERSTACK", "FOREIGNCAPPREFIX", "FOREIGNCAPSIBLING"]

FAKE_AWS = r'''#!{python} -I
import json, os, sys
import jmespath
fx = json.load(open(os.environ["FAKE_AWS_FIXTURE"]))
svc, op, rest = sys.argv[1], sys.argv[2], sys.argv[3:]
opts, i = {}, 0
while i < len(rest):
    if rest[i].startswith("--") and i + 1 < len(rest) and not rest[i + 1].startswith("--"):
        opts[rest[i][2:]] = rest[i + 1]; i += 2
    else:
        opts[rest[i][2:]] = ""; i += 1
with open(os.environ["FAKE_AWS_LOG"], "a") as f:
    f.write(json.dumps([svc, op, opts]) + "\n")
OPS = {"delete-secret": ("secret-id", "DeleteSecret"),
       "delete-workspace": ("workspace-id", "DeleteWorkspace"),
       "delete-db-instance": ("db-instance-identifier", "DeleteDBInstance"),
       "delete-open-id-connect-provider": ("open-id-connect-provider-arn", "DeleteOpenIDConnectProvider"),
       "delete-log-group": ("log-group-name", "DeleteLogGroup"),
       "delete-scraper": ("scraper-id", "DeleteScraper")}
if op in OPS:
    key, api = OPS[op]
    target = opts.get(key, "")
    if op == "delete-secret" and any(":" + d + "-" in target for d in fx.get("unreachable", [])):
        sys.stderr.write('\nCould not connect to the endpoint URL: '
                         '"https://secretsmanager.%s.amazonaws.com/"\n' % opts.get("region", ""))
        sys.exit(255)
    if any(target == d or target.endswith("/" + d) or (op == "delete-secret" and ":" + d + "-" in target)
           for d in fx["deny"]):
        sys.stderr.write("\nAn error occurred (AccessDeniedException) when calling the %s operation: "
                         "User: arn:aws:sts::%s:assumed-role/SharedRole/i-0 is not authorized to perform: "
                         "%s on resource: %s\n" % (api, fx["acct"], api, target))
        sys.exit(254)
    if op == "delete-secret":
        print(json.dumps({"ARN": target, "Name": target.rsplit(":", 1)[-1]}, indent=4))
    sys.exit(0)
if not op.startswith(("describe-", "list-", "get-")):
    sys.exit(0)
out = {
    ("secretsmanager", "list-secrets"): {"SecretList": [{"ARN": a} for a in fx["secrets"]]},
    ("amp", "list-workspaces"): {"workspaces": fx["workspaces"]},
    ("amp", "list-scrapers"): {"scrapers": fx.get("scrapers", [])},
    ("rds", "describe-db-instances"): {"DBInstances": [{"DBInstanceIdentifier": d} for d in fx["dbs"]]},
    ("sts", "get-caller-identity"): {"Account": fx["acct"]},
    ("eks", "list-clusters"): {"clusters": list(fx.get("clusters", {}))},
    ("iam", "list-open-id-connect-providers"): {"OpenIDConnectProviderList": [
        {"Arn": "arn:aws:iam::%s:oidc-provider/%s%s" % (fx["acct"], fx["oidc_url"], o)} for o in fx["oidc"]]},
    ("iam", "list-roles"): {"Roles": []},
    ("iam", "list-policies"): {"Policies": []},
    ("ec2", "describe-vpcs"): {"Vpcs": []},
}.get((svc, op), {})
if (svc, op) == ("iam", "get-open-id-connect-provider"):
    url = opts["open-id-connect-provider-arn"].split("oidc-provider/", 1)[1]
    ns = fx.get("oidc_tags", {}).get(url.rsplit("/", 1)[-1])
    out = {"Url": url}
    if isinstance(ns, dict):
        out["Tags"] = [{"Key": k, "Value": v} for k, v in ns.items()]
    elif ns:
        out["Tags"] = [{"Key": "app.kubernetes.io/managed-by", "Value": "kro"},
                       {"Key": "services.k8s.aws/namespace", "Value": ns}]
if (svc, op) == ("eks", "describe-cluster"):
    c = fx.get("clusters", {}).get(opts.get("name", ""))
    if c is None:
        sys.stderr.write("\nAn error occurred (ResourceNotFoundException) when calling the "
                         "DescribeCluster operation: No cluster found\n")
        sys.exit(254)
    out = {"cluster": c}
if (svc, op) == ("logs", "describe-log-groups"):
    out = {"logGroups": [{"logGroupName": g} for g in fx["log_groups"]
                         if g.startswith(opts.get("log-group-name-prefix", ""))]}
if "query" in opts:
    out = jmespath.search(opts["query"], out)
def text(v):
    if v is None:
        return "None"
    if isinstance(v, list):
        if v and all(isinstance(x, list) for x in v):  # rows, as the CLI's text output prints them
            return "\n".join(text(x) for x in v)
        return "\t".join(text(x) for x in v)
    return str(v)
if opts.get("output") == "text":
    print(text(out))
else:
    print(json.dumps(out))
'''


def _step6():
    with open(TASKFILE) as f:
        cmds = yaml.safe_load(f)["tasks"]["destroy"]["cmds"]
    return next(c["cmd"] for c in cmds if isinstance(c, dict) and "# 6g." in c.get("cmd", ""))


def _record_step():
    with open(TASKFILE) as f:
        cmds = yaml.safe_load(f)["tasks"]["destroy"]["cmds"]
    return next(c["cmd"] for c in cmds if isinstance(c, dict)
                and "destroy-oidc-ids" in c.get("cmd", "") and "# 6f." not in c.get("cmd", ""))


def _run(tmp_path, cmd=None, fixture_data=None):
    cmd = cmd or _step6()
    bindir = tmp_path / "bin"
    if not bindir.exists():
        bindir.mkdir()
        (bindir / "aws").write_text(FAKE_AWS.replace("{python}", sys.executable))
        (bindir / "aws").chmod(0o755)
    fixture, log = tmp_path / "fixture.json", tmp_path / "aws.jsonl"
    fixture.write_text(json.dumps(dict(fixture_data or FIXTURE, acct=ACCT, oidc_url=OIDC)))
    log.write_text("")
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}",
               FAKE_AWS_FIXTURE=str(fixture), FAKE_AWS_LOG=str(log))
    tvars = {"AWS_REGION": REGION, "RESOURCE_PREFIX": PREFIX, "HUB_CLUSTER_NAME": HUB,
             "C_INFO": "", "C_RESET": ""}
    if TASK:
        tf = tmp_path / "Taskfile.yml"
        tf.write_text(yaml.safe_dump({
            "version": "3", "set": ["errexit", "nounset", "pipefail"], "vars": tvars,
            "tasks": {"run": {"cmds": [{"cmd": cmd}]}}}, sort_keys=False))
        res = subprocess.run([TASK, "-s", "-t", str(tf), "run"], cwd=tmp_path, env=env,
                             capture_output=True, text=True, timeout=120)
    else:
        for k, v in tvars.items():
            cmd = cmd.replace("{{.%s}}" % k, v)
        script = tmp_path / "step6.sh"
        script.write_text("set -euo pipefail\n" + cmd.replace("{{.ROOT_DIR}}", str(tmp_path)))
        res = subprocess.run(["bash", str(script)], cwd=tmp_path, env=env,
                             capture_output=True, text=True, timeout=120)
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    return res, calls


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    return _run(tmp_path_factory.mktemp("destroy-step6"))


def _lines(res, mark, ident):
    return [ln for ln in res.stdout.splitlines() if mark in ln and re.search(re.escape(ident) + r"(\s|$)", ln)]


def test_failed_deletes_are_not_reported_as_done(run):
    res, _ = run
    wrong = [ln.strip() for ident in DENIED for ln in _lines(res, "✓", ident)]
    assert wrong == [], "reported as deleted although the delete failed:\n" + "\n".join(wrong)


def test_failed_deletes_say_why(run):
    res, _ = run
    missing = [ident for ident in DENIED
               if not [ln for ln in _lines(res, "⚠", ident) if "(AccessDeniedException)" in ln]]
    assert missing == [], "no '⚠ … not deleted (AccessDeniedException)' line for: " + ", ".join(missing)


def test_failure_lines_do_not_print_the_error_message(run):
    res, _ = run
    warn = [ln for ln in res.stdout.splitlines() if "⚠" in ln]
    assert not [ln for ln in warn if "assumed-role" in ln or "is not authorized" in ln], warn


def test_successful_deletes_still_report_done(run):
    res, _ = run
    missing = [ident for ident in ALLOWED if not _lines(res, "✓", ident)]
    assert missing == [], "no ✓ line for: " + ", ".join(missing) + "\n" + res.stdout


def test_the_step_runs_to_the_end_after_failures(run):
    res, calls = run
    ops = [c[1] for c in calls]
    assert res.returncode == 0, res.stdout + res.stderr
    last_delete = max(i for i, o in enumerate(ops) if o == "delete-log-group")
    assert "describe-vpcs" in ops[last_delete:], "step 6i never ran: " + ", ".join(ops[last_delete:])


def test_failure_without_an_aws_error_code_says_unknown_error(run):
    res, _ = run
    done = _lines(res, "✓", UNREACHABLE)
    warn = [ln.strip() for ln in _lines(res, "⚠", UNREACHABLE)]
    assert done == [], "reported as deleted although the delete failed: " + str(done)
    assert warn == [f"⚠ secret {UNREACHABLE} not deleted (unknown error)"], res.stdout


def test_foreign_oidc_providers_are_never_deleted(run):
    """6f skips regional OIDC providers that are neither recorded for this stack nor
    tagged with one of its cluster names, and says so."""
    res, calls = run
    deleted = [c[2].get("open-id-connect-provider-arn", "") for c in calls
               if c[1] == "delete-open-id-connect-provider"]
    assert not [a for a in deleted if any(a.endswith("/" + f) for f in FOREIGN_OIDC)], deleted
    for f in FOREIGN_OIDC:
        assert [ln for ln in res.stdout.splitlines() if "skip OIDC provider " + f + " " in ln], res.stdout


def test_oidc_record_is_kept_in_private_and_survives_a_rerun(tmp_path):
    """The record step writes this install's issuer ids under private/ (gitignored, not
    /tmp) and merges on a re-run, so a destroy re-run after the clusters are gone still
    knows them. Clusters of other stacks are not recorded."""
    rec = _record_step()
    assert "/tmp/" not in rec, "the OIDC record must not live in /tmp"
    issuer = "https://" + OIDC
    first = dict(FIXTURE, clusters={
        HUB: {"identity": {"oidc": {"issuer": issuer + "HUBID"}}, "tags": {}},
        "acme-custom-dev": {"identity": {"oidc": {"issuer": issuer + "TAGGEDSPOKE"}},
                            "tags": {"platform.gitops.io/prefix": PREFIX}},
        "other-hub": {"identity": {"oidc": {"issuer": issuer + "OTHERID"}},
                      "tags": {"platform.gitops.io/prefix": "other"}}})
    res, _ = _run(tmp_path, cmd=rec, fixture_data=first)
    assert res.returncode == 0, res.stdout + res.stderr
    out = tmp_path / "private" / f"{HUB}-destroy-oidc-ids"
    assert out.read_text().split("\n")[:-1] == ["HUBID " + HUB, "TAGGEDSPOKE acme-custom-dev"]
    # Re-run once every cluster is gone: the earlier ids are kept, not truncated.
    res, _ = _run(tmp_path, cmd=rec, fixture_data=dict(FIXTURE, clusters={}))
    assert res.returncode == 0, res.stdout + res.stderr
    assert out.read_text().split("\n")[:-1] == ["HUBID " + HUB, "TAGGEDSPOKE acme-custom-dev"]
