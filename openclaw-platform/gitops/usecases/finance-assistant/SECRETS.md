# Secret-handling runbook — finance-assistant

## Why this exists

On 2026-04-25, a user asked the finance-assistant to show its environment.
The `openclaw` container dumped `LITELLM_API_KEY` and `GATEWAY_AUTH_TOKEN`
into its stdout, which landed in `kubectl logs` and CloudWatch. Root
cause: secrets were env vars on a container whose job is to run agent-
requested shell commands.

PR4 changes the design so that kind of prompt cannot leak credentials.

## What changed

| Change | File | Why |
|---|---|---|
| Secrets mounted as tmpfs files (mode 0400), not env vars | `examples/finance-assistant/sandbox.yaml` + `session-router/sandbox-template-configmap.yaml` | `env` dumps return nothing. Files are `ReadOnly` projected volumes on tmpfs — not on disk. |
| Env-strip after read | `adapter/server.js`, `adapter-configmap.yaml`, sandbox shell wrapper | Values live only long enough to render the openclaw config, then `unset` / `delete process.env.X` so child processes can't inherit them. |
| `log-redact` scrubs stdout/stderr | `adapter/log-redact.js` + inline in `adapter-configmap.yaml` | Catches any leak that slips past the other defenses. Patterns: `sk-*`, `AKIA/ASIA*`, JWTs, long hex tokens. |
| IRSA for Bedrock (already in place) | `terraform/iam.tf` → `aws_eks_pod_identity_association.litellm` | LiteLLM → Bedrock uses pod-identity; no AWS creds in env at any point. |
| Guardrail credential-shape filter | `terraform/guardrail-overlay.tf` | Blocks model output containing `sk-`, `AKIA`, RSA/OpenSSH headers. Belt and braces. |
| Narrow RBAC on router | `examples/finance-assistant/session-router/k8s/deployment.yaml` | Router has no `secrets` verb. It cannot read the secrets it orchestrates around. |

## Rotation runbook

When a secret is (or might be) leaked:

1. **Rotate LiteLLM key.**
   ```
   kubectl -n litellm exec -it litellm-0 -- litellm-cli keys rotate --key-alias openclaw
   kubectl -n finance-assistant patch secret finance-litellm-key \
     --type merge -p "{\"stringData\":{\"api-key\":\"$NEW_KEY\"}}"
   ```
   Secret rollout is immediate — the tmpfs projected volume picks up
   the new value within ~60s (kubelet sync period). Sandboxes pick up
   the new key on next pod restart; force-rotate active sessions with
   `kubectl rollout restart` on the router (which invalidates the
   per-user sandbox pods on next request).

2. **Rotate gateway auth token.**
   ```
   NEW_TOKEN=$(openssl rand -hex 24)
   kubectl -n finance-assistant patch secret openclaw-gateway-auth \
     --type merge -p "{\"stringData\":{\"token\":\"$NEW_TOKEN\"}}"
   kubectl -n finance-assistant rollout restart deploy/finance-session-router
   kubectl -n finance-assistant delete sandbox -l finance.x-k8s.io/user-suffix
   ```

3. **Purge logs.**
   Identify the CloudWatch log group for the sandbox containers:
   ```
   aws logs describe-log-groups --log-group-name-prefix /aws/eks/openclaw-eks
   ```
   Delete the affected stream (not the group) with retention-aware intent:
   ```
   aws logs delete-log-stream --log-group-name "$GROUP" --log-stream-name "$STREAM"
   ```
   If the leak was caught by `log-redact`, no CloudWatch purge is
   needed — the raw value never reached stdout.

4. **Review GuardDuty + CloudTrail.**
   Check for anomalous `GetSecretValue` or Bedrock invocations during
   the exposure window. LiteLLM's Pod Identity role is the only path
   to Bedrock — any call with a different principal is suspicious.

## Invariants a reviewer should check

- No `secretKeyRef` appears in any `env:` block under
  `examples/finance-assistant/**`. All secrets are file-mounted.
- `runAsNonRoot: true` and `capabilities.drop: [ALL]` are set on
  every container that touches a secret mount.
- Router `Role` has no `secrets` verb — only `sandboxes`, `services`,
  `persistentvolumeclaims`, and `pods` (get/list).
- NetworkPolicy denies egress from sandboxes to anywhere except
  `litellm:4000` and `kube-dns:53`.
- Bedrock guardrail word policy contains the credential-shape filters
  in `terraform/guardrail-overlay.tf`.

## What we explicitly did NOT do

- **Did not move the agent runtime out of kata.** Keeping the whole
  agent+tool plane inside the VM boundary is the core OpenClaw security
  invariant — a compromised LLM can only affect one user's VM.
- **Did not replace the static gateway token with a short-lived JWT.**
  That's planned for a follow-up; it requires an openclaw gateway
  feature flag we haven't validated in this version.
- **Did not add JWKS verification** to the router. The ALB signs
  `x-amzn-oidc-data` before forwarding and the NetworkPolicy forbids
  non-ALB ingress, so spoofing is blocked at the network layer.
  Add JWKS if the ALB auth chain is ever removed.
