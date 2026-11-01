#!/usr/bin/env python3
"""Post-install verification of an appmod-blueprints platform (read-only).

Usage:
    task verify                                  # reads ./config.local.yaml
    python3 scripts/post_install_verify.py --config config.local.yaml [--json-out out.json]

What it does
------------
Every check prints one line ``PASS|FAIL|SKIP <check> <scope>: <reason>``; the script
exits 1 when at least one check FAILs, 0 otherwise, 2 on a usage/config error. go-task
wraps a failing command's code (201), so use ``task -x verify`` to get the 0/1/2 codes
through; plain ``task verify`` is still non-zero on any FAIL or config error.

Inputs are read only from:
  * the config file (``hub.clusterName``, ``aws.region``, ``aws.profile``, ``domain``,
    ``resourcePrefix``, ``insecure``);
  * the hub's ArgoCD cluster secrets (labels = enabled features, annotations = derived
    values such as ``ingress_domain_name``, ``aws_grafana_url``, ``oidc_issuer_url``);
  * the hub's Ingress objects (hosts, paths, backends) and EKS ``describe-cluster``.
Nothing about a particular deployment (cluster names, prefix, domain, region, account)
is hardcoded here.

Read-only guarantee
-------------------
Only ``aws eks describe-cluster``, ``aws eks update-kubeconfig --kubeconfig <tmp file>``
(writes a private temporary kubeconfig, never ``~/.kube/config``), ``kubectl get``,
``kubectl logs`` and anonymous HTTP GETs are issued. Secret values are never printed:
cluster-secret ``data`` is dropped on read and annotation findings report key names only.

Checks (optional ones SKIP when their feature is not enabled on the hub):
  eks.cluster-active        hub + every spoke registered on the hub are ACTIVE
  argocd.applications       every Application Synced + Healthy (lists the bad ones)
  argocd.applicationsets    no ApplicationSet with ErrorOccurred=True
  crossplane.packages       Providers / Functions Installed + Healthy (per cluster)
  kro.rgds                  ResourceGraphDefinitions Active (per cluster)
  pods.failing              no CrashLoopBackOff / ImagePullBackOff / exec format error /
                            long-Pending pods (per cluster)
  workloads.ready           Deployments / StatefulSets / DaemonSets fully ready (per cluster)
  cluster-secret.values     no placeholder / fallback annotation values; key values agree
                            with the config (hub name, region, prefix, domain)
  endpoint.<app>            each public app ingress serves that app's content (not just 200);
                            an enabled feature without an ingress FAILs
  endpoint.grafana/argocd   managed-service endpoints from the cluster secret serve their app
  keycloak.oidc-discovery   discovery document reachable, issuer matches, JWKS has keys
  agentgateway.auth         gateway MCP/SSE endpoints answer 401 without a token
  external-dns.records      ingress hosts resolve to the ingress load balancer
  ray.operator              KubeRay operator ready, no failed RayCluster
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"

# --------------------------------------------------------------------------------------
# Result model
# --------------------------------------------------------------------------------------


@dataclass
class Result:
    check: str
    scope: str
    status: str
    reason: str
    details: List[str] = field(default_factory=list)

    def line(self) -> str:
        return f"{self.status} {self.check} {self.scope}: {self.reason}"


def exit_code(results: Sequence[Result]) -> int:
    return 1 if any(r.status == FAIL for r in results) else 0


def summarize(results: Sequence[Result]) -> Dict[str, int]:
    out = {PASS: 0, FAIL: 0, SKIP: 0}
    for r in results:
        out[r.status] = out.get(r.status, 0) + 1
    return out


# --------------------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------------------


def load_config(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(text) or {}
    except ImportError:
        if not shutil.which("yq"):
            raise RuntimeError("PyYAML or yq is required to read the config file")
        out = subprocess.run(["yq", "-o=json", ".", path], capture_output=True, text=True, check=True)
        data = json.loads(out.stdout or "{}") or {}
    if not isinstance(data, dict):
        raise RuntimeError(f"{path}: top level is not a mapping")
    return data


@dataclass
class Inputs:
    hub: str
    region: str
    profile: Optional[str]
    domain: str
    prefix: str
    insecure: bool


def inputs_from_config(cfg: dict, profile_override: Optional[str] = None,
                       env: Optional[Dict[str, str]] = None) -> Inputs:
    env = os.environ if env is None else env
    hub = ((cfg.get("hub") or {}).get("clusterName") or "").strip()
    aws = cfg.get("aws") or {}
    region = (aws.get("region") or "").strip()
    if not hub or not region:
        raise ValueError("config must set hub.clusterName and aws.region")
    # Precedence: --profile > AWS_PROFILE already in the environment > aws.profile.
    # The config template ships aws.profile: "default"; like the install tasks, treat it as
    # "unset" so env/IMDS credentials keep working (--profile default would not resolve).
    cfg_profile = aws.get("profile")
    if isinstance(cfg_profile, str) and cfg_profile.strip() in ("", "default"):
        cfg_profile = None
    profile = profile_override or (None if env.get("AWS_PROFILE") else (cfg_profile or None))
    return Inputs(
        hub=hub,
        region=region,
        profile=profile,
        domain=str(cfg.get("domain") or "").strip(),
        prefix=str(cfg.get("resourcePrefix") or "").strip(),
        insecure=bool(cfg.get("insecure", False)),
    )


# --------------------------------------------------------------------------------------
# Cluster secrets (ArgoCD) - data is dropped as soon as it is read
# --------------------------------------------------------------------------------------


@dataclass
class ClusterSecret:
    name: str
    labels: Dict[str, str]
    annotations: Dict[str, str]

    @property
    def cluster_name(self) -> str:
        return (self.annotations.get("aws_cluster_name") or self.labels.get("aws_cluster_name")
                or self.name)

    @property
    def region(self) -> str:
        return self.annotations.get("aws_region") or self.annotations.get("region") or ""

    @property
    def is_hub(self) -> bool:
        return self.labels.get("fleet_member") == "control-plane"

    def enabled(self, feature: str) -> bool:
        return str(self.labels.get(f"enable_{feature}", "")).lower() == "true"


KUBECTL_ANNOTATION_PREFIX = "kubectl.kubernetes.io"


def _annotation_prefix(key: str) -> str:
    """Return the DNS prefix of a Kubernetes annotation key ("" when unprefixed)."""
    prefix, sep, _ = key.partition("/")
    return prefix if sep else ""


def parse_cluster_secrets(doc: dict) -> List[ClusterSecret]:
    out = []
    for item in doc.get("items", []):
        item.pop("data", None)
        item.pop("stringData", None)
        md = item.get("metadata", {})
        # Drop kubectl-managed annotations (e.g. last-applied-configuration) by
        # comparing the annotation-key prefix exactly rather than by substring.
        ann = {k: v for k, v in (md.get("annotations") or {}).items()
               if _annotation_prefix(k) != KUBECTL_ANNOTATION_PREFIX}
        out.append(ClusterSecret(md.get("name", ""), dict(md.get("labels") or {}), ann))
    return out


def split_hub_spokes(secrets: List[ClusterSecret], hub_name: str) -> Tuple[Optional[ClusterSecret], List[ClusterSecret]]:
    hub = None
    for s in secrets:
        if s.cluster_name == hub_name or s.name == hub_name:
            hub = s
    if hub is None:
        hubs = [s for s in secrets if s.is_hub]
        hub = hubs[0] if len(hubs) == 1 else None
    spokes = [s for s in secrets if s is not hub and not s.is_hub
              and s.name != "in-cluster"]
    return hub, spokes


PLACEHOLDER_PATTERNS = [
    re.compile(r"^<[^<>]+>$"),
    re.compile(r"\b(changeme|change-me|placeholder|todo|tbd|fixme|dummy)\b", re.I),
    re.compile(r"\breplace[_-]?(me|with)", re.I),
    re.compile(r"(^|[./@])example\.(com|org|net)\b", re.I),
    re.compile(r"\$\{[^}]*\}"),
    re.compile(r"\{\{[^}]*\}\}"),
    re.compile(r"^(null|none|nil|undefined|<nil>)$", re.I),
    re.compile(r"LOOKUP_FAILED|NOT[_-]?FOUND|fallback", re.I),
]

HUB_REQUIRED = ("aws_cluster_name", "aws_region", "aws_account_id", "resource_prefix",
                "addonsRepoURL", "addonsRepoRevision")
SPOKE_REQUIRED = ("aws_cluster_name", "aws_region")
# Annotations holding the endpoint of a managed service; they must be a bare host
# (or https://host), never a path under the platform ingress (e.g. <domain>/grafana).
MANAGED_ENDPOINT_KEYS = ("aws_grafana_url", "aws_argocd_url", "amp_endpoint_url")


def is_placeholder(value: str) -> bool:
    v = (value or "").strip()
    return bool(v) and any(p.search(v) for p in PLACEHOLDER_PATTERNS)


def _host_and_path(value: str) -> Tuple[str, str]:
    v = value.strip()
    if "://" not in v:
        v = "https://" + v
    u = urllib.parse.urlparse(v)
    return (u.hostname or ""), (u.path or "")


def check_secret_values(sec: ClusterSecret, hub: bool, inp: Optional[Inputs]) -> Result:
    """Key names only in the output: annotation values may be credentials (git_token)."""
    problems: List[str] = []
    ann = sec.annotations
    for k in sorted(ann):
        if is_placeholder(ann[k]):
            problems.append(f"{k}: placeholder/fallback-looking value")
    for k in (HUB_REQUIRED if hub else SPOKE_REQUIRED):
        if not (ann.get(k) or "").strip():
            problems.append(f"{k}: missing or empty")
    ingress_domain = (ann.get("ingress_domain_name") or "").strip()
    for k in MANAGED_ENDPOINT_KEYS:
        v = (ann.get(k) or "").strip()
        if not v:
            continue
        host, path = _host_and_path(v)
        if k != "amp_endpoint_url" and path.strip("/"):
            problems.append(f"{k}: carries a path; a managed service has its own endpoint")
        if ingress_domain and host == ingress_domain:
            problems.append(f"{k}: points at the platform ingress domain instead of the managed service")
    if hub and inp is not None:
        expect = {"aws_cluster_name": inp.hub, "aws_region": inp.region}
        if inp.prefix:
            expect["resource_prefix"] = inp.prefix
        if inp.domain:
            expect["ingress_domain_name"] = inp.domain
        for k, want in expect.items():
            got = (ann.get(k) or "").strip()
            if got and got != want:
                problems.append(f"{k}: differs from the config value")
    if problems:
        return Result("cluster-secret.values", sec.name, FAIL,
                      f"{len(problems)} problem(s)", problems)
    return Result("cluster-secret.values", sec.name, PASS,
                  f"{len(ann)} annotations, no placeholder, required keys set")


# --------------------------------------------------------------------------------------
# Kubernetes object evaluation (pure functions over `kubectl get -o json` documents)
# --------------------------------------------------------------------------------------

HEALTHY_APP = "Healthy"
SYNCED_APP = "Synced"


def bad_applications(doc: dict) -> List[str]:
    bad = []
    for a in doc.get("items", []):
        st = a.get("status", {})
        sync = (st.get("sync") or {}).get("status") or "Unknown"
        health = (st.get("health") or {}).get("status") or "Unknown"
        if sync != SYNCED_APP or health != HEALTHY_APP:
            md = a.get("metadata", {})
            dest = (a.get("spec", {}).get("destination") or {})
            target = dest.get("name") or dest.get("server") or "?"
            bad.append(f"{md.get('namespace', '?')}/{md.get('name', '?')} sync={sync} health={health} dest={target}")
    return sorted(bad)


def appset_errors(doc: dict) -> List[str]:
    out = []
    for s in doc.get("items", []):
        for c in (s.get("status") or {}).get("conditions") or []:
            if c.get("type") == "ErrorOccurred" and str(c.get("status")) == "True":
                msg = (c.get("message") or "").replace("\n", " ")[:200]
                out.append(f"{s.get('metadata', {}).get('name', '?')}: {msg}")
    return sorted(out)


def _conditions(obj: dict) -> Dict[str, str]:
    return {c.get("type"): str(c.get("status")) for c in (obj.get("status") or {}).get("conditions") or []}


def unhealthy_packages(doc: dict, kind: str) -> List[str]:
    out = []
    for p in doc.get("items", []):
        c = _conditions(p)
        if c.get("Installed") != "True" or c.get("Healthy") != "True":
            out.append(f"{kind}/{p.get('metadata', {}).get('name', '?')} Installed={c.get('Installed', '?')} Healthy={c.get('Healthy', '?')}")
    return out


def inactive_rgds(doc: dict) -> List[str]:
    out = []
    for r in doc.get("items", []):
        state = (r.get("status") or {}).get("state") or "Unknown"
        if state != "Active":
            out.append(f"rgd/{r.get('metadata', {}).get('name', '?')} state={state}")
    return out


BAD_WAITING = {"CrashLoopBackOff", "ImagePullBackOff", "ErrImagePull", "CreateContainerConfigError",
               "CreateContainerError", "InvalidImageName", "RunContainerError"}


def _parse_ts(ts: Optional[str]) -> Optional[float]:
    if not ts:
        return None
    try:
        return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return None


LONG_RUNNING_OWNERS = frozenset({"ReplicaSet", "StatefulSet", "DaemonSet"})


def failing_pods(doc: dict, now: Optional[float] = None, pending_grace: int = 900) -> List[Tuple[str, str, str, str]]:
    """Return (namespace, pod, container, reason) for every failing pod/container."""
    now = time.time() if now is None else now
    out = []
    for p in doc.get("items", []):
        md, st = p.get("metadata", {}), p.get("status", {})
        ns, name = md.get("namespace", "?"), md.get("name", "?")
        phase = st.get("phase")
        if phase == "Succeeded":
            continue
        statuses = (st.get("initContainerStatuses") or []) + (st.get("containerStatuses") or [])
        hit = False
        for cs in statuses:
            w = (cs.get("state") or {}).get("waiting") or {}
            if w.get("reason") in BAD_WAITING:
                out.append((ns, name, cs.get("name", "?"), w["reason"]))
                hit = True
        if hit:
            continue
        if phase == "Failed":
            # A Failed pod only counts when nothing re-creates it as a managed workload
            # would: bare pods, or pods of a ReplicaSet/StatefulSet/DaemonSet. Pods owned
            # by a Job, an Argo Workflow, Spark or any other batch controller are judged by
            # that owner (and by workloads/apps), and pods a node shutdown/eviction left
            # behind are replaced by their controller.
            owners = {o.get("kind") for o in md.get("ownerReferences") or []}
            long_running = not owners or bool(owners & LONG_RUNNING_OWNERS)
            if long_running and st.get("reason") not in ("Evicted", "Shutdown", "Terminated", "NodeShutdown"):
                out.append((ns, name, "-", f"phase=Failed ({st.get('reason') or 'no reason'})"))
            continue
        if phase == "Pending":
            created = _parse_ts(md.get("creationTimestamp"))
            if created is not None and now - created > pending_grace:
                sched = _conditions(p).get("PodScheduled")
                why = "unschedulable" if sched == "False" else "not started"
                out.append((ns, name, "-", f"Pending > {pending_grace // 60}m ({why})"))
    return out


def unready_workloads(doc: dict) -> List[str]:
    out = []
    for o in doc.get("items", []):
        kind = o.get("kind", "?")
        md, spec, st = o.get("metadata", {}), o.get("spec", {}), o.get("status", {})
        ref = f"{kind.lower()}/{md.get('namespace', '?')}/{md.get('name', '?')}"
        if kind == "DaemonSet":
            want, ready = st.get("desiredNumberScheduled", 0) or 0, st.get("numberReady", 0) or 0
        else:
            want = spec.get("replicas", 1) if spec.get("replicas") is not None else 1
            ready = st.get("readyReplicas", 0) or 0
        if want and ready < want:
            out.append(f"{ref} ready {ready}/{want}")
    return sorted(out)


# --------------------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class AppSpec:
    tokens: Tuple[str, ...]          # matched against backend service name / namespace
    body: Optional[str] = None       # regex on the response body
    url: Optional[str] = None        # regex on any URL of the redirect chain
    feature: Optional[str] = None    # enable_<feature> label on the hub cluster secret


APPS: Dict[str, AppSpec] = {
    "argo-workflows": AppSpec(("argo-server", "argo-workflows"), body=r"<title>\s*Argo\s*</title>",
                              feature="argo_workflows"),
    "backstage": AppSpec(("backstage",), body=r"<title>[^<]*Backstage", feature="backstage"),
    # auto_login sends an anonymous caller to the IdP: require that hop (or a hub login page).
    # A redirect back to /hub/oauth_login itself (empty authorize_url) must NOT count.
    "jupyterhub": AppSpec(("jupyterhub", "proxy-public"), body=r"<title>[^<]*JupyterHub",
                          url=r"/protocol/openid-connect/auth\?[^#]*client_id=jupyterhub", feature="jupyterhub"),
    "kargo": AppSpec(("kargo",), body=r"<title>\s*Kargo", feature="kargo"),
    "keycloak": AppSpec(("keycloak",), body=r"Keycloak", feature="keycloak"),
    "langfuse": AppSpec(("langfuse",), body=r"(?i)langfuse", feature="langfuse"),
}
MANAGED_APPS: Dict[str, Tuple[str, AppSpec]] = {
    "grafana": ("aws_grafana_url", AppSpec((), body=r"Grafana")),
    "argocd": ("aws_argocd_url", AppSpec((), body=r"<title>\s*Argo CD")),
}
AGENTGATEWAY_TOKEN = "agentgateway"


@dataclass(frozen=True)
class IngressPath:
    namespace: str
    ingress: str
    host: str          # "" when the rule has no host (catch-all)
    path: str
    service: str
    lb_hostnames: Tuple[str, ...] = ()


def ingress_paths(doc: dict) -> List[IngressPath]:
    out = []
    for ing in doc.get("items", []):
        md = ing.get("metadata", {})
        lbs = tuple(sorted({(x.get("hostname") or x.get("ip") or "") for x in
                            ((ing.get("status") or {}).get("loadBalancer") or {}).get("ingress") or []} - {""}))
        for rule in (ing.get("spec") or {}).get("rules") or []:
            host = rule.get("host") or ""
            for p in ((rule.get("http") or {}).get("paths")) or []:
                svc = ((p.get("backend") or {}).get("service") or {}).get("name") or ""
                out.append(IngressPath(md.get("namespace", ""), md.get("name", ""), host,
                                       p.get("path") or "/", svc, lbs))
    return out


def app_for(ip: IngressPath) -> Optional[str]:
    hay = f"{ip.service} {ip.namespace} {ip.ingress}".lower()
    if AGENTGATEWAY_TOKEN in hay:
        return None
    for app, spec in APPS.items():
        if any(t in hay for t in spec.tokens):
            return app
    return None


def endpoint_targets(paths: Iterable[IngressPath], domain: str) -> Tuple[Dict[str, List[Tuple[str, IngressPath]]], List[IngressPath]]:
    """Group ingress paths by known app -> [(host+path, ip)]; also return unknown ones."""
    known: Dict[str, List[Tuple[str, IngressPath]]] = {}
    unknown: List[IngressPath] = []
    for ip in paths:
        host = ip.host or domain
        if not host:
            continue
        app = app_for(ip)
        if app is None:
            if AGENTGATEWAY_TOKEN not in f"{ip.service} {ip.namespace} {ip.ingress}".lower():
                unknown.append(ip)
            continue
        path = ip.path if ip.path.startswith("/") else "/" + ip.path
        known.setdefault(app, []).append((host + path, ip))
    return known, unknown


def agentgateway_targets(paths: Iterable[IngressPath], domain: str) -> List[str]:
    out = []
    for ip in paths:
        if AGENTGATEWAY_TOKEN not in f"{ip.service} {ip.namespace} {ip.ingress}".lower():
            continue
        host = ip.host or domain
        if not host or ".well-known" in ip.path:
            continue
        path = "/mcp" if ip.path in ("", "/") else ip.path
        out.append(host + path)
    return sorted(set(out))


def content_matches(spec: AppSpec, status: int, chain: Sequence[str], body: str) -> bool:
    # A URL marker proves the app handed the caller to the expected next hop (e.g. the
    # IdP authorize endpoint), even when that hop then fails for an anonymous probe.
    if spec.url and any(re.search(spec.url, u) for u in chain):
        return True
    if status >= 500 or status == 404 or status == 0:
        return False
    return bool(spec.body and re.search(spec.body, body or ""))


@dataclass
class HttpResponse:
    status: int
    chain: List[str]
    body: str
    error: Optional[str] = None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **kw):  # noqa: D401 - urllib API
        return None


def http_get(url: str, timeout: float = 15.0, follow: bool = True, max_redirects: int = 10,
             headers: Optional[Dict[str, str]] = None) -> HttpResponse:
    """Anonymous GET with explicit redirect following (the chain is recorded)."""
    opener = urllib.request.build_opener(_NoRedirect, urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    chain = [url]
    for _ in range(max_redirects + 1):
        req = urllib.request.Request(chain[-1], headers={"User-Agent": "appmod-post-install-verify/1",
                                                         **(headers or {})})
        try:
            resp = opener.open(req, timeout=timeout)
            status, hdrs, body = resp.status, resp.headers, resp.read(400_000)
        except urllib.error.HTTPError as e:
            status, hdrs, body = e.code, e.headers, e.read(400_000)
        except Exception as e:  # DNS, TLS, timeout, refused
            return HttpResponse(0, chain, "", f"{type(e).__name__}: {str(e)[:160]}")
        text = body.decode("utf-8", "replace")
        loc = hdrs.get("Location") if hdrs is not None else None
        if follow and status in (301, 302, 303, 307, 308) and loc:
            nxt = urllib.parse.urljoin(chain[-1], loc)
            if nxt in chain[-3:]:
                return HttpResponse(status, chain, text)
            chain.append(nxt)
            base = nxt.split("?", 1)[0]
            if sum(1 for u in chain if u.split("?", 1)[0] == base) >= 3:
                return HttpResponse(status, chain, text, f"redirect loop at {urllib.parse.urlparse(base).path}")
            continue
        return HttpResponse(status, chain, text)
    return HttpResponse(0, chain, "", "too many redirects")


# --------------------------------------------------------------------------------------
# Command runner (injectable for tests)
# --------------------------------------------------------------------------------------

Runner = Callable[[List[str]], Tuple[int, str, str]]


def subprocess_runner(timeout: int = 120) -> Runner:
    def run(argv: List[str]) -> Tuple[int, str, str]:
        try:
            p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
            return p.returncode, p.stdout, p.stderr
        except subprocess.TimeoutExpired:
            return 124, "", f"timeout after {timeout}s"
    return run


NO_RESOURCE = re.compile(r"doesn't have a resource type|the server could not find the requested resource|no matches for kind", re.I)


class Cluster:
    def __init__(self, name: str, region: str, kubeconfig: Optional[str], context: Optional[str], run: Runner):
        self.name, self.region, self.kubeconfig, self.context, self.run = name, region, kubeconfig, context, run

    def kubectl(self, *args: str) -> Tuple[int, str, str]:
        argv = ["kubectl"]
        if self.kubeconfig:
            argv += ["--kubeconfig", self.kubeconfig]
        if self.context:
            argv += ["--context", self.context]
        return self.run(argv + ["--request-timeout=60s", *args])

    def get_json(self, resource: str, namespace: Optional[str] = None, selector: Optional[str] = None) -> Optional[dict]:
        """None when the resource type does not exist; raises RuntimeError on other errors."""
        args = ["get", resource, "-o", "json"]
        args += ["-n", namespace] if namespace else ["-A"]
        if selector:
            args += ["-l", selector]
        rc, out, err = self.kubectl(*args)
        if rc != 0:
            if NO_RESOURCE.search(err or ""):
                return None
            raise RuntimeError((err or out or f"kubectl rc={rc}").strip().splitlines()[-1][:200])
        return json.loads(out or "{}")


def aws_argv(inp: Inputs, region: str, *args: str) -> List[str]:
    argv = ["aws"]
    if inp.profile:
        argv += ["--profile", inp.profile]
    return argv + ["--region", region, *args]


def check_eks_active(inp: Inputs, name: str, region: str, run: Runner) -> Result:
    rc, out, err = run(aws_argv(inp, region, "eks", "describe-cluster", "--name", name,
                                "--query", "cluster.[status,version]", "--output", "json"))
    if rc != 0:
        return Result("eks.cluster-active", name, FAIL, f"describe-cluster failed: {(err or '').strip()[:160]}")
    status, version = (json.loads(out) + [None, None])[:2]
    if status != "ACTIVE":
        return Result("eks.cluster-active", name, FAIL, f"status {status}")
    return Result("eks.cluster-active", name, PASS, f"ACTIVE (k8s {version})")


def write_kubeconfig(inp: Inputs, name: str, region: str, path: str, run: Runner) -> Optional[str]:
    rc, _, err = run(aws_argv(inp, region, "eks", "update-kubeconfig", "--name", name,
                              "--kubeconfig", path, "--alias", name))
    return None if rc == 0 else (err or "").strip()[:200]


# --------------------------------------------------------------------------------------
# Per-cluster checks
# --------------------------------------------------------------------------------------


def _wrap(check: str, scope: str, fn: Callable[[], Result]) -> Result:
    try:
        return fn()
    except RuntimeError as e:
        return Result(check, scope, FAIL, f"kubectl error: {e}")


def cluster_checks(c: Cluster, pending_grace: int = 900, max_log_probes: int = 10,
                   expect_crossplane: bool = False, expect_kro: bool = False) -> List[Result]:
    res: List[Result] = []

    def pods() -> Result:
        doc = c.get_json("pods") or {"items": []}
        bad = failing_pods(doc, pending_grace=pending_grace)
        details = []
        for i, (ns, pod, ctr, why) in enumerate(bad):
            extra = ""
            if why == "CrashLoopBackOff" and i < max_log_probes and ctr != "-":
                rc, out, _ = c.kubectl("logs", "-n", ns, pod, "-c", ctr, "--previous", "--tail=30")
                if rc == 0 and "exec format error" in out:
                    extra = " (exec format error: image/node architecture mismatch)"
            details.append(f"{ns}/{pod} [{ctr}] {why}{extra}")
        total = len(doc.get("items", []))
        if details:
            return Result("pods.failing", c.name, FAIL, f"{len(details)} failing of {total} pods", details)
        return Result("pods.failing", c.name, PASS, f"0 failing of {total} pods")

    def workloads() -> Result:
        items = []
        for kind in ("deployments", "statefulsets", "daemonsets"):
            items += (c.get_json(kind) or {"items": []}).get("items", [])
        bad = unready_workloads({"items": items})
        if bad:
            return Result("workloads.ready", c.name, FAIL, f"{len(bad)} not ready of {len(items)}", bad)
        return Result("workloads.ready", c.name, PASS, f"{len(items)} workloads ready")

    def crossplane() -> Result:
        prov = c.get_json("providers.pkg.crossplane.io")
        fn = c.get_json("functions.pkg.crossplane.io")
        if prov is None and fn is None:
            if expect_crossplane:
                return Result("crossplane.packages", c.name, FAIL,
                              "Crossplane is enabled (enable_crossplane) but its CRDs are not installed")
            return Result("crossplane.packages", c.name, SKIP, "Crossplane not installed")
        bad = unhealthy_packages(prov or {}, "provider") + unhealthy_packages(fn or {}, "function")
        n = len((prov or {}).get("items", [])) + len((fn or {}).get("items", []))
        if bad:
            return Result("crossplane.packages", c.name, FAIL, f"{len(bad)} unhealthy of {n}", bad)
        if n == 0:
            return Result("crossplane.packages", c.name, SKIP, "no Provider/Function objects")
        return Result("crossplane.packages", c.name, PASS, f"{n} providers/functions Installed+Healthy")

    def kro() -> Result:
        doc = c.get_json("resourcegraphdefinitions.kro.run")
        if doc is None and expect_kro:
            return Result("kro.rgds", c.name, FAIL,
                          "kro is enabled (enable_kro) but the ResourceGraphDefinition CRD is not installed")
        if doc is None or not doc.get("items"):
            return Result("kro.rgds", c.name, SKIP, "no kro ResourceGraphDefinitions")
        bad = inactive_rgds(doc)
        if bad:
            return Result("kro.rgds", c.name, FAIL, f"{len(bad)} not Active of {len(doc['items'])}", bad)
        return Result("kro.rgds", c.name, PASS, f"{len(doc['items'])} RGDs Active")

    for check, fn in (("pods.failing", pods), ("workloads.ready", workloads),
                      ("crossplane.packages", crossplane), ("kro.rgds", kro)):
        res.append(_wrap(check, c.name, fn))
    return res


def argocd_checks(hub: Cluster) -> List[Result]:
    def apps() -> Result:
        doc = hub.get_json("applications.argoproj.io")
        if doc is None:
            return Result("argocd.applications", hub.name, FAIL, "Application CRD not found on the hub")
        n = len(doc.get("items", []))
        bad = bad_applications(doc)
        if n == 0:
            return Result("argocd.applications", hub.name, FAIL, "no Application on the hub")
        if bad:
            return Result("argocd.applications", hub.name, FAIL, f"{len(bad)} of {n} not Synced+Healthy", bad)
        return Result("argocd.applications", hub.name, PASS, f"{n}/{n} Synced+Healthy")

    def appsets() -> Result:
        doc = hub.get_json("applicationsets.argoproj.io")
        if doc is None:
            return Result("argocd.applicationsets", hub.name, SKIP, "ApplicationSet CRD not found")
        errs = appset_errors(doc)
        n = len(doc.get("items", []))
        if errs:
            return Result("argocd.applicationsets", hub.name, FAIL, f"{len(errs)} of {n} with ErrorOccurred", errs)
        return Result("argocd.applicationsets", hub.name, PASS, f"0 of {n} with ErrorOccurred")

    return [_wrap("argocd.applications", hub.name, apps), _wrap("argocd.applicationsets", hub.name, appsets)]


# --------------------------------------------------------------------------------------
# Hub endpoint checks
# --------------------------------------------------------------------------------------

Fetcher = Callable[..., HttpResponse]


def endpoint_checks(hub_secret: Optional[ClusterSecret], paths: List[IngressPath], domain: str,
                    fetch: Fetcher) -> List[Result]:
    res: List[Result] = []
    known, unknown = endpoint_targets(paths, domain)
    for app, spec in APPS.items():
        targets = known.get(app, [])
        enabled = hub_secret.enabled(spec.feature) if (hub_secret and spec.feature) else bool(targets)
        if not targets:
            if enabled:
                res.append(Result(f"endpoint.{app}", "hub", FAIL, f"enable_{spec.feature}=true but no ingress routes to it"))
            else:
                res.append(Result(f"endpoint.{app}", "hub", SKIP, "feature not enabled / no ingress"))
            continue
        fails, oks = [], []
        for hostpath, _ in targets:
            url = "https://" + hostpath
            r = fetch(url)
            if content_matches(spec, r.status, r.chain, r.body):
                oks.append(f"{hostpath}: HTTP {r.status}, {app} content found")
            elif r.error:
                fails.append(f"{hostpath}: {r.error}")
            else:
                fails.append(f"{hostpath}: HTTP {r.status}, expected {app} content not found (final {r.chain[-1].split('?')[0]})")
        if fails:
            res.append(Result(f"endpoint.{app}", "hub", FAIL, f"{len(fails)} of {len(targets)} paths wrong", fails + oks))
        else:
            res.append(Result(f"endpoint.{app}", "hub", PASS, f"{len(oks)} path(s) serve {app}", oks))
    if unknown:
        res.append(Result("endpoint.unclassified", "hub", SKIP,
                          f"{len(unknown)} ingress path(s) without a known content marker",
                          [f"{u.namespace}/{u.ingress} {u.host or '*'}{u.path} -> {u.service}" for u in unknown]))
    for app, (key, spec) in MANAGED_APPS.items():
        v = (hub_secret.annotations.get(key) if hub_secret else "") or ""
        if not v:
            res.append(Result(f"endpoint.{app}", "managed", SKIP, f"no {key} annotation on the hub"))
            continue
        url = v if "://" in v else "https://" + v
        r = fetch(url)
        if r.error:
            res.append(Result(f"endpoint.{app}", "managed", FAIL, r.error))
        elif content_matches(spec, r.status, r.chain, r.body):
            res.append(Result(f"endpoint.{app}", "managed", PASS, f"HTTP {r.status}, {app} content found"))
        else:
            res.append(Result(f"endpoint.{app}", "managed", FAIL, f"HTTP {r.status}, expected {app} content not found"))
    return res


def expected_issuer(secrets: Iterable[ClusterSecret], paths: Iterable[IngressPath], domain: str,
                    realm: str) -> Optional[str]:
    for s in secrets:
        v = (s.annotations.get("oidc_issuer_url") or "").strip()
        if v:
            return v.rstrip("/")
    for ip in paths:
        if app_for(ip) == "keycloak":
            host = ip.host or domain
            if host:
                base = ip.path.rstrip("/")
                return f"https://{host}{base}/realms/{realm}"
    return None


def keycloak_check(hub_secret: Optional[ClusterSecret], secrets: List[ClusterSecret], paths: List[IngressPath],
                   domain: str, realm: str, fetch: Fetcher) -> Result:
    enabled = hub_secret.enabled("keycloak") if hub_secret else False
    issuer = expected_issuer(secrets, paths, domain, realm)
    # When the hub secret is known, enable_keycloak decides: spoke secrets carry an
    # oidc_issuer_url too, which must not turn the check on for a hub without Keycloak.
    if hub_secret is not None and not enabled:
        return Result("keycloak.oidc-discovery", "hub", SKIP, "Keycloak not enabled")
    if not enabled and issuer is None:
        return Result("keycloak.oidc-discovery", "hub", SKIP, "Keycloak not enabled")
    if issuer is None:
        return Result("keycloak.oidc-discovery", "hub", FAIL, "Keycloak enabled but no issuer could be derived (no ingress, no oidc_issuer_url)")
    r = fetch(issuer + "/.well-known/openid-configuration", follow=False)
    if r.error or r.status != 200:
        return Result("keycloak.oidc-discovery", "hub", FAIL, f"discovery HTTP {r.status} {r.error or ''}".strip())
    try:
        doc = json.loads(r.body)
    except ValueError:
        return Result("keycloak.oidc-discovery", "hub", FAIL, "discovery document is not JSON")
    problems = []
    if (doc.get("issuer") or "").rstrip("/") != issuer:
        problems.append("issuer in the document differs from the expected issuer")
    for k in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        if not doc.get(k):
            problems.append(f"{k} missing")
    if doc.get("jwks_uri"):
        j = fetch(doc["jwks_uri"], follow=False)
        try:
            keys = json.loads(j.body).get("keys") if j.status == 200 else None
        except ValueError:
            keys = None
        if not keys:
            problems.append(f"JWKS has no keys (HTTP {j.status})")
    if problems:
        return Result("keycloak.oidc-discovery", "hub", FAIL, "; ".join(problems))
    return Result("keycloak.oidc-discovery", "hub", PASS, "discovery + JWKS OK, issuer matches")


def agentgateway_check(hub_secret: Optional[ClusterSecret], paths: List[IngressPath], domain: str,
                       fetch: Fetcher) -> Result:
    targets = agentgateway_targets(paths, domain)
    enabled = hub_secret.enabled("agent_gateway") if hub_secret else bool(targets)
    if not enabled:
        return Result("agentgateway.auth", "hub", SKIP, "agent gateway not enabled")
    if not targets:
        return Result("agentgateway.auth", "hub", FAIL, "enable_agent_gateway=true but no ingress routes to the gateway")
    fails, oks = [], []
    for t in targets:
        r = fetch("https://" + t, follow=False)
        (oks if r.status == 401 else fails).append(f"{t}: HTTP {r.status} {r.error or ''}".strip())
    if fails:
        return Result("agentgateway.auth", "hub", FAIL, f"{len(fails)} of {len(targets)} not 401 without a token", fails + oks)
    return Result("agentgateway.auth", "hub", PASS, f"{len(oks)} endpoint(s) answer 401 without a token", oks)


Resolver = Callable[[str], List[str]]


def resolve(host: str) -> List[str]:
    try:
        return sorted({ai[4][0] for ai in socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)})
    except socket.gaierror:
        return []


def external_dns_check(hub_secret: Optional[ClusterSecret], paths: List[IngressPath], domain: str,
                       resolver: Resolver) -> Result:
    if not domain:
        return Result("external-dns.records", "hub", SKIP, "no domain configured")
    if domain.endswith(".cloudfront.net"):
        return Result("external-dns.records", "hub", SKIP, "domain is a CloudFront hostname; no DNS record is managed")
    if hub_secret and not hub_secret.enabled("external_dns"):
        return Result("external-dns.records", "hub", SKIP, "external-dns not enabled on the hub")
    by_host: Dict[str, set] = {}
    for ip in paths:
        host = ip.host or domain
        by_host.setdefault(host, set()).update(ip.lb_hostnames)
    by_host.setdefault(domain, set())
    fails, oks = [], []
    for host in sorted(by_host):
        addrs = set(resolver(host))
        if not addrs:
            fails.append(f"{host}: does not resolve")
            continue
        lb_addrs = set()
        internal_only = bool(by_host[host]) and all(lb.startswith("internal-") for lb in by_host[host])
        for lb in by_host[host]:
            lb_addrs |= set(resolver(lb))
        if internal_only:
            # An internal ALB is reached through a front door (e.g. CloudFront VPC origin):
            # the public name cannot resolve to its private addresses.
            oks.append(f"{host}: resolves (ingress load balancer is internal)")
        elif lb_addrs and not (addrs & lb_addrs):
            fails.append(f"{host}: resolves, but not to its ingress load balancer")
        else:
            oks.append(f"{host}: resolves" + (" to its ingress load balancer" if lb_addrs else ""))
    if fails:
        return Result("external-dns.records", "hub", FAIL, f"{len(fails)} of {len(by_host)} hosts wrong", fails + oks)
    return Result("external-dns.records", "hub", PASS, f"{len(oks)} host(s) resolve", oks)


def ray_check(hub_secret: Optional[ClusterSecret], hub: Cluster) -> Result:
    if not (hub_secret and hub_secret.enabled("ray_operator")):
        return Result("ray.operator", hub.name, SKIP, "Ray operator not enabled")

    def run() -> Result:
        deps = [d for d in (hub.get_json("deployments") or {"items": []}).get("items", [])
                if "kuberay-operator" in d.get("metadata", {}).get("name", "")]
        if not deps:
            return Result("ray.operator", hub.name, FAIL, "enable_ray_operator=true but no kuberay-operator Deployment")
        bad = unready_workloads({"items": [dict(d, kind="Deployment") for d in deps]})
        rc = hub.get_json("rayclusters.ray.io") or {"items": []}
        failed = [f"raycluster/{r['metadata'].get('namespace')}/{r['metadata'].get('name')} state={(r.get('status') or {}).get('state')}"
                  for r in rc.get("items", []) if str((r.get("status") or {}).get("state", "")).lower() == "failed"]
        if bad or failed:
            return Result("ray.operator", hub.name, FAIL, "operator not ready or RayCluster failed", bad + failed)
        return Result("ray.operator", hub.name, PASS, f"operator ready, {len(rc.get('items', []))} RayCluster(s), none failed")

    return _wrap("ray.operator", hub.name, run)


# --------------------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------------------


def verify(inp: Inputs, run: Runner, fetch: Fetcher, resolver: Resolver, workdir: str,
           use_contexts: bool = False, argocd_ns: str = "argocd", realm: str = "platform",
           skip_spokes: bool = False, pending_grace: int = 900) -> List[Result]:
    results: List[Result] = []
    r = check_eks_active(inp, inp.hub, inp.region, run)
    results.append(r)
    if r.status != PASS:
        return results

    def make_cluster(name: str, region: str) -> Tuple[Optional[Cluster], Optional[str]]:
        if use_contexts:
            return Cluster(name, region, None, name, run), None
        path = os.path.join(workdir, f"kubeconfig-{re.sub(r'[^A-Za-z0-9_.-]', '_', name)}")
        err = write_kubeconfig(inp, name, region, path, run)
        return (None, err) if err else (Cluster(name, region, path, None, run), None)

    hub, err = make_cluster(inp.hub, inp.region)
    if hub is None:
        results.append(Result("kubeconfig", inp.hub, FAIL, f"update-kubeconfig failed: {err}"))
        return results

    try:
        doc = hub.get_json("secrets", namespace=argocd_ns, selector="argocd.argoproj.io/secret-type=cluster")
        secrets = parse_cluster_secrets(doc or {"items": []})
    except RuntimeError as e:
        results.append(Result("cluster-secret.read", inp.hub, FAIL, f"cannot read ArgoCD cluster secrets: {e}"))
        secrets = []
    hub_secret, spokes = split_hub_spokes(secrets, inp.hub)
    if hub_secret is None and secrets:
        results.append(Result("cluster-secret.read", inp.hub, FAIL, "no cluster secret identifies the hub"))

    clusters = [hub]
    if not skip_spokes:
        for s in spokes:
            region = s.region or inp.region
            # describe-cluster/update-kubeconfig use the caller's credentials: a spoke living in
            # another AWS account cannot be reached with them, so it is skipped, not failed.
            hub_acct = (hub_secret.annotations.get("aws_account_id") or "").strip() if hub_secret else ""
            spoke_acct = (s.annotations.get("aws_account_id") or "").strip()
            if hub_acct and spoke_acct and hub_acct != spoke_acct:
                results.append(Result("eks.cluster-active", s.cluster_name, SKIP,
                                      "spoke is in a different AWS account than the hub; "
                                      "checks need credentials for that account"))
                continue
            er = check_eks_active(inp, s.cluster_name, region, run)
            results.append(er)
            if er.status != PASS:
                continue
            c, err = make_cluster(s.cluster_name, region)
            if c is None:
                results.append(Result("kubeconfig", s.cluster_name, FAIL, f"update-kubeconfig failed: {err}"))
            else:
                clusters.append(c)

    results += argocd_checks(hub)
    for s in ([hub_secret] if hub_secret else []):
        results.append(check_secret_values(s, True, inp))
    for s in spokes:
        results.append(check_secret_values(s, False, None))
    for c in clusters:
        # Crossplane / kro run on the hub: a missing CRD is only a SKIP when the hub does not enable them.
        is_hub = c is hub and hub_secret is not None
        results += cluster_checks(c, pending_grace=pending_grace,
                                  expect_crossplane=is_hub and hub_secret.enabled("crossplane"),
                                  expect_kro=is_hub and hub_secret.enabled("kro"))

    domain = inp.domain
    hub_domain = (hub_secret.annotations.get("ingress_domain_name", "") if hub_secret else "").strip()
    if domain and is_placeholder(domain):
        results.append(Result("config.domain", inp.hub, FAIL,
                              "config domain is a placeholder; using the hub ingress_domain_name for endpoint checks"))
        domain = hub_domain
    domain = domain or hub_domain
    try:
        paths = ingress_paths(hub.get_json("ingresses.networking.k8s.io") or {"items": []})
    except RuntimeError as e:
        results.append(Result("endpoint.ingress-read", inp.hub, FAIL, str(e)))
        paths = []
    if not domain and not any(p.host for p in paths):
        results.append(Result("endpoint.*", "hub", SKIP, "no domain configured and no ingress host"))
    else:
        results += endpoint_checks(hub_secret, paths, domain, fetch)
        results.append(keycloak_check(hub_secret, secrets, paths, domain, realm, fetch))
        results.append(agentgateway_check(hub_secret, paths, domain, fetch))
        results.append(external_dns_check(hub_secret, paths, domain, resolver))
    results.append(ray_check(hub_secret, hub))
    return results


def render(results: Sequence[Result], verbose: bool = True) -> str:
    lines = []
    for r in results:
        lines.append(r.line())
        if verbose or r.status == FAIL:
            for d in r.details[:40]:
                lines.append(f"    - {d}")
            if len(r.details) > 40:
                lines.append(f"    - ... {len(r.details) - 40} more")
    s = summarize(results)
    lines.append(f"SUMMARY pass={s[PASS]} fail={s[FAIL]} skip={s[SKIP]} -> {'FAIL' if s[FAIL] else 'PASS'}")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Read-only post-install verification of the platform.")
    ap.add_argument("--config", default=os.environ.get("CONFIG_FILE", "config.local.yaml"))
    ap.add_argument("--profile", help="AWS profile (default: AWS_PROFILE, else aws.profile from the config)")
    ap.add_argument("--use-contexts", action="store_true",
                    help="use existing kubeconfig contexts named after the clusters (as `task kubeconfig` writes) "
                         "instead of private temporary kubeconfigs")
    ap.add_argument("--argocd-namespace", default="argocd")
    ap.add_argument("--keycloak-realm", default="platform",
                    help="realm used only when no oidc_issuer_url annotation exists")
    ap.add_argument("--skip-spokes", action="store_true")
    ap.add_argument("--pending-grace", type=int, default=900, help="seconds before a Pending pod counts as failing")
    ap.add_argument("--json-out", help="also write the results as JSON to this file")
    ap.add_argument("--quiet", action="store_true", help="print details only for FAIL")
    a = ap.parse_args(argv)
    try:
        inp = inputs_from_config(load_config(a.config), a.profile)
    except (OSError, ValueError, RuntimeError) as e:
        print(f"config error: {e}", file=sys.stderr)
        return 2
    for tool in ("aws", "kubectl"):
        if not shutil.which(tool):
            print(f"{tool} not found on PATH", file=sys.stderr)
            return 2
    with tempfile.TemporaryDirectory(prefix="post-install-verify-") as wd:
        os.chmod(wd, 0o700)
        results = verify(inp, subprocess_runner(), http_get, resolve, wd, use_contexts=a.use_contexts,
                         argocd_ns=a.argocd_namespace, realm=a.keycloak_realm, skip_spokes=a.skip_spokes,
                         pending_grace=a.pending_grace)
    print(f"post-install-verify hub={inp.hub} region={inp.region} at {datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ}")
    print(render(results, verbose=not a.quiet))
    if a.json_out:
        with open(a.json_out, "w", encoding="utf-8") as fh:
            json.dump({"hub": inp.hub, "summary": summarize(results),
                       "results": [r.__dict__ for r in results]}, fh, indent=2)
    return exit_code(results)


if __name__ == "__main__":
    sys.exit(main())
