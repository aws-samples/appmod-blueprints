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
    """Build the autonomous-incident message the agent expects (mode 1)."""
    return (
        "AUTONOMOUS INCIDENT (delivered by AMP alerting via SNS->SQS).\n"
        f"alertname: {alert.get('alertname')}\n"
        f"cluster: {alert.get('cluster')}\n"
        f"namespace: {alert.get('namespace')}\n"
        f"pod: {alert.get('pod')}\n"
        f"container: {alert.get('container')}\n"
        f"status: {alert.get('status')}\n"
        f"summary: {alert.get('summary')}\n\n"
        "Perform a Root-Cause Analysis using your read-only tools, then open a "
        "GitLab Merge Request on a NEW branch with the GitOps remediation "
        "(e.g. a memory request/limit bump). Never merge, never mutate the "
        "cluster. End with the MR URL and an 'awaiting human approval' note."
    )


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
                if _dedup(fp):
                    log(f"dedup skip {fp}")
                    continue
                try:
                    _forward(alert)
                    log(f"forwarded incident {fp}")
                except Exception as exc:  # noqa: BLE001
                    log(f"forward FAILED {fp}: {exc}")
                    _seen.pop(fp, None)  # allow retry
                    handled = False
            # delete only if every firing alert was handled (or none firing)
            if handled:
                try:
                    sqs.delete_message(QueueUrl=QUEUE_URL, ReceiptHandle=rh)
                except Exception as exc:  # noqa: BLE001
                    log(f"delete error: {exc}")


if __name__ == "__main__":
    sys.exit(main())
