"""Hermetic tests for `secrets-manager:seed`: the optional `external_dns_domain_filters` key set
by hand on <hub>/config metadata survives a re-seed, for kind-kro-ack and kind-crossplane.

ESO expands <hub>/config metadata keys 1:1 into hub cluster-secret annotations; the external-dns
registry entry reads `external_dns_domain_filters` for `domainFilters` and falls back to
`ingress_domain_name` when it is empty or missing (docs/install/prerequisites.md). The seed
rebuilds the metadata from scratch on every install, so without preservation a re-install would
silently narrow external-dns back to `ingress_domain_name`.

Contract:
  - fresh seed            -> no key (default behaviour unchanged);
  - re-seed, key set      -> the stored value is kept verbatim, nothing else changes;
  - re-seed, key absent   -> still absent;
  - re-seed, key empty    -> not written (empty means default).

Same harness as test_seed_nat_egress_cidrs.py: the provider Taskfile's cmds run verbatim under
go-task with a fake `aws` on PATH. No AWS, no network.

Run:  python -m pytest workshop/scripts/tests/test_seed_external_dns_domain_filters.py -q
"""
import json
import os
import re
import shutil
import subprocess
import sys

import pytest

yaml = pytest.importorskip("yaml")
if not (shutil.which("yq") and shutil.which("jq")):
    pytest.skip("yq and jq are required", allow_module_level=True)

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
PROVIDERS = {
    "kind-kro-ack": os.path.join(REPO, "cluster-providers", "kind-kro-ack", "Taskfile.yaml"),
    "kind-crossplane": os.path.join(REPO, "cluster-providers", "kind-crossplane", "Taskfile.yaml"),
}
TASK = shutil.which("task")
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
st.setdefault("calls", []).append([svc, op] + [a for a in rest if not a.startswith("{")][:12])
rc = 0
if (svc, op) == ("ec2", "describe-nat-gateways"):
    if st.get("nat_fails"):
        sys.stderr.write("An error occurred (UnauthorizedOperation)\n"); rc = 254
    else:
        ips = st.get("nat_ips", [])
        print("\t".join(ips) if ips else "")
elif (svc, op) == ("secretsmanager", "get-secret-value"):
    if st["secret"] is None:
        sys.stderr.write("An error occurred (ResourceNotFoundException)\n"); rc = 254
    else:
        print(st["secret"])
elif (svc, op) == ("secretsmanager", "restore-secret"):
    rc = 254
elif (svc, op) == ("secretsmanager", "create-secret"):
    if st["secret"] is not None:
        sys.stderr.write("An error occurred (ResourceExistsException)\n"); rc = 254
    else:
        st["writes"].append(opts["secret-string"]); st["secret"] = opts["secret-string"]
elif (svc, op) == ("secretsmanager", "put-secret-value"):
    st["writes"].append(opts["secret-string"]); st["secret"] = opts["secret-string"]
else:
    sys.stderr.write("unexpected aws call %r\n" % sys.argv[1:]); rc = 2
json.dump(st, open(st_path, "w"))
sys.exit(rc)
'''

BASE_CONFIG = {"domain": "d111111abcdef8.cloudfront.net", "platformTags": {},
               "hub": {"clusterName": HUB}, "aws": {"accountId": "111122223333"}}
TVARS = {"HUB_CLUSTER_NAME": HUB, "AWS_REGION": REGION, "AWS_ACCOUNT_ID": "111122223333",
         "REPO_URL": "https://example.com/acme/appmod-blueprints", "REPO_REVISION": "main",
         "REPO_BASEPATH": "gitops/", "AGENTIC_REPO_URL": "", "AGENTIC_REPO_REVISION": "",
         "FLEET_REPO_URL": "https://example.com/acme/appmod-blueprints", "FLEET_REPO_REVISION": "main",
         "FLEET_REPO_BASEPATH": "gitops/", "CLUSTER_ARN": f"arn:aws:eks:{REGION}:111122223333:cluster/{HUB}",
         "VPC_ID": "vpc-0", "PRIVATE_SUBNET_IDS": "subnet-a,subnet-b", "SUBNET_IDS": "subnet-a,subnet-b",
         "CLUSTER_SG": "sg-0", "INGRESS_SECURITY_GROUPS": "", "RESOURCE_PREFIX": "acme",
         "INSECURE": "false", "INGRESS_CERT_ARN": "", "CERTIFICATE_ARN": "", "INGRESS_NAME": "",
         "ADMIN_ROLE_NAME": "Admin", "USER_PASSWORD": "not-a-real-token",
         "ARGOCD_URL": "argocd-0123abcd.example.com", "INGRESS_DOMAIN": "d111111abcdef8.cloudfront.net",
         "DOMAIN": "d111111abcdef8.cloudfront.net", "GITLAB_DOMAIN": "git.example.com"}


def _task(provider):
    with open(PROVIDERS[provider]) as f:
        task = yaml.safe_load(f)["tasks"].get(TASK_NAME)
    if task is None:
        pytest.fail(f"no task {TASK_NAME} in {PROVIDERS[provider]}")
    return task


def _env(tmp_path, state):
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    (bindir / "aws").write_text(FAKE_AWS.replace("{python}", sys.executable))
    (bindir / "aws").chmod(0o755)
    sf = tmp_path / "state.json"
    sf.write_text(json.dumps(dict({"secret": None, "writes": []}, **state)))
    return sf, dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", FAKE_AWS_STATE=str(sf))


def _go(tmp_path, env, script_text, tvars):
    if TASK:
        tf = tmp_path / "Taskfile.yml"
        tf.write_text(yaml.safe_dump({
            "version": "3", "set": ["errexit", "nounset", "pipefail"],
            "vars": dict({k: "" for k in COLORS}, **tvars),
            "tasks": {"run": {"cmds": [script_text]}}}, sort_keys=False))
        return subprocess.run([TASK, "-s", "-t", str(tf), "run"], cwd=tmp_path, env=env,
                              capture_output=True, text=True, timeout=120)
    text = script_text
    for k, v in tvars.items():
        text = text.replace("{{.%s}}" % k, v)
    script = tmp_path / "seed.sh"
    script.write_text("set -euo pipefail\n" + re.sub(r"\{\{\.C_[A-Z]+\}\}", "", text))
    return subprocess.run(["bash", str(script)], cwd=tmp_path, env=env,
                          capture_output=True, text=True, timeout=120)


def _seed(tmp_path, provider, existing=None):
    """Run the task's cmds; return the one secret string written."""
    cfg = tmp_path / "config.local.yaml"
    cfg.write_text(yaml.safe_dump(BASE_CONFIG))
    sf, env = _env(tmp_path, {"secret": existing})
    tvars = dict(TVARS, CONFIG_FILE=str(cfg), ROOT_DIR=str(tmp_path), NAT_EGRESS_CIDRS="")
    cmds = _task(provider)["cmds"]
    text = "\n".join(c["cmd"] if isinstance(c, dict) else c for c in cmds)
    res = _go(tmp_path, env, text, tvars)
    assert res.returncode == 0, res.stdout + res.stderr
    st = json.loads(sf.read_text())
    assert len(st["writes"]) == 1, st
    return st["writes"][0], res


def _meta(secret_string):
    return json.loads(json.loads(secret_string)["metadata"])


def _sub(tmp_path, name):
    d = tmp_path / name
    d.mkdir()
    return d


def _with(secret_string, **extra):
    s = json.loads(secret_string)
    s["metadata"] = json.dumps(dict(_meta(secret_string), **extra))
    return json.dumps(s)


PARENT = "example.com"


@pytest.mark.parametrize("provider", sorted(PROVIDERS))
class TestDomainFiltersPreserved:
    def test_fresh_seed_has_no_key(self, tmp_path, provider):
        secret, _ = _seed(tmp_path, provider)
        assert "external_dns_domain_filters" not in _meta(secret)

    def test_reseed_keeps_a_hand_set_value(self, tmp_path, provider):
        first, _ = _seed(_sub(tmp_path, "a"), provider)
        again, _ = _seed(_sub(tmp_path, "b"), provider,
                         existing=_with(first, external_dns_domain_filters=PARENT))
        assert _meta(again)["external_dns_domain_filters"] == PARENT
        # Nothing else moves.
        assert dict(_meta(first), external_dns_domain_filters=PARENT) == _meta(again)

    def test_reseed_without_the_key_stays_without_it(self, tmp_path, provider):
        first, _ = _seed(_sub(tmp_path, "a"), provider)
        again, _ = _seed(_sub(tmp_path, "b"), provider, existing=first)
        assert "external_dns_domain_filters" not in _meta(again)

    def test_an_empty_value_is_not_written(self, tmp_path, provider):
        first, _ = _seed(_sub(tmp_path, "a"), provider)
        again, _ = _seed(_sub(tmp_path, "b"), provider,
                         existing=_with(first, external_dns_domain_filters=""))
        assert "external_dns_domain_filters" not in _meta(again)
