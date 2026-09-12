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
