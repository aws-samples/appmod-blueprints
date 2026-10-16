"""Hermetic tests for kind-kro-ack `task destroy` step 6 (extended AWS sweep): a delete
that fails is not reported as done.

The step-6 cmd is read verbatim from cluster-providers/kind-kro-ack/Taskfile.yaml and run
under go-task's own interpreter with the Taskfile's `set:` options (bash with
`set -euo pipefail` if go-task is not on PATH). `aws` is a fake on PATH that answers the
list/describe calls from a fixture with --query applied by jmespath, as the AWS CLI does,
and fails the deletes the fixture denies the way the CLI does (exit 254, "An error
occurred (AccessDeniedException) when calling the ... operation: ..." on stderr). No AWS,
no network.

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
                f"arn:aws:secretsmanager:{REGION}:{ACCT}:secret:{PREFIX}-denied-GhIjKl"],
    "workspaces": [{"alias": f"{PREFIX}-observability-amp", "workspaceId": "ws-ok"},
                   {"alias": f"{PREFIX}-other-amp", "workspaceId": "ws-denied"}],
    "dbs": ["devlake-ok", "devlake-denied"],
    "oidc": ["OKOKOK", "DENIEDDENIED"],
    "log_groups": [f"/aws/eks/{HUB}/cluster", f"/aws/eks/{HUB}/capability/kro",
                   f"/aws/eks/{PREFIX}-spoke-dev/cluster", f"/aws/eks/{PREFIX}-spoke-prod/cluster"],
    # Denied deletes: one of each kind, and three of the four log groups.
    "deny": [f"{PREFIX}-denied", "ws-denied", "devlake-denied", "DENIEDDENIED",
             f"/aws/eks/{HUB}/cluster", f"/aws/eks/{HUB}/capability/kro",
             f"/aws/eks/{PREFIX}-spoke-dev/cluster"],
}
DENIED = [FIXTURE["secrets"][1], "ws-denied", "devlake-denied", "DENIEDDENIED",
          *FIXTURE["log_groups"][:3]]
ALLOWED = [FIXTURE["secrets"][0], "ws-ok", "devlake-ok", "OKOKOK", FIXTURE["log_groups"][3]]

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
       "delete-log-group": ("log-group-name", "DeleteLogGroup")}
if op in OPS:
    key, api = OPS[op]
    target = opts.get(key, "")
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
    ("amp", "list-scrapers"): {"scrapers": []},
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
if (svc, op) == ("logs", "describe-log-groups"):
    out = {"logGroups": [{"logGroupName": g} for g in fx["log_groups"]
                         if g.startswith(opts.get("log-group-name-prefix", ""))]}
if "query" in opts:
    out = jmespath.search(opts["query"], out)
def text(v):
    if v is None:
        return "None"
    if isinstance(v, list):
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


def _run(tmp_path):
    cmd = _step6()
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "aws").write_text(FAKE_AWS.replace("{python}", sys.executable))
    (bindir / "aws").chmod(0o755)
    fixture, log = tmp_path / "fixture.json", tmp_path / "aws.jsonl"
    fixture.write_text(json.dumps(dict(FIXTURE, acct=ACCT, oidc_url=OIDC)))
    log.write_text("")
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}",
               FAKE_AWS_FIXTURE=str(fixture), FAKE_AWS_LOG=str(log))
    tvars = {"AWS_REGION": REGION, "RESOURCE_PREFIX": PREFIX, "HUB_CLUSTER_NAME": HUB}
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
