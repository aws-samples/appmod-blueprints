"""Wiring tests for the install-time spoke-ALB source-IP allowlist (option c).

`config.yaml spokeAlbInboundCidrs` is a fleet-wide default source-IP allowlist for EVERY spoke's
own internet-facing `platform` ALB; a single spoke overrides it with an `albInboundCidrs` field in
its own fleet entry. The value is threaded, with the kro EksCluster RGD as the single writer of the
spoke-secret key:

  config.yaml spokeAlbInboundCidrs
    -> hub:seed  (both providers) normalise -> <hub>/config metadata `spoke_alb_inbound_cidrs`
      -> ESO     -> hub cluster-secret annotation `spoke_alb_inbound_cidrs`
        -> clusters-kro.yaml appset  global.spokeAlbInboundCidrs = that annotation
          -> clusters.yaml claim  albInboundCidrs = $cluster.albInboundCidrs
                                   | default global.spokeAlbInboundCidrs | default "" (per-spoke wins)
            -> rg-eks-vpc.yaml  EksclusterWithVpc passes ${schema.spec.albInboundCidrs} into the
                                nested EksCluster
              -> rg-eks.yaml  EksCluster schema field albInboundCidrs, stamped into the spoke
                              cluster secret as the `config_inbound_cidrs` annotation (default
                              fleet-secret path AND the createArgocdClusterSecret parity path)
                -> registry core.yaml  ingress-class-alb configInboundCidrs reads
                                       `config_inbound_cidrs` (shared hub+spoke entry)
                  -> chart  concatenates it into the spoke ALB allowlist.

These are static parses of the RGDs/appset/claim/registry (kro/CEL cannot be rendered here) plus
helm-template proofs of the kro-clusters claim: the fleet-wide default is inherited, a per-spoke
value wins, and an empty default renders albInboundCidrs "" (spoke ALB unchanged).

Run:  python -m pytest workshop/scripts/tests/test_spoke_alb_inbound_cidrs_wiring.py -q
"""
import os
import shutil
import subprocess

import pytest

yaml = pytest.importorskip("yaml")

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
EKS = os.path.join(REPO, "gitops", "addons", "charts", "kro", "resource-groups", "manifests", "eks")
REGISTRY = os.path.join(REPO, "gitops", "addons", "registry", "core.yaml")
APPSET = os.path.join(REPO, "gitops", "bootstrap", "clusters-kro.yaml")
CLAIM_CHART = os.path.join(REPO, "gitops", "abstractions", "kro", "kro-clusters")
CONFIG_YAML = os.path.join(REPO, "config.yaml")
SCHEMA = os.path.join(REPO, "config.schema.json")
HELM = shutil.which("helm")
needs_helm = pytest.mark.skipif(HELM is None, reason="helm not on PATH")


def _rgd(name):
    with open(os.path.join(EKS, name)) as f:
        return yaml.safe_load(f)


def _resource(rgd, rid):
    for r in rgd["spec"]["resources"]:
        if r.get("id") == rid:
            return r
    raise AssertionError(f"resource id {rid} not found")


# --- config.yaml + schema expose the key ----------------------------------------------------
def test_config_schema_declares_spoke_key_list_or_string():
    import json
    sch = json.load(open(SCHEMA))["properties"]["spokeAlbInboundCidrs"]
    assert sch["type"] == ["array", "string"]
    assert sch["default"] == ""
    # The warning about participant lockout must be in the description (it is the whole point).
    assert "participant" in sch["description"].lower()


def test_config_yaml_documents_the_key_commented_off_by_default():
    text = open(CONFIG_YAML).read()
    # documented but NOT active, so the default render is unchanged (byte-identical behaviour).
    assert "spokeAlbInboundCidrs" in text
    for ln in text.splitlines():
        if "spokeAlbInboundCidrs" in ln:
            assert ln.lstrip().startswith("#"), f"spokeAlbInboundCidrs must stay commented: {ln!r}"


# --- the thread, node by node ---------------------------------------------------------------
def test_appset_reads_the_annotation_into_global():
    # `index` so a hub without the annotation yields "" rather than failing to render.
    docs = [d for d in yaml.safe_load_all(open(APPSET)) if d]
    found = None
    for d in docs:
        s = yaml.safe_dump(d)
        if "spokeAlbInboundCidrs" in s:
            found = s
    assert found is not None, "appset does not thread spokeAlbInboundCidrs"
    assert 'index .metadata.annotations "spoke_alb_inbound_cidrs"' in found


def test_claim_defaults_to_global_and_lets_a_spoke_override():
    # static text assertion of the precedence expression (helm proofs below render it).
    claim = open(os.path.join(CLAIM_CHART, "templates", "clusters.yaml")).read()
    line = next(l for l in claim.splitlines() if "$cluster.albInboundCidrs" in l)
    assert "$.Values.global.spokeAlbInboundCidrs" in line
    assert 'hasKey $cluster "albInboundCidrs"' in line
    # ternary: the per-spoke value comes first => it wins whenever the key is present.
    assert line.index("$cluster.albInboundCidrs") < line.index("$.Values.global.spokeAlbInboundCidrs")


def test_eksclusterwithvpc_schema_and_passthrough():
    wrap = _rgd("rg-eks-vpc.yaml")
    assert wrap["spec"]["schema"]["spec"]["albInboundCidrs"].startswith("string")
    eks = _resource(wrap, "eks")
    assert eks["template"]["spec"]["albInboundCidrs"] == "${schema.spec.albInboundCidrs}"


def test_ekscluster_schema_declares_alb_inbound_cidrs():
    eks = _rgd("rg-eks.yaml")
    assert eks["spec"]["schema"]["spec"]["albInboundCidrs"].startswith("string")


def test_default_fleet_secret_path_stamps_config_inbound_cidrs():
    eks = _rgd("rg-eks.yaml")
    cfg = _resource(eks, "clusterConfigK8sSecretFleet")["template"]["stringData"]["config"]
    assert '\\"config_inbound_cidrs\\":\\"${schema.spec.albInboundCidrs}\\"' in cfg, \
        "config_inbound_cidrs not stamped from albInboundCidrs into the fleet-secret metadata"


def test_parity_argocd_secret_path_stamps_config_inbound_cidrs():
    eks = _rgd("rg-eks.yaml")
    ann = _resource(eks, "argocdSecret")["template"]["metadata"]["annotations"]
    assert ann.get("config_inbound_cidrs") == "${schema.spec.albInboundCidrs}"


def test_registry_feeds_config_inbound_cidrs_to_configInboundCidrs():
    with open(REGISTRY) as f:
        vo = yaml.safe_load(f)["ingress-class-alb"]["valuesObject"]
    assert vo["configInboundCidrs"] == '{{default "" (index .metadata.annotations "config_inbound_cidrs")}}'


# --- helm: the claim precedence actually renders --------------------------------------------
def _render_claim(values):
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
        yaml.safe_dump(values, f)
        vf = f.name
    try:
        res = subprocess.run([HELM, "template", "x", CLAIM_CHART, "-f", vf],
                             capture_output=True, text=True, timeout=60)
        assert res.returncode == 0, res.stderr
        return list(yaml.safe_load_all(res.stdout))
    finally:
        os.unlink(vf)


def _alb_by_cluster(docs):
    out = {}
    for d in docs:
        if d and d.get("kind") == "EksclusterWithVpc":
            out[d["metadata"]["name"]] = d["spec"].get("albInboundCidrs")
    return out


@needs_helm
def test_fleet_default_inherited_and_per_spoke_override_wins():
    docs = _render_claim({
        "global": {"resourcePrefix": "acme", "accountId": "111122223333",
                   "defaultRegion": "us-west-2", "provider": "kro-ack",
                   "spokeAlbInboundCidrs": "203.0.113.0/24"},
        "clusters": {
            "spoke-default": {"accountId": "111122223333"},
            "spoke-override": {"accountId": "111122223333", "albInboundCidrs": "203.0.113.9/32"},
        }})
    alb = _alb_by_cluster(docs)
    assert alb["spoke-default"] == "203.0.113.0/24"   # inherits the fleet-wide default
    assert alb["spoke-override"] == "203.0.113.9/32"  # per-spoke value wins


@needs_helm
def test_empty_default_renders_blank_spoke_allowlist():
    docs = _render_claim({
        "global": {"resourcePrefix": "acme", "accountId": "111122223333",
                   "defaultRegion": "us-west-2", "provider": "kro-ack"},
        "clusters": {"spoke-default": {"accountId": "111122223333"}}})
    assert _alb_by_cluster(docs)["spoke-default"] is None      # not rendered when empty


# --- review #1308: per-spoke override semantics ---------------------------------------------
FLEET_DEFAULT = {"resourcePrefix": "acme", "accountId": "111122223333",
                 "defaultRegion": "us-west-2", "provider": "kro-ack",
                 "spokeAlbInboundCidrs": "203.0.113.0/24"}


@needs_helm
def test_per_spoke_empty_value_disables_the_fleet_default():
    # A spoke entry with albInboundCidrs: "" (or [] / null) turns the allowlist off for that one
    # spoke; `default` used to swallow the empty value and render the fleet default instead.
    docs = _render_claim({"global": FLEET_DEFAULT, "clusters": {
        "spoke-empty": {"accountId": "111122223333", "albInboundCidrs": ""},
        "spoke-emptylist": {"accountId": "111122223333", "albInboundCidrs": []},
        "spoke-null": {"accountId": "111122223333", "albInboundCidrs": None},
        "spoke-absent": {"accountId": "111122223333"}}})
    alb = _alb_by_cluster(docs)
    # not rendered => the RGD default "" applies => no allowlist for that spoke
    assert alb["spoke-empty"] is None
    assert alb["spoke-emptylist"] is None
    assert alb["spoke-null"] is None
    assert alb["spoke-absent"] == "203.0.113.0/24"   # no key => fleet default still applies


@needs_helm
def test_per_spoke_list_renders_comma_separated_cidrs():
    # A YAML list used to render as one invalid CIDR "[198.51.100.0/24 198.51.100.7/32]".
    docs = _render_claim({"global": FLEET_DEFAULT, "clusters": {
        "spoke-list": {"accountId": "111122223333",
                       "albInboundCidrs": ["198.51.100.0/24", "198.51.100.7/32"]},
        "spoke-string": {"accountId": "111122223333",
                         "albInboundCidrs": "198.51.100.0/24,198.51.100.7/32"}}})
    alb = _alb_by_cluster(docs)
    assert alb["spoke-list"] == "198.51.100.0/24,198.51.100.7/32"
    assert alb["spoke-string"] == "198.51.100.0/24,198.51.100.7/32"


def test_docs_point_the_override_at_kro_clusters_values_not_the_trigger_json():
    # clusters/<spoke>.json is only the appset generator trigger; the claim reads
    # clusters.<name> from the fleet repo's kro-clusters/values.yaml.
    import json
    texts = {
        "config.yaml": open(CONFIG_YAML).read(),
        "schema": json.load(open(SCHEMA))["properties"]["spokeAlbInboundCidrs"]["description"],
        "doc": open(os.path.join(REPO, "docs", "platform", "alb-ip-allowlist.md")).read(),
    }
    for name, t in texts.items():
        assert "kro-clusters/clusters/<spoke>.json" not in t, name
        assert "kro-clusters/values.yaml" in t, name


# --- pre-review #1308: default claim render byte-identical to main; field only when set -----
def _git_show(path):
    r = subprocess.run(["git", "-C", REPO, "show", "origin/main:" + path], capture_output=True)
    return r.stdout if r.returncode == 0 else None


@needs_helm
def test_default_claim_render_is_byte_identical_to_main(tmp_path):
    # albInboundCidrs is rendered only when non-empty: a hub whose EksclusterWithVpc RGD
    # predates the field never receives it on a claim it does not need, and the default render
    # is unchanged.
    rel = "gitops/abstractions/kro/kro-clusters"
    ls = subprocess.run(["git", "-C", REPO, "ls-tree", "-r", "--name-only", "origin/main", rel + "/"],
                        capture_output=True, text=True)
    files = [f[len(rel) + 1:] for f in ls.stdout.splitlines()] if ls.returncode == 0 else []
    main = {f: _git_show(f"{rel}/{f}") for f in files}
    if not main or any(v is None for v in main.values()):
        pytest.skip("origin/main not available in this checkout")
    mdir = tmp_path / "main-chart"
    for f, b in main.items():
        (mdir / f).parent.mkdir(parents=True, exist_ok=True)
        (mdir / f).write_bytes(b)
    vals = tmp_path / "v.yaml"
    yaml.safe_dump({"global": {"resourcePrefix": "acme", "accountId": "111122223333",
                               "defaultRegion": "us-west-2", "provider": "kro-ack",
                               "spokeAlbInboundCidrs": ""},
                    "clusters": {"acme-spoke-dev": {"environment": "dev"},
                                 "acme-spoke-off": {"albInboundCidrs": ""}}}, open(vals, "w"))
    out = []
    for chart in (str(mdir), CLAIM_CHART):
        r = subprocess.run([HELM, "template", "x", chart, "-f", str(vals)],
                           capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr
        out.append(r.stdout)
    assert out[0] == out[1]


@needs_helm
def test_field_rendered_only_when_set():
    docs = _render_claim({"global": FLEET_DEFAULT, "clusters": {
        "spoke-default": {"accountId": "111122223333"}}})
    assert _alb_by_cluster(docs)["spoke-default"] == "203.0.113.0/24"
