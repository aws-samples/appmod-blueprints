"""Hermetic tests for `secrets-manager:seed-fleet-nat-egress` (kind-kro-ack, kind-crossplane).

The task runs on the hub, where every spoke's ACK `ElasticIPAddress` CR lives (the kro
EksclusterWithVpc graph runs on the hub, namespace = spoke name). It selects the spokes that run
OAP addons calling the hub's public Keycloak/OTel (cluster-secret labels `enable_agent_gateway` or
`enable_otel_collector`, excluding the control-plane), unions their `status.publicIP` as sorted,
deduplicated /32s, and writes `fleet_nat_egress_cidrs` into `<hub>/config` (empty union removes the
key). The registry passes it to ingress-class-alb as `fleetEgressCidrs`.

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
    items = [{"status": {"publicIP": ip}} for ip in st.get("eips", {}).get(ns, [])]
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
if (svc, op) == ("secretsmanager", "get-secret-value"):
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


def _cluster_secret(name, labels, cluster_name=None):
    s = {"metadata": {"name": name, "labels": labels, "annotations": {}}}
    if cluster_name:
        s["metadata"]["annotations"]["aws_cluster_name"] = cluster_name
    return s


# hub (control-plane, excluded), two OAP spokes (gateway + otel), one non-OAP spoke (excluded).
SECRETS = {"items": [
    _cluster_secret("acme-hub", {"fleet_member": "control-plane",
                                 "enable_agent_gateway": "true"}, "acme-hub"),
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
    "acme-spoke-plain": ["203.0.113.250"],  # must NOT be collected (not OAP)
}
EXPECTED = "203.0.113.201/32,203.0.113.202/32"

META_BASE = {"aws_cluster_name": HUB, "ingress_domain_name": "idp.example.com"}


def _secret_string(meta):
    return json.dumps({"metadata": json.dumps(meta)})


def _task_shell(provider):
    with open(PROVIDERS[provider]) as f:
        t = yaml.safe_load(f)["tasks"][TASK_NAME]
    shell = [c for c in t["cmds"] if isinstance(c, str)]
    assert shell, f"{provider}: no shell cmd in {TASK_NAME}"
    return "\n".join(shell), t


def _env(tmp_path, secret, secrets=SECRETS, eips=EIPS, fail_secrets=False, fail_eips=None):
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    (bindir / "kubectl").write_text(FAKE_KUBECTL.replace("{python}", sys.executable))
    (bindir / "kubectl").chmod(0o755)
    (bindir / "aws").write_text(FAKE_AWS.replace("{python}", sys.executable))
    (bindir / "aws").chmod(0o755)
    ks = tmp_path / "kubectl.json"
    ks.write_text(json.dumps({"secrets": secrets, "eips": eips,
                              "fail_secrets": fail_secrets, "fail_eips": fail_eips or []}))
    aws = tmp_path / "aws.json"
    aws.write_text(json.dumps({"secret": secret, "writes": []}))
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}",
               FAKE_KUBECTL_STATE=str(ks), FAKE_AWS_STATE=str(aws))
    return aws, env


def _run(tmp_path, provider, secret, secrets=SECRETS, eips=EIPS, fail_secrets=False, fail_eips=None):
    shell, _ = _task_shell(provider)
    aws, env = _env(tmp_path, secret, secrets, eips, fail_secrets, fail_eips)
    tf = tmp_path / "Taskfile.yml"
    tf.write_text(yaml.safe_dump({
        "version": "3", "set": ["errexit", "nounset", "pipefail"],
        "vars": dict({k: "" for k in COLORS}, HUB_CLUSTER_NAME=HUB, AWS_REGION=REGION),
        "tasks": {"run": {"cmds": [shell]}}}, sort_keys=False))
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
    def test_unions_selected_spoke_eips_sorted_deduped(self, tmp_path, provider):
        res, st = _run(tmp_path, provider, _secret_string(dict(META_BASE)))
        assert res.returncode == 0, res.stdout + res.stderr
        assert len(st["writes"]) == 1
        assert _meta(st["writes"][0])["fleet_nat_egress_cidrs"] == EXPECTED

    def test_excludes_control_plane_and_non_oap_spokes(self, tmp_path, provider):
        _, st = _run(tmp_path, provider, _secret_string(dict(META_BASE)))
        v = _meta(st["writes"][0])["fleet_nat_egress_cidrs"]
        assert "203.0.113.1/32" not in v   # hub (control-plane)
        assert "203.0.113.250/32" not in v  # non-OAP spoke

    def test_empty_union_removes_the_key(self, tmp_path, provider):
        # No OAP spokes selected -> empty union -> key deleted even if it was stored.
        secrets = {"items": [_cluster_secret("splain", {"fleet_member": "spoke",
                                                        "enable_metrics_server": "true"},
                                             "acme-spoke-plain")]}
        res, st = _run(tmp_path, provider, _secret_string(dict(META_BASE, fleet_nat_egress_cidrs="203.0.113.9/32")),
                       secrets=secrets)
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

    def test_calls_eso_refresh_last(self, provider):
        _, t = _task_shell(provider)
        assert t["cmds"][-1] == {"task": "hub:force-eso-refresh"}

    def test_other_metadata_untouched(self, tmp_path, provider):
        res, st = _run(tmp_path, provider, _secret_string(dict(META_BASE)))
        m = _meta(st["writes"][0])
        assert m["aws_cluster_name"] == HUB and m["ingress_domain_name"] == "idp.example.com"
