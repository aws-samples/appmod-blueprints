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
    "oidc": ["OKOKOK", "DENIEDDENIED"],
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
ALLOWED = [FIXTURE["secrets"][0], "ws-ok", "devlake-ok", "OKOKOK", "s-okok", FIXTURE["log_groups"][3]]
UNREACHABLE = FIXTURE["secrets"][2]

# The RDS (6eii), log-group (6g) and VPC (6h/6h2) sweeps are python helpers using boto3:
# a fake boto3 on PYTHONPATH answers them from the same fixture and fails the denied
# deletes the way botocore does (ClientError carrying the code and a message naming the
# principal). Nothing is sent and no wait is slept.
FAKE_BOTO3 = r'''
import json, os, time
time.sleep = lambda *a, **k: None
_FX = json.load(open(os.environ["FAKE_AWS_FIXTURE"]))
class ClientError(Exception):
    def __init__(self, code, op):
        self.response = {"Error": {"Code": code, "Message": "User: arn:aws:sts::%s:assumed-role/SharedRole/i-0 "
                                   "is not authorized to perform: %s" % (_FX["acct"], op)}}
        super().__init__("An error occurred (%s) when calling the %s operation: %s"
                         % (code, op, self.response["Error"]["Message"]))
class _Client:
    def __init__(self, svc):
        self._svc = svc
    def __getattr__(self, op):
        def call(**kw):
            with open(os.environ["FAKE_AWS_LOG"], "a") as f:
                f.write(json.dumps([self._svc, op, kw]) + "\n")
            if op in _FX.get("boto_fail_ops", []):  # e.g. EKS denied in one region by an SCP
                raise ClientError("AccessDeniedException", op)
            if (self._svc, op) == ("rds", "describe_db_instances"):
                return {"DBInstances": [{"DBInstanceIdentifier": d, "DBInstanceStatus": "available"}
                                        for d in _FX["dbs"]]}
            if (self._svc, op) == ("logs", "describe_log_groups"):
                return {"logGroups": [{"logGroupName": g} for g in _FX["log_groups"]
                                      if g.startswith(kw.get("logGroupNamePrefix", ""))]}
            if (self._svc, op) == ("ec2", "describe_vpcs"):
                return {"Vpcs": []}
            if op.startswith(("describe_", "list_", "get_")):
                return {}
            target = next((v for v in kw.values() if isinstance(v, str)), "")
            if target in _FX["deny"]:
                raise ClientError("AccessDeniedException", op)
            return {}
        return call
def client(svc, **kw):
    return _Client(svc)
class Session:  # sweep_lib.session(): same profile as the CLI, credentials checked
    def __init__(self, **kw):
        pass
    def get_credentials(self):
        return object()
    def client(self, svc, **kw):
        return _Client(svc)
'''

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
if op in fx.get("fail_ops", []):  # a list call that fails (throttled, denied, endpoint down)
    sys.stderr.write("\nAn error occurred (Throttling) when calling the %s operation: Rate exceeded\n" % op)
    sys.exit(254)
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
    ("eks", "list-clusters"): {"clusters": []},
    ("iam", "list-open-id-connect-providers"): {"OpenIDConnectProviderList": [
        {"Arn": "arn:aws:iam::%s:oidc-provider/%s%s" % (fx["acct"], fx["oidc_url"], o)} for o in fx["oidc"]]},
    ("iam", "list-roles"): {"Roles": []},
    ("iam", "list-policies"): {"Policies": []},
    ("ec2", "describe-vpcs"): {"Vpcs": []},
}.get((svc, op), {})
if (svc, op) == ("iam", "get-open-id-connect-provider"):
    out = {"Url": opts["open-id-connect-provider-arn"].split("oidc-provider/", 1)[1]}
if (svc, op) == ("elbv2", "describe-load-balancers"):
    out = {"LoadBalancers": [{"LoadBalancerArn": a} for a in fx.get("albs", {})]}
if (svc, op) == ("elbv2", "describe-tags"):
    arn_ = opts.get("resource-arns", "")
    out = {"TagDescriptions": [{"ResourceArn": arn_, "Tags": [
        {"Key": "elbv2.k8s.aws/cluster", "Value": fx.get("albs", {}).get(arn_, "")}]}]}
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


def _step6(marker="# 6g."):
    with open(TASKFILE) as f:
        cmds = yaml.safe_load(f)["tasks"]["destroy"]["cmds"]
    return next(c["cmd"] for c in cmds if isinstance(c, dict) and marker in c.get("cmd", ""))


def _run(tmp_path, **overrides):
    cmd = _step6(overrides.pop("marker", "# 6g.")).replace("{{.ROOT_DIR}}", REPO)
    bindir, pylib = tmp_path / "bin", tmp_path / "pylib" / "boto3"
    bindir.mkdir()
    pylib.mkdir(parents=True)
    (pylib / "__init__.py").write_text(FAKE_BOTO3)
    (bindir / "aws").write_text(FAKE_AWS.replace("{python}", sys.executable))
    (bindir / "python3").write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
    for b in ("aws", "python3"):
        (bindir / b).chmod(0o755)
    fixture, log = tmp_path / "fixture.json", tmp_path / "aws.jsonl"
    fixture.write_text(json.dumps(dict(FIXTURE, acct=ACCT, oidc_url=OIDC, **overrides.pop("fixture", {}))))
    log.write_text("")
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", PYTHONPATH=str(tmp_path / "pylib"),
               FAKE_AWS_FIXTURE=str(fixture), FAKE_AWS_LOG=str(log),
               SWEEP_FAILURES_FILE=str(tmp_path / "private" / "destroy-sweep-failures"))
    tvars = {"AWS_REGION": REGION, "RESOURCE_PREFIX": PREFIX, "HUB_CLUSTER_NAME": HUB, "HUB_VPC_ID": "",
             "DESTROY_KEEP_DATA": "false", **overrides.pop("tvars", {})}
    (tmp_path / "private").mkdir(exist_ok=True)
    cmd = cmd.replace(REPO + "/private/", str(tmp_path / "private") + "/")
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
        script.write_text("set -euo pipefail\n" + cmd)
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
    last_delete = max(i for i, o in enumerate(ops) if o == "delete_log_group")
    assert "describe-vpcs" in ops[last_delete:], "step 6i never ran: " + ", ".join(ops[last_delete:])


def test_failure_without_an_aws_error_code_says_unknown_error(run):
    res, _ = run
    done = _lines(res, "✓", UNREACHABLE)
    warn = [ln.strip() for ln in _lines(res, "⚠", UNREACHABLE)]
    assert done == [], "reported as deleted although the delete failed: " + str(done)
    assert warn == [f"⚠ secret {UNREACHABLE} not deleted (unknown error)"], res.stdout


def test_a_failing_list_roles_does_not_skip_the_rest_of_step6(tmp_path):
    """Review #1174: under pipefail a failing `aws iam list-roles` aborted step 6 and
    skipped 6b2-6i while the final check still printed success."""
    res, calls = _run(tmp_path, fixture={"fail_ops": ["list-roles", "list-policies"]})
    ops = [c[1] for c in calls]
    assert res.returncode == 0, res.stdout + res.stderr
    assert "delete_log_group" in ops and "describe-vpcs" in ops, "6g/6i never ran: " + ", ".join(ops)
    assert "IAM roles not swept" in res.stdout and "IAM policies not swept" in res.stdout
    failed = (tmp_path / "private" / "destroy-sweep-failures").read_text().split()
    assert "iam-list-roles(6b)" in failed and "iam-list-policies(6c)" in failed


@pytest.mark.parametrize("marker,step", [("# 3. Orphaned ACK-managed IAM roles", "3"), ("# 6g.", "6b")])
def test_a_failed_iam_guard_is_recorded_for_the_final_check(tmp_path, marker, step):
    """Review #1174 (re-review): when the all-region guard can't read EKS (one region
    denied is enough), the role sweep is skipped. That must land in
    destroy-sweep-failures, or destroy prints success with the roles left behind."""
    res, calls = _run(tmp_path, marker=marker, fixture={"boto_fail_ops": ["list_clusters"]})
    assert res.returncode == 0, res.stdout + res.stderr
    assert "not sweeping IAM roles (%s)" % step in res.stdout
    assert not [c for c in calls if c[:2] == ["iam", "list-roles"]], "roles listed despite the failed guard"
    failed = (tmp_path / "private" / "destroy-sweep-failures").read_text().split()
    assert "iam-guard(%s)" % step in failed


def test_step1_deletes_only_the_albs_of_this_stacks_clusters_by_exact_name(tmp_path):
    """Review #1174 (re-review): step 1 matched "${PREFIX}-*", so destroying prefix
    acme also deleted the ALBs of a live acme-a-hub. Only the exact stack names go
    (hub, inventory spokes, legacy spokes); a retained spoke keeps its ALB."""
    (tmp_path / "private").mkdir(exist_ok=True)
    (tmp_path / "private" / "destroy-inventory.json").write_text(json.dumps({
        "hub_vpc_id": "", "clusters": [{"name": "team-dev", "deletionPolicy": "delete"},
                                       {"name": f"{PREFIX}-prod", "deletionPolicy": "retain"}]}))
    albs = {f"arn:alb/{n}": n for n in (HUB, "team-dev", f"{PREFIX}-spoke-dev", f"{PREFIX}-a-hub",
                                         f"{PREFIX}-prod", "other-hub")}
    albs["arn:alb/untagged"] = ""
    res, calls = _run(tmp_path, marker="# 3. Orphaned ACK-managed IAM roles", fixture={"albs": albs})
    assert res.returncode == 0, res.stdout + res.stderr
    gone = sorted(c[2]["load-balancer-arn"] for c in calls if c[:2] == ["elbv2", "delete-load-balancer"])
    assert gone == sorted(f"arn:alb/{n}" for n in (HUB, "team-dev", f"{PREFIX}-spoke-dev"))


def test_hub_vpc_sweep_is_skipped_for_a_pre_existing_vpc(tmp_path):
    res, _ = _run(tmp_path, tvars={"HUB_VPC_ID": "vpc-0123456789abcdef0"})
    assert res.returncode == 0, res.stdout + res.stderr
    assert "hub.network.vpcId is set" in res.stdout


def test_keep_data_snapshots_rds_and_keeps_volumes(tmp_path):
    res, calls = _run(tmp_path, tvars={"DESTROY_KEEP_DATA": "true"})
    assert res.returncode == 0, res.stdout + res.stderr
    rds = [c for c in calls if c[0] == "rds" and c[1] == "delete_db_instance"]
    assert rds and all(c[2].get("SkipFinalSnapshot") is False and c[2].get("FinalDBSnapshotIdentifier")
                       for c in rds), rds
