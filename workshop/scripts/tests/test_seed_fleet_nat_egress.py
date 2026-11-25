"""Hermetic tests for `secrets-manager:seed-fleet-nat-egress` (kind-kro-ack, kind-crossplane).

The task runs on the hub, where every spoke's ACK `ElasticIPAddress` CR lives (the kro
EksclusterWithVpc graph runs on the hub, namespace = spoke name). It takes EVERY registered spoke
(all cluster secrets except the control-plane and any being deleted — no per-addon filter), unions
their `status.publicIP` as sorted, deduplicated /32s (skipping an EIP that is being released), and
writes `fleet_nat_egress_cidrs` into `<hub>/config` (empty union removes the key). The registry
passes it to ingress-class-alb as `fleetEgressCidrs`.

`kubectl` and `aws` are fakes on PATH driven by a state file; `jq`/`awk`/`sort`/`paste` are real.
The task's shell block is read verbatim from the provider Taskfile and run under go-task.

Run:  python -m pytest workshop/scripts/tests/test_seed_fleet_nat_egress.py -q
"""
import json
import os
import shutil
import subprocess
import sys

import pytest

yaml = pytest.importorskip("yaml")
if not (shutil.which("jq") and shutil.which("awk")):
    pytest.skip("jq and awk are required", allow_module_level=True)
TASK = shutil.which("task")
needs_task = pytest.mark.skipif(TASK is None, reason="go-task not on PATH")

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
PROVIDERS = {
    "kind-kro-ack": os.path.join(REPO, "cluster-providers", "kind-kro-ack", "Taskfile.yaml"),
    "kind-crossplane": os.path.join(REPO, "cluster-providers", "kind-crossplane", "Taskfile.yaml"),
}
TASK_NAME = "secrets-manager:seed-fleet-nat-egress"
HUB, REGION = "acme-hub", "us-west-2"
COLORS = ("C_ERR", "C_RESET", "C_OK", "C_INFO", "C_STEP", "C_WARN")

FAKE_KUBECTL = r'''#!{python} -I
import json, os, sys
st = json.load(open(os.environ["FAKE_KUBECTL_STATE"]))
a = sys.argv[1:]
# Only the HUB answers. Any other kubeconfig (the Taskfile-level env KUBECONFIG = the kind
# bootstrap cluster, or nothing) fails like an unreachable/foreign cluster, so a task that
# forgets to point kubectl at the hub kubeconfig cannot pass by accident (review #1308).
kc = os.environ.get("KUBECONFIG", "")
st.setdefault("kubeconfigs", []).append(kc)
json.dump(st, open(os.environ["FAKE_KUBECTL_STATE"], "w"))
if kc != os.environ["FAKE_HUB_KUBECONFIG"] or not os.path.isfile(kc):
    sys.stderr.write("error: not the hub cluster (KUBECONFIG=%r)\n" % kc)
    sys.exit(1)
if a[:2] == ["get", "secrets"]:
    if st.get("fail_secrets"):
        sys.stderr.write("Unable to connect to the server: net/http: TLS handshake timeout\n")
        sys.exit(1)
    print(json.dumps(st["secrets"])); sys.exit(0)
if a[:1] == ["get"] and a[1].startswith("eksclusterwithvpcs") and "-A" in a:
    # kro spoke instances on the hub: st["instances"] = {namespace: "live" | "deleting"}
    if st.get("no_kro_crd"):
        sys.stderr.write('error: the server doesn\'t have a resource type "eksclusterwithvpcs"\n')
        sys.exit(1)
    if st.get("fail_instances"):
        sys.stderr.write("error: the server was unable to return a response\n")
        sys.exit(1)
    items = []
    for ns, state in st.get("instances", {}).items():
        md = {"name": ns, "namespace": ns}
        if state == "deleting":
            md["deletionTimestamp"] = "2026-11-20T00:00:00Z"
        items.append({"metadata": md})
    print(json.dumps({"items": items})); sys.exit(0)
if a[:1] == ["get"] and a[1].startswith("elasticipaddresses") and "-A" in a:
    # every EIP on the hub, all namespaces (unregistered-spoke detection)
    if st.get("no_eip_crd"):
        sys.stderr.write('error: the server doesn\'t have a resource type "elasticipaddresses"\n')
        sys.exit(1)
    if st.get("fail_eips_all"):
        sys.stderr.write("error: the server was unable to return a response\n")
        sys.exit(1)
    items = []
    for ns, ips in st.get("eips", {}).items():
        items += [{"metadata": {"namespace": ns}, "status": {"publicIP": ip}} for ip in ips]
    for ns, ips in st.get("eips_deleting", {}).items():
        items += [{"metadata": {"namespace": ns, "deletionTimestamp": "2026-11-20T00:00:00Z"},
                   "status": {"publicIP": ip}} for ip in ips]
    for ns in st.get("eips_pending", []):
        items.append({"metadata": {"namespace": ns}, "status": {}})
    print(json.dumps({"items": items})); sys.exit(0)
if a[:1] == ["get"] and a[1].startswith("elasticipaddresses"):
    ns = a[a.index("-n") + 1]
    if st.get("no_eip_crd"):
        sys.stderr.write('error: the server doesn\'t have a resource type "elasticipaddresses"\n')
        sys.exit(1)
    if ns in st.get("fail_eips", []):
        sys.stderr.write("error: the server was unable to return a response\n")
        sys.exit(1)
    items = [{"metadata": {}, "status": {"publicIP": ip}}
             for ip in st.get("eips", {}).get(ns, [])]
    # EIPs being released: carry a deletionTimestamp (must be skipped by the task).
    items += [{"metadata": {"deletionTimestamp": "2026-11-20T00:00:00Z"}, "status": {"publicIP": ip}}
              for ip in st.get("eips_deleting", {}).get(ns, [])]
    print(json.dumps({"items": items})); sys.exit(0)
sys.stderr.write("unexpected kubectl %r\n" % a); sys.exit(2)
'''

FAKE_AWS = r'''#!{python} -I
import json, os, sys
st_path = os.environ["FAKE_AWS_STATE"]
st = json.load(open(st_path))
svc, op, rest = sys.argv[1], sys.argv[2], sys.argv[3:]
opts, i = {}, 0
while i < len(rest):
    if rest[i].startswith("--") and i + 1 < len(rest) and not rest[i + 1].startswith("--"):
        opts[rest[i][2:]] = rest[i + 1]; i += 2
    else:
        i += 1
rc = 0
if (svc, op) == ("eks", "update-kubeconfig"):
    # hub:kubeconfig: write a kubeconfig for the hub at --kubeconfig.
    open(opts["kubeconfig"], "w").write("# fake hub kubeconfig for %s\n" % opts["name"])
elif (svc, op) == ("secretsmanager", "get-secret-value"):
    if st["secret"] is None:
        sys.stderr.write("ResourceNotFoundException\n"); rc = 254
    else:
        print(st["secret"])
elif (svc, op) == ("secretsmanager", "put-secret-value"):
    st["writes"].append(opts["secret-string"]); st["secret"] = opts["secret-string"]
else:
    sys.stderr.write("unexpected aws %r\n" % sys.argv[1:]); rc = 2
json.dump(st, open(st_path, "w"))
sys.exit(rc)
'''


def _cluster_secret(name, labels, cluster_name=None, deleting=False):
    s = {"metadata": {"name": name, "labels": labels, "annotations": {}}}
    if cluster_name:
        s["metadata"]["annotations"]["aws_cluster_name"] = cluster_name
    if deleting:
        s["metadata"]["deletionTimestamp"] = "2026-11-20T00:00:00Z"
    return s


# hub (control-plane, excluded), three spokes of ANY addon mix — ALL included now (no addon
# filter); labels are arbitrary to prove the selection no longer depends on them.
SECRETS = {"items": [
    _cluster_secret("acme-hub", {"fleet_member": "control-plane"}, "acme-hub"),
    _cluster_secret("sdev", {"fleet_member": "spoke", "enable_agent_gateway": "true"},
                    "acme-spoke-dev"),
    _cluster_secret("sprod", {"fleet_member": "spoke", "enable_otel_collector": "true"},
                    "acme-spoke-prod"),
    _cluster_secret("splain", {"fleet_member": "spoke", "enable_metrics_server": "true"},
                    "acme-spoke-plain"),
]}
EIPS = {
    "acme-hub": ["203.0.113.1"],            # must NOT be collected (control-plane excluded)
    "acme-spoke-dev": ["203.0.113.201"],
    "acme-spoke-prod": ["203.0.113.202", "203.0.113.202"],  # duplicate -> deduped
    "acme-spoke-plain": ["203.0.113.250"],  # now INCLUDED (no addon filter)
}
EXPECTED = "203.0.113.201/32,203.0.113.202/32,203.0.113.250/32"

META_BASE = {"aws_cluster_name": HUB, "ingress_domain_name": "idp.example.com"}


def _secret_string(meta):
    return json.dumps({"metadata": json.dumps(meta)})


def _task_shell(provider):
    with open(PROVIDERS[provider]) as f:
        t = yaml.safe_load(f)["tasks"][TASK_NAME]
    shell = [c for c in t["cmds"] if isinstance(c, str)]
    assert shell, f"{provider}: no shell cmd in {TASK_NAME}"
    return "\n".join(shell), t


def _provider_task(provider, name):
    with open(PROVIDERS[provider]) as f:
        return yaml.safe_load(f)["tasks"][name]


def _env(tmp_path, secret, secrets=SECRETS, eips=EIPS, fail_secrets=False, fail_eips=None,
         eips_deleting=None, **kstate):
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    (bindir / "kubectl").write_text(FAKE_KUBECTL.replace("{python}", sys.executable))
    (bindir / "kubectl").chmod(0o755)
    (bindir / "aws").write_text(FAKE_AWS.replace("{python}", sys.executable))
    (bindir / "aws").chmod(0o755)
    (tmp_path / "private").mkdir(exist_ok=True)
    ks = tmp_path / "kubectl.json"
    ks.write_text(json.dumps({"secrets": secrets, "eips": eips,
                              "fail_secrets": fail_secrets, "fail_eips": fail_eips or [],
                              "eips_deleting": eips_deleting or {}, **kstate}))
    aws = tmp_path / "aws.json"
    aws.write_text(json.dumps({"secret": secret, "writes": []}))
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}",
               FAKE_KUBECTL_STATE=str(ks), FAKE_AWS_STATE=str(aws),
               FAKE_HUB_KUBECONFIG=str(tmp_path / "private" / "hub-kubeconfig"))
    env.pop("KUBECONFIG", None)
    return aws, env


def _run(tmp_path, provider, secret, secrets=SECRETS, eips=EIPS, fail_secrets=False, fail_eips=None,
         eips_deleting=None, cli_vars=(), **kstate):
    # Every cmd of the real task, in order, except the trailing ESO refresh (it talks to the
    # cluster for 60s and is asserted separately), with the provider's own hub:kubeconfig task
    # and its Taskfile-level env KUBECONFIG (the kind bootstrap cluster), so a kubectl call that
    # is not pointed at the hub kubeconfig reaches the "kind" cluster and fails.
    _, t = _task_shell(provider)
    cmds = [c for c in t["cmds"] if c != {"task": "hub:force-eso-refresh"}]
    aws, env = _env(tmp_path, secret, secrets, eips, fail_secrets, fail_eips, eips_deleting, **kstate)
    tf = tmp_path / "Taskfile.yml"
    tf.write_text(yaml.safe_dump({
        "version": "3", "set": ["errexit", "nounset", "pipefail"],
        "env": {"KUBECONFIG": "{{.ROOT_DIR}}/private/kubeconfig"},
        "vars": dict({k: "" for k in COLORS}, HUB_CLUSTER_NAME=HUB, AWS_REGION=REGION),
        "tasks": {"run": {"cmds": cmds},
                  "hub:kubeconfig": _provider_task(provider, "hub:kubeconfig")}},
        sort_keys=False))
    res = subprocess.run([TASK, "-s", "-t", str(tf), "run", *cli_vars], cwd=tmp_path, env=env,
                         capture_output=True, text=True, timeout=120)
    st = json.loads(aws.read_text())
    return res, st


def _meta(secret_string):
    return json.loads(json.loads(secret_string)["metadata"])


def _sub(tmp_path, n):
    d = tmp_path / n
    d.mkdir()
    return d


@needs_task
@pytest.mark.parametrize("provider", sorted(PROVIDERS))
class TestFleetTask:
    def test_unions_all_spoke_eips_sorted_deduped(self, tmp_path, provider):
        res, st = _run(tmp_path, provider, _secret_string(dict(META_BASE)))
        assert res.returncode == 0, res.stdout + res.stderr
        assert len(st["writes"]) == 1
        assert _meta(st["writes"][0])["fleet_nat_egress_cidrs"] == EXPECTED

    def test_includes_every_spoke_excludes_only_control_plane(self, tmp_path, provider):
        _, st = _run(tmp_path, provider, _secret_string(dict(META_BASE)))
        v = _meta(st["writes"][0])["fleet_nat_egress_cidrs"]
        assert "203.0.113.1/32" not in v          # hub (control-plane) excluded
        # every spoke included regardless of which addon labels it carries
        assert "203.0.113.201/32" in v and "203.0.113.202/32" in v and "203.0.113.250/32" in v

    def test_spoke_being_deleted_is_excluded(self, tmp_path, provider):
        # A spoke whose cluster secret carries a deletionTimestamp must not contribute its NAT.
        secrets = {"items": [
            _cluster_secret("acme-hub", {"fleet_member": "control-plane"}, "acme-hub"),
            _cluster_secret("sdev", {"fleet_member": "spoke"}, "acme-spoke-dev"),
            _cluster_secret("sgone", {"fleet_member": "spoke"}, "acme-spoke-gone", deleting=True),
        ]}
        eips = {"acme-spoke-dev": ["203.0.113.201"], "acme-spoke-gone": ["203.0.113.209"]}
        res, st = _run(tmp_path, provider, _secret_string(dict(META_BASE)), secrets=secrets, eips=eips)
        assert res.returncode == 0, res.stdout + res.stderr
        v = _meta(st["writes"][0])["fleet_nat_egress_cidrs"]
        assert v == "203.0.113.201/32"            # the deleting spoke's 209 is excluded

    def test_eip_being_released_is_excluded(self, tmp_path, provider):
        # An EIP CR with a deletionTimestamp (address being released) must be skipped.
        secrets = {"items": [
            _cluster_secret("sdev", {"fleet_member": "spoke"}, "acme-spoke-dev"),
        ]}
        res, st = _run(tmp_path, provider, _secret_string(dict(META_BASE)),
                       secrets=secrets, eips={"acme-spoke-dev": ["203.0.113.201"]},
                       eips_deleting={"acme-spoke-dev": ["203.0.113.209"]})
        assert res.returncode == 0, res.stdout + res.stderr
        assert _meta(st["writes"][0])["fleet_nat_egress_cidrs"] == "203.0.113.201/32"

    def test_empty_union_removes_the_key(self, tmp_path, provider):
        # No eligible spokes (only the control-plane) -> empty union -> key deleted if stored.
        secrets = {"items": [_cluster_secret("acme-hub", {"fleet_member": "control-plane"}, "acme-hub")]}
        res, st = _run(tmp_path, provider, _secret_string(dict(META_BASE, fleet_nat_egress_cidrs="203.0.113.9/32")),
                       secrets=secrets, eips={"acme-hub": ["203.0.113.1"]})
        assert res.returncode == 0, res.stdout + res.stderr
        assert "fleet_nat_egress_cidrs" not in _meta(st["writes"][0])

    def test_idempotent_no_write_when_unchanged(self, tmp_path, provider):
        res, st = _run(tmp_path, provider,
                       _secret_string(dict(META_BASE, fleet_nat_egress_cidrs=EXPECTED)))
        assert res.returncode == 0, res.stdout + res.stderr
        assert st["writes"] == []

    def test_unreadable_secret_fails(self, tmp_path, provider):
        res, st = _run(tmp_path, provider, None)
        assert res.returncode != 0
        assert st["writes"] == []

    def test_kubectl_secrets_failure_keeps_stored_key(self, tmp_path, provider):
        # A transient `kubectl get secrets` error must NOT be read as "zero spokes" and delete
        # the stored union — fail closed: no write, non-zero exit, key preserved.
        res, st = _run(tmp_path, provider,
                       _secret_string(dict(META_BASE, fleet_nat_egress_cidrs=EXPECTED)),
                       fail_secrets=True)
        assert res.returncode != 0
        assert st["writes"] == []
        assert _meta(st["secret"])["fleet_nat_egress_cidrs"] == EXPECTED

    def test_kubectl_eip_failure_keeps_stored_key(self, tmp_path, provider):
        # A transient per-spoke EIP read error must not narrow/delete the union either.
        res, st = _run(tmp_path, provider,
                       _secret_string(dict(META_BASE, fleet_nat_egress_cidrs=EXPECTED)),
                       fail_eips=["acme-spoke-dev"])
        assert res.returncode != 0
        assert st["writes"] == []
        assert _meta(st["secret"])["fleet_nat_egress_cidrs"] == EXPECTED

    def test_spoke_without_ack_eip_is_reported(self, tmp_path, provider):
        # A Crossplane-composed spoke has no ACK ElasticIPAddress on the hub: it contributes
        # nothing, and the task says so instead of dropping it silently (review #1308).
        secrets = {"items": [
            _cluster_secret("sdev", {"fleet_member": "spoke"}, "acme-spoke-dev"),
            _cluster_secret("sxp", {"fleet_member": "spoke"}, "acme-spoke-xp"),
        ]}
        res, st = _run(tmp_path, provider, _secret_string(dict(META_BASE)), secrets=secrets,
                       eips={"acme-spoke-dev": ["203.0.113.201"]})
        assert res.returncode == 0, res.stdout + res.stderr
        assert _meta(st["writes"][0])["fleet_nat_egress_cidrs"] == "203.0.113.201/32"
        out = res.stdout + res.stderr
        assert "spoke acme-spoke-xp: no ACK ElasticIPAddress" in out
        assert "acme-spoke-dev: no ACK" not in out

    def test_warns_when_the_allowlist_exceeds_28_entries(self, tmp_path, provider):
        cfg = ",".join("198.51.100.%d/32" % i for i in range(1, 26))   # 25 + 1 hub NAT + 3 spokes
        res, _ = _run(tmp_path, provider, _secret_string(dict(
            META_BASE, config_inbound_cidrs=cfg, nat_egress_cidrs="192.0.2.1/32")))
        assert res.returncode == 0, res.stdout + res.stderr
        assert "allowlist has 29 entries" in res.stdout + res.stderr

    def test_no_size_warning_without_config_allowlist(self, tmp_path, provider):
        res, _ = _run(tmp_path, provider, _secret_string(dict(META_BASE)))
        assert "entries before any overlay" not in res.stdout + res.stderr

    # --- pre-review #1308 correctness 1: a spoke not registered (yet) must not vanish silently
    HUB_ONLY = {"items": [_cluster_secret("acme-hub", {"fleet_member": "control-plane"}, "acme-hub")]}
    TWO_EIPS = {"acme-hub": ["203.0.113.1"], "acme-spoke-dev": ["203.0.113.201"],
                "acme-spoke-prod": ["203.0.113.202"]}

    LIVE2 = {"acme-spoke-dev": "live", "acme-spoke-prod": "live"}

    def test_spoke_with_eip_but_no_cluster_secret_is_added_and_reported(self, tmp_path, provider):
        # wait-for-spokes gave up before the spokes' cluster secrets were registered: their EIPs
        # and their live kro instances already live on the hub. They used to be skipped silently
        # ("already up to date (<none>)").
        res, st = _run(tmp_path, provider, _secret_string(dict(
            META_BASE, config_inbound_cidrs="198.51.100.0/24")),
            secrets=self.HUB_ONLY, eips=self.TWO_EIPS, instances=self.LIVE2)
        out = res.stdout + res.stderr
        assert res.returncode == 0, out
        assert _meta(st["writes"][0])["fleet_nat_egress_cidrs"] == "203.0.113.201/32,203.0.113.202/32"
        assert "203.0.113.1/32" not in _meta(st["writes"][0])["fleet_nat_egress_cidrs"]
        for ns in ("acme-spoke-dev", "acme-spoke-prod"):
            assert "namespace %s: ACK ElasticIPAddress but no registered Argo CD cluster secret" % ns in out

    def test_rerun_keeps_the_nat_of_a_live_spoke_whose_secret_is_briefly_absent(self, tmp_path, provider):
        # prod's secret is briefly absent but its kro instance is live (not being deleted).
        secrets = {"items": self.HUB_ONLY["items"] + [
            _cluster_secret("sdev", {"fleet_member": "spoke"}, "acme-spoke-dev")]}
        stored = "203.0.113.201/32,203.0.113.202/32"
        res, st = _run(tmp_path, provider, _secret_string(dict(META_BASE, fleet_nat_egress_cidrs=stored)),
                       secrets=secrets, eips=self.TWO_EIPS, instances=self.LIVE2)
        out = res.stdout + res.stderr
        assert res.returncode == 0, out
        assert st["writes"] == [], st                        # the stored union is not narrowed
        assert "namespace acme-spoke-prod: ACK ElasticIPAddress but no registered" in out

    def test_unregistered_eip_without_public_ip_yet_is_reported(self, tmp_path, provider):
        res, st = _run(tmp_path, provider, _secret_string(dict(META_BASE)),
                       secrets=self.HUB_ONLY, eips={}, eips_pending=["acme-spoke-dev"],
                       instances={"acme-spoke-dev": "live"})
        out = res.stdout + res.stderr
        assert res.returncode == 0, out
        assert "namespace acme-spoke-dev" in out and "no public IP yet" in out

    def test_eip_being_released_in_an_unregistered_namespace_is_not_added(self, tmp_path, provider):
        res, st = _run(tmp_path, provider, _secret_string(dict(META_BASE)), secrets=self.HUB_ONLY,
                       eips={}, eips_deleting={"acme-spoke-gone": ["203.0.113.209"]})
        assert res.returncode == 0, res.stdout + res.stderr
        assert st["writes"] == []

    def test_eip_of_a_spoke_being_deleted_without_secret_is_not_added(self, tmp_path, provider):
        # spokes:disable-kro deletes the cluster secret as soon as the EksclusterWithVpc starts
        # deleting; kro deletes the EIP last. Its NAT must leave the union, not be re-added
        # (review: a deleted spoke's released EIP must not stay allowlisted).
        secrets = {"items": self.HUB_ONLY["items"] + [
            _cluster_secret("sdev", {"fleet_member": "spoke"}, "acme-spoke-dev")]}
        stored = "203.0.113.201/32,203.0.113.202/32"
        res, st = _run(tmp_path, provider, _secret_string(dict(META_BASE, fleet_nat_egress_cidrs=stored)),
                       secrets=secrets, eips=self.TWO_EIPS,
                       instances={"acme-spoke-dev": "live", "acme-spoke-prod": "deleting"})
        out = res.stdout + res.stderr
        assert res.returncode == 0, out
        assert _meta(st["writes"][0])["fleet_nat_egress_cidrs"] == "203.0.113.201/32"
        assert "namespace acme-spoke-prod: ACK ElasticIPAddress (203.0.113.202/32)" in out
        assert "NOT added" in out

    def test_eip_in_a_non_spoke_namespace_is_not_added(self, tmp_path, provider):
        # an ACK EIP in a namespace with no kro instance (team-a) is not a spoke's.
        eips = dict(EIPS, **{"team-a": ["203.0.113.77"]})
        res, st = _run(tmp_path, provider, _secret_string(dict(META_BASE)), eips=eips)
        out = res.stdout + res.stderr
        assert res.returncode == 0, out
        v = _meta(st["writes"][0])["fleet_nat_egress_cidrs"]
        assert v == EXPECTED and "203.0.113.77" not in v
        assert "namespace team-a: ACK ElasticIPAddress (203.0.113.77/32)" in out and "NOT added" in out

    def test_eip_of_a_spoke_with_no_kro_instance_left_is_not_added(self, tmp_path, provider):
        # instance gone (graph deleted) but an EIP CR lingers: not added.
        res, st = _run(tmp_path, provider, _secret_string(dict(META_BASE)), secrets=self.HUB_ONLY,
                       eips={"acme-spoke-gone": ["203.0.113.209"]}, instances={})
        assert res.returncode == 0, res.stdout + res.stderr
        assert st["writes"] == []

    def test_instance_listing_failure_keeps_stored_key(self, tmp_path, provider):
        res, st = _run(tmp_path, provider, _secret_string(dict(META_BASE, fleet_nat_egress_cidrs=EXPECTED)),
                       fail_instances=True)
        assert res.returncode != 0
        assert st["writes"] == []

    def test_hub_without_the_kro_crd_adds_no_orphan(self, tmp_path, provider):
        res, st = _run(tmp_path, provider, _secret_string(dict(META_BASE)), secrets=self.HUB_ONLY,
                       eips={"acme-spoke-dev": ["203.0.113.201"]}, no_kro_crd=True)
        assert res.returncode == 0, res.stdout + res.stderr
        assert st["writes"] == []

    def test_missing_eip_type_never_shrinks_a_stored_union(self, tmp_path, provider):
        # discovery gap: the -A call says "doesn't have a resource type" while a union is stored
        # (and no spoke secret is registered, so no per-spoke call fails first).
        res, st = _run(tmp_path, provider, _secret_string(dict(META_BASE, fleet_nat_egress_cidrs=EXPECTED)),
                       secrets=self.HUB_ONLY, eips={}, no_eip_crd=True)
        assert res.returncode != 0, res.stdout + res.stderr
        assert st["writes"] == []
        assert "reports no ElasticIPAddress type" in res.stdout + res.stderr
        assert "FLEET_NAT_FORCE=true" in res.stdout + res.stderr

    # --- pre-review round 3 of #1308: a REGISTERED spoke being deleted -----------------------
    def test_registered_spoke_being_deleted_is_not_added(self, tmp_path, provider):
        # spokes:disable-kro keeps the cluster secret up to 180 s after the prune (or for good
        # when the appsets do not refresh); the Secret has no finalizer, so its own
        # deletionTimestamp never lingers. The EksclusterWithVpc deletionTimestamp is the signal.
        res, st = _run(tmp_path, provider, _secret_string(dict(META_BASE)),
                       instances={"acme-spoke-dev": "live", "acme-spoke-prod": "deleting",
                                  "acme-spoke-plain": "live"})
        out = res.stdout + res.stderr
        assert res.returncode == 0, out
        v = _meta(st["writes"][0])["fleet_nat_egress_cidrs"]
        assert v == "203.0.113.201/32,203.0.113.250/32", v
        assert "spoke acme-spoke-prod: being deleted (EksclusterWithVpc deletionTimestamp)" in out

    def test_registered_spoke_being_deleted_leaves_a_stored_union(self, tmp_path, provider):
        res, st = _run(tmp_path, provider, _secret_string(dict(META_BASE, fleet_nat_egress_cidrs=EXPECTED)),
                       instances={"acme-spoke-prod": "deleting"})
        out = res.stdout + res.stderr
        assert res.returncode == 0, out
        assert _meta(st["writes"][0])["fleet_nat_egress_cidrs"] == "203.0.113.201/32,203.0.113.250/32"

    def test_missing_kro_type_never_shrinks_a_stored_union(self, tmp_path, provider):
        # the kro type is reported missing while an unregistered spoke's NAT is stored: without
        # the instances the task cannot tell a live spoke from a deleted one, so it keeps it.
        res, st = _run(tmp_path, provider, _secret_string(dict(META_BASE, fleet_nat_egress_cidrs="203.0.113.201/32")),
                       secrets=self.HUB_ONLY, eips={"acme-spoke-dev": ["203.0.113.201"]}, no_kro_crd=True)
        out = res.stdout + res.stderr
        assert res.returncode != 0, out
        assert st["writes"] == []
        assert "reports no EksclusterWithVpc type" in out and "FLEET_NAT_FORCE=true" in out

    @pytest.mark.parametrize("crd", ["no_eip_crd", "no_kro_crd"])
    def test_force_lets_a_missing_type_shrink_the_union(self, tmp_path, provider, crd):
        # the operator's way out once the type is really gone (e.g. every kro spoke deleted and
        # the ACK EC2 controller removed afterwards): FLEET_NAT_FORCE=true.
        res, st = _run(tmp_path, provider, _secret_string(dict(META_BASE, fleet_nat_egress_cidrs=EXPECTED)),
                       secrets=self.HUB_ONLY, eips={}, cli_vars=("FLEET_NAT_FORCE=true",), **{crd: True})
        out = res.stdout + res.stderr
        assert res.returncode == 0, out
        assert "fleet_nat_egress_cidrs" not in _meta(st["writes"][0])
        assert "FLEET_NAT_FORCE=true" in out

    def test_eip_listing_failure_keeps_stored_key(self, tmp_path, provider):
        res, st = _run(tmp_path, provider, _secret_string(dict(META_BASE, fleet_nat_egress_cidrs=EXPECTED)),
                       fail_eips_all=True)
        assert res.returncode != 0
        assert st["writes"] == []

    def test_hub_without_the_eip_crd_and_no_spoke_is_a_noop(self, tmp_path, provider):
        res, st = _run(tmp_path, provider, _secret_string(dict(META_BASE)),
                       secrets=self.HUB_ONLY, eips={}, no_eip_crd=True)
        assert res.returncode == 0, res.stdout + res.stderr
        assert st["writes"] == []

    def test_fetches_hub_kubeconfig_first(self, provider):
        _, t = _task_shell(provider)
        assert t["cmds"][0] == {"task": "hub:kubeconfig"}

    def test_every_kubectl_call_targets_the_hub(self, tmp_path, provider):
        # review #1308 B1: with the Taskfile env KUBECONFIG (kind) the old task found 0 spokes,
        # deleted the stored union and exited 0. Every kubectl call must carry the hub kubeconfig.
        res, st = _run(tmp_path, provider, _secret_string(dict(META_BASE)))
        assert res.returncode == 0, res.stdout + res.stderr
        ks = json.loads((tmp_path / "kubectl.json").read_text())
        hub = str(tmp_path / "private" / "hub-kubeconfig")
        assert ks["kubeconfigs"] and set(ks["kubeconfigs"]) == {hub}

    def test_calls_eso_refresh_last(self, provider):
        _, t = _task_shell(provider)
        assert t["cmds"][-1] == {"task": "hub:force-eso-refresh"}

    def test_other_metadata_untouched(self, tmp_path, provider):
        res, st = _run(tmp_path, provider, _secret_string(dict(META_BASE)))
        m = _meta(st["writes"][0])
        assert m["aws_cluster_name"] == HUB and m["ingress_domain_name"] == "idp.example.com"


# --- review #1308 (second review): the install runs the task a second time ------------------
# The first run is non-fatal and races seed-observability (get/modify/put of <hub>/config, no
# lock); spoke-apps-bg runs the task again minutes later. These are the three cases it covers,
# plus the one where it must stay quiet (a second writer only when something changed).
@needs_task
@pytest.mark.parametrize("provider", sorted(PROVIDERS))
class TestSecondRun:
    def test_after_a_good_first_run_it_writes_nothing(self, tmp_path, provider):
        _, st1 = _run(_sub(tmp_path, "r1"), provider, _secret_string(dict(META_BASE)))
        assert len(st1["writes"]) == 1
        res, st2 = _run(_sub(tmp_path, "r2"), provider, st1["secret"])
        assert res.returncode == 0, res.stdout + res.stderr
        assert st2["writes"] == []
        assert "already up to date" in res.stdout

    def test_restores_a_union_lost_to_a_concurrent_writer(self, tmp_path, provider):
        _, st1 = _run(_sub(tmp_path, "r1"), provider, _secret_string(dict(META_BASE)))
        assert _meta(st1["secret"])["fleet_nat_egress_cidrs"] == EXPECTED
        # seed-observability read <hub>/config before that write and put its copy after it.
        lost = _secret_string(dict(META_BASE, spoke_dev_cluster_name="acme-spoke-dev"))
        res, st2 = _run(_sub(tmp_path, "r2"), provider, lost)
        assert res.returncode == 0, res.stdout + res.stderr
        assert len(st2["writes"]) == 1
        m = _meta(st2["secret"])
        assert m["fleet_nat_egress_cidrs"] == EXPECTED
        assert m["spoke_dev_cluster_name"] == "acme-spoke-dev"    # the other writer's key kept

    def test_adds_a_spoke_whose_eip_was_not_there_on_the_first_run(self, tmp_path, provider):
        late = {k: v for k, v in EIPS.items() if k != "acme-spoke-prod"}
        res1, st1 = _run(_sub(tmp_path, "r1"), provider, _secret_string(dict(META_BASE)), eips=late)
        assert "spoke acme-spoke-prod: no ACK ElasticIPAddress" in res1.stdout + res1.stderr
        assert _meta(st1["secret"])["fleet_nat_egress_cidrs"] == "203.0.113.201/32,203.0.113.250/32"
        res, st2 = _run(_sub(tmp_path, "r2"), provider, st1["secret"])
        assert res.returncode == 0, res.stdout + res.stderr
        assert _meta(st2["secret"])["fleet_nat_egress_cidrs"] == EXPECTED

    def test_writes_after_a_failed_first_run(self, tmp_path, provider):
        res1, st1 = _run(_sub(tmp_path, "r1"), provider, _secret_string(dict(META_BASE)),
                         fail_secrets=True)
        assert res1.returncode != 0 and st1["writes"] == []
        res, st2 = _run(_sub(tmp_path, "r2"), provider, st1["secret"])
        assert res.returncode == 0, res.stdout + res.stderr
        assert _meta(st2["secret"])["fleet_nat_egress_cidrs"] == EXPECTED


# --- review #1308 B2: the workshop runs the task once spokes exist, and after a delete ------
WORKSHOP = os.path.join(REPO, "workshop", "Taskfile.yaml")
STEP = "secrets-manager:seed-fleet-nat-egress"


def _ws_cmds(name):
    with open(WORKSHOP) as f:
        return yaml.safe_load(f)["tasks"][name]["cmds"]


def _idx(cmds, pred):
    hits = [i for i, c in enumerate(cmds) if pred(c)]
    assert hits, "no matching cmd"
    return hits[0]


def _is_wfs(c):
    return isinstance(c, dict) and c.get("task") == "wait-for-spokes"


def _is_step(c):
    return isinstance(c, str) and STEP in c and "task {{.PROVIDER}}:" in c


def test_install_runs_it_after_the_spokes_are_active():
    cmds = _ws_cmds("install")
    assert _idx(cmds, _is_wfs) < _idx(cmds, _is_step)


def test_remote_install_runs_it_after_the_spokes_and_before_the_pivot():
    cmds = _ws_cmds("install:remote")
    pivot = _idx(cmds, lambda c: isinstance(c, str) and ":hub:pivot " in c)
    assert _idx(cmds, _is_wfs) < _idx(cmds, _is_step) < pivot


def test_sweep_kro_runs_it_last():
    last = _ws_cmds("spokes:sweep-kro")[-1]
    assert isinstance(last, str) and STEP in last


def _run_step(tmp_path, cmd_text, fake_task_rc):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    log = tmp_path / "task-calls.log"
    (bindir / "task").write_text(
        '#!/bin/sh\nprintf "%%s|%%s\\n" "$PWD" "$*" >> "%s"\nexit %d\n' % (log, fake_task_rc))
    (bindir / "task").chmod(0o755)
    pdir = tmp_path / "platform"
    pdir.mkdir()
    cfg = tmp_path / "config.local.yaml"
    cfg.write_text("clusterProvider: kind-crossplane\n")
    tf = tmp_path / "Taskfile.yml"
    tf.write_text(yaml.safe_dump({
        "version": "3", "set": ["errexit", "nounset", "pipefail"],
        "vars": dict({k: "" for k in COLORS}, PROVIDER="kind-kro-ack",
                     PLATFORM_DIR=str(pdir), CONFIG_FILE=str(cfg)),
        "tasks": {"run": {"cmds": [cmd_text]}}}, sort_keys=False))
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}")
    res = subprocess.run([TASK, "-s", "-t", str(tf), "run"], cwd=tmp_path, env=env,
                         capture_output=True, text=True, timeout=60)
    calls = log.read_text().splitlines() if log.exists() else []
    return res, calls, str(pdir)


def test_spoke_apps_bg_runs_it_again_after_the_prewarms():
    # review #1308 (second review): the second run, at the end of the background job, before
    # its rc file (the install's final check reads it).
    cmds = _ws_cmds("spoke-apps-bg")
    rust = _idx(cmds, lambda c: isinstance(c, dict) and c.get("task") == "prewarm-pathA-rust-kro")
    rc = _idx(cmds, lambda c: isinstance(c, str) and "> /tmp/spoke-apps-bg.rc" in c)
    assert rust < _idx(cmds, _is_step) < rc


@pytest.mark.parametrize("where", ["install", "install:ide"])
def test_both_installs_start_spoke_apps_bg_after_the_spokes_are_active(where):
    cmds = _ws_cmds(where)
    assert _idx(cmds, _is_wfs) < _idx(cmds, lambda c: isinstance(c, str) and "task spoke-apps-bg" in c)


def test_spoke_apps_bg_reads_the_provider_like_install():
    with open(WORKSHOP) as f:
        t = yaml.safe_load(f)["tasks"]
    assert t["spoke-apps-bg"]["vars"]["PROVIDER"] == t["install"]["vars"]["PROVIDER"]


@needs_task
@pytest.mark.parametrize("where", ["install", "install:remote", "spokes:sweep-kro", "spoke-apps-bg"])
@pytest.mark.parametrize("rc", [0, 1])
def test_workshop_step_calls_the_provider_task_and_never_fails(tmp_path, where, rc):
    cmds = _ws_cmds(where)
    cmd = cmds[-1] if where == "spokes:sweep-kro" else cmds[_idx(cmds, _is_step)]
    res, calls, pdir = _run_step(tmp_path, cmd, rc)
    assert res.returncode == 0, res.stdout + res.stderr          # non-fatal either way
    # install / install:remote use their PROVIDER var; sweep-kro reads clusterProvider.
    provider = "kind-crossplane" if where == "spokes:sweep-kro" else "kind-kro-ack"
    assert calls == [f"{pdir}|{provider}:{STEP}"], calls
    warned = "seed-fleet-nat-egress failed" in res.stdout + res.stderr
    assert warned == (rc != 0)
