# peeks-agent (addon chart)

GitOps-managed form of the PEEKS read-only platform-engineering agent — the whole OAP
Strands agent stack as **one** KubeVela `Application`:

- `peeks-agent` (agent-fixed) — the agent brain (Bedrock via bifrost, 2-mode)
- `skills-mcp` — PEEKS `.kiro/skills` served to the agent
- `eks-read-mcp` — read-only EKS MCP (supergateway → awslabs eks-mcp-server)
- `chat-ui` — Keycloak-gated A2A chat front-end
- `peeks-agent-memory` — AgentCore session memory (Crossplane `bedrockagentcore` provider)
- incident bridge (SNS/SQS + AMP `AlertManagerDefinition` + `incident-bridge`) — autonomous-remediation demo

It renders `files/peeks-agent-app.yaml` via `.Files.Get | replace` so the embedded
AlertManager Go-templates (`{{ .CommonLabels.alertname }}` …) are preserved verbatim and
never evaluated by Helm — only the `REPLACE_*` tokens are substituted.

## Images

Defaults to the workshop-generic **public** registry (anonymous pull), pinned by tag —
participants never build their own:

| value | default |
|---|---|
| `imageRegistry` | `public.ecr.aws/seb-demo` |
| `imageTag` | `v1` |

Published repos: `chat-ui`, `eks-mcp`, `skills-mcp`, `incident-bridge`, `strands-agent`,
`gitlab-mcp`. The `agent-fixed` component pins `imageRegistry/strands-agent:imageTag`
(carries the configurable-`max_tokens` fix — OAP [#34](https://github.com/awslabs/open-agentic-platform/issues/34)/[#35](https://github.com/awslabs/open-agentic-platform/pull/35)),
so `MAX_TOKENS` takes effect on a fresh deploy. Override `imageRegistry`/`imageTag` in the
fleet-config overlay to use your own registry.

> The imperative `platform/peeks-agent/deploy/peeks-agent-app.yaml` (single `kubectl apply`,
> private-ECR `buildspec.yaml`) is the legacy self-contained path and does **not** pin the
> strands-agent image. This chart is the GitOps source of truth; keep the two in sync.

## Enable / disable (default OFF)

Gated by the `enable_peeks_agent` cluster-secret label (registry `platform.yaml` selector
`enable_peeks_agent In ['true']`). That label is **not** written by hand — it is emitted by
the `platform-charts/fleet-secret` chart from the `enabledAddons` map and projected onto the
ArgoCD cluster secret by the on-cluster ExternalSecret (`creationPolicy: Merge`), exactly like
`backstage`/`keycloak`/`devlake`. So peeks-agent is toggled the same way as every other
platform addon: via `enabled-addons.yaml`, not via the RGD or a manual `kubectl label`.

Default is **OFF** — `peeks_agent: false` in the base
`gitops/overlays/environments/control-plane/enabled-addons.yaml`. To enable on the hub for a
deployment, flip it to `true` in the **fleet-config overlay** (no platform-repo edit):

```yaml
# <fleet-config>/overlays/environments/control-plane/enabled-addons.yaml
enabledAddons:
  peeks_agent: true
```

The fleet-secret ESO re-projects `enable_peeks_agent: 'true'` onto the hub cluster secret, the
addons ApplicationSet generates the `peeks-agent` Application, and ArgoCD syncs it. To remove:
set it back to `false` (or drop the key) — the label disappears and the Application is pruned.


## Per-cluster overrides (fleet-config overlay)

The appset auto-adds `overlays/clusters/<cluster>/peeks-agent/values.yaml` (last wins). Example:

```yaml
imageRegistry: "<your-account>.dkr.ecr.<region>.amazonaws.com/peeks-e2e"
imageTag: "prod-2026-09"
ampWorkspaceId: "ws-0123456789abcdef"   # enables the AMP incident-bridge path
```

## Values

| key | source annotation | notes |
|---|---|---|
| `imageRegistry` | `peeks_agent_image_registry` | default `public.ecr.aws/seb-demo` |
| `imageTag` | `peeks_agent_image_tag` | default `v1` |
| `accountId` | `aws_account_id` | required |
| `clusterPrefix` | `resource_prefix` | required |
| `cloudfrontDomain` | `ingress_domain_name` | chat-ui ingress host |
| `ampWorkspaceId` | `aws_amp_workspace_id` | **incident path only** — empty leaves the AlertManagerDefinition + incident IAM inert; the core agent works without it |
