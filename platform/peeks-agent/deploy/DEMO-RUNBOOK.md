# Demo Runbook — Autonomous Incident Remediation (peeks-e2e)

Narrative: **the platform observes → alerts → a read-only agent does RCA → proposes the fix
as a GitLab MR → a human merges → GitOps heals.** The agent never mutates the cluster.

> Demo/live values below are for the `peeks-e2e` environment (account `290085271972`,
> `us-west-2`). Substitute for another env.

## Access (prep before filming)
- **Agent chat**: https://d2pefdj59hxapj.cloudfront.net/peeks-agent-chat
- **GitLab**: https://d25d2ree2k4r35.cloudfront.net → "Sign in with Keycloak"
- **Login**: `user1` / `9ATAX3NLU1jefg5bOUVTcgot0RKaL2fP` (shared demo cred, not prod)
- Terminal with peeks-e2e creds + `kubectl --context peeks-e2e-hub` / `peeks-e2e-spoke-dev`

Key resources: agent `peeks-agent2` (ns `peeks-agent`, hub) · consumer `incident-bridge`
(`:carm-v2`) · SQS `peeks-agent-incidents` · AMP `ws-b9903556-cf70-4aec-9023-c2baf00f0b53`
· victim `memory-hog` (ns `demo-oomkill`, spoke-dev, GitOps app `oomkill-demo` ←
`user1/fleet-config` path `demo-oomkill/deployment.yaml`).

## 0. Pre-flight (before recording — everything green)
```bash
curl -sik https://d2pefdj59hxapj.cloudfront.net/peeks-agent-chat | head -1        # 200
kubectl --context peeks-e2e-hub -n peeks-agent get deploy incident-bridge          # 1/1
aws sqs get-queue-attributes --region us-west-2 \
  --queue-url https://sqs.us-west-2.amazonaws.com/290085271972/peeks-agent-incidents \
  --attribute-names ApproximateNumberOfMessages                                    # 0
aws amp describe-rule-groups-namespace --region us-west-2 \
  --workspace-id ws-b9903556-cf70-4aec-9023-c2baf00f0b53 --name peeks-e2e-alerting-rules \
  --query 'ruleGroupsNamespace.data' --output text | base64 -d | grep -c 'alert:' # 6
```

## Part A — The agent (read-only "brain")
1. Open the chat, login `user1`.
2. Ask: *"Run an eks-recon on spoke-dev"*, then *"list the ArgoCD applications on the hub"*.
   - Show: it uses `eks-read-mcp` across the **3 clusters**, answers in markdown, **never mutates**
     (RBAC read-only).

## Part B — Trigger a real incident (via GitOps, not by hand)
The victim is ArgoCD-managed, so the buggy change must go through Git to stick.
1. GitLab → `user1/fleet-config` → `demo-oomkill/deployment.yaml`.
2. Lower memory to force OOMKill: `resources.limits.memory: 64Mi`, `requests.memory: 32Mi`.
   Commit to `main`. (You introduce the bug via Git; the agent only reacts.)
3. ArgoCD reconciles (~1–2 min) → `memory-hog` crash-loops OOMKilled:
```bash
kubectl --context peeks-e2e-spoke-dev -n demo-oomkill get pods -w   # Restarts ↑, lastState=OOMKilled
```

## Part C — Automatic detection (the platform observes)
```bash
kubectl --context peeks-e2e-hub -n peeks-agent logs -f deploy/incident-bridge
# expected (~1–3 min after the OOMKill):
#   [incident-bridge] forwarded incident PodOOMKilled|spoke-dev|demo-oomkill|memory-hog-...|...
```
Latency = AMP scrape (~30–60s) + rule `for:1m` + AlertManager `group_wait` 30s. The JSON
carries `signal:oomkill` + a `remediation` hint.

## Part D — The agent's autonomous action (fix via MR)
The agent receives the incident, RCAs (eks-read + CloudWatch), locates the manifest in
fleet-config, and **opens a GitLab MR** raising the memory.
1. GitLab → `user1/fleet-config` → **Merge Requests**: a new `fix/oomkill-memory-hog-…` MR.
   - Show: the **diff** (limits/requests raised), body = RCA + "awaiting human approval",
     new branch, **no cluster mutation**.

## Part E — Human approves → GitOps heals
1. **Merge** the MR in GitLab.
2. ArgoCD reconciles `oomkill-demo`:
```bash
kubectl --context peeks-e2e-spoke-dev -n demo-oomkill get pods -w   # memory-hog Running, 0 restarts
```
The loop closes — the fix ships through Git, not a live agent action.

## Bonus (level-1 "any issue") — optional
Set an invalid image in `demo-oomkill/deployment.yaml` (e.g. `:doesnotexist`) → `PodImagePullError`
fires → the agent opens an MR fixing the tag. Same chain, different signal. (Rules also cover
CrashLoopBackOff / Unschedulable / PVC Pending.)

## Reset between takes
```bash
# restore healthy: re-commit demo-oomkill/deployment.yaml to 512Mi/256Mi (or merge the agent MR)
aws sqs purge-queue --region us-west-2 \
  --queue-url https://sqs.us-west-2.amazonaws.com/290085271972/peeks-agent-incidents
kubectl --context peeks-e2e-hub -n peeks-agent rollout restart deploy/incident-bridge  # re-arm 1h dedup
```

## Gotchas for recording
- **external-secrets noise**: `external-secrets-cert-controller` genuinely OOM-kills on all 3
  clusters → real incidents. Dedup (1h) + AMP `repeat_interval` (4h) limit it; **purge the queue
  right before filming**. If you see "external-secrets" MRs, that's this (a real finding).
- **Latency**: don't cut early — allow ~2–4 min from the buggy commit to `forwarded incident`,
  plus ArgoCD reconcile on merge.
- **Bifrost**: inference is keyless (`disableAuthOnInference: true`) → chat works. Don't touch
  bifrost during the demo.
- **Agent name**: live runs `peeks-agent2` (services `peeks-agent2-stable`); the manifest ships
  `peeks-agent` (the rename is deferred to a full re-apply). The consumer's `AGENT_A2A_URL` points
  at `peeks-agent2-stable` live.
