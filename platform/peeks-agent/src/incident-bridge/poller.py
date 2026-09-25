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
import sys
import time
import uuid

import boto3
import requests

REGION = os.getenv("AWS_REGION", "us-west-2")
QUEUE_URL = os.getenv("SQS_QUEUE_URL", "")
AGENT_A2A_URL = os.getenv(
    "AGENT_A2A_URL",
    "http://peeks-agent-stable.peeks-agent.svc.cluster.local:8083/",
)
DEDUP_TTL = int(os.getenv("DEDUP_TTL", "3600"))
POLL_WAIT = int(os.getenv("POLL_WAIT", "20"))
AGENT_TIMEOUT = int(os.getenv("AGENT_TIMEOUT", "300"))

_seen: dict[str, float] = {}  # fingerprint -> last-sent epoch


def log(msg: str) -> None:
    print(f"[incident-bridge] {msg}", flush=True)


def _fingerprint(alert: dict) -> str:
    return "|".join(
        str(alert.get(k, ""))
        for k in ("alertname", "cluster", "namespace", "pod", "container")
    )


def _subject(alert: dict) -> str:
    """Coarse idempotency key: the COMPONENT that is failing, independent of
    which cluster or pod-instance fired. The same addon failing on several
    clusters (or a pod recreated with a new name) collapses to ONE subject, so
    the bridge does not dispatch duplicate remediations for what is a single
    GitOps fix (e.g. the cluster-agnostic `configs/<addon>/values.yaml`). The
    durable backstop is the agent listing open MRs before creating one."""
    comp = (
        alert.get("container")
        or alert.get("persistentvolumeclaim")
        or alert.get("pod", "")
    )
    # For CONTAINER-scoped signals (image-pull / OOM of a named container), the
    # `namespace` label is UNRELIABLE: the same failing pod can be reported under
    # different namespace labels by different AMP rules (observed: the same
    # `langfuse-minio-init` pod's `mc` container fired once as namespace
    # `kube-prometheus-stack` and once as `langfuse`), which split into two
    # subjects and produced two duplicate MRs. Since the GitOps fix
    # (`configs/<addon>/values.yaml`) is namespace-agnostic, key ONLY on
    # alertname + container so those collapse to ONE subject.
    if alert.get("container"):
        return "|".join([str(alert.get("alertname", "")), str(comp)])
    # node/PVC-scoped signals have no container -> keep namespace as discriminator
    # (a PVC name can legitimately repeat across namespaces).
    return "|".join(
        [str(alert.get("alertname", "")), str(alert.get("namespace", "")), str(comp)]
    )


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
    return "\n".join(lines)


def _forward(alert: dict) -> bool:
    rpc = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "message/send",
        "params": {"message": {
            "role": "user",
            "parts": [{"kind": "text", "text": _incident_prompt(alert)}],
            "messageId": str(uuid.uuid4()),
            "contextId": f"incident-{_fingerprint(alert)}",
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
