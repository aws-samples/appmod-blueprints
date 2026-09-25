---
name: manage-addons
description: Add, configure, or modify GitOps addons on the PEEKS platform. Use when adding a new addon, enabling an addon on a cluster, configuring addon values, troubleshooting addon deployment, or editing addon enablement (`enabled-addons.yaml`). Do NOT use for general kubectl troubleshooting — use troubleshoot-platform instead.
---

# Manage Addons

## Overview

Guides the proper GitOps workflow for adding, enabling, and configuring platform addons deployed via ArgoCD ApplicationSets.

## Parameters

- **operation** (required): "add", "enable", "configure", or "debug"
- **addon_name** (required): Name of the addon (kebab-case)
- **cluster_name** (optional): Target cluster (hub, spoke-dev, spoke-prod)

## Workflow

### 1. Understand the GitOps Architecture

The platform uses a three-tier configuration system:

| Layer | File | Purpose |
|-------|------|---------|
| Addon registry | `gitops/addons/registry/<domain>.yaml` | Central registry of all addons (core, platform, security, observability, ml, gitops) |
| Environment enablement | `gitops/overlays/environments/<env>/enabled-addons.yaml` | Per-environment enablement (source of truth for cluster secret `enable_*` labels) |
| Value overlays | `gitops/overlays/environments/<env>/<addon>/values.yaml` | Per-environment/cluster value overrides |

**Constraints:**
- You MUST prefer GitOps workflow (modify Git → commit → push → ArgoCD sync) over manual kubectl apply because manual changes drift from Git state
- You MUST NOT manually modify cluster secrets — always update through `gitops/overlays/environments/<env>/enabled-addons.yaml` because the fleet-secret chart generates these labels from it
- Read-only kubectl operations (get, describe, logs) are allowed without confirmation

### 2. Add a New Addon

**Constraints:**
- You MUST add the addon entry in the appropriate `gitops/addons/registry/<domain>.yaml` with selector and valuesObject
- You MUST add `enable_<addon>: false` to the relevant `gitops/overlays/environments/<env>/enabled-addons.yaml`
- You MUST choose an appropriate sync wave based on dependencies (see references/sync-waves.md)
- You MUST NOT put dynamic template values (`{{.metadata.annotations.*}}`) in values.yaml files because they will be overridden — see [references/values-separation.md](references/values-separation.md)
- You SHOULD create a values overlay at `gitops/addons/default/addons/<addon>/values.yaml` for static config
- You SHOULD apply changes via GitOps (commit → push → ArgoCD sync); use `task install` for provider bootstrap, never raw `terraform apply`

### 3. Configure Addon Values

See [references/values-separation.md](references/values-separation.md) for the dynamic vs static values pattern.

**Constraints:**
- You MUST keep dynamic template values ONLY in `addons.yaml` valuesObject
- You MUST NOT use empty strings for dynamic values in values.yaml because they override templates
- You SHOULD validate YAML after modifications: `yq eval '.' <file> > /dev/null`

### 4. Configure HA for Critical Addons

**Constraints:**
- You MUST configure 2+ replicas for critical services (hub, proxy, controller)
- You MUST add PodDisruptionBudgets with `maxUnavailable: 1`
- You MUST configure topologySpreadConstraints for multi-AZ distribution
- You MUST set memory limits equal to requests for critical components because this prevents OOM kills
- You MUST NOT set CPU limits on critical components because it causes throttling
- You SHOULD use system nodeSelector and CriticalAddonsOnly tolerations

### 5. Debug Addon Deployment

If an addon is not deploying:

1. Check cluster secret has `enable_<addon>: "true"` label
2. Check `addons.yaml` has `enabled: true` for the ApplicationSet
3. Verify template resolution — check cluster secret annotations
4. Check ArgoCD Application events for sync errors

**Constraints:**
- You MUST distinguish between `enabled` (ApplicationSet creation) and `enable_<addon>` (cluster targeting) because they are different mechanisms
- You MUST check sync wave dependencies if addon fails to deploy

### 6. Autonomous incident remediation via the fleet-config overlay

When you (an agent) fix an addon problem by opening a Merge Request, you write to the
**fleet-config** repo — the `$overlay` source that addon ApplicationSets already reference
in their Helm `valueFiles`, last-wins over the `$defaults` (GitHub) base values, with
`ignoreMissingValueFiles: true` (so a file that does not exist yet can simply be **created**).

**⚠️ These `$overlay` (fleet-config) paths are root-relative and DIFFER from the `$defaults`
paths in the table above (which are prefixed `gitops/...`). In the fleet-config repo use:**

| Scope | Path in fleet-config (`$overlay`) |
|-------|-----------------------------------|
| All clusters (cluster-agnostic) | `configs/<addon>/values.yaml` |
| Per environment | `overlays/environments/<env>/<addon>/values.yaml` |
| Per cluster | `overlays/clusters/<exact-deployed-cluster-name>/<addon>/values.yaml` |

**Constraints:**
- You MUST create or edit **EXACTLY ONE** file — the narrowest that fixes the incident.
  You MUST NOT create multiple variants of the same file or guess alternate paths.
- You SHOULD **prefer the cluster-agnostic `configs/<addon>/values.yaml`** because it needs no
  cluster name (no short/full ambiguity) and covers all clusters — usually what you want when a
  controller fails on several clusters. Use a per-cluster overlay ONLY to deliberately scope to
  one cluster.
- **Cluster names are DYNAMIC** (they depend on the deployment's resource prefix; they are NOT
  always `peeks-e2e-*`). You MUST NOT hardcode, shorten, or guess a cluster name. An alert's
  `cluster` label may be a SHORT form (e.g. `spoke-dev`) that does NOT match the fleet-config
  path segment (e.g. `peeks-e2e-spoke-dev`); reconcile it to the REAL deployed cluster name
  (via your read-only tools / the environment's known names) before using it in a path.
- You MUST confirm the addon's real current value (e.g. the memory limit in the base values)
  with read-only tools before writing, so the change is a meaningful delta and the comment is
  accurate.
- You MUST NOT mutate the cluster directly — the fix ships as a Merge Request for human review.
- App workloads (not addons) already have their own manifest in fleet-config (e.g.
  `demo-oomkill/deployment.yaml`); edit that existing file, do NOT invent an overlay for them.

### 7. Idempotency and safe edits (CRITICAL — avoids duplicate/broken MRs)

Before you open an MR, and while you write the fix, follow these hard rules. They exist because
autonomous runs previously produced duplicate MRs and regressions.

**Idempotency — never open a duplicate MR:**
- You MUST, before creating ANY branch or MR, **list the OPEN merge requests** in the target
  repo (`state=opened`) and inspect their titles and changed files.
- An incident is ALREADY handled if an open MR edits the **same file** you would edit
  (e.g. `configs/<addon>/values.yaml`) or targets the **same addon/component**. Multiple alerts
  for the same component across different clusters are **ONE issue**, because
  `configs/<addon>/values.yaml` is cluster-agnostic.
- When a matching open MR exists you MUST NOT create another MR or branch. Instead, add a short
  comment on the EXISTING MR noting the extra affected cluster/pod, then STOP.
- Only open a new MR when NO open MR already addresses that file/component.

**Preserve existing files — never rewrite (anti-regression):**
- When the target values file ALREADY EXISTS, you MUST first READ its current content, then
  **ADD or MERGE only the keys you need**, keeping ALL existing content intact (existing
  `nodeSelector` pins, existing image redirects, etc.).
- You MUST NOT replace or rewrite the whole file. Dropping existing keys (e.g. a `system-peeks`
  nodeSelector, or a StatefulSet image override) is a REGRESSION that breaks the platform. Your
  diff MUST be minimal and purely additive to the relevant block.

**Verify the fix targets something real:**
- Before referencing any image/registry/artifact (e.g. an ECR repository), you MUST CONFIRM it
  actually exists with your read-only tools. Do not invent a registry path or tag.
- For a Helm chart that bundles a **subchart** (e.g. langfuse bundles minio under the `minio:`
  key), overrides for that subchart MUST be nested under the parent key (`minio.<...>`); a
  top-level sibling key (`minioMc:`, `minioInit:`) is silently ignored by the subchart.
