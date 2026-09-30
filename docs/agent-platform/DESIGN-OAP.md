# OAP ↔ Platform Engineering on EKS — Integration Design (peeks-agent)

> **Status:** Draft · **Version:** 1.0.0 · **Supersedes:** the historical
> [`DESIGN.md`](./DESIGN.md) (Kagent/LiteLLM + `sample-agent-platform-on-eks`
> bridge-chart design, kept for reference).
> This document describes the **current** integration: the
> [Open Agentic Platform (OAP)](https://github.com/awslabs/open-agentic-platform)
> deployed as an opt-in, GitOps-native extension of Platform Engineering on EKS
> (PEEKS / `appmod-blueprints`), plus the **`peeks-agent`** — a self-remediating
> platform agent built on top of it.

---

## 1. Executive Summary

PEEKS is a GitOps-native platform on EKS (hub + spokes, Argo CD, KubeVela,
kro + ACK/Crossplane, Backstage, Keycloak, observability). **OAP** is a modular
agentic layer — an LLM gateway, an agent gateway with identity/token exchange,
OAM ComponentDefinitions for agents and MCP servers, agent memory (Bedrock
AgentCore), sandboxes, and an observability pipeline (OpenTelemetry → Langfuse).

This design integrates OAP into PEEKS as an **opt-in addon bundle** wired through
the same Argo CD ApplicationSet machinery that drives every other PEEKS addon,
and adds **`peeks-agent`**: a concrete agent that watches the platform, performs
root-cause analysis on incidents, and opens **GitOps remediation merge requests**
— closing the loop "alert → agent → pull request → Argo CD → fix".

### Design principles

1. **Opt-in, off by default.** The whole agentic bundle is gated by a single
   umbrella flag (`enable_agent_platform`); each sub-addon has its own
   `enable_<addon>` selector. A platform-only deployment is byte-unchanged.
2. **GitOps single source of truth.** Enablement, image coordinates, and
   overrides all live in Git; Argo CD reconciles. No imperative `kubectl`.
3. **Two-repo separation of concerns.** Platform infrastructure and the
   generator chart live in `appmod-blueprints`; the agentic components (charts,
   registry, OAM definitions) live in the **OAP** repo. They are wired by a
   two-source Argo CD Application, not vendored.
4. **Provider-agnostic & workshop-agnostic.** Enablement is expressed via
   `enabled-addons.yaml` flags and cluster-secret annotations; nothing assumes a
   specific identity provider or the workshop CloudFormation.
5. **Least privilege by construction.** Each agent/MCP workload gets its own Pod
   Identity role and a narrowly scoped IAM policy emitted as a managed resource.

---

## 2. Repository Roles

| Repository | Role | Contents (relevant to this design) |
|---|---|---|
| **`appmod-blueprints`** (this repo) | Platform + generator + the agent | `platform-charts/appset-chart` (the ApplicationSet generator, Source B); `gitops/addons/charts/peeks-agent` (the PEEKS agent chart + OAM app); `gitops/addons/registry/platform.yaml` (peeks-agent registry entry); `gitops/overlays/environments/<env>/enabled-addons.yaml` (feature flags) |
| **`open-agentic-platform`** (OAP) | Agentic components (Source A) | `gitops/addons/charts/{bifrost,agent-gateway,oam-agent-components,langfuse,otel-collector,agent-sandbox*,litellm,crossplane-agentcore,gateway-api-crds,kata-nodepool}`; `gitops/addons/registry/{_defaults,gateway,observability,agentcore,sandbox}.yaml`; `gitops/bootstrap/agent-platform-app.yaml` (the two-source Application) |
| **`platform-engineering-on-eks`** (internal, GitLab) | Workshop content + IDE/CFN provisioning | Bakes the OAP git coordinates into the CFN, clones OAP on the IDE at runtime, runs `task install` → `agentic:install`. Also carries the **Bedrock model-access pre-activation** CFN custom resource (see §7). |

---

## 3. Architecture Overview

```
                        ┌──────────────────────── Hub cluster (peeks-hub) ────────────────────────┐
                        │                                                                          │
  enabled-addons.yaml   │   ┌────────────┐        cluster-secret annotations (enable_* labels)     │
  (per-env flags)  ─────┼──▶│ fleet ESO  │────────────────────────────────────────────────────┐   │
                        │   └────────────┘                                                      ▼   │
                        │                                                        ┌────────────────────────┐
                        │   Argo CD  ──────────────────────────────────────────▶│ agent-platform-addons  │
                        │                                                        │  (two-source Application)│
                        │                                                        └────────────────────────┘
                        │        Source A = OAP repo ($values: registry + charts/configs/overlays)   │
                        │        Source B = appmod platform-charts/appset-chart  (the generator)      │
                        │        globalSelectors: { enable_agent_platform: "true" }                   │
                        │                                   │                                         │
                        │        renders one ApplicationSet per enabled OAP addon ▼                   │
                        │   ┌─────────┬──────────────┬───────────────┬───────────┬─────────────────┐ │
                        │   │ bifrost │ agent-gateway│ oam-agent-    │ langfuse  │ otel-collector  │ │
                        │   │ (LLM    │ (identity /  │ components    │ (+minio,  │ (traces→langfuse│ │
                        │   │  proxy →│  token exch.)│ (OAM CDs:     │  clickhouse│  via OTLP)      │ │
                        │   │  Bedrock)│             │  agent/mcp/…) │  postgres)│                 │ │
                        │   └─────────┴──────────────┴───────────────┴───────────┴─────────────────┘ │
                        │                                   │                                         │
                        │   enable_peeks_agent ▼            │ (ComponentDefinitions consumed by)      │
                        │   ┌──────────────────────────────────────────────────────────────────────┐ │
                        │   │ peeks-agent  (KubeVela OAM Application, appmod chart)                  │ │
                        │   │  ├─ peeks-agent (type: agent, Strands)  ── LLM ─▶ bifrost ─▶ Bedrock   │ │
                        │   │  ├─ skills-mcp / eks-read-mcp / gitlab-mcp (MCP servers, tools)        │ │
                        │   │  ├─ peeks-agent-memory (agentcore-memory)                              │ │
                        │   │  ├─ chat-ui (A2A chat, exposed via CloudFront/ALB)                     │ │
                        │   │  ├─ incident-bridge (SQS poller → A2A message/send)                    │ │
                        │   │  └─ amp-incident (AmpIncident kro RGD: AlertManager + SNS/SQS)         │ │
                        │   └──────────────────────────────────────────────────────────────────────┘ │
                        └──────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. OAP Integration Wiring

### 4.1 Two-source Argo CD Application

OAP is deployed by a single Application, `agent-platform-addons`
(`open-agentic-platform/gitops/bootstrap/agent-platform-app.yaml`), that combines
two sources:

- **Source A — the OAP addon repo** (`ref: values`): supplies the registry value
  files consumed via `$values`, plus the `charts/`, `configs/` and `overlays/`
  that Argo CD resolves at sync time. Coordinates are injected at bootstrap:
  `repoURL=${REPO_URL}` (a.k.a. `OAP_REPO_URL`), `targetRevision=${REVISION}`.
- **Source B — the platform repo** (`appmod-blueprints`): the ApplicationSet
  generator chart at `platform-charts/appset-chart`, pinned via
  `${PLATFORM_REPO_URL}` / `${PLATFORM_REPO_REVISION}`. It is **not vendored** into
  OAP; every addon repo reuses this same generator.

The generator reads the OAP registry value files (low→high precedence):

```
$values/${BASEPATH}registry/_defaults.yaml       # syncPolicy, useSelectors:true, base paths
$values/${BASEPATH}registry/gateway.yaml          # bifrost, agent-gateway, gateway-api-crds
$values/${BASEPATH}registry/observability.yaml    # langfuse, otel-collector
$values/${BASEPATH}registry/agentcore.yaml        # agentcore-memory / crossplane-agentcore
$values/${BASEPATH}registry/sandbox.yaml          # agent-sandbox (+ operator / lambda)
```

### 4.2 Gating model (two levels)

- **Umbrella gate** — `valuesObject.globalSelectors.enable_agent_platform: "true"`.
  If the hub cluster-secret does not carry `enable_agent_platform`, the **entire**
  bundle is skipped.
- **Per-addon selectors** — `useSelectors: true` (from `_defaults.yaml`) makes each
  registry entry gate its own placement on an `enable_<addon>` label
  (`enable_bifrost`, `enable_agent_gateway`, `enable_oam_components`,
  `enable_langfuse`, `enable_otel_collector`, …).

### 4.3 In-cluster overlay layer (`$overlay`)

The generator renders a second `$overlay` source (highest precedence,
`ignoreMissingValueFiles: true`) fed by `${OVERLAY_REPO_URL}` /
`${OVERLAY_REVISION}` / `${OVERLAY_BASEPATH}` — normally the **fleet-config** repo.
This lets operators override any OAP addon value (image mirror, endpoints, hosts,
Secrets-Manager keys) **without committing to the OAP repo**, at:

```
$overlay/configs/<addon>/values.yaml                          # all clusters
$overlay/overlays/environments/<env>/<addon>/values.yaml      # per-env
$overlay/overlays/clusters/<cluster>/<addon>/values.yaml      # per-cluster
```

> **Override-key convention (important).** Two planes with **different** key
> conventions coexist and are not interchangeable:
> 1. **per-addon Helm value files** (`configs/<addon>/values.yaml`,
>    `overlays/clusters/<cluster>/<addon>/values.yaml`) take **raw chart values**;
> 2. the **appset-chart `overrides.yaml`** plane
>    (`overlays/environments/<env>/overrides.yaml`) takes
>    `<addon>.valuesObject/version` where `<addon>` **must be the registry
>    KEBAB key** (`external-secrets`, `metrics-server`) — a `snake_case`
>    `enable_<addon>` key here is **silently dropped** (no `namespace` field ⇒ the
>    generator skips it) and the override is a no-op.
>
> Always confirm the exact key/schema from the **ApplicationSet definition that
> consumes the file**, never by copying another file's casing.

### 4.4 Enablement flags → labels

`enabled-addons.yaml` (per environment, e.g. `overlays/environments/control-plane/`)
holds `snake_case` booleans (`agent_platform: true`, `bifrost: true`,
`langfuse: true`, `otel_collector: true`, `peeks_agent: true`, …). The hub
fleet-secret **ExternalSecret** (ESO, `creationPolicy: Owner`) emits the
corresponding `enable_*` labels/annotations onto the hub **cluster-secret**, which
the ApplicationSet selectors and the peeks-agent registry entry read.

> **Consistency rule.** `peeks_agent: true` **requires** `agent_platform`
> (+ `bifrost`, `agent_gateway`, `oam_components`) `true`. Enabling `peeks_agent`
> alone while the umbrella is off leaves the OAM ComponentDefinitions
> (`mcp-server`, `agent`, `agentcore-memory`) uninstalled → the KubeVela admission
> webhook rejects the `peeks-agent` OAM Application (`… not found`). Enable them
> together.

---

## 5. The `peeks-agent`

`peeks-agent` is the PEEKS-specific agent. Its **chart lives in this repo**
(`gitops/addons/charts/peeks-agent`), gated by `enable_peeks_agent` in the
registry (`gitops/addons/registry/platform.yaml`, wave ~8, `dependsOn` KubeVela +
the OAP `agent-platform-addons` bundle). The chart's Argo CD Application renders a
single **KubeVela OAM Application** (`files/peeks-agent-app.yaml`).

### 5.1 Components (OAM)

| Component | OAM type | Role |
|---|---|---|
| `peeks-agent` | `agent` | Strands agent. Discovers its MCP tools **once at boot** (`dependsOn` the MCP servers). LLM calls go to **bifrost** (OpenAI-compatible) → Bedrock. `MAX_TOKENS` env configurable (OAP [#34](https://github.com/awslabs/open-agentic-platform/issues/34)/[#35](https://github.com/awslabs/open-agentic-platform/pull/35)). Traits: `gateway-identity`, `aws-service-identity`. |
| `skills-mcp` | `mcp-server` | Curated remediation/skills tools. |
| `eks-read-mcp` | `k8s-objects` | Read-only EKS/fleet discovery MCP (shares the agent's Pod Identity role). |
| `gitlab-mcp` | (deploy) | Write path — branches/MRs (`supergateway` wrapping `@zereight/gitlab-mcp`), PAT via ExternalSecret. |
| `peeks-agent-memory` | `agentcore-memory` | Bedrock AgentCore persistent memory; its `memoryId` is injected into the agent (`properties.memory.config`). Optional (delete the ▶MEMORY blocks to disable). |
| `eks-read-access` | `k8s-objects` | Emits the least-privilege IAM Policy (`<app>-eks-read-access-iam-policy`) attached to the agent Pod Identity role. |
| `chat-ui` | (deploy + ingress) | A2A chat front-end, exposed via CloudFront/ALB at the ingress domain. |
| `incident-bridge` | (deploy) | Polls the incidents SQS queue, forwards each alert to the agent via A2A `message/send`. Deterministic, restart-proof open-MR dedup. |
| `amp-incident` | `AmpIncident` (kro RGD) | Provisions the AMP `AlertManagerDefinition` + SNS/SQS; reads the AMP workspace id **live** from the Crossplane AMP Workspace CR via `externalRef` (no literal id). |

### 5.2 Images & overrides

Images default to the public workshop registry (`public.ecr.aws/seb-demo`), pinned
by tag. Per-component overrides are supported (`images.<comp>.{registry,tag}`);
empty ⇒ inherit `imageRegistry`/`imageTag`. **Image coordinates are GitOps single
source of truth** (chart `values.yaml` + registry `valuesObject` in
`platform.yaml`, the latter taking precedence per component). Live cluster-secret
annotation overrides for image tags are **not** read on the current integration
branch — bump the git default in both places instead.

### 5.3 Per-deployment values

Not hardcoded — injected from cluster-secret annotations by the registry entry
(the fleet-secret/ESO stamps `resource_prefix`, `aws_account_id`, `aws_region`,
`ingress_domain_name`, `gitlab_domain_name`). The literals in `values.yaml` are
fallbacks for a standalone `helm template` only.

---

## 6. Key Data Flows

### 6.1 Autonomous incident → remediation MR

```
AMP alert (e.g. PodOOMKilled)  ──▶ SNS ──▶ SQS (<prefix>-incidents)
   │
   ▼  incident-bridge (long-poll) parses the alert, dedup-checks OPEN MRs
   ▼  A2A message/send  ──▶ peeks-agent
   ▼  RCA: read-only tools (eks-read-mcp) + skills-mcp  ── LLM ─▶ bifrost ─▶ Bedrock
   ▼  gitlab-mcp: create branch + MR on the fleet-config/overlay repo
   ▼  Argo CD reconciles the merged change → fix applied
```

The incident-bridge performs a **deterministic, restart-proof duplicate check**:
it skips forwarding when an OPEN MR already addresses the failing component
(machine marker `Incident-Component: <c>` or a component match in title/branch),
and is **fail-open** (never blocks a real incident). `gitlabMrProject` is derived
from the overlay repo URL.

### 6.2 Chat (A2A)

`chat-ui` (CloudFront/ALB) → `peeks-agent` A2A endpoint → same RCA/tool loop, for
interactive queries.

### 6.3 Tracing pipeline

```
peeks-agent ──(OTLP)──▶ otel-collector ──▶ Langfuse ──▶ ClickHouse (traces/observations)
```

**Source of truth for "are traces captured" = ClickHouse row counts** (not app
health). Two dependencies must be satisfied on a fresh env (both auto-heal on the
happy path):

- the `langfuse-otel-auth` secret must exist in the `otel` namespace (else the
  collector sends empty Basic auth → 401). It is written by the Langfuse Sync hook
  `push-otel-secret` (SA `langfuse-seed` + Pod Identity) at first successful sync.
- the Langfuse **minio** object store bucket must exist. minio images are pinned to
  the ECR mirror in the chart default (`minio.image` / `minio.mcImage`) to avoid
  upstream registry throttling; the bucket is created by the minio init on first
  healthy sync.

> On an env deployed **before** these fixes, both can be stuck (minio
> `ImagePullBackOff` blocks sync wave 0 → the `push-otel-secret` hook at a later
> wave never runs). On a **fresh** env with the pinned minio image the sync
> proceeds and both resolve automatically.

---

## 7. Provisioning & Bootstrap (PEEKS side)

- The PEEKS CloudFormation template **bakes the OAP git coordinates** as synth-time
  literals (`AGENTIC_REPO_URL` / `AGENTIC_REPO_REVISION`). The IDE clones OAP at
  runtime; `task install` → `agentic:install` renders `agent-platform-app.yaml`
  with the injected `REPO_URL`/`REVISION`/`OVERLAY_*` coordinates.
- **Leak-proof coordinate names.** Source A of `agent-platform-addons` uses
  OAP-specific variable names (`OAP_REPO_URL`/`OAP_REVISION`/`OAP_BASEPATH`) so the
  generic `REPO_URL` exported by the IDE `SETUP_SCRIPT` (for the appmod clone) does
  **not** leak into and override the OAP source. A CDK guard also unsets
  `REPO_URL`/`REPO_REVISION` before the OAP block.

### 7.1 Bedrock model access prerequisite (LLM enablement)

The agent's LLM calls reach Bedrock (Claude Sonnet 4.5) via bifrost. Because
Anthropic models are **AWS Marketplace–gated**, a principal **with Marketplace
permissions** must invoke the model once to subscribe it **account-wide** (the
"Model access" console page is retired; activation is now automatic on first
invocation, subject to Marketplace perms + the Anthropic first-time-use form).
Neither the participant nor the ops workshop role carries
`aws-marketplace:Subscribe`, so activation is handled at **provisioning** by a CFN
custom resource (in the `platform-engineering-on-eks` repo, `team-stack.ts`):

- a Lambda whose role has `aws-marketplace:Subscribe/Unsubscribe/ViewSubscriptions`
  + `bedrock:InvokeModel*` (and the agreement/FTU actions), which submits the FTU
  and invokes `Converse` once (with retry) on
  `us.anthropic.claude-sonnet-4-5-20250929-v1:0` → subscribes account-wide;
- non-fatal (always signals SUCCESS; result exposed as a stack output).

After activation, every role in the account (including the bifrost Pod Identity
role, which already has `bedrock:InvokeModel`) can invoke without Marketplace
perms. Without this, the agent 403s at the LLM step (RCA never runs, no MR, no
useful trace).

---

## 8. Security

- **Pod Identity per workload.** `peeks-agent`/`eks-read-mcp` share one role with a
  least-privilege read policy (`AmazonEKSViewPolicy`-style + the emitted
  `eks-read-access` IAM policy). `gitlab-mcp` gets a PAT via ExternalSecret.
- **AgentCore memory** attaches its own IAM policy to the agent role via the
  `aws-service-identity` trait.
- **Secrets via ESO / Secrets Manager** (`langfuse-otel-auth`, GitLab PAT, Langfuse
  keys) — never in Git.
- **Bifrost** centralizes model access; the agent never holds Bedrock creds
  directly.
- **Blast radius of remediation** is bounded to opening MRs on the fleet-config
  repo; a human still merges (Argo CD then applies). The agent's prompt enforces
  single-file, additive, dedup-checked edits.

---

## 9. Enable / Disable

**Enable** (per environment) in `enabled-addons.yaml`:

```yaml
enabledAddons:
  agent_platform: true      # umbrella
  bifrost: true
  agent_gateway: true
  oam_components: true
  langfuse: true
  otel_collector: true
  peeks_agent: true
```

Commit + push → the fleet ESO stamps `enable_*` labels → Argo CD renders the OAP
ApplicationSets and the peeks-agent OAM Application.

**Disable**: flip the same keys to `false` (umbrella `agent_platform: false`
removes the whole bundle). Core platform is unaffected.

---

## 10. Testing / Validation

- `helm template` the peeks-agent chart and the appset-chart with the OAP registry
  files (selectors on) — assert the expected ApplicationSets render only when
  `enable_agent_platform`/`enable_<addon>` are set.
- **Fresh-env E2E** (the real gate): deploy an env, then validate
  1. OAP apps `agent-platform-addons`, `bifrost`, `agent-gateway`,
     `oam-agent-components`, `langfuse`, `otel-collector` are Healthy/Synced;
  2. `peeks-agent` + `chat-ui` + the 3 MCP servers + `incident-bridge` are Running;
  3. inject a synthetic OOMKill on the incidents SQS queue → assert an MR is opened
     on fleet-config;
  4. assert traces land in ClickHouse (`SELECT count() FROM traces`).
- **Bedrock**: confirm the model-access CFN resource output is `ENABLED` and the
  agent does not 403 at the LLM step.

---

## 11. Open Items / Known Gaps

- **kro annotation-key templating** — the ALB `url-rewrite` transforms annotation
  needs a dynamic key; kro does not substitute CEL in annotation **keys** (only
  values), so path-prefix rewrite for agent/app ingress is limited pending kro
  v0.10 (tracked separately).
- **Image-override convention** — live cluster-secret image-tag annotations are a
  no-op on the current integration branch (GitOps-only); bump git defaults.
- **Teardown sweep IAM** — the workshop sweep role lacks
  `ecr:DeleteRepository`/`s3:DeleteBucket`/`logs:DeleteLogGroup`, leaving a few
  app-layer residues (ray model S3, custom ECR, EKS log groups) after teardown
  (tracked separately).

---

## 12. Glossary

- **OAP** — Open Agentic Platform (`awslabs/open-agentic-platform`).
- **bifrost** — OpenAI-compatible LLM proxy fronting Bedrock.
- **agent-gateway** — agent identity / token-exchange gateway.
- **OAM / KubeVela** — the application model; ComponentDefinitions `agent`,
  `mcp-server`, `agentcore-memory` are provided by `oam-agent-components`.
- **kro / ACK / Crossplane** — Kubernetes-native infra composition and AWS resource
  controllers used for spokes, AMP, IAM, memory, etc.
- **A2A** — agent-to-agent messaging protocol (`message/send`) used by the chat-ui
  and incident-bridge to reach the agent.
- **AMP** — Amazon Managed Service for Prometheus (alert source).

---

**Related:** [`DESIGN.md`](./DESIGN.md) (historical bridge-chart design) ·
[`COMPONENTS.md`](./COMPONENTS.md) · [`README.md`](./README.md) ·
[`TROUBLESHOOTING.md`](./TROUBLESHOOTING.md)
