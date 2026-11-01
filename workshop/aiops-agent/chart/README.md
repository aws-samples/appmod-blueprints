# aiops-agent (addon chart)

GitOps-managed form of the PEEKS read-only platform-engineering agent — the whole OAP
Strands agent stack as **one** KubeVela `Application`:

- `aiops-agent` (agent) — the agent brain (Bedrock via bifrost, 2-mode)
- `skills-mcp` — PEEKS `.kiro/skills` served to the agent
- `eks-read-mcp` — read-only EKS MCP (supergateway → awslabs eks-mcp-server)
- `chat-ui` — Keycloak-gated A2A chat front-end
- `aiops-agent-memory` — AgentCore session memory (Crossplane `bedrockagentcore` provider)
- incident bridge (SNS/SQS + AMP `AlertManagerDefinition` + `incident-bridge`) — autonomous-remediation demo

It renders `files/aiops-agent-app.yaml` via `.Files.Get | replace` so the embedded
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
`gitlab-mcp`. The `agent` component pins `imageRegistry/strands-agent:imageTag`
(carries the configurable-`max_tokens` fix — OAP [#34](https://github.com/awslabs/open-agentic-platform/issues/34)/[#35](https://github.com/awslabs/open-agentic-platform/pull/35)),
so `MAX_TOKENS` takes effect on a fresh deploy. Override `imageRegistry`/`imageTag` in the
fleet-config overlay to use your own registry.

### Per-component overrides + incident-bridge pin (deploy consigne)

`imageRegistry`/`imageTag` are the **global** default for all 6 components. You can also pin a
**single** component to a different registry/tag without moving the others, via
`.Values.images.<component>.{registry,tag}` (empty ⇒ inherit the global). Components:
`skillsMcp, agent, eksMcp, gitlabMcp, chatUi, incidentBridge`. Through the appset each is driven
by a cluster-secret annotation `aiops_agent_img_<component>_{registry,tag}`.

> **⚠ incident-bridge MUST run v1.1, not v1.** The contextId-sanitize fix (`poller.py`, avoids
> the AgentCore `sessionId` `ValidationException` that makes **every** autonomous incident fail)
> is **baked into the image** — the branch source alone is not enough at runtime. The public
> `seb-demo/incident-bridge:v1` tag predates the fix; **`v1.1` carries it**. On this integration
> branch the appset therefore **defaults `incidentBridge.tag` to `v1.1`** (the other 5 stay on the
> global `:v1`), so a fresh deploy is correct with no manual step. If you publish your own
> incident-bridge image, override it with the `aiops_agent_img_incidentbridge_tag` annotation (or
> `images.incidentBridge` in the overlay). Alternatively pin the **whole** set with global
> `imageTag: v1.1` (all 6 are published at `v1.1` on `seb-demo`).

> This chart is the **single GitOps source of truth** for the agent Application. The
> former imperative standalone bundle (`deploy/aiops-agent-app.yaml` + `BUNDLE.md`,
> single `kubectl apply`) has been **removed** to avoid a divergent second copy of the
> manifest — the canonical manifest now lives only at `chart/files/aiops-agent-app.yaml`.

## Enable / disable (default OFF)

Gated by the `enable_aiops_agent` cluster-secret label (registry `platform.yaml` selector
`enable_aiops_agent In ['true']`). That label is **not** written by hand — it is emitted by
the `platform-charts/fleet-secret` chart from the `enabledAddons` map and projected onto the
ArgoCD cluster secret by the on-cluster ExternalSecret (`creationPolicy: Merge`), exactly like
`backstage`/`keycloak`/`devlake`. So aiops-agent is toggled the same way as every other
platform addon: via `enabled-addons.yaml`, not via the RGD or a manual `kubectl label`.

Default is **OFF** — the base solution sets no `aiops_agent` flag (so no label), and the
workshop overlay ships `aiops_agent: false`. The registry entry itself is upstream in
`gitops/addons/registry/platform.yaml`; an overlay never copies it. To enable on the hub for a
deployment, flip it to `true` in the **fleet-config overlay** (no platform-repo edit):

```yaml
# <fleet-config>/overlays/environments/control-plane/enabled-addons.yaml
enabledAddons:
  aiops_agent: true
```

The fleet-secret ESO re-projects `enable_aiops_agent: 'true'` onto the hub cluster secret, the
addons ApplicationSet generates the `aiops-agent` Application, and ArgoCD syncs it. To remove:
set it back to `false` (or drop the key) — the label disappears and the Application is pruned.

> **Non-workshop fleet-config:** flipping `aiops_agent: true` alone deploys the agent and its
> `agent-access` AccessEntries (mapping `aiops-agent-role` into the `aiops-agent-cluster-read`
> group), but the group itself still needs the `aiops-agent-rbac` registry entry (see
> [Cluster read access](#cluster-read-access-rbac) below) — AmazonEKSViewPolicy alone 403s on
> nodes and on every CRD. The workshop's own fleet-config
> (`workshop/overlay/overlays/environments/control-plane/overrides.yaml`) already carries that
> entry, so the workshop path works with `aiops_agent: true` alone. A consumer running the
> solution directly (not through the workshop fleet-config) must copy that same
> `aiops-agent-rbac` block — unchanged — into its own `overlays/environments/<env>/overrides.yaml`.

## Cluster read access (RBAC)

Cluster reads go through `eks-read-mcp` only. It has its **own** ServiceAccount
(`eks-read-mcp`) and Pod Identity role (`<hub>-eks-read-mcp-<hash>-role`, from the
`aws-service-identity` trait and the platform's per-cluster naming rule, recomputed in
`templates/_helpers.tpl`), which carries only the `eks-read-access` policy. The
agent's role (`<hub>-aiops-agent-<hash>-role`) keeps only the AgentCore memory policy and
has no EKS access entry. The read identity is read-only on every fleet cluster through two layers:

- the AccessEntries associate `AmazonEKSViewPolicy` (namespaced built-ins) and map the
  role into the Kubernetes group `aiops-agent-cluster-read`. The hub entry is the
  `agent-access` component; the spoke entries come from the `aiops-agent-spoke-access`
  ApplicationSet (`templates/spoke-access.yaml`), one per spoke cluster secret on this hub
  with its real `aws_cluster_name` and region (`aws_region`, else the hub's), rendered
  from `../access-chart`. Nothing to configure; a hub without spokes gets none. These
  AccessEntry objects (namespace `aiops-agent` on the hub) are also how the agent learns
  the spoke names: eks-mcp-server has no tool that lists EKS clusters, so the prompt tells
  it to list them with `list_k8s_resources` and read `spec.clusterName`;
- the `aiops-agent-rbac` addon (`../rbac-chart`, registry entry in the workshop overlay
  `overrides.yaml`) installs a read-only `ClusterRole`/`ClusterRoleBinding` for that group
  on the hub **and** every spoke: nodes, namespaces, events, CRDs, `argoproj.io`
  Applications/ApplicationSets/AppProjects/Rollouts, ACK `*.services.k8s.aws`, `kro.run`,
  Karpenter/Auto Mode node objects. get/list/watch only — no Secrets, no ConfigMaps, no
  write verbs.

The IAM policy `eks-read-access` adds `eks:ListInsights`/`eks:DescribeInsight` on top of
the discovery calls.

`eks-read-mcp` hardening, in the manifest:

- the server is started with an explicit `--no-allow-write` (container `command`, which
  repeats the image ENTRYPOINT);
- the image is pinned by digest (`images.eksMcp.tag: v1@sha256:…`). If you override
  `imageRegistry` (or `images.eksMcp.registry`), also set `images.eksMcp.tag`: the default
  digest only exists in the default registry;
- the `eks-read-mcp-tool-access` AgentgatewayPolicy (`backend.mcp.authorization`,
  `Require`) is a tool allow-list: `tools/list` and `tools/call` see only the read tools
  plus `manage_k8s_resource` (its `read` operation; the others stay refused by the server
  flag and by `AmazonEKSViewPolicy`). Add a tool there if a new server version adds one.

> Upgrade note: an install that ran the per-cluster role names with the former inline
> spoke entries (`<role>-spoke-dev`/`-prod` in `agent-access`) and then moves to these
> ApplicationSet entries (`<role>-<cluster>`) has two CRs for the same (cluster,
> principal), which is one AWS entry for ACK. When KubeVela deletes the old CR, ACK
> deletes that AWS entry and the new CR only recreates it at its next drift resync. Ship
> both changes together; an install caught in between gets its spoke access back by
> deleting the new AccessEntry CRs (ArgoCD recreates them at once). With eks-read-mcp as
> the principal (above) the old and new entries name different roles, so an install that
> moves straight to this version is not affected.

> Known limitation: one identity serves both the autonomous RCA path and the interactive
> chat, so this cluster-wide read also applies to the chat until the two-agent RBAC split.

## Per-cluster overrides (fleet-config overlay)

The appset auto-adds `overlays/clusters/<cluster>/aiops-agent/values.yaml` (last wins). Example:

```yaml
imageRegistry: "<your-account>.dkr.ecr.<region>.amazonaws.com/<your-ecr-namespace>"
imageTag: "prod-2026-09"
gitlabDomain: "gitlab.mycorp.internal"   # gitlab-mcp GITLAB_API_URL host
```

## Forge variants (GitLab / no forge)

`files/aiops-agent-app.yaml` is a **forge-neutral core**: each `REPLACE_FORGE_<SLOT>` token in
it is filled from `files/forge/<forge>/<slot>.txt` before the other `REPLACE_*` tokens. The
forge is **derived**, there is no parameter for it (`templates/_helpers.tpl`
`aiops-agent.forge`), from two values the registry entry already injects:

| `gitlabDomain` (`gitlab_domain_name`) | host of `fleetRepoUrl` | forge |
|---|---|---|
| set | equal to `gitlabDomain` (case-insensitive, port ignored), or no `fleetRepoUrl` | `gitlab` |
| set | another host (e.g. `github.com`) | `none` |
| empty | any | `none` |

- **`gitlab`** (the workshop): `files/forge/gitlab/` holds the original text byte for byte, so
  the render is unchanged: `gitlab-mcp` + its `gitlab-mcp-token` ExternalSecret, the
  incident-bridge open-MR dup-check env (`GITLAB_*`), and the prompt rules for opening MRs.
- **`none`** (e.g. an appmod install whose fleet repo is on GitHub, or no fleet repo): no
  `gitlab-mcp`, no token ExternalSecret. The agent's `mcpServers` are
  `skills-mcp` + `eks-read-mcp` only. That list is what decides readiness (the OAP agent's
  `/ready` requires every configured server; `MCP_REQUIRED_SERVERS` is not read), so the agent
  becomes Ready without a forge. Its prompt says it has no write tool and must give each fix
  as a file path plus a minimal unified diff for a human to apply.
- **Both variants** render the incident path from the core (IAMRoleSelectors incl. the eks
  one the AccessEntries need, ACK IAM/SNS/SQS, `AmpIncident`, `incident-bridge`). It does not
  need GitLab: the bridge's open-MR dup-check and ceiling are fail-open when `GITLAB_*` is
  unset (slot `BRIDGE_ENV`), and the agent answers an incident with a text diff in the none
  variant. Keeping it in both variants is also what makes a variant switch safe: a GitLab ->
  none switch only GCs the `gitlab-mcp` objects (no finalizer-bearing ACK/kro CR). Removing the
  incident path in the same GC pass as its IAMRoleSelectors left the ACK CRs stuck in deletion,
  with their AWS resources still present.

A GitLab install without the bot token (`aiops_agent_git_token`) still renders the GitLab
variant; making that case fail-soft is a separate change.

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

Validated live: `externalRef` + CEL resolve the real `ws-…` id, and the
RGD compiles to `Active`/`GraphAccepted`.

## Values

| key | source annotation | notes |
|---|---|---|
| `imageRegistry` | `aiops_agent_image_registry` | default `public.ecr.aws/seb-demo` |
| `imageTag` | `aiops_agent_image_tag` | default `v1` |
| `images.<component>.{registry,tag}` | `aiops_agent_img_<component>_{registry,tag}` | per-component override; empty ⇒ inherit global. `incidentBridge.tag` defaults to `v1.1` (see Images) |
| `accountId` | `aws_account_id` | required |
| `clusterPrefix` | `resource_prefix` | required |
| `cloudfrontDomain` | `ingress_domain_name` | chat-ui ingress host |
| `gitlabDomain` | `gitlab_domain_name` | gitlab-mcp `GITLAB_API_URL` host (PAT via ESO); with `fleetRepoUrl` it selects the forge variant (see Forge variants) |
| `fleetRepoUrl` | `overlay_repo_url`, else `fleetRepoURL` if ≠ `addonsRepoURL` | **derived** by the registry entry (same resolution as `gitops/bootstrap/addons.yaml` `$overlay`); the chart strips scheme+host and `.git` to get the MR project. Empty ⇒ bridge dup-check off (fail-open) |
| `gitlabMrProject` | — | **deprecated** explicit MR-project override; wins over `fleetRepoUrl` when set |
