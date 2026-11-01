"""Tests for the orphans found by the first real kind-kro-ack teardown with this
branch (input from that run), fixed in task kind-kro-ack:destroy:

1. DeleteCluster is retried on ResourceInUseException instead of being sent once.
2. Available EBS volumes owned by a removed cluster of the stack are deleted.
3. Target groups of a removed cluster (no load balancer) are deleted.
4. CloudWatch Logs delivery sources/destinations of the hub are deleted.
5. Secrets already scheduled for deletion are listed (and force-deleted).
6. The IAM guard keeps a role a live cluster's access entry still references
   (already covered in test_sweep_orphans.py; documented in the README).

Fakes only: no AWS, no network, no sleeping.

Run:  python -m pytest workshop/scripts/tests/test_destroy_teardown_leftovers.py -q
"""
import importlib.util
import os
import stat
import subprocess
import sys

import yaml

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO, "scripts"))
import sweep_lib as sl  # noqa: E402

TASKFILE = os.path.join(REPO, "cluster-providers", "kind-kro-ack", "Taskfile.yaml")
ACCT = "111122223333"


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), os.path.join(REPO, "scripts", name))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class AwsError(Exception):
    def __init__(self, code):
        self.response = {"Error": {"Code": code}}
        super().__init__(f"An error occurred ({code}) when calling the op")


class FakeEks:
    def __init__(self, live=()):
        self.live = list(live)

    def list_clusters(self, **_):
        return {"clusters": self.live}

    def describe_cluster(self, name):
        return {"cluster": {"status": "ACTIVE", "resourcesVpcConfig": {"vpcId": ""}, "roleArn": "", "tags": {}}}


class FakeEc2:
    def __init__(self, volumes):
        self.volumes = volumes  # id -> {"cluster": name, "status": ...}
        self.deleted = []

    def describe_volumes(self, Filters=(), NextToken=None):
        want = {v for f in Filters if f["Name"] == "status" for v in f["Values"]}
        items = list(self.volumes.items())
        page, rest = items[:2], items[2:]
        if NextToken:
            page, rest = items[2:], []
        out = [{"VolumeId": i, "Tags": [{"Key": f"kubernetes.io/cluster/{v['cluster']}", "Value": v.get("value", "owned")}]}
               for i, v in page if not want or v["status"] in want]
        return {"Volumes": out, **({"NextToken": "p2"} if rest else {})}

    def delete_volume(self, VolumeId):
        self.deleted.append(VolumeId)


class FakeElbv2:
    def __init__(self, tgs):
        self.tgs = tgs  # name -> {"cluster": c, "lbs": [...]}
        self.deleted = []

    def _arn(self, n):
        return f"arn:aws:elasticloadbalancing:us-west-2:{ACCT}:targetgroup/{n}/abc"

    def describe_target_groups(self, Marker=None):
        return {"TargetGroups": [{"TargetGroupArn": self._arn(n), "LoadBalancerArns": t.get("lbs", [])}
                                 for n, t in self.tgs.items()]}

    def describe_tags(self, ResourceArns):
        by = {self._arn(n): t for n, t in self.tgs.items()}
        return {"TagDescriptions": [{"ResourceArn": a, "Tags": ([{"Key": "elbv2.k8s.aws/cluster", "Value": by[a]["cluster"]}]
                                                                 if by[a].get("cluster") else [])} for a in ResourceArns]}

    def delete_target_group(self, TargetGroupArn):
        self.deleted.append(TargetGroupArn.split("/")[1])


class FakeLogs:
    def __init__(self, sources, dests, deliveries=()):
        self.sources, self.dests, self.deliveries = list(sources), list(dests), list(deliveries)
        self.deleted = []

    def describe_deliveries(self, **_):
        return {"deliveries": [{"deliverySourceName": s, "deliveryDestinationArn": f"arn:dest/{d}"}
                               for s, d in self.deliveries]}

    def describe_delivery_sources(self, **_):
        return {"deliverySources": [{"name": s} for s in self.sources]}

    def describe_delivery_destinations(self, **_):
        return {"deliveryDestinations": [{"name": d, "arn": f"arn:dest/{d}"} for d in self.dests]}

    def delete_delivery_source(self, name):
        self.deleted.append(("source", name))

    def delete_delivery_destination(self, name):
        self.deleted.append(("dest", name))


def account():
    ec2 = FakeEc2({
        "vol-hub-1": {"cluster": "hb-hub", "status": "available"},
        "vol-hub-2": {"cluster": "hb-hub", "status": "available"},
        "vol-dev": {"cluster": "hb-dev", "status": "available"},
        "vol-inuse": {"cluster": "hb-hub", "status": "in-use"},
        "vol-other-hub": {"cluster": "ha-hub", "status": "available"},
        "vol-retained": {"cluster": "hb-prod", "status": "available"},
        "vol-shared": {"cluster": "hb-hub", "status": "available", "value": "shared"},
    })
    elbv2 = FakeElbv2({
        "k8s-backstag": {"cluster": "hb-hub"},
        "k8s-kargo": {"cluster": "hb-hub"},
        "k8s-with-lb": {"cluster": "hb-hub", "lbs": ["arn:lb"]},
        "k8s-other": {"cluster": "ha-hub"},
        "untagged": {},
    })
    logs = FakeLogs(["hb-hub-kro", "ha-hub-kro"], ["hb-hub-kro-cwl", "ha-hub-kro-cwl"])
    inventory = {"clusters": [{"name": "hb-dev", "deletionPolicy": "delete"},
                              {"name": "hb-prod", "deletionPolicy": "retain"}]}
    return ec2, elbv2, logs, inventory


def test_leftovers_of_the_removed_hub_and_spoke_are_selected_and_nothing_else():
    ec2, elbv2, logs, inv = account()
    r = sl.sweep_hub_leftovers(ec2, elbv2, logs, "hb", "hb-hub", {"ha-hub": {"status": "ACTIVE", "vpc": ""}}, inv)
    assert sorted(ec2.deleted) == ["vol-dev", "vol-hub-1", "vol-hub-2"]
    assert sorted(elbv2.deleted) == ["k8s-backstag", "k8s-kargo"]
    assert logs.deleted == [("source", "hb-hub-kro"), ("dest", "hb-hub-kro-cwl")]
    assert r["deleted"] == 7


def test_nothing_is_swept_while_the_hub_is_still_live():
    ec2, elbv2, logs, inv = account()
    clusters = {"hb-hub": {"status": "ACTIVE", "vpc": ""}, "ha-hub": {"status": "ACTIVE", "vpc": ""}}
    sl.sweep_hub_leftovers(ec2, elbv2, logs, "hb", "hb-hub", clusters, inv)
    assert ec2.deleted == ["vol-dev"], "only the removed spoke's volume"
    assert elbv2.deleted == [] and logs.deleted == []


def test_live_spoke_with_the_prefix_keeps_its_volumes():
    ec2, elbv2, logs, inv = account()
    clusters = {"hb-dev": {"status": "ACTIVE", "vpc": ""}}
    sl.sweep_hub_leftovers(ec2, elbv2, logs, "hb", "hb-hub", clusters, inv)
    assert "vol-dev" not in ec2.deleted


def test_delivery_source_still_used_by_a_delivery_is_kept():
    logs = FakeLogs(["hb-hub-kro"], ["hb-hub-kro-cwl"], deliveries=[("hb-hub-kro", "hb-hub-kro-cwl")])
    assert sl.select_log_deliveries(logs, "hb-hub", True) == ([], [])


def test_dry_run_deletes_nothing(capsys):
    ec2, elbv2, logs, inv = account()
    r = sl.sweep_hub_leftovers(ec2, elbv2, logs, "hb", "hb-hub", {}, inv, dry_run=True)
    assert ec2.deleted == elbv2.deleted == logs.deleted == []
    assert r["deleted"] == 0 and len(r["volumes"]) == 3
    assert "would delete EBS volume" in capsys.readouterr().out


def test_cli_never_fails_and_reports_codes_only(capsys, tmp_path):
    mod = load("sweep-hub-leftovers.py")
    inv = tmp_path / "destroy-inventory.json"
    inv.write_text('{"clusters": [{"name": "hb-dev", "deletionPolicy": "delete"}, '
                   '{"name": "hb-prod", "deletionPolicy": "retain"}]}')

    class Broken(FakeEks):
        def list_clusters(self, **_):
            raise AwsError("AccessDeniedException")
    ec2, elbv2, logs, _ = account()
    assert mod.main(["hb", "us-west-2", "hb-hub"], ec2=ec2, elbv2=elbv2, logs=logs, eks=Broken()) == 0
    out = capsys.readouterr().out
    assert "AccessDeniedException" in out and ACCT not in out
    assert ec2.deleted == []
    assert mod.main(["hb", "us-west-2", "hb-hub", "--inventory", str(inv)],
                    ec2=ec2, elbv2=elbv2, logs=logs, eks=FakeEks()) == 0
    assert "hub leftovers: 7 selected, 7 deleted" in capsys.readouterr().out


def test_a_longer_prefix_is_not_ours():
    """Review #1174: destroying prefix "hb" must not take the leftovers of an
    "hb-a-hub" stack (its prefix starts with ours) or of an unrecorded hb-* cluster."""
    ec2 = FakeEc2({
        "vol-hub": {"cluster": "hb-hub", "status": "available"},
        "vol-nested-hub": {"cluster": "hb-a-hub", "status": "available"},
        "vol-unrecorded": {"cluster": "hb-something", "status": "available"},
        "vol-legacy": {"cluster": "hb-spoke-dev", "status": "available"},
    })
    elbv2 = FakeElbv2({"k8s-nested": {"cluster": "hb-a-hub"}, "k8s-own": {"cluster": "hb-hub"}})
    logs = FakeLogs([], [])
    sl.sweep_hub_leftovers(ec2, elbv2, logs, "hb", "hb-hub", {}, {"clusters": []})
    assert sorted(ec2.deleted) == ["vol-hub", "vol-legacy"]
    assert elbv2.deleted == ["k8s-own"]


def test_keep_data_keeps_the_volumes_and_still_sweeps_the_rest():
    ec2, elbv2, logs, inv = account()
    r = sl.sweep_hub_leftovers(ec2, elbv2, logs, "hb", "hb-hub", {}, inv, keep_data=True)
    assert ec2.deleted == [] and r["volumes"] == []
    assert sorted(elbv2.deleted) == ["k8s-backstag", "k8s-kargo"]


def test_final_snapshot_id_is_a_valid_rds_identifier():
    sid = sl.final_snapshot_id("hb-devlake-db", now=0)
    assert sid == "hb-devlake-db-final-19700101000000" and "--" not in sid


# ------------------------------------------------------------------ Taskfile

def destroy_cmds():
    t = yaml.safe_load(open(TASKFILE))
    return [c if isinstance(c, str) else c.get("cmd", "") for c in t["tasks"]["destroy"]["cmds"]]


def hub_delete_cmd():
    return next(c for c in destroy_cmds() if c and "HUB_DELETE_TRIES" in c)


FAKE_AWS = """#!/bin/bash
# fake aws: describe-cluster -> ACTIVE until delete accepted; delete-cluster refused N times
S=%(state)s
case "$*" in
  *"eks describe-cluster"*) [ -f "$S/deleting" ] && echo DELETING || echo ACTIVE ;;
  *"eks delete-cluster"*)
    n=$(cat "$S/refusals" 2>/dev/null || echo 0); echo $((n+1)) > "$S/calls.tmp"; c=$(cat "$S/calls" 2>/dev/null || echo 0); echo $((c+1)) > "$S/calls"
    if [ "$n" -gt 0 ]; then echo $((n-1)) > "$S/refusals"
      echo "An error occurred (ResourceInUseException) when calling the DeleteCluster operation: update in progress" >&2; exit 254; fi
    touch "$S/deleting"; echo '{}' ;;
  *) exit 0 ;;
esac
"""


def run_hub_delete(tmp_path, refusals, tries=5):
    state = tmp_path / "state"
    state.mkdir()
    (state / "refusals").write_text(str(refusals))
    bindir = tmp_path / "bin"
    bindir.mkdir()
    aws = bindir / "aws"
    aws.write_text(FAKE_AWS % {"state": state})
    aws.chmod(aws.stat().st_mode | stat.S_IEXEC)
    script = hub_delete_cmd().replace("{{.HUB_CLUSTER_NAME}}", "hb-hub").replace("{{.AWS_REGION}}", "us-west-2")
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", HUB_DELETE_RETRY_SEC="0", HUB_DELETE_TRIES=str(tries))
    res = subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True)
    calls = int((state / "calls").read_text()) if (state / "calls").exists() else 0
    return res, calls, (state / "deleting").exists()


def test_hub_delete_is_retried_on_resource_in_use(tmp_path):
    res, calls, deleting = run_hub_delete(tmp_path, refusals=2)
    assert deleting and calls == 3, res.stdout + res.stderr
    assert "ResourceInUseException" in res.stderr, "the refusal stays visible"
    assert "retrying" in res.stdout and "Submitted hub EKS cluster deletion" in res.stdout


def test_hub_delete_gives_up_after_the_bound(tmp_path):
    res, calls, deleting = run_hub_delete(tmp_path, refusals=99, tries=3)
    assert not deleting and calls == 3


def test_hub_delete_sent_once_when_accepted(tmp_path):
    res, calls, deleting = run_hub_delete(tmp_path, refusals=0)
    assert deleting and calls == 1


def test_wiring_leftovers_after_deliveries_and_planned_deletion_secrets():
    text = "\n".join(destroy_cmds())
    i_deliv = text.index("aws logs delete-delivery --id")
    i_left = text.index('/scripts/sweep-hub-leftovers.py"')
    i_wait = text.index("Hub EKS status")
    assert i_wait < i_deliv < i_left, "leftovers swept after the hub is gone and the deliveries"
    sec = text[text.index("# 6di."):text.index("# 6e.")]
    assert "--include-planned-deletion" in sec and "--force-delete-without-recovery" in sec


def test_readme_documents_the_access_entry_guard():
    readme = open(os.path.join(REPO, "cluster-providers", "README.md")).read()
    assert "access entr" in readme and "sweep-iam-guard.py" in readme
