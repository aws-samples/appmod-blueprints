# Per-user Sandbox isolation

One kata-qemu `Sandbox` + dedicated `PersistentVolumeClaim` per
authenticated Cognito user. No more shared workspace; no more
cross-user prompt-injection read of another user's `goals.md`.

## Components

| Path | Role |
|---|---|
| `server.js` | Reads `x-amzn-oidc-data` (JWT signed by the ALB after Cognito auth), hashes `sub` → 10-char suffix, ensures `finance-sandbox-<suffix>` + `finance-workspace-<suffix>` exist, waits for Ready, proxies the SSE chat stream. |
| `package.json` | `@kubernetes/client-node` only. No LLM/aws-sdk dependencies — router never talks to Bedrock or reads secrets. |
| `sandbox-template-configmap.yaml` | The template the router clones per user. Pulled from ConfigMap at runtime so updates don't require a router image rebuild. |
| `k8s/deployment.yaml` | Router Deployment + Service + SA + Role (CRUD on `sandboxes`, `services`, `persistentvolumeclaims` in-namespace only). Two replicas. |
| `k8s/reaper-cronjob.yaml` | Every 10 min: delete Sandbox + Service + PVC when `finance.x-k8s.io/last-seen` is older than `IDLE_TTL_SECONDS` (default 1800s). |
| `render.sh` | Inlines `server.js` + `package.json` into the two ConfigMaps → `k8s/deployment.rendered.yaml`. |

## Trust and isolation invariants

- Router is the only tenant-aware process. Holds **no LLM key, no Bedrock creds**.
- Router's RBAC is scoped to three resource types in one namespace. No secrets access, no pod/exec, no cluster scope.
- Per-user sandbox selector (`app=finance-sandbox-<suffix>`) means one user's Service cannot match another user's pod.
- NetworkPolicy: only the router can reach a per-user sandbox on :18790. Direct UI→sandbox blocked.
- Workspace files (`goals.md`, `snapshot.md`, …) are in a per-user PVC. Filesystem boundary, not just VM boundary.
- `last-seen` annotation stores a **hash** of the sub, not the sub itself — debuggable without PII.

## Request flow

```
browser
  → ALB (Cognito auth, signs x-amzn-oidc-data)
  → finance-ui (ADAPTER_URL=finance-session-router:18790)
  → finance-session-router  ← holds no secrets, narrow RBAC
       ├─ ensure PVC/Sandbox/Service for user-suffix
       ├─ wait Ready (heartbeat SSE)
       └─ proxy /chat to finance-sandbox-<suffix>:18790
  → kata-qemu VM per user
  → openclaw gateway → LiteLLM → Bedrock
```

## Build / deploy (no deploys yet — staged)

```
cd examples/finance-assistant/session-router
./render.sh
kubectl apply -f sandbox-template-configmap.yaml
kubectl apply -f k8s/deployment.rendered.yaml
kubectl apply -f k8s/reaper-cronjob.yaml
```

The old shared `Sandbox` (`finance-assistant/finance-assistant`) can be
deleted after cutover; no migration of the shared workspace is planned
(ephemeral).

## Known follow-ups

- **Warm pool** for cold-start elimination. Cold boot of a kata-qemu Sandbox is 3–8s today; gate this with k6 numbers first. Tier-2 improvement, not blocker.
- **Image-baked router** instead of `npm install` at container start; currently the ConfigMap pattern matches the adapter, but a purpose-built image is faster and more auditable.
- **JWKS verification** inside the router in case the ALB auth is ever removed; we currently trust `x-amzn-oidc-data` because the ALB signs it before forwarding.
