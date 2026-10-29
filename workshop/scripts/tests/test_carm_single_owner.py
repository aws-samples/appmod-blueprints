"""ACK CARM coverage (Namespace + IAMRoleSelectors) has ONE way to be declared and ONE owner.

- kro-clusters renders, for every spoke it defines, the spoke's Namespace and its
  IAMRoleSelectors, with no opt-in, with Prune=false,Delete=false (they must outlive the
  spoke's ACK CRs during a deliberate prune or a cascade delete).
- multi-acct renders the hub's own coverage only: legacy spoke entries in configs/multi-acct
  (written by spokes:enable-kro before this change) are ignored, so no object is declared by
  two Applications, and existing fleet repos keep rendering.
- A spoke named like the hub fails to render (that would be a double declaration).
- The objects kro-clusters takes over are byte-identical in spec to what multi-acct rendered
  (same names, ARNs, selectors), so Argo CD adopts them in place (tracking-id rewrite) and
  ACK sees an update of a cached selector, never a delete.
- Both charts cover the same AWS services.
- No hub value reads the removed spoke_namespaces annotation / global.spokeNames, and
  spokes:enable-kro no longer writes configs/multi-acct.

Run:  python -m pytest workshop/scripts/tests/test_carm_single_owner.py -q
"""
import os
import re
import shutil
import subprocess

import pytest

yaml = pytest.importorskip("yaml")

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
KRO = os.path.join(REPO, "gitops", "abstractions", "kro", "kro-clusters")
MA = os.path.join(REPO, "gitops", "addons", "charts", "multi-acct")
HELM = shutil.which("helm")
HUB, ACCT, XACCT, PREFIX = "acme-hub", "111122223333", "444455556666", "acme"

needs_helm = pytest.mark.skipif(HELM is None, reason="helm not on PATH")


def render(chart, values, tmp_path, name):
    f = tmp_path / (name + ".yaml")
    f.write_text(yaml.safe_dump(values))
    r = subprocess.run([HELM, "template", name, chart, "-f", str(f)], capture_output=True, text=True)
    return r, [d for d in yaml.safe_load_all(r.stdout) if d] if r.returncode == 0 else []


def carm(docs):
    return {(d["kind"], d["metadata"]["name"]): d for d in docs
            if d["kind"] in ("Namespace", "IAMRoleSelector")}


def kro(spokes, target, tmp_path, hub=HUB):
    g = {"accountId": ACCT, "resourcePrefix": PREFIX, "targetCluster": target, "hubClusterName": hub}
    return render(KRO, {"global": g, "clusters": spokes}, tmp_path, "clusters-kro-" + target)


def multi_acct(clusters, tmp_path):
    v = {"global": {"clusterName": HUB, "resourcePrefix": PREFIX, "accountId": ACCT}}
    if clusters is not None:
        v["clusters"] = clusters
    return render(MA, v, tmp_path, "multi-acct-" + HUB)


def services(objs, name):
    return sorted(k[1][: -len(name) - 1] for k in objs if k[0] == "IAMRoleSelector" and k[1].endswith("-" + name))


@needs_helm
def test_every_spoke_gets_namespace_and_selectors_by_default(tmp_path):
    spokes = {"dev": {}, "prod": {"accountId": XACCT}}
    for s in spokes:
        r, docs = kro(spokes, s, tmp_path)
        assert r.returncode == 0, r.stderr
        objs = carm(docs)
        assert ("Namespace", s) in objs
        svcs = services(objs, s)
        assert len(svcs) == 8, svcs
        other = "prod" if s == "dev" else "dev"
        assert not any(k[1].endswith("-" + other) or k[1] == other for k in objs), "targetCluster gate leaked"
        acct = XACCT if s == "prod" else ACCT
        for k, d in objs.items():
            opts = d["metadata"]["annotations"]["argocd.argoproj.io/sync-options"]
            assert "Prune=false" in opts and "Delete=false" in opts, (k, opts)
            if k[0] == "IAMRoleSelector":
                svc = k[1][: -len(s) - 1]
                assert d["spec"]["arn"] == "arn:aws:iam::%s:role/%s-cluster-mgmt-%s" % (acct, PREFIX, svc)
                assert d["spec"]["namespaceSelector"]["names"] == [s]


@needs_helm
def test_multi_acct_renders_the_hub_only_and_ignores_legacy_spoke_entries(tmp_path):
    r0, hub_only = multi_acct(None, tmp_path)
    r1, legacy = multi_acct({"dev": ACCT, "prod": XACCT}, tmp_path)
    assert r0.returncode == 0 and r1.returncode == 0, r0.stderr + r1.stderr
    assert carm(hub_only).keys() == carm(legacy).keys()
    assert {k[1] for k in carm(legacy)} == {HUB} | {"%s-%s" % (s, HUB) for s in services(carm(legacy), HUB)}
    assert len(services(carm(legacy), HUB)) == 8
    r2, pinned = multi_acct({HUB: XACCT}, tmp_path)
    assert r2.returncode == 0, r2.stderr
    assert carm(pinned)[("IAMRoleSelector", "ec2-" + HUB)]["spec"]["arn"].startswith("arn:aws:iam::%s:" % XACCT)


@needs_helm
def test_no_object_has_two_owners(tmp_path):
    spokes = {"dev": {}, "prod": {}}
    owners = {}
    _, docs = multi_acct({"dev": ACCT, "prod": ACCT}, tmp_path)  # upgraded fleet repo
    for k in carm(docs):
        owners.setdefault(k, []).append("multi-acct")
    for s in spokes:
        _, docs = kro(spokes, s, tmp_path)
        for k in carm(docs):
            owners.setdefault(k, []).append("clusters-kro-" + s)
    dup = {k: v for k, v in owners.items() if len(v) > 1}
    assert not dup, dup


@needs_helm
def test_spoke_named_like_the_hub_fails_to_render(tmp_path):
    r, _ = kro({HUB: {}}, HUB, tmp_path)
    assert r.returncode != 0
    assert "same name as the hub" in r.stderr


@needs_helm
def test_taken_over_objects_match_what_multi_acct_used_to_render(tmp_path):
    """Adoption in place: the legacy multi-acct spec (reconstructed from the hub template,
    which renders the spoke entries the same way) equals the kro-clusters spec."""
    _, hub = multi_acct(None, tmp_path)
    _, spoke = kro({"dev": {}}, "dev", tmp_path)
    h, s = carm(hub), carm(spoke)
    for svc in services(h, HUB):
        hs = h[("IAMRoleSelector", "%s-%s" % (svc, HUB))]["spec"]
        ss = s[("IAMRoleSelector", "%s-dev" % svc)]["spec"]
        assert ss == yaml.safe_load(yaml.safe_dump(hs).replace(HUB, "dev")), svc
    assert s[("Namespace", "dev")]["metadata"]["annotations"]["services.k8s.aws/team-id"] == "dev"
    assert services(h, HUB) == services(s, "dev"), "multi-acct and kro-clusters must cover the same services"


def test_spoke_names_annotation_and_configs_multi_acct_writes_are_gone():
    reg = open(os.path.join(REPO, "gitops", "addons", "registry", "platform.yaml")).read()
    assert "spoke_namespaces" not in reg and "spokeNames" not in reg
    for root in (MA, KRO):
        for dp, _, fs in os.walk(root):
            for f in fs:
                txt = open(os.path.join(dp, f)).read()
                assert "spokeNames" not in txt and "manageIamRoleSelectors" not in txt, f
    tf = yaml.safe_load(open(os.path.join(REPO, "workshop", "Taskfile.yaml")))
    enable = "\n".join(c if isinstance(c, str) else c.get("cmd", "")
                       for c in tf["tasks"]["spokes:enable-kro"]["cmds"])
    assert not re.search(r"configs/multi-acct", enable.replace("into configs/multi-acct", "")), \
        "spokes:enable-kro must not write configs/multi-acct"
