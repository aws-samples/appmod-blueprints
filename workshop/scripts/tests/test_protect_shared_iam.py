"""Unit tests for the shared-IAM protection of task kind-kro-ack:destroy.

A chart can create an IAM role with a fixed name, outside the stack prefix, on every
hub (each hub then holds a managed resource for the SAME AWS role, deletion policy
Delete). Removing one hub's addons must not delete it while another hub's pod identity
association still uses it. hub:destroy-addons step 0 (protect-shared-iam.py) marks such
managed resources retain/Orphan; step 6b2 (sweep-shared-iam.py) deletes the role once
no live cluster references it.

kubectl, EKS and IAM are in-memory fakes. No cluster, no AWS, no network.

Run:  python -m pytest workshop/scripts/tests/test_protect_shared_iam.py -q
"""
import importlib.util
import json
import os
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO, "scripts"))
import sweep_lib as sl  # noqa: E402

TASKFILE = os.path.join(REPO, "cluster-providers", "kind-kro-ack", "Taskfile.yaml")
ACCT = "111122223333"
SHARED = "agent-cw-observability-role"


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), os.path.join(REPO, "scripts", name))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def arn(role):
    return f"arn:aws:iam::{ACCT}:role/{role}"


class AwsError(Exception):
    def __init__(self, code):
        self.response = {"Error": {"Code": code}}
        super().__init__(f"An error occurred ({code}) when calling the op")


class FakeEks:
    def __init__(self, clusters):
        self.c = clusters

    def list_clusters(self, **_):
        return {"clusters": list(self.c)}

    def describe_cluster(self, name):
        c = self.c[name]
        return {"cluster": {"status": c.get("status", "ACTIVE"), "resourcesVpcConfig": {"vpcId": ""},
                            "roleArn": c.get("roleArn", ""), "tags": {}}}

    def list_access_entries(self, clusterName, **_):
        return {"accessEntries": self.c[clusterName].get("access", [])}

    def list_pod_identity_associations(self, clusterName, **_):
        return {"associations": [{"associationId": str(i)} for i, _ in enumerate(self.c[clusterName].get("pia", []))]}

    def describe_pod_identity_association(self, clusterName, associationId):
        return {"association": {"roleArn": self.c[clusterName]["pia"][int(associationId)]}}

    def list_capabilities(self, clusterName, **_):
        return {"capabilities": []}


class BrokenEks:
    def list_clusters(self, **_):
        raise AwsError("AccessDeniedException")


class FakeKubectl:
    """Holds CRs by resource; records patch/annotate calls."""

    def __init__(self, crs):
        self.crs = crs
        self.calls = []

    def __call__(self, args):
        if args[0] == "get":
            items = self.crs.get(args[1])
            if items is None:
                return 1, ""  # CRD not installed
            return 0, json.dumps({"items": items})
        self.calls.append(args)
        return 0, ""


def xp_role(name, ext=None, **spec):
    meta = {"name": name, "annotations": {"crossplane.io/external-name": ext or name}}
    return {"metadata": meta, "spec": dict({"forProvider": {}}, **spec)}


def ack_role(ns, name, aws_name, annotations=None):
    return {"metadata": {"name": name, "namespace": ns, "annotations": annotations or {}},
            "spec": {"name": aws_name}}


def two_hubs():
    """Hub B is being destroyed (prefix hb, spoke hb-dev). Hub A is live and its pod
    identity uses the shared fixed-name role."""
    return {
        "hb-hub": {"roleArn": arn("hb-hub-cluster-role"), "pia": [arn("hb-ebs"), arn(SHARED)]},
        "hb-dev": {"roleArn": arn("hb-dev-cluster-role"), "pia": [arn("hb-dev-ebs")]},
        "ha-hub": {"roleArn": arn("ha-hub-cluster-role"), "pia": [arn(SHARED), arn("ha-ebs")],
                   "access": [arn("hb-hub-argocd-capability-role")]},
    }


def inventory(tmp_path, clusters):
    p = tmp_path / "destroy-inventory.json"
    p.write_text(json.dumps({"hub_vpc_id": "", "clusters": clusters}))
    return str(p)


# ------------------------------------------------------------------ selection

def test_fixed_name_role_outside_the_prefix_is_retained():
    crs = {"roles.iam.aws.upbound.io": [xp_role(SHARED), xp_role("hb-team-role")]}
    retain, delete = sl.select_shared_iam_crs(crs, "hb", set())
    assert [r[3] for r in retain] == [SHARED]
    assert "not owned" in retain[0][4]
    assert [d[3] for d in delete] == ["hb-team-role"]


def test_prefixed_role_still_used_by_a_live_cluster_outside_the_stack_is_retained():
    crs = {"roles.iam.aws.upbound.io": [xp_role("hb-hub-argocd-capability-role"), xp_role("hb-team-role")]}
    retain, delete = sl.select_shared_iam_crs(crs, "hb", {"hb-hub-argocd-capability-role"})
    assert [r[3] for r in retain] == ["hb-hub-argocd-capability-role"]
    assert [d[3] for d in delete] == ["hb-team-role"]


def test_reference_check_failure_retains_every_role_cr_fail_closed():
    crs = {"roles.iam.aws.upbound.io": [xp_role("hb-team-role")],
           "policies.iam.aws.upbound.io": [xp_role("hb-team-policy")]}
    retain, delete = sl.select_shared_iam_crs(crs, "hb", set(), guard_ok=False)
    assert [r[3] for r in retain] == ["hb-team-role"]
    assert [d[3] for d in delete] == ["hb-team-policy"], "policies are prefix-scoped only"


def test_nested_prefix_role_is_not_owned_by_a_longer_prefix():
    # destroying prefix "hb-x" never claims a role of prefix "hb"
    crs = {"roles.iam.aws.upbound.io": [xp_role("hb-team-role")]}
    retain, _ = sl.select_shared_iam_crs(crs, "hb-x", set())
    assert [r[3] for r in retain] == ["hb-team-role"]


def test_attachment_to_a_shared_role_is_retained():
    att = {"metadata": {"name": "att"}, "spec": {"forProvider": {"role": SHARED, "policyArn": "x"}}}
    retain, _ = sl.select_shared_iam_crs({"rolepolicyattachments.iam.aws.upbound.io": [att]}, "hb", set())
    assert [r[3] for r in retain] == [SHARED]


def test_ack_role_uses_spec_name():
    crs = {"roles.iam.services.k8s.aws": [ack_role("hb-dev", "r1", "shared-ack-role"),
                                          ack_role("hb-dev", "r2", "hb-dev-x")]}
    retain, delete = sl.select_shared_iam_crs(crs, "hb", set())
    assert [(r[1], r[3]) for r in retain] == [("hb-dev", "shared-ack-role")]
    assert [d[3] for d in delete] == ["hb-dev-x"]


def test_retain_patches_per_family():
    assert sl.retain_patch("ack") == ["annotate", "--overwrite", "services.k8s.aws/deletion-policy=retain"]
    xp1 = sl.retain_patch("xp1")
    assert json.loads(xp1[-1]) == {"spec": {"deletionPolicy": "Orphan"}}
    xp2 = json.loads(sl.retain_patch("xp2")[-1])["spec"]["managementPolicies"]
    assert "Delete" not in xp2 and "Observe" in xp2


def test_already_retained_is_detected():
    assert sl.already_retained("xp1", xp_role(SHARED, deletionPolicy="Orphan"))
    assert not sl.already_retained("xp1", xp_role(SHARED, deletionPolicy="Delete"))
    assert sl.already_retained("ack", ack_role("n", "r", SHARED, {"services.k8s.aws/deletion-policy": "retain"}))
    assert sl.already_retained("xp2", xp_role(SHARED, managementPolicies=["Observe", "Create"]))
    assert not sl.already_retained("xp2", xp_role(SHARED, managementPolicies=["*"]))


# ------------------------------------------------------------------ protect CLI

def test_protect_cli_orphans_the_shared_role_and_keeps_own_roles(tmp_path, capsys):
    mod = load("protect-shared-iam.py")
    kc = FakeKubectl({"roles.iam.aws.upbound.io": [xp_role(SHARED), xp_role("hb-ebs"), xp_role("hb-team-role")]})
    inv = inventory(tmp_path, [{"name": "hb-dev", "deletionPolicy": "delete"}])
    rc = mod.main(["hb", "us-west-2", "hb-hub", "--inventory", inv], eks=FakeEks(two_hubs()), kubectl=kc)
    assert rc == 0
    assert kc.calls == [["patch", "roles.iam.aws.upbound.io", SHARED, "--type", "merge", "-p",
                         json.dumps({"spec": {"deletionPolicy": "Orphan"}})]]
    rec = json.loads((tmp_path / "shared-iam-retained.json").read_text())
    assert rec == {"roles": [SHARED]}
    out = capsys.readouterr().out
    assert "1 IAM managed resource(s) retained, 2 left to their controller" in out


def test_protect_cli_counts_this_stacks_spokes_as_own_but_not_a_retained_spoke(tmp_path):
    mod = load("protect-shared-iam.py")
    clusters = {"hb-hub": {"pia": [arn("hb-ebs")]},
                "hb-prod": {"pia": [arn("hb-prod-ebs")], "access": [arn("hb-cluster-mgmt")]},
                "hb-dev": {"pia": [arn("hb-dev-ebs")]}}
    kc = FakeKubectl({"roles.iam.aws.upbound.io": [xp_role("hb-cluster-mgmt"), xp_role("hb-dev-ebs")]})
    inv = inventory(tmp_path, [{"name": "hb-dev", "deletionPolicy": "delete"},
                               {"name": "hb-prod", "deletionPolicy": "retain"}])
    mod.main(["hb", "us-west-2", "hb-hub", "--inventory", inv], eks=FakeEks(clusters), kubectl=kc)
    assert [c[2] for c in kc.calls] == ["hb-cluster-mgmt"], "retained spoke keeps its role; deleted spoke's goes"


def test_protect_cli_dry_run_patches_nothing(tmp_path, capsys):
    mod = load("protect-shared-iam.py")
    kc = FakeKubectl({"roles.iam.aws.upbound.io": [xp_role(SHARED)]})
    inv = inventory(tmp_path, [])
    assert mod.main(["hb", "us-west-2", "hb-hub", "--inventory", inv, "--dry-run"],
                    eks=FakeEks(two_hubs()), kubectl=kc) == 0
    assert kc.calls == []
    assert not (tmp_path / "shared-iam-retained.json").exists()
    assert f"would retain roles.iam.aws.upbound.io {SHARED}" in capsys.readouterr().out


def test_protect_cli_skips_already_retained_and_hub_unreachable(tmp_path, capsys):
    mod = load("protect-shared-iam.py")
    kc = FakeKubectl({"roles.iam.aws.upbound.io": [xp_role(SHARED, deletionPolicy="Orphan")]})
    assert mod.main(["hb", "us-west-2", "hb-hub"], eks=FakeEks(two_hubs()), kubectl=kc) == 0
    assert kc.calls == []
    assert "already retained" in capsys.readouterr().out
    assert mod.main(["hb", "us-west-2", "hb-hub"], eks=FakeEks({}), kubectl=FakeKubectl({})) == 0


def test_protect_cli_fails_closed_when_eks_is_unreadable(tmp_path, capsys):
    mod = load("protect-shared-iam.py")
    kc = FakeKubectl({"roles.iam.aws.m.upbound.io": [dict(xp_role("hb-team-role"),
                                                          metadata={"name": "hb-team-role", "namespace": "hb-hub"})]})
    assert mod.main(["hb", "us-west-2", "hb-hub"], eks=BrokenEks(), kubectl=kc) == 0
    assert kc.calls and kc.calls[0][:5] == ["patch", "roles.iam.aws.m.upbound.io", "hb-team-role", "-n", "hb-hub"]
    assert "fail closed" in capsys.readouterr().out


# ------------------------------------------------------------------ last-user sweep

class FakeIam:
    def __init__(self, roles):
        self.roles = set(roles)
        self.calls = []

    def list_attached_role_policies(self, RoleName, **_):
        self._exists(RoleName)
        return {"AttachedPolicies": [{"PolicyArn": "arn:aws:iam::aws:policy/X"}]}

    def list_role_policies(self, RoleName, **_):
        return {"PolicyNames": ["inline"]}

    def list_instance_profiles_for_role(self, RoleName, **_):
        return {"InstanceProfiles": []}

    def detach_role_policy(self, **kw):
        self.calls.append(("detach", kw["RoleName"]))

    def delete_role_policy(self, **kw):
        self.calls.append(("inline", kw["RoleName"]))

    def remove_role_from_instance_profile(self, **kw):
        self.calls.append(("ip", kw["RoleName"]))

    def delete_role(self, RoleName):
        self.calls.append(("delete", RoleName))
        self.roles.discard(RoleName)

    def _exists(self, name):
        if name not in self.roles:
            raise AwsError("NoSuchEntity")


def record(tmp_path, roles):
    inv = inventory(tmp_path, [])
    (tmp_path / "shared-iam-retained.json").write_text(json.dumps({"roles": roles}))
    return inv


def test_shared_role_is_kept_while_another_hub_uses_it(tmp_path):
    mod = load("sweep-shared-iam.py")
    iam = FakeIam([SHARED])
    clusters = {k: v for k, v in two_hubs().items() if k.startswith("ha-")}  # hub B gone
    assert mod.main(["us-west-2", "--inventory", record(tmp_path, [SHARED])], eks=FakeEks(clusters), iam=iam) == 0
    assert iam.calls == [] and SHARED in iam.roles


def test_shared_role_is_deleted_by_its_last_user(tmp_path):
    mod = load("sweep-shared-iam.py")
    iam = FakeIam([SHARED])
    assert mod.main(["us-west-2", "--inventory", record(tmp_path, [SHARED])], eks=FakeEks({}), iam=iam) == 0
    assert iam.calls == [("detach", SHARED), ("inline", SHARED), ("delete", SHARED)]


def test_shared_sweep_dry_run_and_fail_closed(tmp_path, capsys):
    mod = load("sweep-shared-iam.py")
    iam = FakeIam([SHARED])
    inv = record(tmp_path, [SHARED])
    assert mod.main(["us-west-2", "--inventory", inv, "--dry-run"], eks=FakeEks({}), iam=iam) == 0
    assert iam.calls == []
    assert mod.main(["us-west-2", "--inventory", inv], eks=BrokenEks(), iam=iam) == 0
    assert iam.calls == []
    out = capsys.readouterr().out
    assert "would delete shared role" in out and "fail closed" in out


class FakeEc2Regions:
    def __init__(self, regions):
        self.regions = regions

    def describe_regions(self, AllRegions=False):
        return {"Regions": [{"RegionName": r} for r in self.regions]}


class EksByRegion:
    """eks_for(region) over per-region cluster maps; a region set to None is unreadable."""

    def __init__(self, by_region):
        self.by_region = by_region
        self.seen = []

    def __call__(self, region):
        self.seen.append(region)
        c = self.by_region.get(region, {})
        return BrokenEks() if c is None else FakeEks(c)


def test_shared_role_is_kept_while_a_hub_in_another_region_uses_it(tmp_path):
    """Review #1174 (blocking): IAM is global. A hub in eu-west-1 that uses the same
    fixed-name role keeps it when the us-west-2 stack is destroyed."""
    mod = load("sweep-shared-iam.py")
    iam = FakeIam([SHARED])
    other = {"hc-hub": {"pia": [arn(SHARED)]}}
    eks_for = EksByRegion({"us-west-2": {}, "eu-west-1": other})
    assert mod.main(["us-west-2", "--inventory", record(tmp_path, [SHARED])], iam=iam,
                    ec2=FakeEc2Regions(["eu-west-1", "us-west-2"]), eks_for=eks_for) == 0
    assert iam.calls == [] and SHARED in iam.roles
    assert sorted(set(eks_for.seen)) == ["eu-west-1", "us-west-2"]


def test_shared_role_is_kept_when_any_region_is_unreadable(tmp_path, capsys):
    mod = load("sweep-shared-iam.py")
    iam = FakeIam([SHARED])
    eks_for = EksByRegion({"us-west-2": {}, "ap-south-1": None})
    assert mod.main(["us-west-2", "--inventory", record(tmp_path, [SHARED])], iam=iam,
                    ec2=FakeEc2Regions(["ap-south-1", "us-west-2"]), eks_for=eks_for) == 0
    assert iam.calls == [] and "fail closed" in capsys.readouterr().out


def test_shared_role_is_deleted_when_no_region_uses_it(tmp_path):
    mod = load("sweep-shared-iam.py")
    iam = FakeIam([SHARED])
    eks_for = EksByRegion({"us-west-2": {}, "eu-west-1": {"hc-hub": {"pia": [arn("other-role")]}}})
    assert mod.main(["us-west-2", "--inventory", record(tmp_path, [SHARED])], iam=iam,
                    ec2=FakeEc2Regions(["eu-west-1", "us-west-2"]), eks_for=eks_for) == 0
    assert ("delete", SHARED) in iam.calls


def test_iam_guard_covers_every_enabled_region(capsys):
    mod = load("sweep-iam-guard.py")
    eks_for = EksByRegion({"us-west-2": {}, "eu-west-1": {"hc-hub": {"access": [arn("hb-hub-mgmt")]}}})
    assert mod.main(["us-west-2"], ec2=FakeEc2Regions(["eu-west-1", "us-west-2"]), eks_for=eks_for) == 0
    assert capsys.readouterr().out.split() == ["hb-hub-mgmt"]
    assert mod.main(["us-west-2"], ec2=FakeEc2Regions(["eu-west-1", "us-west-2"]),
                    eks_for=EksByRegion({"eu-west-1": None})) == 1


def test_protect_cli_retains_a_role_a_live_cluster_in_another_region_uses(tmp_path):
    """Review #1174 (re-review, blocking): step 0 must read every enabled region, not
    only AWS_REGION. A live hub in eu-west-1 whose access entry holds an hb- role keeps
    it: the CR is retained so the hub's controller does not delete the AWS role."""
    mod = load("protect-shared-iam.py")
    kc = FakeKubectl({"roles.iam.aws.upbound.io": [xp_role("hb-hub-argocd-capability-role"),
                                                   xp_role("hb-team-role")]})
    eks_for = EksByRegion({"us-west-2": {"hb-hub": {"pia": [arn("hb-team-role")]}},
                           "eu-west-1": {"hc-hub": {"access": [arn("hb-hub-argocd-capability-role")]}}})
    rc = mod.main(["hb", "us-west-2", "hb-hub", "--inventory", inventory(tmp_path, [])], kubectl=kc,
                  ec2=FakeEc2Regions(["eu-west-1", "us-west-2"]), eks_for=eks_for)
    assert rc == 0
    assert [c[2] for c in kc.calls] == ["hb-hub-argocd-capability-role"]
    assert sorted(set(eks_for.seen)) == ["eu-west-1", "us-west-2"]


def test_protect_cli_fails_closed_when_any_region_is_unreadable(tmp_path, capsys):
    mod = load("protect-shared-iam.py")
    kc = FakeKubectl({"roles.iam.aws.upbound.io": [xp_role("hb-team-role")]})
    eks_for = EksByRegion({"us-west-2": {}, "ap-south-1": None})
    assert mod.main(["hb", "us-west-2", "hb-hub", "--inventory", inventory(tmp_path, [])], kubectl=kc,
                    ec2=FakeEc2Regions(["ap-south-1", "us-west-2"]), eks_for=eks_for) == 0
    assert [c[2] for c in kc.calls] == ["hb-team-role"]
    assert "fail closed" in capsys.readouterr().out


def test_protect_cli_counts_a_spoke_in_its_own_region_as_own(tmp_path):
    """A spoke of this stack recorded in eu-west-1 is being deleted: its roles are
    left to the controller. A cluster with the SAME name in another region is not
    this stack's and still protects the role it uses."""
    mod = load("protect-shared-iam.py")
    kc = FakeKubectl({"roles.iam.aws.upbound.io": [xp_role("hb-dev-ebs"), xp_role("hb-dev-mgmt")]})
    inv = inventory(tmp_path, [{"name": "hb-dev", "deletionPolicy": "delete", "region": "eu-west-1"}])
    eks_for = EksByRegion({"us-west-2": {"hb-hub": {}},
                           "eu-west-1": {"hb-dev": {"pia": [arn("hb-dev-ebs")]}},
                           "ap-south-1": {"hb-dev": {"access": [arn("hb-dev-mgmt")]}}})
    mod.main(["hb", "us-west-2", "hb-hub", "--inventory", inv], kubectl=kc,
             ec2=FakeEc2Regions(["ap-south-1", "eu-west-1", "us-west-2"]), eks_for=eks_for)
    assert [c[2] for c in kc.calls] == ["hb-dev-mgmt"]


def test_deleted_clusters_by_region_defaults_to_home_and_skips_retained():
    inv = {"clusters": [{"name": "a", "deletionPolicy": "delete"},
                        {"name": "b", "deletionPolicy": "delete", "region": "eu-west-1"},
                        {"name": "c", "deletionPolicy": "retain", "region": "eu-west-1"}]}
    assert sl.deleted_clusters_by_region(inv, "us-west-2", "hub") == {
        "us-west-2": {"hub", "a"}, "eu-west-1": {"b"}}


def test_inventory_records_each_spokes_region():
    text = open(TASKFILE).read()
    destroy = text[text.index("\n  destroy:\n"):]
    block = destroy[destroy.index("destroy-inventory.json"):destroy.index("recorded teardown inventory")]
    assert "region: (.spec.region" in block and "region: .[0].region" in block


def test_shared_sweep_tolerates_an_already_deleted_role(tmp_path):
    mod = load("sweep-shared-iam.py")
    iam = FakeIam([])
    assert mod.main(["us-west-2", "--inventory", record(tmp_path, [SHARED])], eks=FakeEks({}), iam=iam) == 0


# ------------------------------------------------------------------ wiring

def test_wiring_protect_runs_before_any_addon_is_removed_and_sweep_after_role_sweep():
    text = open(TASKFILE).read()
    addons = text[text.index("\n  hub:destroy-addons:\n"):text.index("\n  destroy:\n")]
    i_protect = addons.index('/scripts/protect-shared-iam.py"')
    assert i_protect < addons.index("Stopping all regeneration")
    assert i_protect < addons.index("agent-platform")
    assert "destroy-inventory.json" in addons[i_protect:i_protect + 400]
    destroy = text[text.index("\n  destroy:\n"):]
    assert destroy.index("destroy-inventory.json") < destroy.index("- task: hub:destroy-addons")
    assert destroy.index("# 6b. ALL remaining") < destroy.index("scripts/sweep-shared-iam.py") \
        < destroy.index("# 6c. ALL remaining")
