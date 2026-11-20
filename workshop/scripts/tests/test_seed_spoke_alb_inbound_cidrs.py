"""Hermetic tests for the install-time spoke-ALB source-IP allowlist seed (`spokeAlbInboundCidrs`).

Two halves (mirrors test_seed_config_inbound_cidrs.py, which covers the HUB key albInboundCidrs):

1. appmod providers (kind-kro-ack, kind-crossplane) `secrets-manager:seed`: `spokeAlbInboundCidrs`
   from config.yaml (a YAML list OR a comma-separated string) is normalised to a comma-separated
   string and written as the `spoke_alb_inbound_cidrs` metadata key of <hub>/config. ESO turns it
   into a hub cluster-secret annotation; the clusters-kro appset threads it as the default
   `albInboundCidrs` of every spoke claim, which the EksCluster RGD stamps onto each spoke cluster
   secret as `config_inbound_cidrs`. Empty or absent -> the key is not written -> unchanged.

2. OAP `platform:configure`: the OAP config's `spokeAlbInboundCidrs` is forwarded into the
   generated appmod config.local.yaml ONLY when non-empty, so an OAP config without it renders as
   before.

The provider task vars/cmds are read verbatim and run under go-task. `aws` is a fake on PATH;
`yq`/`jq` are the real tools. No AWS, no network.

Run:  python -m pytest workshop/scripts/tests/test_seed_spoke_alb_inbound_cidrs.py -q
"""
import json
import os
import shutil
import subprocess
import sys

import pytest

yaml = pytest.importorskip("yaml")
if not (shutil.which("yq") and shutil.which("jq")):
    pytest.skip("yq and jq are required", allow_module_level=True)
TASK = shutil.which("task")
needs_task = pytest.mark.skipif(TASK is None, reason="go-task not on PATH (templating required)")

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
OAP_CANDIDATES = [
    os.path.join(REPO, "..", "open-agentic-platform", "Taskfile.yml"),
    os.path.join(REPO, "..", "oap-cidrs", "Taskfile.yml"),
]
PROVIDERS = {
    "kind-kro-ack": os.path.join(REPO, "cluster-providers", "kind-kro-ack", "Taskfile.yaml"),
    "kind-crossplane": os.path.join(REPO, "cluster-providers", "kind-crossplane", "Taskfile.yaml"),
}
TASK_NAME = "secrets-manager:seed"
HUB, REGION = "acme-hub", "us-west-2"
COLORS = ("C_ERR", "C_RESET", "C_OK", "C_INFO", "C_STEP", "C_WARN")

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
if (svc, op) == ("ec2", "describe-nat-gateways"):
    print("")  # no NAT -> isolate spoke_alb_inbound_cidrs from nat_egress_cidrs
elif (svc, op) == ("secretsmanager", "get-secret-value"):
    if st["secret"] is None:
        sys.stderr.write("ResourceNotFoundException\n"); rc = 254
    else:
        print(st["secret"])
elif (svc, op) == ("secretsmanager", "restore-secret"):
    rc = 254
elif (svc, op) == ("secretsmanager", "create-secret"):
    if st["secret"] is not None:
        sys.stderr.write("ResourceExistsException\n"); rc = 254
    else:
        st["writes"].append(opts["secret-string"]); st["secret"] = opts["secret-string"]
elif (svc, op) == ("secretsmanager", "put-secret-value"):
    st["writes"].append(opts["secret-string"]); st["secret"] = opts["secret-string"]
else:
    sys.stderr.write("unexpected aws call %r\n" % sys.argv[1:]); rc = 2
json.dump(st, open(st_path, "w"))
sys.exit(rc)
'''

TVARS = {"HUB_CLUSTER_NAME": HUB, "AWS_REGION": REGION, "AWS_ACCOUNT_ID": "111122223333",
         "REPO_URL": "https://example.com/acme/appmod-blueprints", "REPO_REVISION": "main",
         "REPO_BASEPATH": "gitops/", "AGENTIC_REPO_URL": "", "AGENTIC_REPO_REVISION": "",
         "FLEET_REPO_URL": "https://example.com/acme/appmod-blueprints", "FLEET_REPO_REVISION": "main",
         "FLEET_REPO_BASEPATH": "gitops/", "CLUSTER_ARN": f"arn:aws:eks:{REGION}:111122223333:cluster/{HUB}",
         "VPC_ID": "vpc-0", "PRIVATE_SUBNET_IDS": "subnet-a,subnet-b", "SUBNET_IDS": "subnet-a,subnet-b",
         "CLUSTER_SG": "sg-0", "INGRESS_SECURITY_GROUPS": "", "RESOURCE_PREFIX": "acme",
         "INSECURE": "false", "INGRESS_CERT_ARN": "", "CERTIFICATE_ARN": "", "INGRESS_NAME": "",
         "ADMIN_ROLE_NAME": "Admin", "USER_PASSWORD": "not-a-real-token",
         "ARGOCD_URL": "argocd-0123abcd.example.com", "INGRESS_DOMAIN": "idp.example.com",
         "DOMAIN": "idp.example.com", "GITLAB_DOMAIN": "git.example.com",
         "NAT_EGRESS_CIDRS": ""}


def _task(provider):
    with open(PROVIDERS[provider]) as f:
        t = yaml.safe_load(f)["tasks"].get(TASK_NAME)
    assert t is not None, f"no task {TASK_NAME} in {PROVIDERS[provider]}"
    return t


def _env(tmp_path, secret=None):
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    (bindir / "aws").write_text(FAKE_AWS.replace("{python}", sys.executable))
    (bindir / "aws").chmod(0o755)
    sf = tmp_path / "state.json"
    sf.write_text(json.dumps({"secret": secret, "writes": []}))
    return sf, dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", FAKE_AWS_STATE=str(sf))


def _run(tmp_path, env, script_text, tvars):
    tf = tmp_path / "Taskfile.yml"
    tf.write_text(yaml.safe_dump({
        "version": "3", "set": ["errexit", "nounset", "pipefail"],
        "vars": dict({k: "" for k in COLORS}, **tvars),
        "tasks": {"run": {"cmds": [script_text]}}}, sort_keys=False))
    return subprocess.run([TASK, "-s", "-t", str(tf), "run"], cwd=tmp_path, env=env,
                          capture_output=True, text=True, timeout=120)


def _seed(tmp_path, provider, config, insecure="false", domain="idp.example.com", existing=None):
    cfg = tmp_path / "config.local.yaml"
    cfg.write_text(yaml.safe_dump(config))
    sf, env = _env(tmp_path, secret=existing)
    tvars = dict(TVARS, CONFIG_FILE=str(cfg), ROOT_DIR=str(tmp_path),
                 INSECURE=insecure, DOMAIN=domain, INGRESS_DOMAIN=domain)
    cmds = _task(provider)["cmds"]
    text = "\n".join(c["cmd"] if isinstance(c, dict) else c for c in cmds)
    res = _run(tmp_path, env, text, tvars)
    assert res.returncode == 0, res.stdout + res.stderr
    st = json.loads(sf.read_text())
    assert len(st["writes"]) == 1, st
    return st["writes"][0], res


def _meta(secret_string):
    return json.loads(json.loads(secret_string)["metadata"])


def _cfg(**extra):
    base = {"domain": "idp.example.com", "insecure": False, "platformTags": {},
            "hub": {"clusterName": HUB}, "aws": {"accountId": "111122223333"}}
    base.update(extra)
    return base


def _sub(tmp_path, name):
    d = tmp_path / name
    d.mkdir()
    return d


# --- appmod providers: spoke_alb_inbound_cidrs written from spokeAlbInboundCidrs ------------
@needs_task
@pytest.mark.parametrize("provider", sorted(PROVIDERS))
class TestSeedSpokeAlbInbound:
    def test_list_form_is_joined(self, tmp_path, provider):
        secret, _ = _seed(tmp_path, provider,
                          _cfg(spokeAlbInboundCidrs=["203.0.113.0/24", "203.0.113.5/32"]))
        assert _meta(secret)["spoke_alb_inbound_cidrs"] == "203.0.113.0/24,203.0.113.5/32"

    def test_comma_string_form_is_kept(self, tmp_path, provider):
        secret, _ = _seed(tmp_path, provider,
                          _cfg(spokeAlbInboundCidrs="203.0.113.0/24,203.0.113.5/32"))
        assert _meta(secret)["spoke_alb_inbound_cidrs"] == "203.0.113.0/24,203.0.113.5/32"

    def test_absent_key_writes_nothing(self, tmp_path, provider):
        secret, _ = _seed(tmp_path, provider, _cfg())
        assert "spoke_alb_inbound_cidrs" not in _meta(secret)

    def test_empty_forms_write_nothing(self, tmp_path, provider):
        for i, v in enumerate(["", []]):
            secret, _ = _seed(_sub(tmp_path, f"e{i}"), provider, _cfg(spokeAlbInboundCidrs=v))
            assert "spoke_alb_inbound_cidrs" not in _meta(secret)

    def test_present_key_does_not_disturb_other_metadata(self, tmp_path, provider):
        without, _ = _seed(_sub(tmp_path, "w"), provider, _cfg())
        withk, _ = _seed(_sub(tmp_path, "k"), provider, _cfg(spokeAlbInboundCidrs=["203.0.113.0/24"]))
        assert dict(_meta(without), spoke_alb_inbound_cidrs="203.0.113.0/24") == _meta(withk)

    def test_independent_of_the_hub_key(self, tmp_path, provider):
        # the hub key (albInboundCidrs -> config_inbound_cidrs) and the spoke key are distinct.
        secret, _ = _seed(tmp_path, provider,
                          _cfg(albInboundCidrs=["198.51.100.0/24"],
                               spokeAlbInboundCidrs=["203.0.113.0/24"]))
        m = _meta(secret)
        assert m["config_inbound_cidrs"] == "198.51.100.0/24"
        assert m["spoke_alb_inbound_cidrs"] == "203.0.113.0/24"

    def test_the_secret_is_never_printed(self, tmp_path, provider):
        _, res = _seed(tmp_path, provider, _cfg(spokeAlbInboundCidrs=["203.0.113.0/24"]))
        assert "not-a-real-token" not in res.stdout + res.stderr


# --- OAP forwarding into the generated appmod config.local.yaml -----------------------------
def _oap_taskfile():
    for p in OAP_CANDIDATES:
        if os.path.exists(p):
            return os.path.abspath(p)
    return None


OAP = _oap_taskfile()
needs_oap = pytest.mark.skipif(OAP is None, reason="OAP Taskfile not found next to the appmod repo")


def _oap_configure_cmd():
    with open(OAP) as f:
        t = yaml.safe_load(f)["tasks"]["platform:configure"]
    return "\n".join(c["cmd"] if isinstance(c, dict) else c for c in t["cmds"])


def _oap_spoke_var_expr():
    with open(OAP) as f:
        return yaml.safe_load(f)["vars"]["SPOKE_ALB_INBOUND_CIDRS"]["sh"]


OAP_TVARS = {
    "CLUSTER_PROVIDER": "kind-kro-ack", "PLATFORM_REPO": "https://example.com/acme/appmod",
    "PLATFORM_REF": "main", "HUB_CLUSTER_NAME": HUB, "K8S_VERSION": "1.37",
    "AWS_REGION": REGION, "AWS_ACCOUNT_ID": "111122223333", "AWS_PROFILE": "default",
    "DOMAIN": "idp.example.com", "INSECURE": "false", "RESOURCE_PREFIX": "acme",
    "IDC_INSTANCE_ARN": "arn:aws:sso:::instance/ssoins-0", "IDC_REGION": "us-east-1",
    "IDC_ADMIN_GROUP_ID": "group-0", "FLEET_REPO_URL": "https://example.com/acme/appmod",
    "FLEET_REPO_REVISION": "main", "FLEET_REPO_BASEPATH": "gitops/", "FLEET_SCOPE_BY_PREFIX": "",
    "AGENTIC_REPO_URL": "https://example.com/acme/oap", "AGENTIC_REPO_REVISION": "main",
    "ALB_INBOUND_CIDRS": "",
}


def _oap_configure(tmp_path, spoke_value, alb_value=""):
    pdir = tmp_path / ".platform"
    pdir.mkdir()
    tf = tmp_path / "Taskfile.yml"
    tf.write_text(yaml.safe_dump({
        "version": "3", "set": ["errexit", "nounset", "pipefail"],
        "vars": dict(OAP_TVARS, PLATFORM_DIR=str(pdir),
                     ALB_INBOUND_CIDRS=alb_value, SPOKE_ALB_INBOUND_CIDRS=spoke_value),
        "tasks": {"run": {"cmds": [_oap_configure_cmd()]}}}, sort_keys=False))
    res = subprocess.run([TASK, "-s", "-t", str(tf), "run"], cwd=tmp_path,
                         capture_output=True, text=True, timeout=120)
    assert res.returncode == 0, res.stdout + res.stderr
    return yaml.safe_load((pdir / "config.local.yaml").read_text())


@needs_task
@needs_oap
class TestOapForwardSpoke:
    def test_var_normalises_list_csv_and_empty(self, tmp_path):
        expr = _oap_spoke_var_expr()
        tf = tmp_path / "Taskfile.yml"

        def run(cfg_text):
            cfg = tmp_path / "config.local.yaml"
            cfg.write_text(cfg_text)
            tf.write_text(yaml.safe_dump({
                "version": "3",
                "vars": {"CONFIG_FILE": str(cfg), "V": {"sh": expr}},
                "tasks": {"run": {"cmds": ['echo "[{{.V}}]"']}}}, sort_keys=False))
            r = subprocess.run([TASK, "-s", "-t", str(tf), "run"], cwd=tmp_path,
                               capture_output=True, text=True, timeout=60)
            assert r.returncode == 0, r.stdout + r.stderr
            return r.stdout.strip()

        assert run("spokeAlbInboundCidrs:\n  - 203.0.113.0/24\n  - 203.0.113.5/32\n") == \
            "[203.0.113.0/24,203.0.113.5/32]"
        assert run('spokeAlbInboundCidrs: "203.0.113.0/24,203.0.113.5/32"\n') == \
            "[203.0.113.0/24,203.0.113.5/32]"
        assert run("domain: idp.example.com\n") == "[]"

    def test_value_is_forwarded_when_set(self, tmp_path):
        out = _oap_configure(tmp_path, "203.0.113.0/24,203.0.113.5/32")
        assert out["spokeAlbInboundCidrs"] == "203.0.113.0/24,203.0.113.5/32"

    def test_key_is_omitted_when_empty(self, tmp_path):
        out = _oap_configure(tmp_path, "")
        assert "spokeAlbInboundCidrs" not in out
        assert out["domain"] == "idp.example.com" and out["resourcePrefix"] == "acme"

    def test_hub_and_spoke_keys_are_independent(self, tmp_path):
        out = _oap_configure(tmp_path, "203.0.113.0/24", alb_value="198.51.100.0/24")
        assert out["albInboundCidrs"] == "198.51.100.0/24"
        assert out["spokeAlbInboundCidrs"] == "203.0.113.0/24"
