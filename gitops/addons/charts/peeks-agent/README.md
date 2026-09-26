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
gitlabDomain: "gitlab.mycorp.internal"   # gitlab-mcp GITLAB_API_URL host
```

## gitlab-mcp (agent write path)

The `gitlab-mcp` component (supergateway wrapping upstream `@zereight/gitlab-mcp`,
stateful, exposed via AgentGateway at `/mcp/gitlab-mcp`) gives the agent its
branch/MR write path. The GitLab PAT is **never baked into the image** — an
ExternalSecret pulls it from Secrets Manager (`<clusterPrefix>-hub/secrets:git_token`,
the same canonical PAT the ArgoCD repo-creds use) via the `aws-secrets-manager`
ClusterSecretStore and injects it as `GITLAB_PERSONAL_ACCESS_TOKEN`. Set `gitlabDomain`
(from the `gitlab_domain_name` cluster-secret annotation) so `GITLAB_API_URL` resolves.

## AMP incident path (native — reads the Workspace CR, no id literal)

The AMP AlertManagerDefinition + SNS/SQS incident sub-graph is provisioned by the
**`AmpIncident` kro RGD** (`files/amp-incident-rgd.yaml`), which reads the AMP workspace
id **live from the Crossplane `Workspace` CR** via `externalRef` +
`${ampworkspace.status.atProvider.id}` — so there is **no `ampWorkspaceId` value and no
cluster-secret stamp**. Requirements (both shipped in the chart):

- the `AmpIncident` instance's `workspaceName` must match your AMP `Workspace` CR name
  (default `<clusterPrefix>-amp`);
- the bundled `kro-amp-workspace-reader` ClusterRole/Binding grants the kro
  capability controller (`<clusterPrefix>-hub-kro-capability-role/KRO`) read on
  `amp.aws.upbound.io/workspaces` — **without it `externalRef` is forbidden (RBAC)** and
  the instance stays `ERROR: cannot get resource workspaces`.

Validated live on peeks-e2e: `externalRef` + CEL resolve the real `ws-…` id, and the
RGD compiles to `Active`/`GraphAccepted`.

## Values

| key | source annotation | notes |
|---|---|---|
| `imageRegistry` | `peeks_agent_image_registry` | default `public.ecr.aws/seb-demo` |
| `imageTag` | `peeks_agent_image_tag` | default `v1` |
| `accountId` | `aws_account_id` | required |
| `clusterPrefix` | `resource_prefix` | required |
| `cloudfrontDomain` | `ingress_domain_name` | chat-ui ingress host |
| `gitlabDomain` | `gitlab_domain_name` | gitlab-mcp `GITLAB_API_URL` host (PAT via ESO) |
