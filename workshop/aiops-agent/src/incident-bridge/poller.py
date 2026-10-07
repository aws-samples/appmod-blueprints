#!/usr/bin/env python3
"""incident-bridge — SNS->SQS->agent bridge for the PEEKS autonomous-remediation demo.

AMP evaluates the OOMKill alerting rule (observability-aws chart) and its
AlertManager pushes firing alerts to an SNS topic; SNS fans out to an SQS queue
(raw message delivery). This consumer long-polls that queue IN-CLUSTER on the hub
and forwards each incident to the agent's A2A JSON-RPC endpoint — so nothing is
exposed publicly and the hop uses in-cluster DNS. Credentials come from EKS Pod
Identity on the `incident-bridge` ServiceAccount (SQS read only).

Env:
  SQS_QUEUE_URL   full queue URL (required)
  AGENT_A2A_URL   agent A2A JSON-RPC URL (default in-cluster stable svc)
  AWS_REGION      region (default us-west-2)
  DEDUP_TTL       seconds to suppress a repeat of the same alert (default 3600)
  POLL_WAIT       SQS long-poll seconds (default 20)
"""
import json
import os
import re
import sys
import time
import uuid

import boto3
import requests

REGION = os.getenv("AWS_REGION", "us-west-2")
QUEUE_URL = os.getenv("SQS_QUEUE_URL", "")
AGENT_A2A_URL = os.getenv(
    "AGENT_A2A_URL",
    "http://aiops-agent-stable.aiops-agent.svc.cluster.local:8083/",
)
DEDUP_TTL = int(os.getenv("DEDUP_TTL", "3600"))
POLL_WAIT = int(os.getenv("POLL_WAIT", "20"))
AGENT_TIMEOUT = int(os.getenv("AGENT_TIMEOUT", "300"))

# Durable, restart-proof anti-duplicate: before forwarding, check the target repo
# for an OPEN MR that already addresses this failing component. Generic and
# fail-open — if any of these are unset or GitLab is unreachable, the check is
# skipped (we still forward; the in-memory _seen dedup and the agent's own
# open-MR listing remain). No cluster/addon/repo names are hardcoded.
GITLAB_API_URL = os.getenv("GITLAB_API_URL", "")            # e.g. https://<domain>/api/v4
GITLAB_TOKEN = os.getenv("GITLAB_PERSONAL_ACCESS_TOKEN", "")  # reused read-only from gitlab-mcp secret
GITLAB_MR_PROJECT = os.getenv("GITLAB_MR_PROJECT", "")       # project path or numeric id the agent opens MRs on

_seen: dict[str, float] = {}  # fingerprint -> last-sent epoch


def log(msg: str) -> None:
    # ISO-8601 UTC timestamp prefix so the incident chronology is followable in
    # `kubectl logs` (SQS receive -> dedup/open-MR skip -> forward), independent
    # of any log-collector timestamps.
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    print(f"{ts} [incident-bridge] {msg}", flush=True)


def _fingerprint(alert: dict) -> str:
    return "|".join(
        str(alert.get(k, ""))
        for k in ("alertname", "cluster", "namespace", "pod", "container")
    )


def _subject(alert: dict) -> str:
    """Coarse idempotency key: the COMPONENT that is failing, independent of
    alertname, cluster, or pod-instance.

    AMP fires SEVERAL alertnames for one broken pod (PodOOMKilled,
    PodFrequentRestarts, PodCrashLoopBackOff, …); a SINGLE GitOps fix addresses
    all of them, so they MUST collapse to ONE subject. Keying on the component
    (container, else PVC, else pod) WITHOUT the alertname removes the race where
    a second alertname arrived before the first remediation's MR was open and
    produced a duplicate forward (observed: PodOOMKilled|hog forwarded, then
    PodCrashLoopBackOff|hog forwarded again for the same pod).

    The `namespace` label is deliberately EXCLUDED for container-scoped signals:
    the same failing pod is reported under different namespace labels by
    different AMP rules (observed: `kube-prometheus-stack` vs the real
    namespace), and the GitOps fix (`configs/<addon>/values.yaml`) is
    namespace-agnostic anyway. It is kept ONLY for PVC/node-scoped signals (no
    container), where a name can legitimately repeat across namespaces."""
    comp = _component(alert)
    if alert.get("container"):
        return comp
    # node/PVC-scoped signals have no container -> keep namespace as discriminator
    # (a PVC name can legitimately repeat across namespaces).
    return "|".join([str(alert.get("namespace", "")), str(comp)])


def _dedup(fp: str) -> bool:
    """Return True if this fingerprint was handled within DEDUP_TTL."""
    now = time.time()
    for k, ts in list(_seen.items()):
        if now - ts > DEDUP_TTL:
            _seen.pop(k, None)
    if fp in _seen:
        return True
    _seen[fp] = now
    return False


def _component(alert: dict) -> str:
    """The failing COMPONENT, independent of alertname/cluster/pod-instance.

    AMP typically fires SEVERAL alertnames for one broken pod (CrashLoopBackOff,
    PodNotReady, ContainerWaiting, …); keying dedup on the component (container,
    else PVC, else pod) collapses those variants to ONE remediation, which is what
    a single GitOps fix addresses. Generic: derived from labels, nothing hardcoded."""
    return str(
        alert.get("container")
        or alert.get("persistentvolumeclaim")
        or alert.get("pod", "")
    )


def _open_mr_exists(alert: dict) -> bool:
    """Deterministic, restart-proof duplicate guard: True if the target repo
    already has an OPEN MR addressing this component. Fail-open (returns False)
    when GitLab is not configured or unreachable, so it never blocks a real
    incident. Matches on an explicit machine marker (`Incident-Component: <c>`)
    the agent embeds, and falls back to a component substring in title/branch."""
    if not (GITLAB_API_URL and GITLAB_TOKEN and GITLAB_MR_PROJECT):
        return False
    comp = _component(alert)
    if not comp:
        return False
    try:
        from urllib.parse import quote
        url = f"{GITLAB_API_URL}/projects/{quote(GITLAB_MR_PROJECT, safe='')}/merge_requests"
        page = 1
        marker = f"incident-component: {comp}".lower()
        comp_l = comp.lower()
        while True:
            r = requests.get(
                url,
                headers={"PRIVATE-TOKEN": GITLAB_TOKEN},
                params={"state": "opened", "per_page": 100, "page": page},
                timeout=15,
            )
            r.raise_for_status()
            mrs = r.json()
            if not mrs:
                return False
            for mr in mrs:
                desc = (mr.get("description") or "").lower()
                if marker in desc:
                    return True
                hay = (mr.get("title", "") + " " + mr.get("source_branch", "")).lower()
                if comp_l and comp_l in hay:
                    return True
            if len(mrs) < 100:
                return False
            page += 1
    except Exception as exc:  # noqa: BLE001
        log(f"gitlab dup-check failed ({exc}); fail-open (forwarding)")
        return False


def _incident_prompt(alert: dict) -> str:
    """Build the autonomous-incident message the agent expects (mode 1).

    Signal-agnostic: we forward the alert's signal type, remediation hint and
    description, and let the AGENT decide the appropriate GitOps fix (memory
    bump, image ref, probe/config, requests/affinity/nodepool, storageClass, …)
    based on its skills. The bridge never assumes a specific remedy.
    """
    lines = ["AUTONOMOUS INCIDENT (delivered by AMP alerting via SNS->SQS)."]
    for k in (
        "alertname", "signal", "severity", "remediation", "cluster",
        "namespace", "pod", "container", "persistentvolumeclaim",
        "status", "summary", "description",
    ):
        v = alert.get(k)
        if v:  # skip empty labels (e.g. pod/container on node/PVC-scoped signals)
            lines.append(f"{k}: {v}")
    lines.append(
        "\nFIRST: list the OPEN merge requests in the target repo and check none "
        "already fixes this component/file — if one does, comment on it and STOP "
        "(do NOT open a duplicate). Otherwise perform a Root-Cause Analysis using "
        "your read-only tools (load the matching skill first — e.g. "
        "troubleshoot-platform / troubleshoot-kro / eks-*). Then open a GitLab "
        "Merge Request on a NEW branch with the appropriate GitOps remediation for "
        "THIS signal — identify the owning repo/manifest (read the resource's "
        "owning ArgoCD Application source if needed); the `remediation` hint above "
        "is a starting point, not a prescription. If the target file already "
        "exists, READ it and ADD only the keys you need (never rewrite/drop "
        "existing content). Never merge, never mutate the cluster. End with the MR "
        "URL and an 'awaiting human approval' note."
    )
    comp = _component(alert)
    if comp:
        # Machine-readable marker: the bridge greps OPEN MRs for this exact line
        # to deterministically suppress duplicates across restarts. Keep it verbatim.
        lines.append(f"\nInclude this EXACT line verbatim in the MR description:\nIncident-Component: {comp}")
    return "\n".join(lines)


def _context_id(alert: dict) -> str:
    """A2A contextId used by the agent as its AgentCore Memory sessionId, which
    must match ``[a-zA-Z0-9][a-zA-Z0-9-_]*``. The fingerprint joins labels with
    ``|`` (an invalid sessionId char), so sanitize every non-``[A-Za-z0-9_-]``
    char to ``-`` — otherwise the agent fails every autonomous incident with
    ``ValidationException ... sessionId failed to satisfy constraint`` on the
    memory ListEvents call and never runs the RCA."""
    return "incident-" + re.sub(r"[^A-Za-z0-9_-]", "-", _fingerprint(alert))


def _forward(alert: dict) -> bool:
    rpc = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "message/send",
        "params": {"message": {
            "role": "user",
            "parts": [{"kind": "text", "text": _incident_prompt(alert)}],
            "messageId": str(uuid.uuid4()),
            "contextId": _context_id(alert),
        }},
    }
    r = requests.post(AGENT_A2A_URL, json=rpc, timeout=AGENT_TIMEOUT)
    r.raise_for_status()
    return True


def _alerts_from_body(body: str) -> list[dict]:
    """Parse the SQS message body. With raw SNS delivery the body is the AMP
    AlertManager message; our template emits one compact JSON object per alert,
    concatenated. Be tolerant: accept a single object, a JSON array, or
    newline/`}{`-separated objects."""
    body = body.strip()
    out: list[dict] = []
    # normalise concatenated objects `}{` into a JSON array
    candidates = []
    if body.startswith("["):
        try:
            return [a for a in json.loads(body) if isinstance(a, dict)]
        except Exception:  # noqa: BLE001
            pass
    for chunk in body.replace("}{", "}\n{").splitlines():
        chunk = chunk.strip()
        if chunk:
            candidates.append(chunk)
    for c in candidates:
        try:
            obj = json.loads(c)
            if isinstance(obj, dict):
                out.append(obj)
        except Exception:  # noqa: BLE001
            log(f"skip unparseable chunk: {c[:120]}")
    return out


def main() -> int:
    if not QUEUE_URL:
        log("FATAL: SQS_QUEUE_URL not set")
        return 2
    sqs = boto3.client("sqs", region_name=REGION)
    log(f"polling {QUEUE_URL} -> {AGENT_A2A_URL} (dedup {DEDUP_TTL}s)")
    while True:
        try:
            resp = sqs.receive_message(
                QueueUrl=QUEUE_URL,
                MaxNumberOfMessages=1,
                WaitTimeSeconds=POLL_WAIT,
                VisibilityTimeout=max(AGENT_TIMEOUT + 30, 90),
            )
        except Exception as exc:  # noqa: BLE001
            log(f"receive error: {exc}; backing off 10s")
            time.sleep(10)
            continue
        for msg in resp.get("Messages", []):
            rh = msg["ReceiptHandle"]
            alerts = _alerts_from_body(msg.get("Body", ""))
            firing = [a for a in alerts if a.get("status", "firing") != "resolved"]
            handled = True
            for alert in firing:
                fp = _fingerprint(alert)
                subj = _subject(alert)
                if _dedup(subj):
                    log(f"dedup skip (subject={subj}) fp={fp}")
                    continue
                if _open_mr_exists(alert):
                    log(f"open-MR skip (component={_component(alert)}) fp={fp} — MR already open in {GITLAB_MR_PROJECT}")
                    continue
                try:
                    _forward(alert)
                    log(f"forwarded incident {fp} (subject={subj})")
                except Exception as exc:  # noqa: BLE001
                    log(f"forward FAILED {fp}: {exc}")
                    _seen.pop(subj, None)  # allow retry
                    handled = False
            # delete only if every firing alert was handled (or none firing)
            if handled:
                try:
                    sqs.delete_message(QueueUrl=QUEUE_URL, ReceiptHandle=rh)
                except Exception as exc:  # noqa: BLE001
                    log(f"delete error: {exc}")


if __name__ == "__main__":
    sys.exit(main())
