"""Unit tests for ``scripts/post_install_verify.py``.

Hermetic: no AWS, no cluster, no network beyond a loopback HTTP server. The command
runner, HTTP fetcher and DNS resolver are injected fakes. Besides the per-check logic,
two contracts are asserted:

  * read-only: every command the verifier issues is ``aws eks describe-cluster``,
    ``aws eks update-kubeconfig --kubeconfig <private tmp file>``, ``kubectl get`` or
    ``kubectl logs``;
  * no secret value (cluster-secret ``data``, credential-like annotations) ever appears
    in the rendered output or the JSON results.

Run:  python -m pytest scripts/tests/test_post_install_verify.py -q
"""

import http.server
import json
import threading
import time

import pytest

import post_install_verify as piv

SECRET = "s3cr3t-v4lue-never-printed"
NOW = time.time()


def ts(seconds_ago):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(NOW - seconds_ago))


# ---------------------------------------------------------------------------------------
# config / inputs
# ---------------------------------------------------------------------------------------


def test_inputs_require_hub_and_region():
    with pytest.raises(ValueError):
        piv.inputs_from_config({"aws": {"region": "r1"}}, env={})
    with pytest.raises(ValueError):
        piv.inputs_from_config({"hub": {"clusterName": "h"}}, env={})


@pytest.mark.parametrize("override,env,expected", [
    ("cli", {"AWS_PROFILE": "envp"}, "cli"),
    (None, {"AWS_PROFILE": "envp"}, None),    # the AWS CLI picks AWS_PROFILE up itself
    (None, {}, "cfgp"),
])
def test_profile_precedence(override, env, expected):
    cfg = {"hub": {"clusterName": "h"}, "aws": {"region": "r1", "profile": "cfgp"}}
    assert piv.inputs_from_config(cfg, override, env=env).profile == expected


def test_load_config_reads_yaml(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("hub:\n  clusterName: h\naws:\n  region: r1\ndomain: d.example.test\n")
    inp = piv.inputs_from_config(piv.load_config(str(p)), env={})
    assert (inp.hub, inp.region, inp.domain) == ("h", "r1", "d.example.test")


def test_main_config_error_exits_2(tmp_path, capsys):
    assert piv.main(["--config", str(tmp_path / "missing.yaml")]) == 2


# ---------------------------------------------------------------------------------------
# cluster secrets
# ---------------------------------------------------------------------------------------


def secret_item(name, labels=None, ann=None):
    return {"metadata": {"name": name, "labels": labels or {}, "annotations": ann or {}},
            "data": {"config": SECRET}}


HUB_ANN = {
    "aws_cluster_name": "h", "aws_region": "r1", "aws_account_id": "000000000000",
    "resource_prefix": "p", "addonsRepoURL": "https://git.test/a.git", "addonsRepoRevision": "main",
    "ingress_domain_name": "d.test", "aws_grafana_url": "g-1.grafana.test",
    "aws_argocd_url": "argocd-1.caps.test", "git_token": SECRET,
}


def hub_secret(**overrides):
    ann = dict(HUB_ANN, **overrides)
    return piv.parse_cluster_secrets({"items": [secret_item("h", {"fleet_member": "control-plane"}, ann)]})[0]


def test_parse_drops_data_and_splits_hub_spokes():
    doc = {"items": [secret_item("h", {"fleet_member": "control-plane"}, {"aws_cluster_name": "h"}),
                     secret_item("s1", {"fleet_member": "spoke"}, {"aws_cluster_name": "s1-eks", "aws_region": "r2"}),
                     secret_item("in-cluster")]}
    secrets = piv.parse_cluster_secrets(doc)
    assert all("data" not in d for d in doc["items"])
    hub, spokes = piv.split_hub_spokes(secrets, "h")
    assert hub.name == "h"
    assert [(s.cluster_name, s.region) for s in spokes] == [("s1-eks", "r2")]


def test_parse_drops_only_kubectl_prefixed_annotations():
    ann = {"kubectl.kubernetes.io/last-applied-configuration": "{}",
           "x.kubectl.kubernetes.io/keep": "1",
           "kubectl.kubernetes.io": "keep-unprefixed",
           "aws_cluster_name": "h"}
    sec = piv.parse_cluster_secrets({"items": [secret_item("h", {}, ann)]})[0]
    assert sorted(sec.annotations) == ["aws_cluster_name", "kubectl.kubernetes.io", "x.kubectl.kubernetes.io/keep"]


def test_secret_values_clean_hub_passes():
    inp = piv.Inputs("h", "r1", None, "d.test", "p", False)
    r = piv.check_secret_values(hub_secret(), True, inp)
    assert r.status == piv.PASS, r.details


@pytest.mark.parametrize("key,value,needle", [
    ("aws_grafana_url", "d.test/grafana", "aws_grafana_url"),           # managed service routed via ingress
    ("aws_argocd_url", "https://argocd-1.caps.test/argocd", "aws_argocd_url"),
    ("ingress_domain_name", "REPLACE_WITH_RESERVED_DOMAIN", "ingress_domain_name"),
    ("aws_region", "<region>", "aws_region"),
    ("addonsRepoRevision", "", "addonsRepoRevision: missing"),
    ("nat_egress_cidrs", "NAT_LOOKUP_FAILED", "nat_egress_cidrs"),
    ("resource_prefix", "other", "resource_prefix: differs"),
])
def test_secret_values_findings(key, value, needle):
    inp = piv.Inputs("h", "r1", None, "d.test", "p", False)
    r = piv.check_secret_values(hub_secret(**{key: value}), True, inp)
    assert r.status == piv.FAIL
    assert any(needle in d for d in r.details), r.details
    if value:
        assert all(value not in d for d in r.details)   # key names only, never the value


def test_secret_values_never_print_a_credential_placeholder():
    r = piv.check_secret_values(hub_secret(git_token="CHANGEME-" + SECRET), True, None)
    assert r.status == piv.FAIL
    assert SECRET not in json.dumps(r.__dict__)


def test_spoke_secret_needs_only_spoke_keys():
    s = piv.parse_cluster_secrets({"items": [secret_item("s", {}, {"aws_cluster_name": "s", "aws_region": "r",
                                                                    "amp_endpoint_url": ""})]})[0]
    assert piv.check_secret_values(s, False, None).status == piv.PASS


# ---------------------------------------------------------------------------------------
# ArgoCD / Crossplane / kro
# ---------------------------------------------------------------------------------------


def app(name, sync, health, dest="h"):
    return {"metadata": {"name": name, "namespace": "argocd"}, "spec": {"destination": {"name": dest}},
            "status": {"sync": {"status": sync}, "health": {"status": health}}}


def test_bad_applications_lists_each_problem():
    doc = {"items": [app("ok", "Synced", "Healthy"), app("deg", "Synced", "Degraded"),
                     app("miss", "OutOfSync", "Missing", "s1"), {"metadata": {"name": "new"}}]}
    bad = piv.bad_applications(doc)
    assert len(bad) == 3
    assert any("deg" in b and "health=Degraded" in b for b in bad)
    assert any("miss" in b and "sync=OutOfSync" in b and "dest=s1" in b for b in bad)
    assert any("new" in b and "Unknown" in b for b in bad)


def test_appset_errors_only_true_error_conditions():
    doc = {"items": [
        {"metadata": {"name": "a"}, "status": {"conditions": [{"type": "ErrorOccurred", "status": "True", "message": "boom"}]}},
        {"metadata": {"name": "b"}, "status": {"conditions": [{"type": "ErrorOccurred", "status": "False"}]}},
        {"metadata": {"name": "c"}},
    ]}
    assert piv.appset_errors(doc) == ["a: boom"]


def pkg(name, installed="True", healthy="True"):
    return {"metadata": {"name": name}, "status": {"conditions": [
        {"type": "Installed", "status": installed}, {"type": "Healthy", "status": healthy}]}}


def test_unhealthy_packages_and_rgds():
    assert piv.unhealthy_packages({"items": [pkg("ok"), pkg("bad", healthy="False")]}, "provider") == \
        ["provider/bad Installed=True Healthy=False"]
    assert piv.inactive_rgds({"items": [{"metadata": {"name": "x"}, "status": {"state": "Active"}},
                                        {"metadata": {"name": "y"}, "status": {"state": "Inactive"}}]}) == \
        ["rgd/y state=Inactive"]


# ---------------------------------------------------------------------------------------
# pods / workloads
# ---------------------------------------------------------------------------------------


def pod(name, phase="Running", waiting=None, age=60, owner=None, reason=None, sched=None, init=False):
    cs = [{"name": "c", "state": {"waiting": {"reason": waiting}} if waiting else {"running": {}}}]
    st = {"phase": phase}
    st["initContainerStatuses" if init else "containerStatuses"] = cs
    if reason:
        st["reason"] = reason
    if sched:
        st["conditions"] = [{"type": "PodScheduled", "status": sched}]
    md = {"name": name, "namespace": "ns", "creationTimestamp": ts(age)}
    if owner:
        md["ownerReferences"] = [{"kind": owner}]
    return {"metadata": md, "status": st}


def test_failing_pods_classification():
    doc = {"items": [
        pod("ok"),
        pod("crash", waiting="CrashLoopBackOff"),
        pod("pull", phase="Pending", waiting="ImagePullBackOff"),
        pod("initpull", phase="Pending", waiting="ErrImagePull", init=True),
        pod("young-pending", phase="Pending", age=60),
        pod("old-pending", phase="Pending", age=3600, sched="False"),
        pod("job-failed", phase="Failed", owner="Job"),
        pod("evicted", phase="Failed", owner="ReplicaSet", reason="Evicted"),
        pod("bare-failed", phase="Failed"),
        pod("done", phase="Succeeded"),
        pod("creating", waiting="ContainerCreating"),
    ]}
    got = {(p, why) for _, p, _, why in piv.failing_pods(doc, now=NOW, pending_grace=900)}
    assert got == {("crash", "CrashLoopBackOff"), ("pull", "ImagePullBackOff"), ("initpull", "ErrImagePull"),
                   ("old-pending", "Pending > 15m (unschedulable)"), ("bare-failed", "phase=Failed (no reason)")}


def test_unready_workloads():
    doc = {"items": [
        {"kind": "Deployment", "metadata": {"name": "ok", "namespace": "n"}, "spec": {"replicas": 2}, "status": {"readyReplicas": 2}},
        {"kind": "Deployment", "metadata": {"name": "half", "namespace": "n"}, "spec": {"replicas": 2}, "status": {"readyReplicas": 1}},
        {"kind": "Deployment", "metadata": {"name": "zero", "namespace": "n"}, "spec": {"replicas": 0}, "status": {}},
        {"kind": "StatefulSet", "metadata": {"name": "sts", "namespace": "n"}, "spec": {"replicas": 1}, "status": {}},
        {"kind": "DaemonSet", "metadata": {"name": "ds", "namespace": "n"}, "status": {"desiredNumberScheduled": 3, "numberReady": 2}},
    ]}
    assert piv.unready_workloads(doc) == ["daemonset/n/ds ready 2/3", "deployment/n/half ready 1/2",
                                          "statefulset/n/sts ready 0/1"]


def test_crashloop_exec_format_error_is_flagged():
    calls = []

    def run(argv):
        calls.append(argv)
        if "logs" in argv:
            return 0, "standard_init_linux.go:228: exec user process caused: exec format error\n", ""
        if argv[-4:-2] == ["get", "pods"] or "pods" in argv:
            return 0, json.dumps({"items": [pod("crash", waiting="CrashLoopBackOff")]}), ""
        return 1, "", "error: the server doesn't have a resource type \"x\""

    c = piv.Cluster("c1", "r", "/tmp/kc", None, run)
    res = {r.check: r for r in piv.cluster_checks(c)}
    assert res["pods.failing"].status == piv.FAIL
    assert "exec format error" in res["pods.failing"].details[0]
    assert res["crossplane.packages"].status == piv.SKIP
    assert res["kro.rgds"].status == piv.SKIP


# ---------------------------------------------------------------------------------------
# ingress / endpoints
# ---------------------------------------------------------------------------------------


def ingress(ns, name, rules, lb=None):
    return {"metadata": {"namespace": ns, "name": name},
            "spec": {"rules": [{**({"host": h} if h else {}),
                                "http": {"paths": [{"path": p, "backend": {"service": {"name": s}}} for p, s in paths]}}
                               for h, paths in rules]},
            "status": {"loadBalancer": {"ingress": [{"hostname": lb}] if lb else []}}}


INGRESSES = {"items": [
    ingress("argo", "argo-workflows", [("", [("/argo-workflows", "argo-server")])], "lb-public.test"),
    ingress("backstage", "backstage", [("d.test", [("/backstage", "backstage")])], "lb-public.test"),
    ingress("jupyterhub", "jupyterhub", [("", [("/jupyterhub", "proxy-public")])], "lb-public.test"),
    ingress("keycloak", "keycloak", [("", [("/keycloak", "keycloak")])], "lb-public.test"),
    ingress("agentgateway-system", "agentgateway", [("d.test", [("/sse", "agentgateway-ingress"),
                                                                 ("/.well-known/oauth-protected-resource", "agentgateway-ingress")])], "lb-public.test"),
    ingress("agentgateway-system", "agentgateway-agents", [("agents.d.test", [("/", "agentgateway-ingress")])], "lb-public.test"),
    ingress("misc", "thing", [("", [("/thing", "thing-svc")])], "lb-public.test"),
]}


def test_endpoint_targets_and_agentgateway_targets():
    paths = piv.ingress_paths(INGRESSES)
    known, unknown = piv.endpoint_targets(paths, "d.test")
    assert {a: [h for h, _ in v] for a, v in known.items()} == {
        "argo-workflows": ["d.test/argo-workflows"], "backstage": ["d.test/backstage"],
        "jupyterhub": ["d.test/jupyterhub"], "keycloak": ["d.test/keycloak"]}
    assert [u.service for u in unknown] == ["thing-svc"]
    assert piv.agentgateway_targets(paths, "d.test") == ["agents.d.test/mcp", "d.test/sse"]


@pytest.mark.parametrize("app,status,chain,body,ok", [
    ("argo-workflows", 200, ["u"], "<html><title>Argo</title>", True),
    ("argo-workflows", 200, ["u"], "<title>404: This page could not be found.</title>", False),
    ("kargo", 404, ["u"], "<title>Kargo</title>", False),
    ("langfuse", 502, ["u"], "langfuse", False),
    ("jupyterhub", 200, ["https://d/jupyterhub",
                         "https://d/keycloak/realms/r/protocol/openid-connect/auth?response_type=code&client_id=jupyterhub"],
     "<title>Sign in</title>", True),
    ("jupyterhub", 200, ["https://d/jupyterhub/hub/login"], "<title>JupyterHub</title>", True),
    # empty authorize_url: oauth_login redirects to itself, never reaching the IdP
    ("jupyterhub", 0, ["https://d/jupyterhub/hub/oauth_login?response_type=code&client_id=jupyterhub"], "", False),
])
def test_content_matches(app, status, chain, body, ok):
    assert piv.content_matches(piv.APPS[app], status, chain, body) is ok


def fake_fetch(table):
    def fetch(url, timeout=15.0, follow=True, **_):
        for prefix, resp in table.items():
            if url.startswith(prefix):
                return resp
        return piv.HttpResponse(404, [url], "<title>404</title>")
    return fetch


def test_endpoint_checks_enabled_without_ingress_fails_disabled_skips():
    sec = piv.parse_cluster_secrets({"items": [secret_item("h", {"fleet_member": "control-plane",
                                                                   "enable_kargo": "true", "enable_backstage": "true"},
                                                                  dict(HUB_ANN))]})[0]
    fetch = fake_fetch({
        "https://d.test/backstage": piv.HttpResponse(200, ["https://d.test/backstage"], "<title>Backstage</title>"),
        "https://d.test/argo-workflows": piv.HttpResponse(200, ["x"], "<title>404: This page could not be found.</title>"),
        "https://d.test/jupyterhub": piv.HttpResponse(0, ["x"], "", "redirect loop at /jupyterhub/hub/oauth_login"),
        "https://d.test/keycloak": piv.HttpResponse(200, ["x"], "Keycloak"),
        "https://g-1.grafana.test": piv.HttpResponse(200, ["x"], "<title>Amazon Managed Grafana</title>"),
        "https://argocd-1.caps.test": piv.HttpResponse(200, ["x"], "<title>Argo CD</title>"),
    })
    res = {r.check: r for r in piv.endpoint_checks(sec, piv.ingress_paths(INGRESSES), "d.test", fetch)}
    assert res["endpoint.backstage"].status == piv.PASS
    assert res["endpoint.argo-workflows"].status == piv.FAIL          # 200 but wrong content
    assert res["endpoint.jupyterhub"].status == piv.FAIL
    assert "redirect loop" in res["endpoint.jupyterhub"].details[0]
    assert res["endpoint.kargo"].status == piv.FAIL                   # enabled, no ingress
    assert res["endpoint.langfuse"].status == piv.SKIP                # not enabled, no ingress
    assert res["endpoint.unclassified"].status == piv.SKIP
    assert res["endpoint.grafana"].status == piv.PASS
    assert res["endpoint.argocd"].status == piv.PASS


def kc_doc(issuer):
    return json.dumps({"issuer": issuer, "authorization_endpoint": issuer + "/auth",
                       "token_endpoint": issuer + "/token", "jwks_uri": issuer + "/certs"})


@pytest.mark.parametrize("doc_issuer,keys,status", [
    ("https://d.test/keycloak/realms/platform", [{"kid": "1"}], piv.PASS),
    ("https://other.test/keycloak/realms/platform", [{"kid": "1"}], piv.FAIL),
    ("https://d.test/keycloak/realms/platform", [], piv.FAIL),
])
def test_keycloak_check(doc_issuer, keys, status):
    sec = hub_secret()
    sec.labels["enable_keycloak"] = "true"
    iss = "https://d.test/keycloak/realms/platform"
    fetch = fake_fetch({
        iss + "/.well-known": piv.HttpResponse(200, ["x"], kc_doc(doc_issuer)),
        doc_issuer + "/certs": piv.HttpResponse(200, ["x"], json.dumps({"keys": keys})),
    })
    r = piv.keycloak_check(sec, [sec], piv.ingress_paths(INGRESSES), "d.test", "platform", fetch)
    assert r.status == status, r.reason


def test_keycloak_issuer_prefers_annotation():
    s = piv.parse_cluster_secrets({"items": [secret_item("s", {}, {"oidc_issuer_url": "https://x.test/kc/realms/r/"})]})
    assert piv.expected_issuer(s, [], "d.test", "platform") == "https://x.test/kc/realms/r"
    assert piv.expected_issuer([], piv.ingress_paths(INGRESSES), "d.test", "platform") == \
        "https://d.test/keycloak/realms/platform"


def test_keycloak_skip_when_disabled():
    sec = hub_secret()
    assert piv.keycloak_check(sec, [sec], [], "d.test", "platform", fake_fetch({})).status == piv.SKIP


@pytest.mark.parametrize("code,status", [(401, piv.PASS), (200, piv.FAIL), (404, piv.FAIL)])
def test_agentgateway_check(code, status):
    sec = hub_secret()
    sec.labels["enable_agent_gateway"] = "true"
    fetch = fake_fetch({"https://": piv.HttpResponse(code, ["x"], "")})
    assert piv.agentgateway_check(sec, piv.ingress_paths(INGRESSES), "d.test", fetch).status == status


def test_agentgateway_skip_when_disabled_fail_when_enabled_without_ingress():
    sec = hub_secret()
    assert piv.agentgateway_check(sec, [], "d.test", fake_fetch({})).status == piv.SKIP
    sec.labels["enable_agent_gateway"] = "true"
    assert piv.agentgateway_check(sec, [], "d.test", fake_fetch({})).status == piv.FAIL


def test_external_dns_check():
    sec = hub_secret()
    sec.labels["enable_external_dns"] = "true"
    paths = piv.ingress_paths(INGRESSES)
    good = {"d.test": ["1.1.1.1"], "agents.d.test": ["1.1.1.1"], "lb-public.test": ["1.1.1.1", "2.2.2.2"]}
    assert piv.external_dns_check(sec, paths, "d.test", lambda h: good.get(h, [])).status == piv.PASS
    stale = dict(good, **{"agents.d.test": ["9.9.9.9"]})
    r = piv.external_dns_check(sec, paths, "d.test", lambda h: stale.get(h, []))
    assert r.status == piv.FAIL and any("agents.d.test" in d for d in r.details)
    missing = {"d.test": ["1.1.1.1"], "lb-public.test": ["1.1.1.1"]}
    assert piv.external_dns_check(sec, paths, "d.test", lambda h: missing.get(h, [])).status == piv.FAIL
    assert piv.external_dns_check(sec, paths, "abc.cloudfront.net", lambda h: []).status == piv.SKIP
    assert piv.external_dns_check(sec, paths, "", lambda h: []).status == piv.SKIP
    internal = piv.ingress_paths({"items": [ingress("k", "k", [("", [("/keycloak", "keycloak")])], "internal-x.test")]})
    assert piv.external_dns_check(sec, internal, "d.test", lambda h: ["3.3.3.3"] if h == "d.test" else []).status == piv.PASS
    sec.labels["enable_external_dns"] = "false"
    assert piv.external_dns_check(sec, paths, "d.test", lambda h: []).status == piv.SKIP


# ---------------------------------------------------------------------------------------
# http_get against a loopback server
# ---------------------------------------------------------------------------------------


class _Handler(http.server.BaseHTTPRequestHandler):
    n = 0

    def do_GET(self):  # noqa: N802
        _Handler.n += 1
        if self.path.startswith("/loop"):
            self.send_response(302)
            self.send_header("Location", f"?state={_Handler.n}")   # empty authorize_url pattern
            self.end_headers()
        elif self.path == "/go":
            self.send_response(302)
            self.send_header("Location", "/app")
            self.end_headers()
        else:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"<title>App</title>")

    def log_message(self, *a):
        pass


@pytest.fixture(scope="module")
def server():
    srv = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def test_http_get_follows_and_records_chain(server):
    r = piv.http_get(server + "/go")
    assert r.status == 200 and r.chain[-1].endswith("/app") and "App" in r.body


def test_http_get_detects_self_redirect_loop(server):
    r = piv.http_get(server + "/loop")
    assert r.error and "redirect loop at /loop" in r.error


def test_http_get_no_follow_returns_redirect(server):
    assert piv.http_get(server + "/go", follow=False).status == 302


# ---------------------------------------------------------------------------------------
# end to end with a fake runner: read-only + no secret leak + exit code
# ---------------------------------------------------------------------------------------


def fake_env(app_health="Healthy"):
    secrets = {"items": [
        secret_item("h", {"fleet_member": "control-plane", "enable_keycloak": "true",
                          "enable_agent_gateway": "true", "enable_backstage": "true"}, dict(HUB_ANN)),
        secret_item("s1", {"fleet_member": "spoke"}, {"aws_cluster_name": "s1", "aws_region": "r1",
                                                      "git_token": SECRET}),
    ]}
    calls = []

    def run(argv):
        calls.append(argv)
        if argv[0] == "aws":
            if "describe-cluster" in argv:
                return 0, json.dumps(["ACTIVE", "1.37"]), ""
            if "update-kubeconfig" in argv:
                return 0, "", ""
        if argv[0] == "kubectl":
            res = argv[argv.index("get") + 1] if "get" in argv else None
            if res == "secrets":
                return 0, json.dumps(secrets), ""
            if res == "applications.argoproj.io":
                return 0, json.dumps({"items": [app("a", "Synced", app_health)]}), ""
            if res == "ingresses.networking.k8s.io":
                return 0, json.dumps(INGRESSES), ""
            if res in ("pods", "deployments", "statefulsets", "daemonsets", "applicationsets.argoproj.io"):
                return 0, json.dumps({"items": []}), ""
            return 1, "", f"error: the server doesn't have a resource type \"{res}\""
        return 127, "", "unexpected"

    iss = "https://d.test/keycloak/realms/platform"
    fetch = fake_fetch({
        "https://d.test/backstage": piv.HttpResponse(200, ["x"], "<title>Backstage</title>"),
        "https://d.test/argo-workflows": piv.HttpResponse(200, ["x"], "<title>Argo</title>"),
        "https://d.test/jupyterhub": piv.HttpResponse(200, ["x"], "<title>JupyterHub</title>"),
        "https://d.test/keycloak/realms/platform/.well-known": piv.HttpResponse(200, ["x"], kc_doc(iss)),
        iss + "/certs": piv.HttpResponse(200, ["x"], json.dumps({"keys": [{"kid": "1"}]})),
        "https://d.test/keycloak": piv.HttpResponse(200, ["x"], "Keycloak"),
        "https://agents.d.test/mcp": piv.HttpResponse(401, ["x"], ""),
        "https://d.test/sse": piv.HttpResponse(401, ["x"], ""),
        "https://g-1.grafana.test": piv.HttpResponse(200, ["x"], "Grafana"),
        "https://argocd-1.caps.test": piv.HttpResponse(200, ["x"], "<title>Argo CD</title>"),
    })
    return run, fetch, calls


def test_verify_end_to_end_read_only_and_no_secret(tmp_path):
    run, fetch, calls = fake_env()
    inp = piv.Inputs("h", "r1", "prof", "d.test", "p", False)
    results = piv.verify(inp, run, fetch, lambda h: [], str(tmp_path))
    out = piv.render(results) + json.dumps([r.__dict__ for r in results])
    assert SECRET not in out
    assert piv.exit_code(results) == 0, piv.render(results)
    checks = {(r.check, r.scope) for r in results}
    assert ("eks.cluster-active", "s1") in checks and ("pods.failing", "s1") in checks
    for argv in calls:
        if argv[0] == "aws":
            assert argv[1:3] == ["--profile", "prof"]
            assert argv[5:7] in (["eks", "describe-cluster"], ["eks", "update-kubeconfig"])
            if "update-kubeconfig" in argv:
                assert argv[argv.index("--kubeconfig") + 1].startswith(str(tmp_path))
        else:
            assert argv[0] == "kubectl"
            verb = next(a for a in argv[1:] if not a.startswith("-") and "/" not in a and a != "kubectl")
            assert verb in ("get", "logs"), argv


def test_verify_exit_code_on_degraded_app(tmp_path):
    run, fetch, _ = fake_env(app_health="Degraded")
    inp = piv.Inputs("h", "r1", None, "d.test", "p", False)
    results = piv.verify(inp, run, fetch, lambda h: [], str(tmp_path))
    assert piv.exit_code(results) == 1
    bad = [r for r in results if r.status == piv.FAIL]
    assert [r.check for r in bad] == ["argocd.applications"]


def test_verify_stops_when_hub_not_active(tmp_path):
    def run(argv):
        return 0, json.dumps(["CREATING", "1.37"]), ""
    results = piv.verify(piv.Inputs("h", "r1", None, "", "", False), run, fake_fetch({}), lambda h: [], str(tmp_path))
    assert [(r.check, r.status) for r in results] == [("eks.cluster-active", piv.FAIL)]


def test_placeholder_config_domain_fails_and_falls_back(tmp_path):
    run, fetch, _ = fake_env()
    inp = piv.Inputs("h", "r1", None, "REPLACE_WITH_RESERVED_CLOUDFRONT_DOMAIN", "p", False)
    results = piv.verify(inp, run, fetch, lambda h: [], str(tmp_path))
    by = {r.check: r for r in results}
    assert by["config.domain"].status == piv.FAIL
    assert by["endpoint.backstage"].status == piv.PASS   # used the hub ingress_domain_name


def test_root_taskfile_exposes_verify():
    yaml = pytest.importorskip("yaml")
    import os
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    with open(os.path.join(root, "Taskfile.yaml"), encoding="utf-8") as fh:
        tf = yaml.safe_load(fh)
    cmd = " ".join(tf["tasks"]["verify"]["cmds"])
    assert "scripts/post_install_verify.py" in cmd and "--config {{.CONFIG_FILE}}" in cmd
