# Agents for Managing Platform on EKS — Design

> **Status:** Draft · **Version:** 1.3.0 · **Related:** the historical
> [`DESIGN.md`](./DESIGN.md) (Kagent/LiteLLM + `sample-agent-platform-on-eks`
> bridge-chart design, kept for reference).
> This document is the durable design reference for **using agents to manage a
> platform on EKS**: an agent that observes the platform, performs root-cause
> analysis on incidents, and opens GitOps remediation merge requests for a human
> to approve. The reference implementation is **`aiops-agent`**, running on
> Platform Engineering on EKS (PEEKS / `appmod-blueprints`) and built on the
> platform's agentic layer.
> Implementation PRs reference this document; this document does not track
> individual PRs.
>
> **Naming note.** This document uses **`aiops-agent`** — the functional name for
> the reference agent — matching the implementation. In
> [#926](https://github.com/aws-samples/appmod-blueprints/pull/926) the agent was
> renamed `peeks-agent` → `aiops-agent`
> ([appmod #954](https://github.com/aws-samples/appmod-blueprints/issues/954))
> **and relocated under `workshop/aiops-agent/`** (chart at
> `workshop/aiops-agent/chart`, sources under `workshop/aiops-agent/src/`). Its
> **registry entry is upstream** in `gitops/addons/registry/platform.yaml`,
> **disabled by default** (gated by `enable_aiops_agent`); an overlay only decides
> whether to deploy it (`aiops_agent: true`) — see §7 for why this reverses the
> earlier "agent-free base registry" decision. The `workshop/` path is the interim
> home of the chart. The
> enablement/registry key is `aiops_agent` / `enable_aiops_agent` — this design is
> the source implementation PRs copy the key from (§6.4, §13).

---

## 1. Background & Motivation

Platform Engineering on EKS (PEEKS) gives teams a GitOps-native internal
developer platform: a hub + spoke EKS topology reconciled by Argo CD, with
KubeVela, kro + ACK/Crossplane, Backstage, Keycloak and a managed observability
stack. It answers *"how do I build and run a golden-path platform on EKS?"*.

The next question is *"can agents help **operate** that platform?"* Operators
increasingly want agents that can triage an incident, perform read-only
root-cause analysis, and propose a GitOps-native fix for a human to approve —
turning a page of alerts into a reviewable pull request. This design answers that
question with a concrete, end-to-end reference agent for platform operations on
EKS.

Running such an agent needs an **agentic layer** on the platform: an LLM gateway,
an agent gateway with identity/token exchange, reusable agent/MCP component
definitions, agent memory, and agent-grade observability. PEEKS provides this
layer, deployed the same GitOps way as every other platform addon (opt-in and
governed, not a bolt-on). The agentic building blocks come from the
[Open Agentic Platform (OAP)](https://github.com/awslabs/open-agentic-platform),
which PEEKS consumes as modular components — but the **story here is the agent and
what it does for the platform**, not the plumbing beneath it.

---

## 2. Executive Summary

**The deliverable: `aiops-agent` — a reference agent for managing a platform on
EKS.** A concrete agent that watches the platform, performs root-cause analysis
on incidents, and opens **GitOps remediation merge requests** — closing the loop
*"alert → agent → pull request → Argo CD → fix"*. It runs in two modes:
interactive (a Keycloak-authenticated chat UI) and autonomous (event-driven RCA
triggered by observability alerts). It is intentionally small and **human-gated**
— the agent proposes, a human approves and merges. (**What enforces that gate is
spelled out in §12** — PAT scope + branch protection, not a convention.)

**The enabling layer.** `aiops-agent` is composed entirely from the platform's
**agentic building blocks** — an LLM gateway (bifrost), an agent gateway with
identity/token exchange, OAM ComponentDefinitions for agents and MCP servers,
agent memory (Bedrock AgentCore), and an observability pipeline
(OpenTelemetry → Langfuse). These components are provided by OAP and deployed
into PEEKS as an **opt-in addon bundle**, wired through the same Argo CD
ApplicationSet machinery that drives every other PEEKS addon. The agent doubles
as a **worked example** of how to build an agent on that layer.

**Scope boundary.** `aiops-agent` is the reference/showcase agent for
platform-managing agents on EKS. It *seeds* the broader idea of agent-driven
platform operations (AIOps) but does **not** claim to be a general AIOps product;
that is a larger track this design does not attempt to deliver in full. See §3
for the explicit scope boundary.

### Design principles

1. **Opt-in, off by default.** The whole agentic bundle is gated by a single
   umbrella flag (`enable_agent_platform`); each sub-addon has its own
   `enable_<addon>` selector. With the flags off, a `helm template` of the
   appset-chart renders **diff-empty** against the pre-change baseline (see §14) —
   that is the testable meaning of "a platform-only deployment is unchanged".
2. **GitOps single source of truth.** Enablement, image coordinates, and
   overrides all live in Git; Argo CD reconciles. No imperative `kubectl` in the
   steady state. *(The one place today's implementation still needs a manual
   `kubectl rollout restart` — fresh-apply tool discovery — is a known defect, not
   a design step; see §7.1 and [OAP #50](https://github.com/awslabs/open-agentic-platform/issues/50).)*
3. **Two-repo separation of concerns.** Platform infrastructure and the
   generator chart live in `appmod-blueprints`; the agentic components (charts,
   registry, OAM definitions) live in the **OAP** repo. They are wired by a
   two-source Argo CD Application, not vendored.
4. **Provider-agnostic & workshop-agnostic.** Enablement is expressed via
   `enabled-addons.yaml` flags and cluster-secret annotations; nothing assumes a
   specific identity provider or the workshop CloudFormation.
5. **Least privilege by construction.** Each agent/MCP workload gets its own Pod
   Identity role and a narrowly scoped IAM policy emitted as a managed resource.
6. **Mandatory automated policy gate, upstream of the human merge-gate.** Every
   acting agent must pass an allow/deny **guardrail agent** (fail-closed) before
   it proposes a change; the change policy is owned by one team and decoupled
   from the actors (§6.5). The gate is enforced as **agent-side wiring plus a
   forge-enforced merge-blocking check**, never as a prompt instruction —
   consistent with "the prompt is not a security boundary" (§12). Going through
   **Git** (not a live-CR patch) is what makes an approved fix durable under Argo
   CD `selfHeal` and auditable (§8.1).

---

## 3. Scope, Non-Goals & Acceptance Criteria

**In scope**

- `aiops-agent` as the **reference agent for managing a platform on EKS**:
  interactive chat mode and autonomous incident → RCA → remediation-MR mode.
- The **agentic layer** the agent needs, deployed into PEEKS as an **opt-in,
  GitOps-native addon bundle** (LLM gateway, agent gateway, OAM agent/MCP
  ComponentDefinitions, agent memory, agent observability — provided by OAP).
- The **Bedrock model-access pre-activation** needed for the agent's LLM calls
  to work on a fresh account (see §9.1).

**Non-goals (explicitly out of scope for this deliverable)**

- A general-purpose **AIOps** product. `aiops-agent` seeds the "agents operate the
  platform" direction but the broader AIOps track is a **separate initiative**.
- Replacing or re-architecting existing platform addons or the app-delivery
  modules.
- Multi-tenant agent authorization / **On-Behalf-Of identity** for the **chat**
  path — see the *Planned* status below and §15. (Note: OBO is structurally
  inapplicable to the **autonomous** path, which has no caller — see §7.0/§12.)

**Status legend.** ✅ Implemented & live-validated · 🟡 Implemented, partial /
rough edges · ⏳ Planned, not yet implemented.

| Capability | Status |
|---|---|
| OAP bundle deploys via opt-in flags; appset-chart renders diff-empty when off | ✅ |
| `aiops-agent` chat mode (Keycloak-authenticated) | ✅ |
| Autonomous incident → RCA → remediation MR | ✅ |
| Human merge-gate **enforced** (PAT scope + branch protection, not convention) | 🟡 (spelled out §12; hardening tracked [appmod #956](https://github.com/aws-samples/appmod-blueprints/issues/956)) |
| Autonomous path runs with complete toolset (readiness-gated) | 🟡 (boot-time discovery; [OAP #50](https://github.com/awslabs/open-agentic-platform/issues/50)) |
| Remediation loop closes / bounded (verify, dedup, circuit-breaker) | 🟡 (open-MR dedup only; [OAP #51](https://github.com/awslabs/open-agentic-platform/issues/51)) |
| Tracing pipeline (OTLP → Langfuse → ClickHouse) | 🟡 (fresh-env auto-heal; see §8.3) |
| Bedrock model-access pre-activation (account-wide) | ✅ |
| **On-Behalf-Of (OBO)** identity propagation in **chat** mode | ⏳ Planned (see §7.0, §15) |
| Convergence of OAP OAM components with the `appmod-service` ComponentDefinition | ⏳ Planned (see §7.4, §15) |

**Acceptance criteria (testable)**

1. With all agentic flags **off**, `helm template` of the appset-chart renders
   **diff-empty** against the pre-change baseline.
2. Enabling the flags renders the OAP ApplicationSets **and** `aiops-agent`, all
   `Healthy/Synced` on a **fresh** environment.
3. A synthetic incident (e.g. OOMKill) on the incidents queue results in an MR
   opened on the fleet-config repo (deduplicated, human-gated) — and the bot
   identity **cannot merge it itself** (§12).
4. Agent traces land in ClickHouse (row count > 0).
5. The Bedrock model-access resource reports `ENABLED`; the agent does not 403 at
   the LLM step; the id the Lambda subscribes **equals** the id bifrost routes
   (§9.1).

> The agent (chat + autonomous RCA→MR) and its agentic layer have been validated
> end-to-end on a fresh environment (self-managed account and workshop
> provisioning). OBO (⏳) is **not** part of this validation — it is a planned
> follow-up.

---

## 4. Repository Roles

| Repository | Role | Contents (relevant to this design) |
|---|---|---|
| **`appmod-blueprints`** (this repo) | Platform + generator + the agent | `platform-charts/appset-chart` (the ApplicationSet generator, Source B); `workshop/aiops-agent/chart` (the agent chart + OAM app, sources under `workshop/aiops-agent/src/` — moved under `workshop/` in [#926](https://github.com/aws-samples/appmod-blueprints/pull/926), **interim**); `gitops/addons/registry/platform.yaml` (agent registry entry — **upstream, disabled by default**, gated `enable_aiops_agent`; §7); `workshop/overlay/overlays/environments/<env>/enabled-addons.yaml` (feature flags, incl. `aiops_agent` — the overlay only decides) |
| **`open-agentic-platform`** (OAP) | Agentic components (Source A) | `gitops/addons/charts/{bifrost,agent-gateway,oam-agent-components,langfuse,otel-collector,agent-sandbox*,litellm,crossplane-agentcore,gateway-api-crds,kata-nodepool}`; `gitops/addons/registry/{_defaults,gateway,observability,agentcore,sandbox}.yaml`; `gitops/bootstrap/agent-platform-app.yaml` (the two-source Application); `gitops/addons/configs/bifrost/values.yaml` (the model route) |
| **`platform-engineering-on-eks`** (internal, GitLab) | Workshop content + IDE/CFN provisioning | Bakes the OAP git coordinates into the CFN, clones OAP on the IDE at runtime, runs `task install` → `agentic:install`. Also carries the **Bedrock model-access pre-activation** CFN custom resource (see §9). |

---

## 5. Architecture Overview

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
                        │   enable_aiops_agent ▼            │ (ComponentDefinitions consumed by)      │
                        │   ┌──────────────────────────────────────────────────────────────────────┐ │
                        │   │ aiops-agent  (KubeVela OAM Application, appmod chart)                  │ │
                        │   │  ├─ aiops-agent (type: agent, Strands)  ── LLM ─▶ bifrost ─▶ Bedrock   │ │
                        │   │  ├─ skills-mcp / eks-read-mcp / gitlab-mcp (MCP servers, tools)        │ │
                        │   │  ├─ agent-memory (agentcore-memory)                                    │ │
                        │   │  ├─ chat-ui (A2A chat, exposed via CloudFront/ALB)                     │ │
                        │   │  ├─ incident-bridge (SQS poller → A2A message/send)                    │ │
                        │   │  └─ amp-incident (AmpIncident kro RGD: AlertManager + SNS/SQS)         │ │
                        │   └──────────────────────────────────────────────────────────────────────┘ │
                        └──────────────────────────────────────────────────────────────────────────────┘
```

---

## 6. Agentic Layer Wiring

### 6.1 Two-source Argo CD Application

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

### 6.2 Gating model (two levels)

- **Umbrella gate** — `valuesObject.globalSelectors.enable_agent_platform: "true"`.
  If the hub cluster-secret does not carry `enable_agent_platform`, the **entire**
  bundle is skipped.
- **Per-addon selectors** — `useSelectors: true` (from `_defaults.yaml`) makes each
  registry entry gate its own placement on an `enable_<addon>` label
  (`enable_bifrost`, `enable_agent_gateway`, `enable_oam_components`,
  `enable_langfuse`, `enable_otel_collector`, …).

> **A third, behavioural gate.** §6.2 gates addon *placement* (what is installed,
> where). A separate **runtime** gate on an acting agent's **behaviour** — the
> guardrail agent — is defined in **§6.5**.

> **Not all pairs are independently toggleable.** The gating model presents addons
> as free toggles, but some have hard dependencies that must be expressed as
> `dependsOn` in the registry (not left to prose or human convention):
> `aiops_agent` → `agent_platform` (+ `bifrost`, `agent_gateway`, `oam_components`),
> and **`otel_collector` → `langfuse`** (the tracing-auth ExternalSecret only
> renders when langfuse is on and configured — see §8.3 and
> [OAP #53](https://github.com/awslabs/open-agentic-platform/issues/53)).

### 6.3 In-cluster overlay layer (`$overlay`)

**Goal.** Let users track the **upstream** `appmod-blueprints` and OAP GitHub repos
as the **main source** (so they keep receiving upstream fixes and features without
forking), while still keeping **full control** over their own deployment through a
**fleet-config git repo they own**. Value files committed to that fleet-config repo
are layered at **highest precedence**, so they **override** the upstream defaults
without ever committing to (or forking) the upstream repos. In short: *upstream for
the code and defaults, your fleet-config for the last word.* This is the GitOps
equivalent of a private override layer — pin an image mirror, point an endpoint at
your own service, set your hostnames/Secrets-Manager keys, or disable/replace a
value — all in a repo you control, reconciled by Argo CD.

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

> **Overlay basepath — seed at fleet-config ROOT (`OVERLAY_BASEPATH=""`), not under
> `gitops/`.** The bootstrap appsets read `$overlay/<OVERLAY_BASEPATH>overlays/*` with the
> basepath **as-is** and intentionally do **not** apply the `gitops/` fallback to the
> `$overlay` (only the `$overlay` `fleet/*` reads keep the `… or fleetRepoBasepath`
> fallback). This differs from the base solution, whose own `$defaults` overrides read
> under `gitops/` (`addonsRepoBasepath`). So a bring-your-own fleet-config must place
> `overlays/environments/<env>/{enabled-addons,overrides}.yaml` at the repo **root**; filing
> them under `gitops/` by analogy with the base solution resolves nothing. (Validated e2e
> 2026-10-07: OAP addons fan out to hub+spokes with the overlay seeded at root.)

> **⚠️ No lifecycle for agent-authored overrides (known gap).** This overlay is
> the **highest-precedence** layer for **both** planes, and the autonomous agent
> commits to it at volume. Nothing retires those entries: a year of incidents
> later, an operator tracking upstream silently stops receiving upstream fixes for
> every key a past agent MR pinned — invisible precisely because this layer is
> *supposed* to win. There is also no provenance in the artifact itself (the
> `Incident-Component:` dedup marker's storage is not specified; if it lives in the
> MR description/branch rather than the committed YAML, the override's origin is
> lost once the MR is pruned). Agent-authored files should carry a **provenance
> header** (incident id, date, alert) and live under an **auditable/sweepable
> path**, with a defined **retirement owner**. Tracked in
> [OAP #52](https://github.com/awslabs/open-agentic-platform/issues/52); see §15.

> **Same overlay mechanism for BOTH planes — appmod & OAP.** This is not an
> OAP-specific invention: OAP reuses, verbatim, the overlay pattern that the
> **platform (appmod) addons** already use. Both are instances of the *same*
> `platform-charts/appset-chart` generator, each a two-source Application with an
> identical layered value-file precedence (defaults → env → cluster → `$overlay`,
> `ignoreMissingValueFiles: true`), differing only in **which registry files and
> git base path** they load:
>
> | | Platform addons (appmod) | Agentic addons (OAP) |
> |---|---|---|
> | Argo CD Application | `cluster-addons` | `agent-platform-addons` |
> | Source A (`$values`) | appmod `gitops/addons/registry/*` (base `gitops/addons`) | OAP `gitops/addons/registry/*` (`${BASEPATH}`) |
> | Source B (generator) | `platform-charts/appset-chart` | `platform-charts/appset-chart` (same chart) |
> | `$overlay` repo | fleet-config (`overlayRepoURLGit…`) | fleet-config (`overlayRepoURLGit…`, same repo) |
> | Umbrella gate | — (core, always on) | `globalSelectors.enable_agent_platform` |
>
> Because the `$overlay` repo is the **same fleet-config** for both, an operator
> overrides a **platform** addon and an **agentic** addon through the *same* paths
> and the *same* precedence rules — just under that addon's own key. The layered
> value files resolved by the generator for either plane are:
>
> ```
> $values/<base>/configs/<addon>/values.yaml                              # repo defaults (all clusters)
> $values/<base>/overlays/environments/<env>/<addon>/values.yaml          # repo per-env
> $values/<base>/overlays/clusters/<cluster>/<addon>/values.yaml          # repo per-cluster
> $overlay/configs/<addon>/values.yaml                                    # fleet-config, all clusters
> $overlay/overlays/environments/<env>/<addon>/values.yaml                # fleet-config, per-env
> $overlay/overlays/clusters/<cluster>/<addon>/values.yaml                # fleet-config, per-cluster (highest)
> ```

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

### 6.4 Enablement flags → labels

`enabled-addons.yaml` (per environment, e.g. `overlays/environments/control-plane/`)
holds `snake_case` booleans (`agent_platform: true`, `bifrost: true`,
`langfuse: true`, `otel_collector: true`, `aiops_agent: true`, …). The hub
fleet-secret **ExternalSecret** (ESO, `creationPolicy: Owner`) emits the
corresponding `enable_*` labels/annotations onto the hub **cluster-secret**, which
the ApplicationSet selectors and the agent registry entry read.

> **Consistency rule.** `aiops_agent: true` **requires** `agent_platform`
> (+ `bifrost`, `agent_gateway`, `oam_components`) `true`. Enabling `aiops_agent`
> alone while the umbrella is off leaves the OAM ComponentDefinitions
> (`mcp-server`, `agent`, `agentcore-memory`) uninstalled → the KubeVela admission
> webhook rejects the agent OAM Application (`… not found`). Enable them together.
> This dependency should be enforced as `dependsOn` in the registry, not left as a
> human convention (see §6.2).

> **Legacy `agent_platform` key.** On `main` today the key `agent_platform` was
> already bound to the **archived** Kagent/LiteLLM platform
> (`enabled-addons.yaml`, *"deploys from sample-agent-platform-on-eks repo"*). It
> has **no live consumer** (only the historical docs reference it). To avoid
> silently repurposing it, that legacy entry is **removed** so `agent_platform` is
> free as the new agentic umbrella gate — tracked in
> [appmod #955](https://github.com/aws-samples/appmod-blueprints/issues/955).

---

### 6.5 Guardrail agent — automated policy gate

Beyond the human merge-gate (§12), the platform exposes a **separate guardrail
agent**: a small A2A agent, owned by the platform team, whose only job is to
answer allow/deny for one specific proposed change. It is deliberately
**decoupled from the agent that acts** — `aiops-agent` (or any future acting
agent, built by any team) must call the guardrail agent and get an `allow` for
the specific target before it opens a remediation MR. The principle, borrowed
from the AWS DevOps Agent / A2A blog
([*Controlled self-healing Amazon EKS clusters with AWS DevOps Agent and A2A remote agents*](https://aws.amazon.com/blogs/mt/controlled-self-healing-amazon-eks-clusters-with-aws-devops-agent-and-a2a-remote-agents/),
public sample code: [`aws-samples/Amazon-prometheus-bedrock-agent-example`](https://github.com/aws-samples/Amazon-prometheus-bedrock-agent-example),
`a2a/` directory), is *one team owns the change policy, and
every other agent has to pass through it.* Centralising the policy in one agent
means a new acting agent inherits the same gate for free, and the policy can
evolve in one place without touching every actor.

It is complementary to — not a replacement for — the human merge-gate. The two
gates sit in series and answer different questions:

| Gate | Kind | Question it answers | Enforced by |
|---|---|---|---|
| **Guardrail agent** | Automatic, **deterministic** policy code (not an LLM) | "Does *policy* permit a change to this target *right now*?" (change-freeze window, min replica count, approval-ticket present) | Mandatory MCP-gateway policy on the MR-create path **and** a merge-blocking forge check re-evaluated at merge time (see below) |
| **Human merge-gate** (§12) | Human judgement on the artifact | "Is *this specific MR* correct and safe to merge?" | GitLab Developer role + protected `main` (the bot cannot merge its own MR) |

The guardrail agent runs **upstream**: it decides whether the agent is even
allowed to *propose* a change for that target before an MR is cut, cutting off
known-bad changes (e.g. during a freeze) before they consume a review. The human
merge-gate remains the final, non-negotiable control on the MR itself. Neither
removes the other.

**Policy content — adopt the pattern, not the demo check.** The AWS DevOps
Agent / A2A blog's *demo* guardrail checks only whether the target deployment has
a PodDisruptionBudget, and the authors state plainly that this check is
**illustrative and technically weak** (a PDB limits voluntary evictions such as
node drains; it does *not* constrain the Deployment rolling update that actually
applies the change). We adopt the **pattern** — a separate, mandatory,
programmable gate — and **not** that specific check. Our real policy examples are:

- a **change-freeze window** (deny all changes during a declared freeze);
- a **minimum replica count** (deny a change to a target below N replicas);
- an **approval-ticket present** (deny unless a referenced change ticket is open
  and approved).

The guardrail agent is the platform team's codified change policy; it is where
"what may change, and when" lives — programmable, versioned, and owned by one
team.

**The guardrail is deterministic policy code, not an LLM.** Every check above is
a plain function of inputs it reads itself — the freeze calendar, the target's
replica count, the referenced change ticket's state — so the same change at the
same moment always gets the same answer, and the decision is testable and
auditable like any other code. An LLM may be used only to *explain* a decision
(e.g. phrase the deny reason for the MR comment); it never *makes* the
allow/deny. An LLM-judged gate would be a probabilistic control, which is what
this design rejects for a component that blocks or permits changes.

**The target comes from the change itself, never from the acting agent.** The
guardrail does not trust a target name, label or description supplied by
`aiops-agent`: an acting agent could mislabel it. It derives the target(s) from
the proposed change — the files and Kubernetes resources the MR diff touches in
the fleet-config/overlay repo (upstream: from the tool call's change payload at
the gateway; downstream: from the MR diff the forge check reads). A change
touching several targets is allowed only if policy allows **every** one.

*Why the blog's own guardrail is not enough.* In the blog's public sample the
"mandatory" guardrail call is enforced **only by skill text** read by the
orchestrator's LLM (`a2a/skills/eks-troubleshooting.md`, Step 3). The acting
agent's mutating tools (`a2a/app/argocd_agent/tools/memory_adjustment.py`,
`a2a/app/argocd_agent/tools/restart_rollback.py`) gate only on a local,
in-process action allowlist (`a2a/app/argocd_agent/guardrails.py`) and never call
the guardrail agent (`a2a/app/guardrail_agent/main.py`), which answers only if
asked. So in the sample the gate is advisory in effect: an orchestrator that
skips the step still gets the change applied.

**Enforcement: advisory-upstream + forge-enforced, never advisory-only.** The
guardrail decision is enforced at two independent layers, consistent with §12's
rule that the prompt is not a security boundary:

1. **Upstream, at the MCP gateway (fail-fast, mandatory).** No MR can be opened
   without an explicit `allow` from the guardrail agent for the target(s) derived
   from the proposed change. This is **wiring, not prompt**, and the **required
   enforcement layer is an MCP-gateway policy** on the agent-gateway in front of
   `gitlab-mcp`'s MR-create tool: the gateway calls the guardrail agent and
   refuses the tool call unless it returns `allow`. The gateway is the right
   layer because acting agents can be built by **any team**: a policy enforced
   at the gateway holds for every agent that reaches `gitlab-mcp` through it,
   whatever its runtime or code. A guardrail wrapper on the create-MR tool
   *inside* an agent's runtime is at most a **convenience** (earlier, friendlier
   failure for agents we own); it is never the enforcement layer, because it
   lives in the actor's own code and does not exist for another team's agent.
   Any non-`allow` — deny, timeout, or unreachable after a bounded retry — is
   treated as **deny**; the attempt is recorded as *blocked*. This cuts off
   known-bad proposals (change-freeze window, below minimum replicas, no
   approval ticket) before they consume a human review.
2. **Downstream, forge-enforced (structural guarantee).** The guardrail decision
   is also published to GitLab as a **merge-blocking check** on the MR, required
   by branch protection on `main`. So even a *skipped* guardrail cannot result
   in a merge — the guarantee is enforced by the forge, on the artifact, exactly
   like the human merge-gate it complements. Where GitLab is **Ultimate**, this
   is an **external status check** with *"Status checks must succeed"* enabled
   and an absent/pending response treated as blocking (not GitLab's permissive
   default). Where it is not Ultimate, the equivalent is a **required CI job**
   that **re-calls the guardrail agent** (it must not merely trust an
   agent-written label) and fails the pipeline on `deny`/unreachable, with
   pipeline-must-pass branch protection. In both variants the check passes the
   **MR diff** to the guardrail, which derives the target(s) from the changed
   files/resources — never from an agent-supplied target label.
   **Re-evaluated at merge time.** "Policy permits this *right now*" must hold
   when the change *merges*, not only when CI first ran: a change-freeze window
   can open after the check passed. So the check is re-run immediately before
   merge — via **merge trains** (each merge re-runs the pipeline on the
   to-be-merged result) or a **re-run on approval / pre-merge re-run** of the
   guardrail job (or a re-requested external status check), with a stale result
   treated as not passed.

**Advisory-only is explicitly rejected** — a prompt-instructed call the agent
*could* skip is precisely the "strong suggestion, not an enforced boundary" §12
warns against. The human merge-gate (§12) already makes the advisory path *safe*
(nothing merges without a human), but policy-vs-right-now and §12 consistency
require the forge check as well. Three gates sit in series — guardrail policy
(upstream), guardrail-as-forge-check (merge-block), human merge-gate (final
judgement) — each answering a different question, none redundant.

**Caveats carried:** (a) merge-blocking external status checks are a GitLab
**Ultimate** feature; the CI-job variant is the CE-compatible substitute; (b)
GitLab's default lets a *failing or never-reported* external check merge — the
fail-closed posture requires explicitly enabling *"Status checks must succeed"*
and treating a missing/pending guardrail response as blocking; (c) the
merge-time re-evaluation depends on the forge feature available (merge trains
are a GitLab Premium/Ultimate feature); on CE the pre-merge re-run must be
wired explicitly (e.g. an approval-triggered pipeline), otherwise a pass from
before a freeze window opened could still be merged.

> **Relationship to the §8.1 unbounded-volume gap.** A change-freeze / rate-style
> guardrail could *also* serve as the circuit breaker §8.1 calls for
> ([OAP #51](https://github.com/awslabs/open-agentic-platform/issues/51)). Whether
> the guardrail agent owns rate/volume policy too, or stays purely per-change
> correctness, is for the team (§15).

---

## 7. The `aiops-agent`

`aiops-agent` is the reference platform-ops agent. Its **chart lives in this repo**
at `workshop/aiops-agent/chart` (moved under `workshop/` in
[#926](https://github.com/aws-samples/appmod-blueprints/pull/926), **interim**). Its
**registry entry is upstream**, in `gitops/addons/registry/platform.yaml`, **disabled
by default**: gated by `enable_aiops_agent` (the label exists only when an overlay
sets `aiops_agent: true` in `enabled-addons.yaml`), **sync-wave 9**, `dependsOn`
KubeVela + the OAP `agent-platform-addons` bundle. The chart's Argo CD Application
renders a single **KubeVela OAM Application**.

> **Design change — the upstream registry describes, the overlay decides.** The
> entry used to live in the workshop overlay
> (`workshop/overlay/overlays/environments/control-plane/overrides.yaml`) to keep the
> base registry "agent-free". That decision is reversed: with the definition in an
> overlay, every consumer that wants the agent (a GitHub fork, a non-workshop
> fleet-config) had to **copy** the full entry (chart path, selector, `valuesObject`
> expressions) into its own `overrides.yaml`, and each copy drifts from the chart.
> Every other addon is defined upstream and only toggled by the overlay; the agent
> now follows the same rule. Nothing changes for a hub that does not opt in: without
> the `enable_aiops_agent` label the ApplicationSet generates no Application. The
> workshop render is byte-identical (the overlay entry was identical to the new
> upstream entry, apart from the derived fleet-repo value below, which resolves to
> the same MR project).

> **This is narrower than it may read against #926.** @shapirov103 scoped
> `aiops-agent` to the workshop there specifically because of a hard dependency on
> OAP (external repo, then unpinned on main) and on the personal-registry image
> default ([#945](https://github.com/aws-samples/appmod-blueprints/issues/945)),
> suggesting the solution move happen "after release of OAP so that we can
> properly manage dependencies." Neither has changed: OAP's newest tag is still a
> pre-release
> ([`v0.1.0-rc5`](https://github.com/awslabs/open-agentic-platform/releases/tag/v0.1.0-rc5)),
> and `#945` is still open (`chart/values.yaml` still defaults `imageRegistry` to
> `public.ecr.aws/seb-demo`). What this PR moves upstream is only the registry
> *definition* — `aiops-agent` stays exactly as opt-in as it was in the overlay
> (disabled by default, same `enable_aiops_agent` gate), and a hub that flips
> `aiops_agent: true` inherits the OAP-prerelease and personal-registry
> dependencies identically either way. So this does not widen that surface, only
> stops the definition from drifting between copies — it does not, by itself,
> resolve #945 or wait for an OAP release, and those remain open items before
> `aiops-agent` is recommended for a production deployment.

### 7.0 Purpose & operating modes

`aiops-agent` is an **AIOps-style reference agent** for the platform: it observes
the fleet, reasons about incidents, and proposes/opens GitOps remediations. It is
also the **reference showcase for the OAP feature set** — it is composed entirely
from OAP building blocks (the `agent`/`mcp-server`/`agentcore-memory` OAM
ComponentDefinitions, the bifrost LLM gateway, the agent-gateway identity/token
exchange, AgentCore memory, and the OTLP→Langfuse tracing), so it doubles as a
worked example of "how to build an agent on OAP".

> **Scope note.** `aiops-agent` is intentionally a *reference/example* agent, not
> a general AIOps product. It is the smallest end-to-end thing that proves
> platform-managing agents work on EKS and demonstrates the agentic layer working
> together. Broader agent-driven platform operations is a separate, larger track
> (see §3).

It operates in **two complementary modes**, which have **different identity and
trust models** — a distinction that matters for the sections below:

1. **Interactive — Chat UI (human-in-the-loop).** A conversational front-end
   (`chat-ui`, exposed via CloudFront/ALB) lets an operator ask the agent to
   investigate the platform and draft/open remediation MRs. Access is
   **authenticated via Keycloak** (the platform IdP). There is a caller identity.
   > **⏳ Planned improvement — On-Behalf-Of (OBO) for CHAT. Not yet implemented.**
   > Today the agent acts with its own Pod-Identity role regardless of who is
   > chatting. The goal is an **on-behalf-of token exchange** (via the OAP
   > **agent-gateway** identity layer) so the agent **inherits the authenticated
   > user's permissions** and can do **only what that user is allowed to do** —
   > least privilege scoped to the human. This applies to the chat path **only**.
   > Tracked in §15.

2. **Autonomous — RCA (event-driven).** The agent runs **root-cause analysis
   automatically**, triggered by **observability events** (AMP alerts such as
   `PodOOMKilled` → SNS/SQS → `incident-bridge` → the agent). It performs read-only
   investigation and opens a **GitOps remediation merge request** for a human to
   review and merge (see §8.1). No human prompt starts it; a human still approves
   the fix.
   > **No caller identity on this path — OBO is structurally inapplicable.** The
   > trigger is an alert, not a user, so there is no identity to inherit. This path
   > **always runs as itself**, under a **dedicated bounded role that is
   > deliberately NOT user-scoped**. It is therefore the path that writes without a
   > human at initiation *and* has no identity-propagation story — so its only
   > controls are (a) the bounded role, (b) the enforced merge-gate from §12
   > ([appmod #956](https://github.com/aws-samples/appmod-blueprints/issues/956)),
   > and (c) refusing to act on an incomplete toolset (§7.1).

### 7.1 Components (OAM)

| Component | OAM type | Role |
|---|---|---|
| `aiops-agent` | `agent` | Strands agent. Discovers its MCP tools **once at boot** (`dependsOn` the MCP servers) — see the readiness caveat below. LLM calls go to **bifrost** (OpenAI-compatible) → Bedrock. `MAX_TOKENS` env configurable (OAP [#34](https://github.com/awslabs/open-agentic-platform/issues/34)/[#35](https://github.com/awslabs/open-agentic-platform/pull/35)). Traits: `gateway-identity`, `aws-service-identity`. |
| `skills-mcp` | `mcp-server` | Curated remediation/skills tools. |
| `eks-read-mcp` | `k8s-objects` | Read-only EKS/fleet discovery MCP (shares the agent's Pod Identity role). |
| `gitlab-mcp` | (deploy) | Write path — branches/MRs (`supergateway` wrapping `@zereight/gitlab-mcp`), PAT via ExternalSecret. **PAT scope is a security control — see §12.** |
| `agent-memory` | `agentcore-memory` | Bedrock AgentCore persistent memory; its `memoryId` is injected into the agent (`properties.memory.config`). Optional (delete the ▶MEMORY blocks to disable). Today it is generic persistent memory with **no remediation-history role** — see [OAP #51](https://github.com/awslabs/open-agentic-platform/issues/51). |
| `eks-read-access` | `k8s-objects` | Emits the least-privilege IAM Policy (`<app>-eks-read-access-iam-policy`) attached to the agent Pod Identity role. |
| `chat-ui` | (deploy + ingress) | A2A chat front-end, exposed via CloudFront/ALB at the ingress domain. |
| `incident-bridge` | (deploy) | Polls the incidents SQS queue, forwards each alert to the agent via A2A `message/send`. Deterministic, restart-proof open-MR dedup. |
| `amp-incident` | `AmpIncident` (kro RGD) | Provisions the AMP `AlertManagerDefinition` + SNS/SQS; reads the AMP workspace id **live** from the Crossplane AMP Workspace CR via `externalRef` (no literal id). |

> **🟠 Boot-time tool discovery is a real risk on the autonomous path.** The agent
> freezes its toolset at boot, with nothing tying capability to readiness. If an
> MCP server (e.g. `eks-read-mcp`) rolls or crashloops, the toolset silently
> shrinks. In chat mode a human notices and restarts; in **autonomous** mode nobody
> is watching — the agent can run an RCA on a fraction of the evidence, reach a
> confident conclusion, and open an MR that looks exactly like a good one. This is
> **the one failure mode in the design that produces confident garbage rather than
> an error**. The current operational remedy (`kubectl rollout restart
> rollout/peeks-agent`, raised on #926) also violates design principle 2. The real
> fix — lazy/retrying discovery, **fail readiness when expected tools are missing**,
> and **refuse to open MRs when the toolset is incomplete** — is tracked in
> [OAP #50](https://github.com/awslabs/open-agentic-platform/issues/50) (fix soon).

### 7.2 Images & overrides

Images default to the public workshop registry (`public.ecr.aws/seb-demo`), pinned
by tag. Per-component overrides are supported (`images.<comp>.{registry,tag}`);
empty ⇒ inherit `imageRegistry`/`imageTag`. **Image coordinates are GitOps single
source of truth** in the chart `values.yaml` (the upstream registry entry
deliberately sets no image value; a per-cluster overlay
`overlays/clusters/<cluster>/aiops-agent/values.yaml` may override one). Live cluster-secret
annotation overrides for image tags are **not** read on the current integration
branch — bump the git default in both places instead. (The `seb-demo` default
registry is an interim; durable registry tracked in
[appmod #945](https://github.com/aws-samples/appmod-blueprints/issues/945).)

### 7.3 Per-deployment values

Not hardcoded — injected from cluster-secret annotations by the registry entry
(the fleet-secret/ESO stamps `resource_prefix`, `aws_account_id`, `aws_region`,
`ingress_domain_name`, `gitlab_domain_name`). The literals in `values.yaml` are
fallbacks for a standalone `helm template` only.

### 7.4 Convergence with the `appmod-service` ComponentDefinition (design intent)

> **Which object we mean.** Two similarly-named things exist and are **different
> objects**: the KubeVela **ComponentDefinition `appmod-service`**
> (`gitops/addons/charts/kubevela/templates/components/appmod-service.yaml`,
> consumed as `type: appmod-service`), and the kro RGD **CRD kind `AppmodService`**
> (`appmodservice.kro.run`, `.../kro/resource-groups/manifests/appmod-service.yaml`).
> The convergence goal below targets the **KubeVela `appmod-service`
> ComponentDefinition** — i.e. one consistent OAM *component model* — while noting
> the kro `AppmodService` RGD as a sibling the same conventions should reach.

**We want the KubeVela/OAM ComponentDefinitions that evolve in OAP
(`agent`, `mcp-server`, `agentcore-memory`, …) to converge with the KubeVela
`appmod-service` ComponentDefinition of `appmod-blueprints`** — the component that
already backs the polyglot app-delivery modules (**java, next-js, rust, dotnet**).
The goal is **one consistent KubeVela component model** across the platform, not
two divergent lineages (an "app-delivery" family in appmod and an "agentic" family
in OAP).

> **Scope accuracy.** `appmod-service` backs **java, next-js, rust, dotnet**.
> `golang` ships only source (`go.mod`/`main.go`/templates) with no OAM/deployment
> manifest, and `RayService` is its own ~713-line kro RGD (`rayservice.kro.run`)
> with no `appmod-service` reference — a sibling, not something built on it.
> Neither is in scope for this convergence statement.

Rationale and direction:

- **Shared conventions.** `agent`/`mcp-server` and `appmod-service` should share the
  same trait/exposure conventions (ingress + ALB annotations, `healthcheckPath`,
  the kro RGD wiring, `peeks/depends-on` ordering, IRSA/Pod-Identity
  `aws-service-identity` accessFor) so that a fix or capability added on one side
  (e.g. path-prefix `url-rewrite`, health-check overrides, publishVersion-driven
  rollout triggers) is portable to the other rather than re-implemented.
- **Single source for the OAM building blocks.** Where a definition is generic
  (ingress, service identity, kro-backed AWS resources), it should live once and be
  consumed by both the agentic components and `appmod-service`, avoiding drift in
  CUE schemas and admission behaviour (e.g. the CUE `list.Concat` / v0.11 breakage,
  the annotation-key templating limits) being fixed twice.
- **Migration path.** As OAP's agentic ComponentDefinitions stabilise, fold their
  improvements back into the appmod `appmod-service` line (and vice-versa), so the
  workshop presents a single, coherent "define your service (or agent) as an OAM
  component" story.

> This is a **forward-looking alignment goal**, tracked as an open item (see §15).
> It does not block the current integration — today the agentic ComponentDefinitions
> ship from OAP (`oam-agent-components`) and `appmod-service` ships from appmod
> independently; convergence is incremental.

---

## 8. Key Data Flows

### 8.1 Autonomous incident → remediation MR

```
AMP alert (e.g. PodOOMKilled)  ──▶ SNS ──▶ SQS (<prefix>-incidents)
   │
   ▼  incident-bridge (long-poll) parses the alert, dedup-checks OPEN MRs
   ▼  A2A message/send  ──▶ aiops-agent
   ▼  RCA: read-only tools (eks-read-mcp) + skills-mcp  ── LLM ─▶ bifrost ─▶ Bedrock
   ▼  agent-gateway policy: guardrail-agent allow/deny for the target(s) derived from the change  (deny / unreachable ⇒ blocked, no MR — §6.5)
   ▼  gitlab-mcp: create branch + MR on the fleet-config/overlay repo
   ▼  forge requires the guardrail merge-check green, re-evaluated at merge (§6.5) AND a human merges  (the bot cannot merge its own MR — §12)
   ▼  Argo CD reconciles the merged change → fix applied
```

> The guardrail decision is enforced twice (§6.5): **upstream** the agent-gateway
> refuses the MR-create call without an `allow` (fail-closed at the point of action), and
> **downstream** the forge requires a green guardrail check before the MR can be
> merged — so a skipped or unreachable guardrail can never yield a merge.

> **Why Git, not a live-CR patch (our differentiator).** The AWS DevOps Agent /
> A2A blog's acting agent remediates by **patching the live
> `argoproj.io/Application` custom resource in-cluster** — it edits
> `spec.source.helm.parameters` directly and forces a sync; it does **not** write
> the change back to Git. Their demo Application has
> `syncPolicy.automated.selfHeal: true` pointing at a Git `repoURL`, so a live-CR
> patch that is not mirrored to Git is **drift that Argo CD's `selfHeal` reverts
> on the next reconcile** — the fix lives only in cluster state. **Our path is the
> inverse, by design:** `aiops-agent` never touches live CRs; it opens a
> remediation MR on the Git fleet-config/overlay repo, a human reviews and merges
> (§12), and Argo CD reconciles **from Git**. Because the change *is* the Git
> source of truth it is **durable** (`selfHeal` applies *our* fix on every
> reconcile instead of fighting it — no drift to revert), **auditable** (a
> reviewable commit/MR with authorship and history, not an untracked in-cluster
> mutation), and **human-gated** (the MR cannot merge itself — §12). In short:
> *their live-CR patch races `selfHeal`; our Git-MR flow makes `selfHeal` an
> ally.* This composes with the guardrail (§6.5): the guardrail is the upstream
> automated policy on whether to propose at all, while the Git-MR flow is what
> makes an approved fix durable and auditable. (Evidence in the blog's public
> sample: `a2a/app/argocd_agent/clients/argocd_client.py` patches the
> `Application` CR via `patch_namespaced_custom_object`, with no git client;
> `a2a/argocd-application.yaml` sets `syncPolicy.automated.selfHeal: true`.)

The incident-bridge performs a **deterministic, restart-proof duplicate check**:
it skips forwarding when an OPEN MR already addresses the failing component
(machine marker `Incident-Component: <c>` or a component match in title/branch),
and is **fail-open** (never blocks a real incident). The MR project is derived by
the chart from `fleetRepoUrl`, itself a **derived** registry value (not a user
knob): the same resolution `gitops/bootstrap/addons.yaml` uses for `$overlay` —
`overlay_repo_url` when wired, else the hub's `fleetRepoURL` when it is a separate
repo from `addonsRepoURL`, else empty (dup-check off). The former `gitlabMrProject`
value is a deprecated explicit override, honoured for one release.

> **⚠️ The loop does not close, and volume is unbounded (known gap).** The flow
> ends at "fix applied" and never verifies the outcome. Because dedup suppresses
> only while an MR is **open**, *merging ends the suppression*: if the fix was
> wrong the alert re-fires, there is no open MR, and the agent writes a fresh one —
> possibly a variant of what just failed, with **no memory it tried**. Volume
> compounds it: one root cause across N components yields **N MRs** (per-component
> dedup, fail-open), each an LLM run → a storm is a cost spike **and** a Bedrock
> throttling risk at once; **DLQ behaviour** on throttle mid-RCA is undefined.
> Fail-open is right for not missing an incident, but paired with per-component
> dedup it optimises for volume — backwards at 3am. The remedy — close the loop
> (verify via the same AMP signal, annotate/close the MR, record outcome in
> AgentCore memory) **or** declare verification human-only and **cap retries**,
> plus an aggregation window, a ceiling on open agent MRs, and a circuit breaker —
> is tracked in [OAP #51](https://github.com/awslabs/open-agentic-platform/issues/51).

### 8.2 Chat (A2A)

`chat-ui` (CloudFront/ALB) → `aiops-agent` A2A endpoint → same RCA/tool loop, for
interactive queries.

### 8.3 Tracing pipeline

```
aiops-agent ──(OTLP)──▶ otel-collector ──▶ Langfuse ──▶ ClickHouse (traces/observations)
```

**Source of truth for "are traces captured" = ClickHouse row counts** (not app
health). Two dependencies must be satisfied on a fresh env:

**1. The tracing-auth secret — a three-hop chain (not one hop).** When chasing a
401, open the hops in order:

```
Langfuse Sync hook  push-otel-secret  (SA langfuse-seed, hook: Sync, wave 5)
   │  creates Secret `langfuse-otel-keys` + Job `langfuse-push-otel-keys`
   ▼  the Job shells out to `aws secretsmanager put-secret-value|create-secret`
Secrets Manager  (keys pushed here)
   ▼
ExternalSecret `langfuse-otel-auth`  (owned by the otel-collector chart,
   creationPolicy: Owner, 1h refresh)  ──▶  K8s Secret the collector mounts
```

The hook pushes keys **to Secrets Manager**; it does **not** write `langfuse-otel-auth`
directly. `langfuse-otel-auth` is an **ExternalSecret owned by otel-collector**
(`charts/otel-collector/templates/langfuse-secret.yaml`). The 1h ESO refresh means
the chain **self-heals** — better than a one-shot hook.

> **Coupling across two independently-gated addons (known gap).** That
> ExternalSecret renders only
> `if and .Values.langfuse.enabled .Values.langfuse.endpoint .Values.langfuse.secretManagerKey`,
> yet `langfuse` and `otel_collector` sit behind **separate** flags. Enable
> `otel_collector` without `langfuse`, or leave `secretManagerKey` empty, and you
> get **no ExternalSecret, no error, and a collector sending empty Basic auth →
> 401** — traces silently absent (which is why acceptance is a ClickHouse row
> count, not a health check). This pair must be a `dependsOn` in the registry and
> the empty-key case must **fail loudly** — tracked in
> [OAP #53](https://github.com/awslabs/open-agentic-platform/issues/53) (see also
> [#45](https://github.com/awslabs/open-agentic-platform/issues/45)).

**2. The Langfuse minio object-store bucket.** The upstream chart default still
ships `quay.io/minio/minio` and `quay.io/minio/mc` on **`tag: "latest"`**
(`gitops/addons/charts/langfuse/values.yaml`) — **not** an ECR mirror, and **not**
pinned. quay has been observed returning **401 for `latest` and `RELEASE.*`** (and
docker.io 404), giving `ImagePullBackOff` on fresh installs, which blocks sync
wave 0 → the `push-otel-secret` hook at a later wave never runs → the 🟡 tracing
row does **not** self-heal. **Interim fix: repoint minio/mc to the `seb-demo`
public ECR mirror with an immutable pinned tag** (`public.ecr.aws/seb-demo/minio`
and `.../mc` at `mirror-20260921`) — **OAP
[#43](https://github.com/awslabs/open-agentic-platform/pull/43)**. The mirror is a
**personal namespace and explicitly interim**; moving to a durable, non-personal
registry is tracked in **OAP
[#42](https://github.com/awslabs/open-agentic-platform/issues/42)** / **appmod
[#945](https://github.com/aws-samples/appmod-blueprints/issues/945)**. (Until #43
merges, the upstream default is quay/`latest` as-shipped — this doc describes it
as-is rather than claiming a pin that isn't on `main`.)

---

## 9. Provisioning & Bootstrap (PEEKS side)

- The PEEKS CloudFormation template **bakes the OAP git coordinates** as synth-time
  literals (`AGENTIC_REPO_URL` / `AGENTIC_REPO_REVISION`). The IDE clones OAP at
  runtime; `task install` → `agentic:install` renders `agent-platform-app.yaml`
  with the injected `REPO_URL`/`REVISION`/`OVERLAY_*` coordinates.
- **Leak-proof coordinate names.** Source A of `agent-platform-addons` uses
  OAP-specific variable names (`OAP_REPO_URL`/`OAP_REVISION`/`OAP_BASEPATH`) so the
  generic `REPO_URL` exported by the IDE `SETUP_SCRIPT` (for the appmod clone) does
  **not** leak into and override the OAP source. A CDK guard also unsets
  `REPO_URL`/`REPO_REVISION` before the OAP block.

### 9.1 Bedrock model access prerequisite (LLM enablement)

The agent's LLM calls reach Bedrock via bifrost, which routes
**`us.anthropic.claude-sonnet-4-5-20250929-v1:0`** (the cross-region inference
profile for Claude Sonnet 4.5 — `open-agentic-platform/gitops/addons/configs/bifrost/values.yaml:76`,
`claude-sonnet: …`). Because Anthropic models are **AWS Marketplace–gated**, a
principal **with Marketplace permissions** must invoke the model once to subscribe
it **account-wide** (the "Model access" console page is retired; activation is
reported to be automatic on first invocation, subject to Marketplace perms + the
Anthropic first-time-use form — *this console-retirement detail is as-reported and
not independently re-confirmed here*). Neither the participant nor the ops workshop
role carries `aws-marketplace:Subscribe`, so activation is handled at
**provisioning** by a CFN custom resource (in the `platform-engineering-on-eks`
repo, `cdk/lib/team-stack.ts`):

- a Lambda whose role has `aws-marketplace:Subscribe/Unsubscribe/ViewSubscriptions`
  + `bedrock:InvokeModel*` (and the agreement/FTU actions), which submits the FTU
  and invokes `Converse` once (with retry) on the **same id bifrost routes** →
  subscribes account-wide;
- non-fatal (always signals SUCCESS; result exposed as a stack output).

> **The subscribed id MUST equal the routed id.** If the Lambda subscribes one
> model and bifrost invokes another, you get a **silent 403 at the LLM step** — the
> exact "RCA never runs, no MR, no useful trace" failure this section exists to
> prevent. The Lambda id and the bifrost route are now aligned on
> `us.anthropic.claude-sonnet-4-5-20250929-v1:0`
> (foundation-model id `anthropic.claude-sonnet-4-5-20250929-v1:0`). **Keep them in
> one place so they cannot drift** — a shared/baked constant rather than two
> independently-edited literals across the OAP bifrost config and the provisioning
> Lambda (open item, §15). *(Historical note: an earlier draft named
> `claude-sonnet-5`, which bifrost never routes — corrected.)*
>
> **⏳ Newer model (e.g. Sonnet 5) — handle later.** Workshop Studio guidance is to
> move to the newest Claude models. That upgrade is deferred and must be done
> **in lockstep**: bump the **bifrost route** (`configs/bifrost/values.yaml`) **and**
> the provisioning Lambda id **together** (ideally the single shared constant above),
> and re-confirm Marketplace subscription for the new id. Changing one without the
> other reintroduces the silent-403 mismatch. Tracked in §15.

After activation, every role in the account (including the bifrost Pod Identity
role, which already has `bedrock:InvokeModel`) can invoke without Marketplace
perms. Without this, the agent 403s at the LLM step (RCA never runs, no MR, no
useful trace).

---

## 10. Impacted Components & Change Map

High-level → low-level view of what each deliverable touches, so the change
surface is legible at a glance. This is the durable map; implementation PRs
reference this document and are consolidated **one PR per repo per feature**
(see §11).

| Repo | Component / path | Change | Why |
|---|---|---|---|
| `appmod-blueprints` | `platform-charts/appset-chart` | Reused (unchanged generator) as the generator for the agentic plane | One generator drives platform **and** agentic addons — no second machinery |
| `appmod-blueprints` | `workshop/aiops-agent/chart` (+ OAM app; sources `workshop/aiops-agent/src/`) | **New** chart + KubeVela OAM Application (moved under `workshop/` in [#926](https://github.com/aws-samples/appmod-blueprints/pull/926), **interim**) | The reference agent (chat + autonomous RCA→MR) |
| `appmod-blueprints` | `gitops/addons/registry/platform.yaml` | **New** agent registry entry — **upstream, disabled by default**; gated `enable_aiops_agent`, sync-wave 9 | Overlay opts in with `aiops_agent: true` only; wave + `dependsOn` ordering |
| `appmod-blueprints` | `workshop/overlay/overlays/environments/*/enabled-addons.yaml` | **New** agentic flags (`aiops_agent`, `amp_incident`, …) in the workshop overlay; **remove** legacy `agent_platform` entry from the base ([#955](https://github.com/aws-samples/appmod-blueprints/issues/955)) | Per-env enablement, off by default; free the umbrella key |
| `open-agentic-platform` | `gitops/bootstrap/agent-platform-app.yaml` | **New** two-source Application | Deploy OAP via the appmod generator (no vendoring) |
| `open-agentic-platform` | `gitops/addons/registry/*` (`_defaults`, `gateway`, `observability`, `agentcore`, `sandbox`) | Registry files with per-addon selectors + **`dependsOn`** for coupled pairs | Per-addon gating; enforce `otel→langfuse`, `agent→umbrella` ([#53](https://github.com/awslabs/open-agentic-platform/issues/53)) |
| `open-agentic-platform` | `charts/configs` (`bifrost`, `agent-gateway`, `oam-agent-components`, `langfuse`, `otel-collector`, …) | Agentic component charts/configs | The OAP feature set consumed by `aiops-agent` |
| `open-agentic-platform` | `eks-read-access` ComponentDefinition; otel-auth self-heal; strands tool discovery | Least-privilege discovery + tracing-auth robustness + readiness gate ([#50](https://github.com/awslabs/open-agentic-platform/issues/50)) | Security + fresh-env reliability + no half-blind RCA |
| `platform-engineering-on-eks` (GitLab) | `cdk/lib/team-stack.ts` | Bake OAP coordinates + **Bedrock model-access** CFN custom resource (id aligned to the bifrost route) | Provisioning wires OAP; LLM works on a fresh account |
| `platform-engineering-on-eks` (GitLab) | workshop content / `task` targets | Enablement + guidance (as applicable) | Participant-facing enablement path |

---

## 11. Delivery & Review Plan

This document is the single design reference; the process around it:

- **Design review first.** Circulate this document and hold a design-review with
  the PEEKS/OAP core maintainers; capture agreement (or changes) before merging
  implementation. PRs stay in **draft** until the design is agreed. **The item to
  settle before implementation PRs cite this doc is the enforced human merge-gate
  (§12, [appmod #956](https://github.com/aws-samples/appmod-blueprints/issues/956)).**
- **One PR per repo per feature.** Consolidate the changes into a single PR per
  repository for this feature (one in `appmod-blueprints`, one in
  `open-agentic-platform`, one in the internal provisioning repo), rather than many
  small PRs, to keep the review coherent. Each PR **references this design
  document**; the document itself does not enumerate PR numbers.
- **Task tracking.** Track the deliverable as discrete tasks (design doc,
  agentic layer, `aiops-agent`, provisioning/Bedrock, content, dry-run) with the
  acceptance criteria from §3 as the definition of done. Review follow-ups are
  tracked as the issues listed in §15.
- **Validation gate.** A PR is ready to leave draft when the §3 acceptance
  criteria pass on a **fresh** environment (see §14).
- **Presentation assets** related to this work are kept under version control
  (a decks repository), so the material is not lost and evolves from a single
  source of truth.

---

## 12. Security

- **Pod Identity per workload.** `aiops-agent`/`eks-read-mcp` share one role with a
  least-privilege read policy (`AmazonEKSViewPolicy`-style + the emitted
  `eks-read-access` IAM policy). `gitlab-mcp` gets a PAT via ExternalSecret.
- **AgentCore memory** attaches its own IAM policy to the agent role via the
  `aws-service-identity` trait.
- **Secrets via ESO / Secrets Manager** (`langfuse-otel-auth`, GitLab PAT, Langfuse
  keys) — never in Git.
- **Bifrost** centralizes model access; the agent never holds Bedrock creds
  directly.
- **What enforces the human merge-gate (the control the whole design rests on).**
  "The agent proposes, a human merges" is enforced by **GitLab configuration, not
  by the agent**:
  - the bot identity is a **Developer (access level 30)** on every repo — it can
    push a branch and open an MR, but **not** merge;
  - **every** repo (fleet-config AND the app repos) has `main` **protected**, with
    push/merge gated to Maintainer (40) and force-push disabled, so the bot
    **cannot approve, merge, or force-push its own MR** on any repo the bridge can
    route to;
  - a human (the repo Owner) merges; Argo CD then applies.

  Note: the `gitlab-mcp` PAT carries `api` scope (needed to open MRs via the API),
  and `api` **can** also merge — so the token scope is **not** the control. The
  merge-gate is the **Developer role + branch protection** above.

  This matters more here than elsewhere because fleet-config is the
  **highest-precedence** layer for *both* planes — a merged agent MR outranks every
  upstream default, platform addons included. Hardening/verifying the PAT scope and
  branch protection is tracked in
  [appmod #956](https://github.com/aws-samples/appmod-blueprints/issues/956).
- **The agent's prompt is NOT a security boundary.** The agent's prompt *asks* for
  single-file, additive, dedup-checked edits. This is a **strong suggestion, not an
  enforced boundary** — it is listed here only to be explicit that it does **not**
  constrain what the agent *can* write. The actual boundary is the PAT scope +
  branch protection above; the blast radius is bounded to *opening* MRs, and a
  human merges.
- **Identity scoping.** **Chat path:** until OBO (§7.0/§15) lands, the agent acts
  under its own Pod-Identity role, not the chat user's — a known limitation to close
  before any multi-user, higher-privilege use. **Autonomous path:** has no caller
  identity by construction (OBO inapplicable); it runs under a **dedicated bounded
  role, deliberately not user-scoped**, and is governed by the merge-gate above and
  the toolset-completeness guard (§7.1).
- **The guardrail agent (§6.5) is an additional, upstream, forge-enforced control**
  on top of the merge-gate; it is enforced as agent-side wiring on the MR-create
  path **and** a merge-blocking GitLab check — deliberately **not** as a prompt
  instruction, consistent with "the prompt is not a security boundary" above. It
  does **not** relax the human merge-gate.

---

## 13. Enable / Disable

**Enable** (per environment) in `enabled-addons.yaml`:

```yaml
enabledAddons:
  agent_platform: true      # umbrella (legacy same-named key removed — #955)
  bifrost: true
  agent_gateway: true
  oam_components: true
  langfuse: true
  otel_collector: true      # requires langfuse: true (coupled — §6.2/§8.3/#53)
  agent_core: true          # AgentCore memory provider (OAP crossplane-agentcore)
  amp_incident: true        # AMP incident RGD — MUST be set with aiops_agent, else the agent's AmpIncident CR has no RGD
  aiops_agent: true         # requires the umbrella + all of the above
```

Commit + push → the fleet ESO stamps `enable_*` labels → Argo CD renders the OAP
ApplicationSets and the agent OAM Application.

**Disable**: flip the same keys to `false` (umbrella `agent_platform: false`
removes the whole bundle). Core platform is unaffected.

> **Legacy key.** The `agent_platform` key previously bound to the archived
> Kagent/LiteLLM platform has **no live consumer** and is **removed** so this
> umbrella gate does not silently repurpose it
> ([#955](https://github.com/aws-samples/appmod-blueprints/issues/955)).

---

## 14. Testing / Validation

- **Diff-empty when off (principle 1, testable):** `helm template` the appset-chart
  with the agentic flags **off** and assert it renders **diff-empty** against the
  pre-change baseline. With selectors on, assert the expected ApplicationSets render
  only when `enable_agent_platform`/`enable_<addon>` are set.
- **Fresh-env E2E** (the real gate): deploy an env, then validate
  1. OAP apps `agent-platform-addons`, `bifrost`, `agent-gateway`,
     `oam-agent-components`, `langfuse`, `otel-collector` are Healthy/Synced;
  2. `aiops-agent` + `chat-ui` + the 3 MCP servers + `incident-bridge` are Running;
  3. inject a synthetic OOMKill on the incidents SQS queue → assert an MR is opened
     on fleet-config, **and that the bot cannot merge it** (§12);
  4. assert traces land in ClickHouse (`SELECT count() FROM traces`).
- **Bedrock**: confirm the model-access CFN resource output is `ENABLED`, the agent
  does not 403 at the LLM step, **and the subscribed id equals the bifrost route**.

---

## 15. Open Items / Known Gaps

Review follow-ups from the design review are tracked as issues; each line links the
tracking issue so this doc is the index.

**Integration levels at a glance.** The levels below are **composable layers**
that plug in at different points of the same pipeline — *orchestration* (who
starts and drives the investigation), *diagnosis* (what evidence the RCA reads),
*policy gate* (whether a change may be proposed/merged) and *apply* (how the fix
lands) — not mutually exclusive variants. V1 is core and applies at every level;
V2 and V3 are optional and independent of each other.

| Level | What it is | What it adds vs V0 | Cost | Coexists? |
|---|---|---|---|---|
| **V0 — current `aiops-agent`** | AMP alert → SNS → SQS → `incident-bridge` → read-only RCA (`eks-read-mcp` + skills) → GitLab MR → human merge → Argo CD (GitOps) | — (baseline) | Already deployed: agent + MCP servers + bifrost route | Baseline for all levels |
| **V1 — + guardrail (CORE)** | Deterministic policy agent (§6.5): freeze window, replica floor, ticket check; enforced at the MCP gateway and as a merge-time forge check | Automated "may this change, right now?" gate in series with the human merge-gate; same policy for agents built by any team | One small policy agent + gateway policy + a required forge check; policy content to own | **Core** — applies to V0, V2 and V3 alike (*policy gate*) |
| **V2 — + AWS DevOps Agent** (optional) | Managed A2A orchestrator front-end that starts investigations and delegates to our in-cluster agents | Bridge to the AWS ecosystem: console-driven investigations, CloudWatch-alarm triggers, reuse of our A2A agents unchanged | External control plane + cross-account trust (role assuming into our account), API Gateway/VPC Link exposure; its sample patches live CRs — **we keep the Git MR** apply path | Yes — alongside `incident-bridge` (*orchestration*); does not change diagnosis, gate or apply |
| **V3 — + K8sGPT** (optional) | Deterministic Kubernetes analyzer catalogue, LLM backend off, as one more read-only tool | Cross-object checks (e.g. Service selector ↔ pods) and breadth for unalerted issues; **no gain for the current demo class**; never produces the MR | Extra operator or MCP server, ClusterRole review (operator reads `secrets`), auto-remediation pinned off, CNCF Sandbox maturity | Yes — feeds RCA (*diagnosis*); not part of the guardrail |

- **Enforce the human merge-gate — 🔴 settle before impl PRs cite this doc.** Scope
  the `gitlab-mcp` PAT to branch+MR only (not merge); protected branches so the bot
  cannot approve/merge its own MR. §12 ·
  [appmod #956](https://github.com/aws-samples/appmod-blueprints/issues/956).
- **Autonomous path runs half-blind on an incomplete toolset — 🟠 fix soon.**
  Lazy/retrying MCP discovery; fail readiness when tools are missing; refuse to
  open MRs when the toolset is incomplete. §7.1 ·
  [OAP #50](https://github.com/awslabs/open-agentic-platform/issues/50).
- **Remediation loop does not close; volume unbounded.** Verify/annotate/close
  (or human-only + retry cap), outcome memory in AgentCore, aggregation window,
  open-MR ceiling, circuit breaker, DLQ-on-throttle. §8.1 ·
  [OAP #51](https://github.com/awslabs/open-agentic-platform/issues/51).
- **Agent-authored overrides have no provenance or lifecycle.** Provenance header
  in the committed YAML, auditable/sweepable path, defined retirement owner. §6.3 ·
  [OAP #52](https://github.com/awslabs/open-agentic-platform/issues/52).
- **otel-collector⇄langfuse coupling.** Express `dependsOn` in the registry; fail
  loud on empty `secretManagerKey` instead of rendering nothing. §8.3 ·
  [OAP #53](https://github.com/awslabs/open-agentic-platform/issues/53) (see also
  [#45](https://github.com/awslabs/open-agentic-platform/issues/45)).
- **minio images ship as quay/`latest`, not a pinned ECR mirror.** Fresh-env
  `ImagePullBackOff` risk; blocks tracing self-heal. §8.3 · interim fix
  [OAP #43](https://github.com/awslabs/open-agentic-platform/pull/43); durable
  registry [OAP #42](https://github.com/awslabs/open-agentic-platform/issues/42) /
  [appmod #945](https://github.com/aws-samples/appmod-blueprints/issues/945).
- **Bedrock model id drift-prevention.** The subscribed id and the bifrost route
  are aligned (Sonnet 4.5); keep them in **one place** (shared/baked constant) so
  they cannot diverge again. §9.1.
- **Upgrade to a newer Claude model (e.g. Sonnet 5) — ⏳ deferred.** Per Workshop
  Studio guidance to adopt the newest models; do it **in lockstep** (bifrost route
  + provisioning Lambda id + Marketplace subscription for the new id), via the
  single shared constant, to avoid the silent-403 mismatch. §9.1.
- **Agent naming & location.** `peeks-agent` → `aiops-agent` rename **done in
  [#926](https://github.com/aws-samples/appmod-blueprints/pull/926)**
  ([appmod #954](https://github.com/aws-samples/appmod-blueprints/issues/954)); the
  agent chart + sources also moved under `workshop/aiops-agent/` (**interim**); the
  registry entry is upstream in `platform.yaml`, disabled by default. A later
  cleanup may fold the chart itself into the generic `gitops/addons/` tree once
  stabilized.
- **Remove the legacy `agent_platform` enabled-addons key** + mark neighbouring
  agent-platform docs (`README.md`, `COMPONENTS.md`, `UPGRADE-APPROACH.md`)
  historical. §6.4/§13 ·
  [appmod #955](https://github.com/aws-samples/appmod-blueprints/issues/955).
- **On-Behalf-Of (OBO) for the chat path — ⏳ planned, not implemented.** Add
  agent-gateway token exchange so the chat-authenticated (Keycloak) user's
  identity/permissions are propagated to the agent. **Chat only** — structurally
  inapplicable to the autonomous path (§7.0/§12). See §7.0.
- **Converge OAP OAM components with the `appmod-service` ComponentDefinition —
  ⏳ planned.** Align `agent`/`mcp-server`/`agentcore-memory` with the KubeVela
  `appmod-service` ComponentDefinition toward one component model (shared
  traits/ingress/health/kro-RGD conventions). §7.4.
- **kro annotation-key templating** — the ALB `url-rewrite` transforms annotation
  needs a dynamic key; kro does not substitute CEL in annotation **keys** (only
  values), so path-prefix rewrite for agent/app ingress is limited pending kro
  v0.10 (tracked separately).
- **Image-override convention** — live cluster-secret image-tag annotations are a
  no-op on the current integration branch (GitOps-only); bump git defaults. Durable
  default registry: [appmod #945](https://github.com/aws-samples/appmod-blueprints/issues/945).
- **Teardown sweep IAM** — the workshop sweep role lacks
  `ecr:DeleteRepository`/`s3:DeleteBucket`/`logs:DeleteLogGroup`, leaving a few
  app-layer residues (ray model S3, custom ECR, EKS log groups) after teardown
  (tracked separately).
- **(Optional, for team discussion — not the default path) AWS DevOps Agent as the
  A2A orchestrator.** Instead of our incident-bridge driving `aiops-agent`
  directly, **AWS DevOps Agent** orchestrates: it starts the investigation, reads
  a troubleshooting skill, and **delegates** to our in-cluster A2A agents (acting
  + guardrail), which stay in our account. Secure network blueprint verified in
  the sample code: agent pods are **not internet-reachable**; exposure is
  *DevOps Agent → (HTTPS, SigV4) → API Gateway (`AWS_IAM` authz) → VPC Link →
  internal NLB → agent pod*; DevOps Agent assumes a **dedicated role** scoped to
  `execute-api:Invoke` on one API (`.../<api-id>/*`). **Pro:** managed
  orchestrator, console-driven investigations, CloudWatch-alarm triggers, reuse of
  our A2A agents unchanged. **Con:** a new external control plane and trust
  relationship (its role assuming into our account); our current design is
  self-contained (SNS → SQS → incident-bridge → agent). **Open:** does it
  *coexist* with our incident-bridge path or *replace* it for some triggers, and
  how does it interact with our GitOps/MR differentiator (§8.1)? **Prereqs if
  adopted for production:** AWS Load Balancer Controller + `TargetGroupBinding`
  (the sample registers the pod IP directly, which the authors call a demo
  shortcut that breaks on pod restart), **and** the `AWS_IAM` authorizer actually
  attached to each method (the sample's quick-setup script creates methods with
  `--authorization-type NONE`). Evidence: the
  [blog](https://aws.amazon.com/blogs/mt/controlled-self-healing-amazon-eks-clusters-with-aws-devops-agent-and-a2a-remote-agents/) and its public
  [sample](https://github.com/aws-samples/Amazon-prometheus-bedrock-agent-example)
  (`a2a/k8s/argocd-agent-eks/setup-apigw.sh`).
- **(Optional, for team discussion — not the default path) K8sGPT as a
  deterministic pre-triage feed (LLM backend off).** K8sGPT's value for us is its
  **rule-based analyzer catalogue** (Pod, Service, Ingress, PVC, Node, webhooks,
  HPA/PDB, Karpenter NodePool/NodeClaim, …): plain Go checks over Kubernetes
  status that return the same findings for the same cluster state. The LLM is
  used only for its optional "explain" step and is disabled with
  `spec.ai.enabled: false` (operator) or `explain=false` (MCP `analyze`).
  Integration would be **one more read-only tool** for `aiops-agent`, preferably
  on demand via `k8sgpt serve --mcp` behind the agent-gateway (allow only
  `analyze`/read tools), or the operator's `core.k8sgpt.ai/v1alpha1` `Result`
  CRDs read the way the [blog sample](https://github.com/aws-samples/Amazon-prometheus-bedrock-agent-example) does
  (`a2a/app/argocd_agent_eks/tools/k8sgpt_diagnostics.py`). **What it adds:**
  cross-object checks we do not have (e.g. *Service has no endpoints, expected
  label k=v*), breadth for unalerted issues, a cheap structured first pass, and a
  "finding cleared" check after sync. **What it does not add:** anything for our
  current demo class beyond what the AMP alert + `eks-read-mcp` already give (its
  OOMKilled finding carries no limit/usage), and **never the fix** — it has no
  notion of the GitOps source, so the RCA→MR path stays ours. **Costs/constraints
  if adopted:** an extra operator (or MCP server) to run and upgrade; no second
  model (LLM backend off; if ever on, route through bifrost rather than a separate
  Bedrock model); auto-remediation pinned off (it mutates the cluster directly,
  against our MR model); review the operator ClusterRole (it includes
  cluster-wide `secrets` read); CNCF Sandbox maturity. Optional read-only
  pre-triage, **not a default**, and it is a **detection** signal — not part of
  the guardrail (§6.5).

---

## 16. Glossary

- **OAP** — Open Agentic Platform (`awslabs/open-agentic-platform`).
- **bifrost** — OpenAI-compatible LLM proxy fronting Bedrock.
- **agent-gateway** — agent identity / token-exchange gateway.
- **OAM / KubeVela** — the application model; ComponentDefinitions `agent`,
  `mcp-server`, `agentcore-memory` are provided by `oam-agent-components`. The
  app-delivery component is the KubeVela ComponentDefinition `appmod-service`
  (distinct from the kro RGD kind `AppmodService`).
- **kro / ACK / Crossplane** — Kubernetes-native infra composition and AWS resource
  controllers used for spokes, AMP, IAM, memory, etc.
- **A2A** — agent-to-agent messaging protocol (`message/send`) used by the chat-ui
  and incident-bridge to reach the agent.
- **AMP** — Amazon Managed Service for Prometheus (alert source).
- **OBO** — On-Behalf-Of identity propagation; a token exchange so the agent acts
  with the caller's permissions. Applies to the **chat** path only.
- **AIOps** — using agents/automation to help operate the platform (incident
  triage, RCA, remediation). `aiops-agent` is a reference example, not a full
  AIOps product (see §3).

---

**Related:** [`DESIGN.md`](./DESIGN.md) (historical bridge-chart design) ·
[`COMPONENTS.md`](./COMPONENTS.md) *(historical — Kagent/LiteLLM)* ·
[`README.md`](./README.md) *(historical — Kagent/LiteLLM)* ·
[`TROUBLESHOOTING.md`](./TROUBLESHOOTING.md)
