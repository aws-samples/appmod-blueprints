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

# §8.1 backpressure controls for the autonomous loop.
# Open-MR ceiling: refuse to forward (open new remediation MRs) once this many
# incident MRs are already OPEN on the target repo (0 disables). Stops a storm from
# flooding the highest-precedence GitOps layer with agent MRs.
OPEN_MR_CEILING = int(os.getenv("OPEN_MR_CEILING", "10"))
# Circuit breaker: after this many CONSECUTIVE forward failures, stop forwarding and
# leave messages on the queue for CB_COOLDOWN seconds (then resume; the next failure
# re-trips). Guards against a systemic failure (agent/model/GitLab down) turning every
# incident into a 300s failed run.
CB_FAILURE_THRESHOLD = int(os.getenv("CB_FAILURE_THRESHOLD", "5"))
CB_COOLDOWN = int(os.getenv("CB_COOLDOWN", "300"))

# Durable, restart-proof anti-duplicate: before forwarding, check the target repo
# for an OPEN MR that already addresses this failing component. Generic and
# fail-open — if any of these are unset or GitLab is unreachable, the check is
# skipped (we still forward; the in-memory _seen dedup and the agent's own
# open-MR listing remain). No cluster/addon/repo names are hardcoded.
GITLAB_API_URL = os.getenv("GITLAB_API_URL", "")            # e.g. https://<domain>/api/v4
GITLAB_TOKEN = os.getenv("GITLAB_PERSONAL_ACCESS_TOKEN", "")  # reused read-only from gitlab-mcp secret
GITLAB_MR_PROJECT = os.getenv("GITLAB_MR_PROJECT", "")       # project path or numeric id the agent opens MRs on

_seen: dict[str, float] = {}  # fingerprint -> last-sent epoch

# Circuit-breaker state (process-local): consecutive forward failures, and the epoch
# until which the breaker stays OPEN (no forwarding).
_cb_failures: int = 0
_cb_open_until: float = 0.0


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
    """Idempotency key: the failing COMPONENT scoped by its NAMESPACE, independent
    of alertname, cluster, or pod-instance.

    AMP fires SEVERAL alertnames for one broken pod (PodOOMKilled,
    PodFrequentRestarts, PodCrashLoopBackOff, …); a SINGLE GitOps fix addresses all
    of them, so they collapse to ONE subject by keying on the component (container,
    else PVC, else pod) WITHOUT the alertname.

    The `namespace` label IS included (previously it was dropped for container-scoped
    signals). A GitOps remediation targets a specific workload (e.g.
    configs/<addon>/values.yaml for a specific namespace), and the same container
    name can legitimately recur in DIFFERENT namespaces for unrelated workloads —
    dropping namespace would collapse two genuinely distinct incidents into one and
    SUPPRESS the second remediation (fail-closed, the dangerous direction). Including
    it means at worst a duplicate forward if AMP reports the same pod under two
    namespace labels, which the open-MR check and the agent's own open-MR listing
    absorb — a far safer failure mode than silently dropping a real incident."""
    return "|".join([str(alert.get("namespace", "")), str(_component(alert))])


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
    incident. Matches ONLY on an explicit machine marker (`Incident-Component: <c>`)
    the agent embeds verbatim in every remediation MR description."""
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
                # EXACT machine marker only. The agent embeds "Incident-Component: <comp>"
                # verbatim in every remediation MR, so this is a precise, reliable match.
                # A looser title/branch SUBSTRING match was REMOVED: a short or common
                # component name (e.g. "app", "api", "web") substring-matches unrelated MRs
                # -> false positive -> the real incident is SUPPRESSED (fail-closed, the
                # dangerous direction). When the marker is absent we deliberately fail OPEN
                # (forward) rather than risk dropping a genuine incident; the in-memory
                # _seen dedup and the agent's own open-MR listing still prevent a storm.
                if marker in desc:
                    return True
            if len(mrs) < 100:
                return False
            page += 1
    except Exception as exc:  # noqa: BLE001
        log(f"gitlab dup-check failed ({exc}); fail-open (forwarding)")
        return False


def _open_mr_count() -> int:
    """Count OPEN remediation MRs on the target repo (those carrying the agent's
    ``Incident-Component:`` marker). Returns -1 when GitLab is not configured, so the
    caller treats the ceiling as disabled. Fail-open on error (returns -1) — the
    ceiling must never block a real incident because of a transient GitLab blip."""
    if not (GITLAB_API_URL and GITLAB_TOKEN and GITLAB_MR_PROJECT):
        return -1
    try:
        from urllib.parse import quote
        url = f"{GITLAB_API_URL}/projects/{quote(GITLAB_MR_PROJECT, safe='')}/merge_requests"
        count = 0
        page = 1
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
                break
            for mr in mrs:
                if "incident-component:" in (mr.get("description") or "").lower():
                    count += 1
            if len(mrs) < 100:
                break
            page += 1
        return count
    except Exception as exc:  # noqa: BLE001
        log(f"open-MR count failed ({exc}); treating ceiling as disabled")
        return -1


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
    # A2A/JSON-RPC surfaces APPLICATION-level failures (e.g. the agent's §7.1
    # readiness gate raising AgentNotReadyError, or any execution error) as an
    # HTTP 200 carrying a JSON-RPC `error` member or a terminal `failed`/`rejected`/
    # `canceled` task state — NOT as a 4xx/5xx. So raise_for_status() alone would let
    # a refused/failed incident look "forwarded", the message would be deleted, and
    # the incident silently dropped — defeating the readiness gate AND the circuit
    # breaker. Inspect the body so a genuine failure propagates to the caller, which
    # leaves the message on the queue (NACK -> SQS redelivery -> DLQ after
    # maxReceiveCount) and counts toward the breaker.
    try:
        payload = r.json()
    except ValueError:
        return True  # 200 with a non-JSON body: nothing actionable to fail on
    if isinstance(payload, dict):
        if payload.get("error"):
            err = payload["error"]
            msg = err.get("message", err) if isinstance(err, dict) else err
            raise RuntimeError(f"agent returned JSON-RPC error: {msg}")
        result = payload.get("result")
        if isinstance(result, dict) and result.get("kind") == "task":
            state = (result.get("status") or {}).get("state", "")
            if state in {"failed", "rejected", "canceled", "unknown"}:
                raise RuntimeError(f"agent task ended in '{state}' state (not forwarded)")
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
    global _cb_failures, _cb_open_until
    if not QUEUE_URL:
        log("FATAL: SQS_QUEUE_URL not set")
        return 2
    sqs = boto3.client("sqs", region_name=REGION)
    log(
        f"polling {QUEUE_URL} -> {AGENT_A2A_URL} "
        f"(dedup {DEDUP_TTL}s, open-MR ceiling {OPEN_MR_CEILING}, "
        f"circuit-breaker {CB_FAILURE_THRESHOLD} fails/{CB_COOLDOWN}s)"
    )
    while True:
        # Circuit breaker: while OPEN, do not receive/forward — leave messages on the
        # queue (bounded by the SQS redrivePolicy -> DLQ) until the cooldown elapses.
        now = time.time()
        if now < _cb_open_until:
            time.sleep(min(_cb_open_until - now, POLL_WAIT))
            continue
        try:
            resp = sqs.receive_message(
                QueueUrl=QUEUE_URL,
                MaxNumberOfMessages=1,
                WaitTimeSeconds=POLL_WAIT,
                # Hide the message for the full agent-processing budget so it is NOT
                # redelivered mid-RCA (the old 90s floor was shorter than one RCA and caused
                # duplicate forwards). Kept >= the queue's own visibilityTimeout (360s). A
                # message the agent can never process is redelivered up to the queue's
                # maxReceiveCount, after which the SQS redrivePolicy parks it in the DLQ — so
                # the consumer never loops forever on a poison pill.
                VisibilityTimeout=max(AGENT_TIMEOUT + 60, 360),
                AttributeNames=["ApproximateReceiveCount"],
            )
        except Exception as exc:  # noqa: BLE001
            log(f"receive error: {exc}; backing off 10s")
            time.sleep(10)
            continue
        for msg in resp.get("Messages", []):
            rh = msg["ReceiptHandle"]
            rc = int(msg.get("Attributes", {}).get("ApproximateReceiveCount", "1"))
            if rc > 1:
                log(f"redelivery #{rc} of this message (SQS redrivePolicy parks it in the DLQ after maxReceiveCount)")
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
                if OPEN_MR_CEILING > 0:
                    open_mrs = _open_mr_count()
                    if open_mrs >= OPEN_MR_CEILING:
                        log(
                            f"open-MR CEILING reached ({open_mrs} >= {OPEN_MR_CEILING}); NOT forwarding "
                            f"subject={subj} — backpressure, resolve/close open incident MRs. Message "
                            f"left on queue (DLQ after maxReceiveCount)."
                        )
                        _seen.pop(subj, None)  # don't consume the dedup slot
                        handled = False        # keep the message on the queue
                        continue
                try:
                    _forward(alert)
                    _cb_failures = 0  # a success resets the breaker
                    log(f"forwarded incident {fp} (subject={subj})")
                except Exception as exc:  # noqa: BLE001
                    _cb_failures += 1
                    log(f"forward FAILED {fp} (consecutive failures {_cb_failures}): {exc}")
                    _seen.pop(subj, None)  # allow retry
                    handled = False
                    if _cb_failures >= CB_FAILURE_THRESHOLD:
                        _cb_open_until = time.time() + CB_COOLDOWN
                        log(
                            f"CIRCUIT BREAKER OPEN after {_cb_failures} consecutive failures; pausing "
                            f"forwarding for {CB_COOLDOWN}s (messages stay on the queue)"
                        )
                        break  # stop processing the rest of this batch
            # delete only if every firing alert was handled (or none firing)
            if handled:
                try:
                    sqs.delete_message(QueueUrl=QUEUE_URL, ReceiptHandle=rh)
                except Exception as exc:  # noqa: BLE001
                    log(f"delete error: {exc}")


if __name__ == "__main__":
    sys.exit(main())
