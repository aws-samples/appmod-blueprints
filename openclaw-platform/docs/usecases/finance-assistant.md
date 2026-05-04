# Finance Assistant

Per-user AI financial reasoning assistant running in a Kata VM. Cognito direct-API auth for sign-in/sign-up (not ALB Cognito integration), Server-Sent Events for streaming chat, persistent EFS-backed `/workspace` so context survives across sessions.

## Flow

```mermaid
sequenceDiagram
    autonumber
    participant U as Browser
    participant ALB as ALB (HTTPS)
    participant UI as finance-ui<br>(Next.js)
    participant C as Cognito User Pool<br>(pre-signup Lambda:<br>@amazon.com only)
    participant R as finance-session-router
    participant K as Kubernetes API
    participant S as finance-sandbox-<hash><br>(kata-qemu pod)
    participant O as openclaw gateway<br>(:18789 in pod)
    participant A as adapter sidecar<br>(:18790 in pod)
    participant L as LiteLLM
    participant B as Bedrock Guardrail<br>+ Claude Haiku 4.5
    participant EFS as EFS /workspace<br>subPath=<user-suffix>

    rect rgb(240,248,255)
    Note over U,C: Sign-in / sign-up (auto-confirmed for @amazon.com)
    U->>ALB: POST /api/auth/signin
    ALB->>UI: /api/auth/signin
    UI->>C: InitiateAuth (USER_PASSWORD_AUTH)
    C-->>UI: id_token + refresh_token
    UI-->>U: Set fa_session cookie (JWT: sub+email, <1.5KB)
    end

    rect rgb(245,255,245)
    Note over U,S: Warmup fires on sign-in success (fire-and-forget, @amazon.com only)
    U->>UI: POST /api/warmup
    UI->>UI: verify fa_session, re-check email domain == amazon.com
    UI->>R: POST /warmup (x-amzn-oidc-data shaped header)
    R->>R: hash(sub) → user-suffix
    R->>K: ensure PVC + Sandbox + Service (with retry on transient errors)
    Note over K,S: Karpenter provisions kata-nested node if none available
    S->>EFS: mount subPath=<user-suffix>
    R-->>UI: 200 {status: "ready"}
    end

    rect rgb(255,250,240)
    Note over U,B: Chat turn
    U->>UI: POST /api/chat (SSE)
    UI->>R: POST /chat (x-amzn-oidc-data shaped header)
    R->>R: find existing Sandbox (or create — idempotent)
    R-->>UI: status: provisioning → ready → thinking
    R->>A: HTTP POST /chat (SSE)
    A->>O: loopback :18789 (openclaw agent --session-id)
    O->>L: /v1/chat/completions (OpenAI compat)
    L->>B: InvokeModel + Guardrail
    B-->>L: stream tokens
    L-->>O: stream tokens
    O-->>A: reply (whole-reply JSON in 2026.5.2)
    A-->>R: SSE (heartbeat 10s, secret redact)
    R-->>UI: SSE
    UI-->>U: stream tokens + per-message timestamp + response-time
    end

    Note over S,EFS: On idle>30m, reaper deletes Sandbox + Service.<br>EFS PVC persists. Next sign-in triggers warmup → Sandbox re-mounts same EFS subPath.
```

## Per-user lifecycle

1. **Sign-up (`@amazon.com` only)**: Cognito pre-signup Lambda rejects any other email domain and auto-confirms amazon addresses (no email code). UI then auto-signs the user in and redirects to `/chat`.
2. **Warmup on sign-in**: `AuthModal` fires `POST /api/warmup` fire-and-forget. The server-side route double-checks `email.endsWith("@amazon.com")` before calling the router. Router ensures PVC + Sandbox + Service exist, waits for pod Ready, returns 200. By the time the user types, the Kata pod is up.
3. **First request from user X**: router hashes `sub` claim into 10-hex `suffix`. Creates `PersistentVolumeClaim finance-workspace-<suffix>` (EFS RWX) and `Sandbox finance-sandbox-<suffix>` from a template ConfigMap. Karpenter provisions a kata node if needed. Pod starts, mounts EFS at `/workspace` with `subPath=<suffix>`. openclaw gateway boots, reads its rendered config, binds `:18789`.
4. **Subsequent requests**: router finds existing Sandbox, proxies SSE stream directly.
5. **Idle > 30 min**: reaper CronJob deletes the Sandbox. EFS PVC is kept. `goals.md`, `snapshot.md`, `scenarios/*.md`, `decisions.md`, `questions.md`, and openclaw's `sessions/*.jsonl` all remain.
6. **User returns**: `/chat` page useEffect also fires a defensive warmup so the Sandbox rebuilds in the background before they type. All EFS content is still there.

## What's in /workspace

| File | Purpose |
|---|---|
| `goals.md` | User-stated financial goals, horizon, priorities |
| `snapshot.md` | Self-reported financial picture, dated |
| `scenarios/*.md` | Saved scenario models |
| `decisions.md` | Log of material decisions the user made |
| `questions.md` | Open items for a licensed pro |
| `sessions/*.jsonl` | openclaw chat history (cross-turn memory) |

Note: UI chat history (timestamps + response-time) is additionally persisted client-side in `localStorage` keyed on Cognito `sub` for fast page-load render; the server-side transcript on EFS is the source of truth.

## Customize the system prompt

Edit `gitops/usecases/finance-assistant/system-prompt-configmap.yaml`. It is written into the gateway's `openclaw.json` as `agents.defaults.systemPromptOverride` (not as a BOOT.md file — that caused the agent to greet each user with an identity-bootstrap preamble on every turn). `skipBootstrap: true` prevents openclaw from injecting its own workspace-bootstrap context. ArgoCD reconciles and the next pod boot reads the new prompt. Existing workspaces are preserved.

## Security posture

- Kata-qemu VM isolation (own kernel)
- Non-root, readOnlyRootFilesystem where possible, all caps dropped, seccomp RuntimeDefault
- NetworkPolicy: egress only to litellm:4000 and kube-dns:53
- Secrets via tmpfs projected volume, mode 0400 (no env vars → never show in `env`)
- Adapter redacts `sk-*`, `AKIA*`, JWTs, hashes, base64 blobs from every stream
- Bedrock Guardrail enforces PII anonymization + content filtering
- LiteLLM → Bedrock via Pod Identity (no IAM keys at rest)
- **Three fences against non-`@amazon.com` provisioning**: Cognito pre-signup Lambda, client-side check in `AuthModal.kickWarmup()`, server-side check in `/api/warmup` route.
- **Session cookie discipline**: `fa_session` JWT carries only `sub` + `email` (stays under 1.5KB) — never the Cognito `id_token`/`refresh_token` (blowing past Chromium's 4KB limit, cookie silently dropped).

## Troubleshooting

```bash
# see all user sandboxes
kubectl get sandbox -n finance-assistant

# router logs (routing decisions, creation events, warmup calls)
kubectl logs -n finance-assistant -l app=finance-session-router --tail=50

# a specific user's sandbox
kubectl logs -n finance-assistant finance-sandbox-<suffix> -c openclaw --tail=50
kubectl logs -n finance-assistant finance-sandbox-<suffix> -c adapter  --tail=50

# LiteLLM health
kubectl get pods -n litellm
kubectl logs -n litellm -l app.kubernetes.io/name=litellm --tail=30
```
