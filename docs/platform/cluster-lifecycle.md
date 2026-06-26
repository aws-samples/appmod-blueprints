# Spoke Cluster Lifecycle (Enable / Delete) and Prune Safety

This document describes how spoke clusters are provisioned and removed in the
hub-and-spoke fleet, and the guardrails that prevent accidental cluster deletion.

## TL;DR

- Spoke clusters are declared **only** in the GitLab `fleet-config` overlay
  (`gitops/fleet/spoke-values/tenants/<tenant>/{kro,crossplane}-clusters/...`).
- The cluster-provisioning ApplicationSets run with **`prune: false`**. ArgoCD
  will **never auto-delete** a live cluster, even if the overlay momentarily
  renders without it.
- Enabling a spoke is declarative + automatic. **Deleting** a spoke is a
  **deliberate, explicit** action — never a side effect.

## Why prune is disabled on cluster appsets

Cluster definitions live only in the overlay. If the overlay is ever
**reachable-but-empty** — e.g. it gets re-seeded/reset, or `overlay_repo_url`
is transiently unset and apps fall back to the GitHub base where `clusters: {}` —
then with `prune: true` ArgoCD would see the cluster "removed from Git" and
**cascade-delete the live EKS cluster + VPC**. This actually happened during a
re-run of `task install` (the `hub:set-overlay-repo` step briefly unset the
overlay).

`allowEmpty: false` does **not** protect against this: it only blocks a sync that
renders the *entire* app to zero resources, not the removal of a single cluster
entry from an app that still renders other content.

Therefore the `clusters-kro` and `clusters` (crossplane) ApplicationSets in
`gitops/bootstrap/` set `prune: false`. See those files for the inline rationale.

## Enabling a spoke (declarative, automatic)

```bash
# KRO-provisioned spoke (ACK + multi-acct CARM)
task kind-crossplane:spokes:enable-kro -- <cluster-name>

# Crossplane-provisioned spoke
task kind-crossplane:spokes:enable-crossplane -- <cluster-name>
```

These write the cluster entry into the `fleet-config` overlay and push. ArgoCD
auto-syncs and provisions the cluster. The tasks are **idempotent** — re-running
them keeps existing CIDRs and does not churn the VPC.

## Deleting a spoke ON PURPOSE

Because auto-prune is off, removing a cluster from Git does **not** delete it.
Deletion is an explicit, two-part action: (1) remove from Git, (2) prune.

### Recommended: the disable tasks

```bash
# KRO spoke
task kind-crossplane:spokes:disable-kro -- <cluster-name>

# Crossplane spoke
task kind-crossplane:spokes:disable-crossplane -- <cluster-name>
```

What they do:
1. Remove the cluster entry from the `fleet-config` overlay (Git).
2. `argocd app get <app> --refresh` then print `argocd app diff` so you see
   exactly what will be deleted.
3. `argocd app sync <app> --prune` — the explicit destructive step.
4. (KRO only) After a successful prune, remove the `clusters/<name>.json`
   marker and the `multi-acct` CARM mapping, so the now-empty app is cleaned up.

> KRO ordering matters: the per-cluster app is `clusters-kro-<name>`, generated
> from the `clusters/<name>.json` marker. The appset uses
> `preserveResourcesOnDeletion: true`, so deleting the marker **before** pruning
> would *orphan* the `EksclusterWithVpc` instead of deleting it. The task removes
> the spec first, prunes through the still-existing app, then removes the marker.

### Manual equivalent

```bash
# 1. Remove the cluster from the overlay (fleet-config) and push.
# 2. Preview, then prune the owning app:
argocd app diff clusters-kro-<name>            # KRO: per-cluster app
argocd app sync clusters-kro-<name> --prune

argocd app diff clusters-workshop              # Crossplane: per-tenant app
argocd app sync clusters-workshop --prune
```

`--prune` forces pruning for that **single sync operation only**; it does not
change the Application's `prune: false` policy. Scope further with
`--resource <group>:<kind>:<name>` if needed.

If the ArgoCD CLI returns an auth error:

```bash
argocd-refresh-token && source ~/.bashrc.d/platform.sh
```

## What NOT to do

- **Don't flip `prune: true` then back.** While true, *any* transient empty
  render would delete **every** cluster in that appset — re-opening the exact
  hole this design closes.
- **Don't `kubectl delete` / `argocd app delete` while the cluster is still in
  Git.** Auto-sync is on, so ArgoCD will just recreate it. Remove it from Git
  first, then prune.
- For a **full environment teardown**, use `destroy.sh`, not prune. Prune is for
  selective, intentional removals.

## Related files

- `gitops/bootstrap/clusters-kro.yaml`, `gitops/bootstrap/clusters-crossplane.yaml`
  — the ApplicationSets (`prune: false` guardrail).
- `cluster-providers/kind-crossplane/Taskfile.yaml` — `spokes:enable-*` /
  `spokes:disable-*` tasks and the hardened `hub:set-overlay-repo`.
