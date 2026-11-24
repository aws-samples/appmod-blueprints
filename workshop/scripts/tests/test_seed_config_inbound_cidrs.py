"""Hermetic tests for the install-time ALB source-IP allowlist (`albInboundCidrs`).

Two halves:

1. appmod providers (kind-kro-ack, kind-crossplane) `secrets-manager:seed`: `albInboundCidrs`
   from config.yaml (a YAML list OR a comma-separated string) is normalised to a comma-separated
   string and written as the `config_inbound_cidrs` metadata key of <hub>/config. ESO turns it
   into a hub cluster-secret annotation that the ingress-class-alb registry entry passes to the
   chart as `configInboundCidrs` (see test_ingress_class_alb_config_inbound_cidrs.py). Empty or
   absent -> the key is not written -> unchanged. A non-fatal hardening warning is printed when a
   domain is set, insecure != true, and the allowlist is empty.

2. OAP `platform:configure`: the OAP config's `albInboundCidrs` is forwarded into the generated
   appmod config.local.yaml ONLY when non-empty, so an OAP config without it renders as before.

The provider task vars/cmds are read verbatim and run under go-task with the Taskfile's `set:`
options. `aws` is a fake on PATH; `yq`/`jq` are the real tools. No AWS, no network.

Run:  python -m pytest workshop/scripts/tests/test_seed_config_inbound_cidrs.py -q
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
    print("")  # no NAT -> isolate config_inbound_cidrs from nat_egress_cidrs
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


def _seed_raw(tmp_path, provider, config, insecure="false", domain="idp.example.com", existing=None,
              nat=""):
    cfg = tmp_path / "config.local.yaml"
    cfg.write_text(yaml.safe_dump(config))
    sf, env = _env(tmp_path, secret=existing)
    tvars = dict(TVARS, CONFIG_FILE=str(cfg), ROOT_DIR=str(tmp_path),
                 INSECURE=insecure, DOMAIN=domain, INGRESS_DOMAIN=domain, NAT_EGRESS_CIDRS=nat)
    cmds = _task(provider)["cmds"]
    text = "\n".join(c["cmd"] if isinstance(c, dict) else c for c in cmds)
    res = _run(tmp_path, env, text, tvars)
    return res, json.loads(sf.read_text())


def _seed(tmp_path, provider, config, insecure="false", domain="idp.example.com", existing=None):
    res, st = _seed_raw(tmp_path, provider, config, insecure, domain, existing)
    assert res.returncode == 0, res.stdout + res.stderr
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


# --- appmod providers: config_inbound_cidrs written from albInboundCidrs --------------------
@needs_task
@pytest.mark.parametrize("provider", sorted(PROVIDERS))
class TestSeedConfigInbound:
    def test_list_form_is_joined(self, tmp_path, provider):
        secret, _ = _seed(tmp_path, provider,
                          _cfg(albInboundCidrs=["203.0.113.0/24", "203.0.113.5/32"]))
        assert _meta(secret)["config_inbound_cidrs"] == "203.0.113.0/24,203.0.113.5/32"

    def test_comma_string_form_is_kept(self, tmp_path, provider):
        secret, _ = _seed(tmp_path, provider,
                          _cfg(albInboundCidrs="203.0.113.0/24,203.0.113.5/32"))
        assert _meta(secret)["config_inbound_cidrs"] == "203.0.113.0/24,203.0.113.5/32"

    def test_absent_key_writes_nothing(self, tmp_path, provider):
        secret, _ = _seed(tmp_path, provider, _cfg())
        assert "config_inbound_cidrs" not in _meta(secret)

    def test_empty_forms_write_nothing(self, tmp_path, provider):
        for i, v in enumerate(["", []]):
            secret, _ = _seed(_sub(tmp_path, f"e{i}"), provider, _cfg(albInboundCidrs=v))
            assert "config_inbound_cidrs" not in _meta(secret)

    def test_present_key_does_not_disturb_other_metadata(self, tmp_path, provider):
        without, _ = _seed(_sub(tmp_path, "w"), provider, _cfg())
        withk, _ = _seed(_sub(tmp_path, "k"), provider, _cfg(albInboundCidrs=["203.0.113.0/24"]))
        assert dict(_meta(without), config_inbound_cidrs="203.0.113.0/24") == _meta(withk)

    def test_the_secret_is_never_printed(self, tmp_path, provider):
        _, res = _seed(tmp_path, provider, _cfg(albInboundCidrs=["203.0.113.0/24"]))
        assert "not-a-real-token" not in res.stdout + res.stderr


@needs_task
@pytest.mark.parametrize("provider", sorted(PROVIDERS))
class TestSeedPreservesFleetNat:
    # fleet_nat_egress_cidrs is written AFTER hub:seed by secrets-manager:seed-fleet-nat-egress,
    # so hub:seed must carry it across a re-seed (like nat_egress_cidrs / the spoke_* keys) or a
    # re-install drops the fleet spokes' NAT from the hub allowlist.
    def _existing(self, **extra):
        meta = dict({"aws_cluster_name": HUB, "ingress_domain_name": "idp.example.com"}, **extra)
        return json.dumps({"metadata": json.dumps(meta)})

    def test_fleet_nat_is_preserved_across_reseed(self, tmp_path, provider):
        existing = self._existing(fleet_nat_egress_cidrs="203.0.113.201/32,203.0.113.202/32")
        secret, _ = _seed(tmp_path, provider, _cfg(), existing=existing)
        assert _meta(secret)["fleet_nat_egress_cidrs"] == "203.0.113.201/32,203.0.113.202/32"

    def test_absent_fleet_nat_is_not_invented(self, tmp_path, provider):
        secret, _ = _seed(tmp_path, provider, _cfg(), existing=self._existing())
        assert "fleet_nat_egress_cidrs" not in _meta(secret)

    def test_removing_albInboundCidrs_drops_the_stored_key(self, tmp_path, provider):
        # docs "Remove the filtering": config.yaml is authoritative, a re-seed without the key
        # removes config_inbound_cidrs (it is not preserved like the fleet NAT).
        existing = self._existing(config_inbound_cidrs="203.0.113.0/24")
        secret, _ = _seed(tmp_path, provider, _cfg(), existing=existing)
        assert "config_inbound_cidrs" not in _meta(secret)


# --- appmod providers: invalid allowlists and insecure mode are refused (review #1308) -------
BAD_CIDRS = [
    ["203.0.113.5"],                          # no mask
    ["10.0.0.0/33"],                          # mask > 32
    ["corp-vpn"],                             # a name, not a CIDR
    "203.0.113.0/24;198.51.100.0/24",         # wrong separator
    ["203.0.113.0/24", "198.51.100.256/32"],  # octet > 255 (one bad entry among good ones)
    "203.0.113.0/24,,198.51.100.0/24",        # blank entry
    ["2001:db8::/32"],                        # IPv6: the schema promises IPv4 CIDRs
    ["203.0.113.0/08"],                       # leading zero in the mask
    ["10.0.0.1/8"],                           # host bits set (network is 10.0.0.0/8)
    ["203.0.113.5/24"],                       # host bits set (network is 203.0.113.0/24)
]


@needs_task
@pytest.mark.parametrize("provider", sorted(PROVIDERS))
class TestSeedRejects:
    @pytest.mark.parametrize("key", ["albInboundCidrs", "spokeAlbInboundCidrs"])
    @pytest.mark.parametrize("bad", BAD_CIDRS, ids=lambda v: repr(v))
    def test_invalid_cidr_fails_before_any_write(self, tmp_path, provider, key, bad):
        res, st = _seed_raw(tmp_path, provider, _cfg(**{key: bad}))
        assert res.returncode != 0, res.stdout + res.stderr
        assert st["writes"] == [], st
        assert key in res.stdout + res.stderr and "not an IPv4 CIDR" in res.stdout + res.stderr

    def test_network_addresses_of_every_mask_are_accepted(self, tmp_path, provider):
        good = ["203.0.113.5/32", "203.0.113.4/30", "192.0.2.128/25", "198.51.100.0/24",
                "10.0.0.0/8", "128.0.0.0/1", "0.0.0.0/0"]
        secret, _ = _seed(tmp_path, provider, _cfg(albInboundCidrs=good))
        assert _meta(secret)["config_inbound_cidrs"] == ",".join(good)

    def test_entries_are_trimmed_and_normalised(self, tmp_path, provider):
        secret, _ = _seed(tmp_path, provider,
                          _cfg(albInboundCidrs=" 203.0.113.0/24 , 198.51.100.7/32",
                               spokeAlbInboundCidrs=["0.0.0.0/0", " 192.0.2.0/24"]))
        m = _meta(secret)
        assert m["config_inbound_cidrs"] == "203.0.113.0/24,198.51.100.7/32"
        assert m["spoke_alb_inbound_cidrs"] == "0.0.0.0/0,192.0.2.0/24"

    def test_insecure_with_hub_allowlist_fails(self, tmp_path, provider):
        res, st = _seed_raw(tmp_path, provider,
                            _cfg(insecure=True, albInboundCidrs=["203.0.113.0/24"]), insecure="true")
        assert res.returncode != 0, res.stdout + res.stderr
        assert st["writes"] == [], st
        assert "insecure" in res.stdout + res.stderr

    def test_insecure_without_hub_allowlist_still_seeds(self, tmp_path, provider):
        secret, _ = _seed(tmp_path, provider, _cfg(insecure=True), insecure="true")
        assert "config_inbound_cidrs" not in _meta(secret)


# --- the CIDR check must parse on the macOS (BWK) awk, not only on gawk (pre-review #1308) ---
# BWK awk ends a regex literal at the first unescaped "/", even inside [...], so "[/]" is a
# parse error there and hub:seed failed on EVERY non-empty value on a macOS host while gawk (the
# awk of CI) accepted it. Two barriers:
#   1. static, runs everywhere: no "/" inside a bracket expression and no {n,m} interval (BWK
#      20200816, the macOS awk, has none) in the CIDR_CHECK program;
#   2. dynamic, when a BWK awk is available: run hub:seed with it as `awk` on PATH. Found from
#      $BWK_AWK, then bwkawk / original-awk / one-true-awk / nawk on PATH, then a PATH `awk`
#      that reports "awk version YYYYMMDD" (BWK's format, the macOS awk). Skipped otherwise.
import re as _re


def _cidr_check_program(provider):
    text = "\n".join(c["cmd"] if isinstance(c, dict) else c for c in _task(provider)["cmds"])
    m = _re.search(r"CIDR_CHECK='(.*?)'\n", text, _re.S)
    assert m, f"{provider}: CIDR_CHECK program not found"
    return m.group(1)


def _bwk_awk():
    cands = [os.environ.get("BWK_AWK", "")]
    cands += [shutil.which(n) or "" for n in ("bwkawk", "original-awk", "one-true-awk", "nawk")]
    for c in cands:
        if c and os.access(c, os.X_OK):
            return c
    a = shutil.which("awk")
    if a:
        v = subprocess.run([a, "--version"], capture_output=True, text=True).stdout
        if _re.match(r"awk version \d{8}", v):
            return a
    return None


BWK = _bwk_awk()
needs_bwk = pytest.mark.skipif(BWK is None, reason="no BWK awk (set BWK_AWK=<path> to run)")


@pytest.mark.parametrize("provider", sorted(PROVIDERS))
class TestCidrCheckPortable:
    def test_no_slash_inside_a_bracket_expression(self, provider):
        prog = _cidr_check_program(provider)
        for b in _re.findall(r"\[[^\]]*\]", prog):
            assert "/" not in b, f"{provider}: {b!r} ends the regex on BWK awk; write \\/"

    def test_no_interval_expression(self, provider):
        assert not _re.search(r"\{\d", _cidr_check_program(provider)), \
            f"{provider}: BWK awk 20200816 has no {{n,m}} intervals"

    @needs_task
    @needs_bwk
    @pytest.mark.parametrize("value,expected", [
        (["203.0.113.0/24", "198.51.100.7/32"], "203.0.113.0/24,198.51.100.7/32"),
        (" 203.0.113.0/24 , 0.0.0.0/0", "203.0.113.0/24,0.0.0.0/0"),
        (["10.0.0.0/33"], None),
        (["10.0.0.1/8"], None),
        (["203.0.113.5/32", "0.0.0.0/0", "192.0.2.128/25"], "203.0.113.5/32,0.0.0.0/0,192.0.2.128/25"),
        (["corp-vpn"], None),
        ("203.0.113.0/24;198.51.100.0/24", None),
    ], ids=repr)
    def test_seed_under_bwk_awk(self, tmp_path, provider, value, expected):
        (tmp_path / "bin").mkdir()
        os.symlink(BWK, tmp_path / "bin" / "awk")
        res, st = _seed_raw(tmp_path, provider, _cfg(albInboundCidrs=value))
        out = res.stdout + res.stderr
        if expected is None:
            assert res.returncode != 0 and st["writes"] == [], out
            bad = value if isinstance(value, str) else value[0]
            assert '"%s"' % bad.strip() in out, out    # the message names the bad entry
        else:
            assert res.returncode == 0, out
            assert _meta(st["writes"][0])["config_inbound_cidrs"] == expected


# --- review #1308 smaller items: no hub NAT, and too many entries for the SG ---------------
@needs_task
@pytest.mark.parametrize("provider", sorted(PROVIDERS))
class TestSeedAllowlistWarnings:
    def test_warns_when_allowlist_set_without_hub_nat(self, tmp_path, provider):
        res, st = _seed_raw(tmp_path, provider, _cfg(albInboundCidrs=["203.0.113.0/24"]), nat="")
        assert res.returncode == 0 and len(st["writes"]) == 1, res.stdout + res.stderr
        assert "no hub NAT egress IP is known" in res.stdout

    def test_no_nat_warning_when_hub_nat_known(self, tmp_path, provider):
        res, _ = _seed_raw(tmp_path, provider, _cfg(albInboundCidrs=["203.0.113.0/24"]),
                           nat="198.51.100.9/32")
        assert res.returncode == 0, res.stdout + res.stderr
        assert "no hub NAT egress IP is known" not in res.stdout

    def test_no_nat_warning_without_allowlist(self, tmp_path, provider):
        res, _ = _seed_raw(tmp_path, provider, _cfg(), nat="")
        assert "no hub NAT egress IP is known" not in res.stdout

    def test_warns_above_28_entries(self, tmp_path, provider):
        many = ["203.0.113.%d/32" % i for i in range(1, 29)]      # 28 + hub NAT = 29
        res, st = _seed_raw(tmp_path, provider, _cfg(albInboundCidrs=many), nat="198.51.100.9/32")
        assert res.returncode == 0 and len(st["writes"]) == 1, res.stdout + res.stderr
        assert "allowlist has 29 entries" in res.stdout

    def test_no_size_warning_at_28_entries(self, tmp_path, provider):
        many = ["203.0.113.%d/32" % i for i in range(1, 28)]      # 27 + hub NAT = 28
        res, _ = _seed_raw(tmp_path, provider, _cfg(albInboundCidrs=many), nat="198.51.100.9/32")
        assert res.returncode == 0, res.stdout + res.stderr
        assert "entries before any overlay" not in res.stdout


# --- appmod providers: the non-fatal hardening warning --------------------------------------
@needs_task
@pytest.mark.parametrize("provider", sorted(PROVIDERS))
class TestSeedWarning:
    def test_warns_when_domain_set_and_allowlist_empty(self, tmp_path, provider):
        _, res = _seed(tmp_path, provider, _cfg(), insecure="false")
        assert "WARNING" in res.stdout and "allowlist" in res.stdout
        # Non-fatal: the seed still completed and wrote the secret (asserted in _seed).

    def test_no_warning_when_allowlist_is_set(self, tmp_path, provider):
        _, res = _seed(tmp_path, provider, _cfg(albInboundCidrs=["203.0.113.0/24"]), insecure="false")
        # The open-ALB warning is gone. (This fake finds no hub NAT, so the separate "no hub NAT
        # egress IP is known" warning still prints: see TestSeedAllowlistWarnings.)
        assert "has no source-IP allowlist" not in res.stdout

    def test_no_warning_in_insecure_mode(self, tmp_path, provider):
        # insecure=true => internal ALB behind an edge; a client allowlist must not be set.
        _, res = _seed(tmp_path, provider, _cfg(insecure=True), insecure="true")
        assert "WARNING" not in res.stdout


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


def _oap_alb_var_expr():
    with open(OAP) as f:
        return yaml.safe_load(f)["vars"]["ALB_INBOUND_CIDRS"]["sh"]


OAP_TVARS = {
    "CLUSTER_PROVIDER": "kind-kro-ack", "PLATFORM_REPO": "https://example.com/acme/appmod",
    "PLATFORM_REF": "main", "HUB_CLUSTER_NAME": HUB, "K8S_VERSION": "1.37",
    "AWS_REGION": REGION, "AWS_ACCOUNT_ID": "111122223333", "AWS_PROFILE": "default",
    "DOMAIN": "idp.example.com", "INSECURE": "false", "RESOURCE_PREFIX": "acme",
    "IDC_INSTANCE_ARN": "arn:aws:sso:::instance/ssoins-0", "IDC_REGION": "us-east-1",
    "IDC_ADMIN_GROUP_ID": "group-0", "FLEET_REPO_URL": "https://example.com/acme/appmod",
    "FLEET_REPO_REVISION": "main", "FLEET_REPO_BASEPATH": "gitops/", "FLEET_SCOPE_BY_PREFIX": "",
    "AGENTIC_REPO_URL": "https://example.com/acme/oap", "AGENTIC_REPO_REVISION": "main",
}


def _oap_configure(tmp_path, alb_value):
    pdir = tmp_path / ".platform"
    pdir.mkdir()
    tf = tmp_path / "Taskfile.yml"
    tf.write_text(yaml.safe_dump({
        "version": "3", "set": ["errexit", "nounset", "pipefail"],
        "vars": dict(OAP_TVARS, PLATFORM_DIR=str(pdir), ALB_INBOUND_CIDRS=alb_value),
        "tasks": {"run": {"cmds": [_oap_configure_cmd()]}}}, sort_keys=False))
    res = subprocess.run([TASK, "-s", "-t", str(tf), "run"], cwd=tmp_path,
                         capture_output=True, text=True, timeout=120)
    assert res.returncode == 0, res.stdout + res.stderr
    return yaml.safe_load((pdir / "config.local.yaml").read_text())


@needs_task
@needs_oap
class TestOapForward:
    def test_var_normalises_list_csv_and_empty(self, tmp_path):
        expr = _oap_alb_var_expr()
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

        assert run("albInboundCidrs:\n  - 203.0.113.0/24\n  - 203.0.113.5/32\n") == \
            "[203.0.113.0/24,203.0.113.5/32]"
        assert run('albInboundCidrs: "203.0.113.0/24,203.0.113.5/32"\n') == \
            "[203.0.113.0/24,203.0.113.5/32]"
        assert run("domain: idp.example.com\n") == "[]"

    def test_value_is_forwarded_when_set(self, tmp_path):
        out = _oap_configure(tmp_path, "203.0.113.0/24,203.0.113.5/32")
        assert out["albInboundCidrs"] == "203.0.113.0/24,203.0.113.5/32"

    def test_key_is_omitted_when_empty(self, tmp_path):
        out = _oap_configure(tmp_path, "")
        assert "albInboundCidrs" not in out
        # The rest of the generated config is still well-formed.
        assert out["domain"] == "idp.example.com" and out["resourcePrefix"] == "acme"
