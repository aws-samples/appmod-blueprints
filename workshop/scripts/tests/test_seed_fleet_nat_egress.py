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
if a[:1] == ["get"] and a[1].startswith("elasticipaddresses"):
    ns = a[a.index("-n") + 1]
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
         eips_deleting=None):
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
                              "eips_deleting": eips_deleting or {}}))
    aws = tmp_path / "aws.json"
    aws.write_text(json.dumps({"secret": secret, "writes": []}))
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}",
               FAKE_KUBECTL_STATE=str(ks), FAKE_AWS_STATE=str(aws),
               FAKE_HUB_KUBECONFIG=str(tmp_path / "private" / "hub-kubeconfig"))
    env.pop("KUBECONFIG", None)
    return aws, env


def _run(tmp_path, provider, secret, secrets=SECRETS, eips=EIPS, fail_secrets=False, fail_eips=None,
         eips_deleting=None):
    # Every cmd of the real task, in order, except the trailing ESO refresh (it talks to the
    # cluster for 60s and is asserted separately), with the provider's own hub:kubeconfig task
    # and its Taskfile-level env KUBECONFIG (the kind bootstrap cluster), so a kubectl call that
    # is not pointed at the hub kubeconfig reaches the "kind" cluster and fails.
    _, t = _task_shell(provider)
    cmds = [c for c in t["cmds"] if c != {"task": "hub:force-eso-refresh"}]
    aws, env = _env(tmp_path, secret, secrets, eips, fail_secrets, fail_eips, eips_deleting)
    tf = tmp_path / "Taskfile.yml"
    tf.write_text(yaml.safe_dump({
        "version": "3", "set": ["errexit", "nounset", "pipefail"],
        "env": {"KUBECONFIG": "{{.ROOT_DIR}}/private/kubeconfig"},
        "vars": dict({k: "" for k in COLORS}, HUB_CLUSTER_NAME=HUB, AWS_REGION=REGION),
        "tasks": {"run": {"cmds": cmds},
                  "hub:kubeconfig": _provider_task(provider, "hub:kubeconfig")}},
        sort_keys=False))
    res = subprocess.run([TASK, "-s", "-t", str(tf), "run"], cwd=tmp_path, env=env,
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
