"""Tests for the residue the demo5 teardowns of two kind-kro-ack installs left in AWS
(task kind-kro-ack:destroy), one test group per residue:

1. Target groups: the delete answered ResourceInUse because step 1 had just deleted
   their ALB; it is now retried, bounded.
2. Fluent Bit log group /aws/eks/fluentbit-cloudwatch/<cluster>/logs: outside the
   /aws/eks/<cluster>/ rule, now swept by the same exact-name rule.
3. Legacy fixed-name IAM policies (<app>-<component>-iam-policy): retained by step 0
   and never deleted; now deleted by their last user when attached to nothing.
4. AgentCore memory, SNS topic, SQS queue and DLQ of the aiops-agent OAM app:
   recorded from the hub's CRs while it is readable, deleted once it is gone
   (2c), and the OAM app is drained before its controllers go (6c).
Every sweep is scoped to THIS install: another prefix, a longer prefix, a live hub
and anything not recorded from this hub are left alone. Fakes only: no AWS, no
cluster, no network, no sleeping.

Run:  python -m pytest workshop/scripts/tests/test_destroy_residue_demo5.py -q
"""
import importlib.util
import json
import os
import sys

import pytest
import yaml

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO, "scripts"))
import sweep_lib as sl  # noqa: E402

TASKFILE = os.path.join(REPO, "cluster-providers", "kind-kro-ack", "Taskfile.yaml")
ACCT = "111122223333"
REGION = "us-west-2"


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), os.path.join(REPO, "scripts", name))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class AwsError(Exception):
    def __init__(self, code):
        self.response = {"Error": {"Code": code}}
        super().__init__(f"An error occurred ({code}) when calling the op")


@pytest.fixture(autouse=True)
def _failures_file(tmp_path, monkeypatch):
    path = tmp_path / "private" / "destroy-sweep-failures"
    monkeypatch.setenv(sl.FAILURES_FILE_ENV, str(path))
    return path


class FakeEks:
    def __init__(self, live=()):
        self.live = list(live)

    def list_clusters(self, **_):
        return {"clusters": self.live}

    def describe_cluster(self, name):
        return {"cluster": {"status": "ACTIVE", "resourcesVpcConfig": {"vpcId": ""}, "roleArn": "", "tags": {}}}


# ------------------------------------------------------------- 1. target groups

class BusyElbv2:
    """Target groups whose delete answers ResourceInUse `busy` times, then succeeds."""

    def __init__(self, tgs, busy=0, code="ResourceInUse"):
        self.tgs, self.busy, self.code = tgs, dict.fromkeys(tgs, busy), code
        self.calls, self.deleted = [], []

    def _arn(self, n):
        return f"arn:aws:elasticloadbalancing:{REGION}:{ACCT}:targetgroup/{n}/abc"

    def describe_target_groups(self, Marker=None):
        return {"TargetGroups": [{"TargetGroupArn": self._arn(n), "LoadBalancerArns": []} for n in self.tgs]}

    def describe_tags(self, ResourceArns):
        by = {self._arn(n): c for n, c in self.tgs.items()}
        return {"TagDescriptions": [{"ResourceArn": a, "Tags": [{"Key": "elbv2.k8s.aws/cluster", "Value": by[a]}]}
                                    for a in ResourceArns]}

    def delete_target_group(self, TargetGroupArn):
        n = TargetGroupArn.split("/")[1]
        self.calls.append(n)
        if self.busy[n] > 0:
            self.busy[n] -= 1
            raise AwsError(self.code)
        self.deleted.append(n)


class Empty:
    def describe_volumes(self, **_):
        return {"Volumes": []}

    def describe_deliveries(self, **_):
        return {"deliveries": []}

    def describe_delivery_sources(self, **_):
        return {"deliverySources": []}

    def describe_delivery_destinations(self, **_):
        return {"deliveryDestinations": []}


def _leftovers(elbv2, **kw):
    sleeps = []
    r = sl.sweep_hub_leftovers(Empty(), elbv2, Empty(), "hb", "hb-hub", {}, {"clusters": []},
                               sleep=sleeps.append, **kw)
    return r, sleeps


def test_target_group_in_use_right_after_the_alb_delete_is_retried():
    elbv2 = BusyElbv2({"k8s-aiopsage-x": "hb-hub", "k8s-backstag-x": "hb-hub"}, busy=3)
    r, sleeps = _leftovers(elbv2)
    assert sorted(elbv2.deleted) == ["k8s-aiopsage-x", "k8s-backstag-x"]
    assert r["deleted"] == 2 and len(sleeps) == 6


def test_target_group_retry_is_bounded(capsys):
    elbv2 = BusyElbv2({"k8s-kargo-x": "hb-hub"}, busy=99)
    r, sleeps = _leftovers(elbv2, tg_attempts=4, tg_delay=10)
    assert elbv2.deleted == [] and len(elbv2.calls) == 4 and sleeps == [10, 10, 10]
    assert "target group k8s-kargo-x not deleted (ResourceInUse)" in capsys.readouterr().out


def test_target_group_other_error_is_not_retried():
    elbv2 = BusyElbv2({"k8s-kargo-x": "hb-hub"}, busy=1, code="AccessDenied")
    _, sleeps = _leftovers(elbv2)
    assert elbv2.calls == ["k8s-kargo-x"] and sleeps == []


def test_target_group_of_another_install_is_not_touched():
    elbv2 = BusyElbv2({"k8s-a": "hb-a-hub", "k8s-b": "ha-hub", "k8s-ours": "hb-hub"})
    _leftovers(elbv2)
    assert elbv2.deleted == ["k8s-ours"]


def test_target_group_dry_run_deletes_nothing():
    elbv2 = BusyElbv2({"k8s-ours": "hb-hub"})
    r = sl.sweep_hub_leftovers(Empty(), elbv2, Empty(), "hb", "hb-hub", {}, {"clusters": []}, dry_run=True)
    assert elbv2.calls == [] and r["target_groups"]


# ------------------------------------------------------------ 2. Fluent Bit log group

class FakeLogGroups:
    def __init__(self, groups):
        self.groups = groups
        self.deleted = []

    def describe_log_groups(self, logGroupNamePrefix, nextToken=None):
        return {"logGroups": [{"logGroupName": g} for g in self.groups if g.startswith(logGroupNamePrefix)]}

    def delete_log_group(self, logGroupName):
        self.deleted.append(logGroupName)


FB = "/aws/eks/fluentbit-cloudwatch"


def test_fluentbit_log_groups_of_the_removed_clusters_are_selected():
    logs = FakeLogGroups([f"{FB}/hb-dev/logs", f"{FB}/hb-hub/logs", f"{FB}/logs",
                          f"{FB}/hb-a-dev/logs", f"{FB}/ha-dev/logs", "/aws/eks/hb-dev/cluster"])
    inv = {"clusters": [{"name": "hb-dev", "deletionPolicy": "delete"}]}
    sel, _ = sl.select_log_groups(logs, "hb", "hb-hub", {}, inv)
    assert sorted(sel) == sorted(["/aws/eks/hb-dev/cluster", f"{FB}/hb-dev/logs", f"{FB}/hb-hub/logs"])


def test_fluentbit_log_group_kept_while_cluster_live_or_retained():
    logs = FakeLogGroups([f"{FB}/hb-dev/logs", f"{FB}/hb-prod/logs"])
    inv = {"clusters": [{"name": "hb-dev"}, {"name": "hb-prod", "deletionPolicy": "retain"}]}
    clusters = {"hb-dev": {"status": "ACTIVE", "vpc": "", "roleArn": "", "tags": {}}}
    sel, skipped = sl.select_log_groups(logs, "hb", "hb-hub", clusters, inv)
    assert sel == [] and {g for g, _ in skipped} == {f"{FB}/hb-dev/logs", f"{FB}/hb-prod/logs"}


def test_fluentbit_shared_default_group_is_never_swept():
    logs = FakeLogGroups([f"{FB}/logs", f"{FB}/"])
    sel, skipped = sl.select_log_groups(logs, "hb", "hb-hub", {}, {"clusters": []})
    assert sel == [] and skipped == []


def test_fluentbit_log_group_cli_dry_run(capsys):
    mod = load("sweep-log-groups.py")
    logs = FakeLogGroups([f"{FB}/hb-hub/logs"])
    assert mod.main(["hb", REGION, "hb-hub", "--dry-run"], logs=logs, eks=FakeEks()) == 0
    assert logs.deleted == []
    assert f"[dry-run] would delete log group {FB}/hb-hub/logs" in capsys.readouterr().out


# --------------------------------------------------------- 3. legacy shared policies

LEGACY = ["aiops-agent-hub-aiops-agent-memory-iam-policy", "aiops-agent-hub-eks-read-access-iam-policy"]


class FakeKubectl:
    def __init__(self, crs):
        self.crs = crs
        self.calls = []

    def __call__(self, args):
        if args[0] == "get":
            items = self.crs.get(args[1])
            if items is None:
                return 1, ""
            return 0, json.dumps({"items": items})
        self.calls.append(args)
        return 0, ""


def xp(name, ext=None, **spec):
    return {"metadata": {"name": name, "annotations": {"crossplane.io/external-name": ext or name}},
            "spec": dict({"forProvider": {}}, **spec)}


class PolicyIam:
    def __init__(self, policies):
        self.p = policies  # name -> attachment count
        self.calls = []

    def list_policies(self, Scope, Marker=None):
        return {"Policies": [{"PolicyName": n, "Arn": f"arn:aws:iam::{ACCT}:policy/{n}", "AttachmentCount": c}
                             for n, c in self.p.items()]}

    def list_policy_versions(self, PolicyArn, Marker=None):
        return {"Versions": [{"VersionId": "v2", "IsDefaultVersion": True},
                             {"VersionId": "v1", "IsDefaultVersion": False}]}

    def delete_policy_version(self, PolicyArn, VersionId):
        self.calls.append(("version", PolicyArn.rsplit("/", 1)[1], VersionId))

    def delete_policy(self, PolicyArn):
        self.calls.append(("delete", PolicyArn.rsplit("/", 1)[1]))


def inventory(tmp_path):
    p = tmp_path / "destroy-inventory.json"
    p.write_text(json.dumps({"hub_vpc_id": "", "clusters": []}))
    return str(p)


def test_protect_records_the_retained_legacy_policies(tmp_path):
    mod = load("protect-shared-iam.py")
    kc = FakeKubectl({"policies.iam.aws.upbound.io": [xp(n) for n in LEGACY] + [xp("hb-hub-own-policy")]})
    inv = inventory(tmp_path)
    assert mod.main(["hb", REGION, "hb-hub", "--inventory", inv], eks=FakeEks(["hb-hub"]), kubectl=kc) == 0
    rec = json.loads((tmp_path / "shared-iam-retained.json").read_text())
    assert rec == {"roles": [], "policies": sorted(LEGACY)}
    assert sorted(c[2] for c in kc.calls) == sorted(LEGACY), "own prefixed policy left to its controller"


def test_legacy_policy_deleted_once_attached_to_nothing_and_kept_while_used(tmp_path, capsys):
    mod = load("sweep-shared-iam.py")
    inv = inventory(tmp_path)
    (tmp_path / "shared-iam-retained.json").write_text(json.dumps({"roles": [], "policies": LEGACY}))
    iam = PolicyIam({LEGACY[0]: 0, LEGACY[1]: 1, "not-recorded-policy": 0})
    assert mod.main([REGION, "--inventory", inv], eks=FakeEks(), iam=iam) == 0
    assert iam.calls == [("version", LEGACY[0], "v1"), ("delete", LEGACY[0])]
    out = capsys.readouterr().out
    assert f"keep shared policy {LEGACY[1]}: still attached (1)" in out
    assert "shared IAM policies: 1 deleted, 1 kept" in out


def test_legacy_policy_sweep_dry_run_and_already_gone(tmp_path, capsys):
    mod = load("sweep-shared-iam.py")
    inv = inventory(tmp_path)
    (tmp_path / "shared-iam-retained.json").write_text(json.dumps({"policies": LEGACY}))
    iam = PolicyIam({LEGACY[0]: 0})
    assert mod.main([REGION, "--inventory", inv, "--dry-run"], eks=FakeEks(), iam=iam) == 0
    assert iam.calls == []
    err = capsys.readouterr().out
    assert f"would delete shared policy {LEGACY[0]}" in err and f"shared policy {LEGACY[1]} already gone" in err


def test_roles_go_before_their_policies(tmp_path):
    """The role delete is what makes the policy unattached: roles are swept first."""
    mod = load("sweep-shared-iam.py")
    inv = inventory(tmp_path)
    (tmp_path / "shared-iam-retained.json").write_text(json.dumps({"roles": ["aiops-agent-role"],
                                                                   "policies": [LEGACY[0]]}))
    order = []

    class Iam(PolicyIam):
        def list_attached_role_policies(self, RoleName, **_):
            return {"AttachedPolicies": []}

        def list_role_policies(self, RoleName, **_):
            return {"PolicyNames": []}

        def list_instance_profiles_for_role(self, RoleName, **_):
            return {"InstanceProfiles": []}

        def delete_role(self, RoleName):
            order.append("role")
            self.p[LEGACY[0]] = 0

        def delete_policy(self, PolicyArn):
            order.append("policy")

    iam = Iam({LEGACY[0]: 1})
    assert mod.main([REGION, "--inventory", inv], eks=FakeEks(), iam=iam) == 0
    assert order == ["role", "policy"]


# ------------------------------------------- 4a. app resources: record from the hub

def memory(name, mid, **spec):
    return {"metadata": {"name": name, "annotations": {"crossplane.io/external-name": mid}},
            "spec": dict({"forProvider": {"region": REGION}}, **spec), "status": {"atProvider": {"id": mid}}}


def ack(kind, name, arn, url="", annotations=None):
    st = {"ackResourceMetadata": {"arn": arn}}
    if url:
        st["queueURL"] = url
    return {"kind": kind, "metadata": {"name": name, "namespace": "aiops-agent", "annotations": annotations or {}},
            "status": st}


def sns_arn(n):
    return f"arn:aws:sns:{REGION}:{ACCT}:{n}"


def sqs_arn(n):
    return f"arn:aws:sqs:{REGION}:{ACCT}:{n}"


MID = "Mhb_hub_aiops_agent_aiops_agent_m_0123456789abcdef-AbCdEf1234"


def hub_crs():
    return {
        "memories.bedrockagentcore.aws.upbound.io": [
            memory("aiops-agent.aiops-agent-memory", MID),
            memory("kept.memory", "Mkept-x", deletionPolicy="Orphan"),
            {"metadata": {"name": "new.memory", "annotations": {"crossplane.io/external-name": "new.memory"}},
             "spec": {"forProvider": {}}, "status": {}},
        ],
        "topics.sns.services.k8s.aws": [ack("Topic", "hb-amp-incidents", sns_arn("hb-amp-incidents"))],
        "queues.sqs.services.k8s.aws": [
            ack("Queue", "hb-amp-incidents", sqs_arn("hb-amp-incidents")),
            ack("Queue", "hb-amp-incidents-dlq", sqs_arn("hb-amp-incidents-dlq")),
            ack("Queue", "kept", sqs_arn("hb-kept"), annotations={"services.k8s.aws/deletion-policy": "retain"}),
        ],
    }


def test_record_keeps_ids_skips_retained_and_uncreated_and_merges(tmp_path):
    mod = load("record-app-resources.py")
    inv = inventory(tmp_path)
    assert mod.main([REGION, "hb-hub", "--inventory", inv], kubectl=FakeKubectl(hub_crs())) == 0
    rec = sl.load_app_record(sl.app_record_path(inv), "hb-hub")
    assert [m["id"] for m in rec["agentcore_memories"]] == [MID]
    assert [t["name"] for t in rec["sns_topics"]] == ["hb-amp-incidents"]
    assert [q["name"] for q in rec["sqs_queues"]] == ["hb-amp-incidents", "hb-amp-incidents-dlq"]
    # Re-run after the hub is gone (kubectl fails): the record is kept, not truncated.
    assert mod.main([REGION, "hb-hub", "--inventory", inv], kubectl=FakeKubectl({})) == 0
    assert sl.load_app_record(sl.app_record_path(inv), "hb-hub") == rec


def test_record_dry_run_writes_nothing(tmp_path):
    mod = load("record-app-resources.py")
    inv = inventory(tmp_path)
    assert mod.main([REGION, "hb-hub", "--inventory", inv, "--dry-run"], kubectl=FakeKubectl(hub_crs())) == 0
    assert not os.path.exists(sl.app_record_path(inv))


# ------------------------------------------- 4b. app resources: sweep once hub is gone

class FakeAws:
    def __init__(self, memories=(), topics=(), queues=()):
        self.memories, self.topics, self.queues = set(memories), set(topics), set(queues)
        self.deleted = []

    def get_memory(self, memoryId):
        if memoryId not in self.memories:
            raise AwsError("ResourceNotFoundException")

    def delete_memory(self, memoryId):
        self.deleted.append(("memory", memoryId))

    def get_topic_attributes(self, TopicArn):
        if TopicArn.rsplit(":", 1)[1] not in self.topics:
            raise AwsError("NotFound")

    def delete_topic(self, TopicArn):
        self.deleted.append(("topic", TopicArn.rsplit(":", 1)[1]))

    def get_queue_url(self, QueueName):
        if QueueName not in self.queues:
            raise AwsError("AWS.SimpleQueueService.NonExistentQueue")
        return {"QueueUrl": f"https://sqs.{REGION}.amazonaws.com/{ACCT}/{QueueName}"}

    def delete_queue(self, QueueUrl):
        self.deleted.append(("queue", QueueUrl.rsplit("/", 1)[1]))


def _record(tmp_path, hub="hb-hub", **rec):
    inv = inventory(tmp_path)
    full = {k: rec.get(k, []) for k in sl.APP_KEYS}
    path = sl.app_record_path(inv)
    data = json.load(open(path)) if os.path.exists(path) else {}
    data[hub] = full
    open(path, "w").write(json.dumps(data))
    return inv


def demo5_record(prefix="hb"):
    return dict(
        agentcore_memories=[{"id": MID, "region": REGION}],
        sns_topics=[{"arn": sns_arn(f"{prefix}-amp-incidents"), "name": f"{prefix}-amp-incidents", "region": REGION}],
        sqs_queues=[{"arn": sqs_arn(f"{prefix}-amp-incidents"), "name": f"{prefix}-amp-incidents", "region": REGION},
                    {"arn": sqs_arn(f"{prefix}-amp-incidents-dlq"), "name": f"{prefix}-amp-incidents-dlq",
                     "region": REGION}])


def test_app_resources_of_the_removed_hub_are_deleted(tmp_path):
    mod = load("sweep-app-resources.py")
    inv = _record(tmp_path, **demo5_record())
    aws = FakeAws([MID], ["hb-amp-incidents"], ["hb-amp-incidents", "hb-amp-incidents-dlq"])
    assert mod.main(["hb", REGION, "hb-hub", "--inventory", inv], eks=FakeEks(), client_for=lambda s, r: aws) == 0
    assert aws.deleted == [("memory", MID), ("queue", "hb-amp-incidents"), ("queue", "hb-amp-incidents-dlq"),
                           ("topic", "hb-amp-incidents")]


def test_nothing_is_deleted_while_the_hub_is_live(tmp_path, capsys):
    mod = load("sweep-app-resources.py")
    inv = _record(tmp_path, **demo5_record())
    aws = FakeAws([MID], ["hb-amp-incidents"], ["hb-amp-incidents"])
    assert mod.main(["hb", REGION, "hb-hub", "--inventory", inv], eks=FakeEks(["hb-hub"]),
                    client_for=lambda s, r: aws) == 0
    assert aws.deleted == [] and "still ACTIVE" in capsys.readouterr().out


def test_dry_run_lists_what_would_be_deleted(tmp_path, capsys):
    mod = load("sweep-app-resources.py")
    inv = _record(tmp_path, **demo5_record())
    aws = FakeAws([MID], ["hb-amp-incidents"], ["hb-amp-incidents-dlq"])
    assert mod.main(["hb", REGION, "hb-hub", "--inventory", inv, "--dry-run", "--assume-deleted", "hb-hub"],
                    eks=FakeEks(["hb-hub"]), client_for=lambda s, r: aws) == 0
    assert aws.deleted == []
    out = capsys.readouterr().out
    assert f"would delete AgentCore memory {MID}" in out
    assert "would delete SQS queue hb-amp-incidents-dlq" in out
    assert "SQS queue hb-amp-incidents already gone" in out
    assert "would delete SNS topic hb-amp-incidents" in out
    assert "3 would be deleted" in out


def test_names_outside_the_prefix_and_other_hubs_records_are_left_alone(tmp_path):
    mod = load("sweep-app-resources.py")
    # A record for another hub in the same file, and a recorded topic named for another
    # install (a nested prefix hb-a- is NOT hb-x-, and ha- is another prefix).
    _record(tmp_path, hub="ha-hub", **demo5_record("ha"))
    rec = demo5_record("hb")
    rec["sns_topics"].append({"arn": sns_arn("ha-amp-incidents"), "name": "ha-amp-incidents", "region": REGION})
    inv = _record(tmp_path, **rec)
    aws = FakeAws([MID, "Mha-other"], ["hb-amp-incidents", "ha-amp-incidents"],
                  ["hb-amp-incidents", "ha-amp-incidents", "ha-amp-incidents-dlq"])
    assert mod.main(["hb", REGION, "hb-hub", "--inventory", inv], eks=FakeEks(), client_for=lambda s, r: aws) == 0
    assert not any(n.startswith("ha-") or n == "Mha-other" for _, n in aws.deleted)
    assert ("topic", "hb-amp-incidents") in aws.deleted


def test_longer_prefix_is_not_ours(tmp_path):
    sel, skipped = sl.select_app_resources(demo5_record("hb-a"), "hb-x")
    assert sel["sns_topics"] == [] and sel["sqs_queues"] == [] and len(skipped) == 3


def test_no_record_is_a_no_op(tmp_path, capsys):
    mod = load("sweep-app-resources.py")
    assert mod.main(["hb", REGION, "hb-hub", "--inventory", inventory(tmp_path)], eks=FakeEks(),
                    client_for=lambda s, r: pytest.fail("no AWS call expected")) == 0
    assert "nothing to sweep" in capsys.readouterr().out


# --------------------------------------------- 4c. drain the OAM apps before step 7

class DrainKubectl:
    """Hub model: Argo CD apps, OAM apps, Crossplane MRs and kro instances. Deleting the
    owner ApplicationSet starts the Argo CD app's deletion; each poll (sleep) advances it."""

    def __init__(self, steps_to_finish=3, vela=True, argo_fails=False):
        self.calls = []
        self.left = None
        self.steps = steps_to_finish
        self.vela = vela
        self.argo_fails = argo_fails
        self.timeouts = []
        self.selectors = {
            "incident-bridge-aws": {"metadata": {"name": "incident-bridge-aws", "labels": {"app.oam.dev/name": "aiops-agent-hub"}}},
            "other-install-sel": {"metadata": {"name": "other-install-sel", "labels": {"app.oam.dev/name": "another-app"}}},
            "unlabelled": {"metadata": {"name": "unlabelled"}},
        }
        self.argo = [
            self._app("aiops-agent-hb-hub", "aiops-agent", "hb-hub", oam=True),
            self._app("aiops-agent-spoke-access-hb-dev", "aiops-agent-spoke-access", "hb-dev", oam=True),
            self._app("backstage-hb-hub", "backstage", "hb-hub", oam=False),
        ]

    @staticmethod
    def _app(name, owner, dest, oam):
        res = [{"group": "core.oam.dev", "kind": "Application", "namespace": "aiops-agent", "name": "aiops-agent-hub"}] \
            if oam else [{"group": "apps", "kind": "Deployment", "namespace": "backstage", "name": "b"}]
        return {"metadata": {"name": name, "ownerReferences": [{"kind": "ApplicationSet", "name": owner}]},
                "spec": {"destination": {"name": dest}}, "status": {"resources": res}}

    def tick(self, _):
        if self.left is not None and self.left > 0:
            self.left -= 1

    def deleting(self):
        return self.left is not None and self.left > 0

    def __call__(self, args, timeout=None):
        self.calls.append(args)
        self.timeouts.append(timeout)
        verb, what = args[0], args[1]
        if verb == "get" and what == "customresourcedefinitions.apiextensions.k8s.io":
            return 0, json.dumps({"items": [
                {"spec": {"group": "sqs.services.k8s.aws", "scope": "Namespaced", "names": {"plural": "queues"}}},
                {"spec": {"group": "services.k8s.aws", "scope": "Cluster", "names": {"plural": "iamroleselectors"}}},
                {"spec": {"group": "apps", "scope": "Namespaced", "names": {"plural": "deployments"}}}]})
        if verb == "get" and what == "queues.sqs.services.k8s.aws":
            md = {"name": "hb-amp-incidents-dlq", "labels": {"app.oam.dev/name": "aiops-agent-hub"}}
            if self.deleting():
                md["deletionTimestamp"] = "now"
            return 0, json.dumps({"items": [{"kind": "Queue", "metadata": md}]})
        if verb == "get" and what == SELECTORS:
            if len(args) > 2 and args[2] != "-o":
                sel = self.selectors.get(args[2])
                return (0, json.dumps(sel)) if sel else (1, "")
            return 0, json.dumps({"items": list(self.selectors.values())})
        if verb == "patch" and what == SELECTORS:
            self.selectors[args[2]]["metadata"]["finalizers"] = json.loads(args[6])["metadata"]["finalizers"]
            return 0, ""
        if verb == "get" and what == "applications.argoproj.io":
            if self.argo_fails:
                return 1, ""
            items = [a for a in self.argo
                     if not (a["metadata"]["name"] == "aiops-agent-hb-hub" and self.left == 0)]
            return 0, json.dumps({"items": items})
        if verb == "get" and what == "applications.core.oam.dev":
            return 0, json.dumps({"items": [{"metadata": {"name": "aiops-agent-hub"}}] if self.deleting() else []})
        if verb == "get" and what == "managed":
            md = {"name": "aiops-agent.aiops-agent-memory", "labels": {"app.oam.dev/name": "aiops-agent-hub"}}
            if self.deleting():
                md["deletionTimestamp"] = "now"
            return 0, json.dumps({"items": [{"kind": "Memory", "metadata": md},
                                            {"kind": "Workspace", "metadata": {"name": "w", "deletionTimestamp": "x"}}]})
        if verb == "get" and what == "resourcegraphdefinitions.kro.run":
            return 0, json.dumps({"items": [{"spec": {"schema": {"kind": "AmpIncident"}}}]})
        if verb == "get" and what == "ampincident.kro.run":
            md = {"name": "hb-amp-incidents", "labels": {"app.oam.dev/name": "aiops-agent-hub"}}
            if self.deleting():
                md["deletionTimestamp"] = "now"
            return 0, json.dumps({"items": [{"kind": "AmpIncident", "metadata": md}]})
        if verb == "get" and what == "pods":
            return 0, json.dumps({"items": [{"metadata": {"name": "kubevela-vela-core-abc"},
                                             "status": {"phase": "Running"}}] if self.vela else []})
        if verb == "delete" and what == "applicationset":
            if args[2] == "aiops-agent":
                self.left = self.steps
            return 0, ""
        return 0, ""


SELECTORS = "iamroleselectors.services.k8s.aws"
HOLD = "appmod-blueprints.aws/drain-hold"


class FakeClock:
    """Virtual monotonic clock: only sleeping (and slow kubectl calls) advance it."""

    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, s):
        self.now += s


def _mutations(kc):
    return [c[:3] for c in kc.calls
            if c[0] == "delete" or (c[0] == "patch" and c[1] != SELECTORS)]


def test_drain_deletes_the_oam_appset_and_waits_for_its_aws_resources(capsys):
    mod = load("drain-oam-apps.py")
    kc = DrainKubectl(steps_to_finish=3)
    clk = FakeClock()

    def tick(s):
        kc.tick(s)
        clk.sleep(s)
    assert mod.main(["hb-hub", "1200"], kubectl=kc, sleep=tick, clock=clk) == 0
    assert _mutations(kc) == [["patch", "applicationset", "aiops-agent"], ["delete", "applicationset", "aiops-agent"]]
    out = capsys.readouterr().out
    assert "waiting for the OAM apps" in out and "memory/aiops-agent.aiops-agent-memory" in out
    assert "ampincident/hb-amp-incidents" in out and "OAM apps drained (45s)" in out
    assert "workspace/w" not in out, "a deleting MR KubeVela did not apply is not waited for"


def test_drain_ignores_apps_on_spokes_and_non_oam_apps():
    mod = load("drain-oam-apps.py")
    kc = DrainKubectl(steps_to_finish=0)
    mod.main(["hb-hub", "1200"], kubectl=kc, sleep=kc.tick, clock=FakeClock())
    touched = {c[2] for c in kc.calls if c[0] in ("patch", "delete") and c[1] != SELECTORS}
    assert touched == {"aiops-agent"}


def test_drain_is_bounded(capsys):
    mod = load("drain-oam-apps.py")
    kc = DrainKubectl(steps_to_finish=10 ** 6)
    clk = FakeClock()
    sleeps = []

    def tick(s):
        sleeps.append(s)
        clk.sleep(s)
    assert mod.main(["hb-hub", "60"], kubectl=kc, sleep=tick, clock=clk) == 0
    assert sum(sleeps) == 60 and "still deleting after 60s, going on" in capsys.readouterr().out


def test_drain_bound_is_wall_clock_not_the_sum_of_sleeps(capsys):
    """Every kubectl call takes 40 s of the virtual clock: the 200 s bound is reached
    after a few polls, not after 200 s of sleeping."""
    mod = load("drain-oam-apps.py")
    kc = DrainKubectl(steps_to_finish=10 ** 6)
    clk = FakeClock()
    sleeps = []

    def slow(args, timeout=None):
        clk.now += 40
        return kc(args, timeout=timeout)

    def tick(s):
        sleeps.append(s)
        clk.sleep(s)
    assert mod.main(["hb-hub", "200"], kubectl=slow, sleep=tick, clock=clk) == 0
    assert "still deleting after" in capsys.readouterr().out
    assert sum(sleeps) < 100, "the loop stopped on the clock, not on the sum of the sleeps"


def test_every_kubectl_call_has_a_timeout_within_the_remaining_time():
    mod = load("drain-oam-apps.py")
    kc = DrainKubectl(steps_to_finish=10 ** 6)
    clk = FakeClock()
    mod.main(["hb-hub", "100"], kubectl=kc, sleep=clk.sleep, clock=clk)
    assert kc.timeouts and all(t is not None and 1 <= t <= 200 for t in kc.timeouts)
    polls = [t for c, t in zip(kc.calls, kc.timeouts) if c[0] == "get"]
    assert polls and max(polls) <= 60


def test_run_kubectl_turns_a_timeout_into_a_failed_call(monkeypatch):
    import subprocess
    mod = load("drain-oam-apps.py")

    def boom(*a, **k):
        assert k["timeout"] == 5
        raise subprocess.TimeoutExpired("kubectl", 5)
    monkeypatch.setattr(mod.subprocess, "run", boom)
    assert mod.run_kubectl(["get", "x"], timeout=5) == (124, "")


def test_drain_output_is_flushed_line_by_line():
    mod = load("drain-oam-apps.py")

    class Out:
        def __init__(self):
            self.lines, self.flushes = 0, 0

        def write(self, t):
            self.lines += t.count("\n")

        def flush(self):
            self.flushes += 1
    o = Out()
    kc = DrainKubectl(steps_to_finish=2)
    clk = FakeClock()
    mod.main(["hb-hub", "1200"], kubectl=kc, sleep=clk.sleep, clock=clk, out=o)
    assert o.lines > 3 and o.flushes >= o.lines


# --- the app's IAMRoleSelectors outlive the ACK resources that need them

def _selector_events(kc):
    return [(i, c[2], json.loads(c[6])["metadata"]["finalizers"]) for i, c in enumerate(kc.calls)
            if c[:2] == ["patch", SELECTORS]]


def test_selectors_are_held_before_the_appset_goes_and_released_after_the_wait():
    mod = load("drain-oam-apps.py")
    kc = DrainKubectl(steps_to_finish=3)
    clk = FakeClock()
    assert mod.main(["hb-hub", "1200"], kubectl=kc, sleep=clk.sleep, clock=clk) == 0
    ev = _selector_events(kc)
    assert [e[1] for e in ev] == ["incident-bridge-aws", "incident-bridge-aws"], \
        "only the selector of this hub's OAM app is touched (not another app's, not unlabelled ones)"
    assert ev[0][2] == [HOLD] and ev[1][2] == []
    delete_appset = next(i for i, c in enumerate(kc.calls) if c[:2] == ["delete", "applicationset"])
    assert ev[0][0] < delete_appset < ev[1][0]
    last_wait = max(i for i, c in enumerate(kc.calls) if c[:2] == ["get", "applications.core.oam.dev"])
    assert ev[1][0] > last_wait, "released only when the wait is over"


def test_selectors_are_released_on_timeout_without_kubevela_and_on_crash():
    mod = load("drain-oam-apps.py")
    for kw in (dict(steps_to_finish=10 ** 6), dict(steps_to_finish=5, vela=False)):
        kc = DrainKubectl(**kw)
        clk = FakeClock()
        mod.main(["hb-hub", "30"], kubectl=kc, sleep=clk.sleep, clock=clk)
        assert kc.selectors["incident-bridge-aws"]["metadata"]["finalizers"] == []
    kc = DrainKubectl(steps_to_finish=5)

    def bad_sleep(_):
        raise RuntimeError("interrupted")
    with pytest.raises(RuntimeError):
        mod.main(["hb-hub", "1200"], kubectl=kc, sleep=bad_sleep, clock=FakeClock())
    assert kc.selectors["incident-bridge-aws"]["metadata"]["finalizers"] == []


def test_foreign_finalizers_are_kept_and_dry_run_holds_nothing():
    mod = load("drain-oam-apps.py")
    kc = DrainKubectl(steps_to_finish=1)
    kc.selectors["incident-bridge-aws"]["metadata"]["finalizers"] = ["x.io/keep"]
    clk = FakeClock()
    mod.main(["hb-hub", "1200"], kubectl=kc, sleep=clk.sleep, clock=clk)
    assert _selector_events(kc)[0][2] == ["x.io/keep", HOLD]
    assert kc.selectors["incident-bridge-aws"]["metadata"]["finalizers"] == ["x.io/keep"]
    kc = DrainKubectl()
    mod.main(["hb-hub", "1200", "--dry-run"], kubectl=kc, sleep=pytest.fail, clock=FakeClock())
    assert _selector_events(kc) == []


def test_ack_resources_of_the_app_being_deleted_are_waited_for(capsys):
    mod = load("drain-oam-apps.py")
    kc = DrainKubectl(steps_to_finish=2)
    clk = FakeClock()
    mod.main(["hb-hub", "1200"], kubectl=kc, sleep=clk.sleep, clock=clk)
    assert "queue/hb-amp-incidents-dlq" in capsys.readouterr().out


def test_drain_does_not_wait_without_kubevela(capsys):
    mod = load("drain-oam-apps.py")
    kc = DrainKubectl(steps_to_finish=5, vela=False)
    assert mod.main(["hb-hub", "1200"], kubectl=kc, sleep=pytest.fail, clock=FakeClock()) == 0
    assert "no KubeVela controller running" in capsys.readouterr().out


def test_drain_dry_run_and_unreachable_hub(capsys):
    mod = load("drain-oam-apps.py")
    kc = DrainKubectl()
    assert mod.main(["hb-hub", "1200", "--dry-run"], kubectl=kc, sleep=pytest.fail, clock=FakeClock()) == 0
    assert _mutations(kc) == []
    assert "would delete ApplicationSet aiops-agent" in capsys.readouterr().out
    kc = DrainKubectl(argo_fails=True)
    assert mod.main(["hb-hub", "1200"], kubectl=kc, sleep=pytest.fail, clock=FakeClock()) == 0
    assert _mutations(kc) == [] and "nothing to drain" in capsys.readouterr().out


# ------------------------------------------------------------- Taskfile wiring

def _cmds(task):
    tf = yaml.safe_load(open(TASKFILE))
    out = []
    for c in tf["tasks"][task]["cmds"]:
        out.append(c.get("cmd", "") if isinstance(c, dict) else (c if isinstance(c, str) else json.dumps(c)))
    return out


def _index(cmds, needle):
    return next(i for i, c in enumerate(cmds) if needle in c)


def test_drain_runs_after_the_spokes_and_before_the_per_addon_pass():
    cmds = _cmds("hub:destroy-addons")
    drain = _index(cmds, "drain-oam-apps.py")
    assert _index(cmds, "clusters-kro clusters") < drain < _index(cmds, 'SKIP="{{.INFRA_STACK}}')
    assert '"{{.XP_DELETE_WAIT}}"' in cmds[drain], "bounded by the existing wait, no new parameter"
    assert "python3 -u " in cmds[drain], "unbuffered: the log shows the wait while it happens"


def test_destroy_records_app_resources_before_the_hub_goes_and_sweeps_after():
    cmds = _cmds("destroy")
    rec = _index(cmds, "record-app-resources.py")
    assert rec < _index(cmds, "kind delete cluster --name") < _index(cmds, "delete-cluster --name")
    sweep = _index(cmds, "sweep-app-resources.py")
    assert sweep > _index(cmds, "delete-cluster --name")
    assert "--inventory" in cmds[sweep]
