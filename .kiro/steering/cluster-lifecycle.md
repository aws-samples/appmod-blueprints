---
inclusion: auto
---

# Spoke Cluster Lifecycle and Prune Safety

How spoke clusters are created and deleted in the hub-and-spoke fleet, and the
guardrails that prevent accidental deletion. Full details:
`docs/platform/cluster-lifecycle.md`.

## Key facts

- Spoke clusters are declared **only** in the GitLab `fleet-config` overlay:
  `gitops/fleet/spoke-values/tenants/<tenant>/{kro,crossplane}-clusters/...`.
  The GitHub base repo ships `clusters: {}` (empty).
- The cluster-provisioning ApplicationSets (`clusters-kro` and `clusters`
  /crossplane, in `gitops/bootstrap/`) run with **`prune: false`** and
  `selfHeal: false`. This is a deliberate guardrail — do NOT set it back to
  `prune: true`.
- App naming: KRO = one app **per cluster** (`clusters-kro-<name>`); Crossplane =
  one app **per tenant** (`clusters-<tenant>`, e.g. `clusters-workshop`).

## Why prune is false (do not "fix" this)

Cluster specs live only in the overlay. If the overlay is ever
reachable-but-empty (re-seed/reset, or `overlay_repo_url` transiently unset so
apps fall back to the base `clusters: {}`), `prune: true` would cascade-delete a
live EKS cluster + VPC. This happened once via the `hub:set-overlay-repo` step
during a `task install` re-run. `allowEmpty: false` does NOT prevent it (it only
blocks a fully-empty render, not removal of one cluster entry).

`hub:set-overlay-repo` is also hardened: it skips when the overlay is already
wired, and on a failed flip it restores the previous overlay instead of dropping
to base.

## Enabling a spoke (declarative, automatic, idempotent)

```bash
task kind-crossplane:spokes:enable-kro -- <cluster-name>
task kind-crossplane:spokes:enable-crossplane -- <cluster-name>
```

## Deleting a spoke (must be DELIBERATE)

Removing a cluster from Git does NOT delete it (prune is off). Use the disable
tasks, which remove from the overlay then run an explicit scoped prune:

```bash
task kind-crossplane:spokes:disable-kro -- <cluster-name>
task kind-crossplane:spokes:disable-crossplane -- <cluster-name>
```

Manual equivalent (after removing the cluster from the overlay and pushing):

```bash
argocd app diff <app> && argocd app sync <app> --prune
#   KRO:        <app> = clusters-kro-<name>
#   Crossplane: <app> = clusters-<tenant> (e.g. clusters-workshop)
```

`--prune` forces a one-off prune for that operation only; it does not change the
`prune: false` policy.

### Rules for the assistant

- Never enable `prune: true` on the cluster appsets to "make a delete work" — use
  a one-off `argocd app sync <app> --prune` instead.
- KRO ordering: prune through the still-existing `clusters-kro-<name>` app BEFORE
  removing the `clusters/<name>.json` marker. The appset has
  `preserveResourcesOnDeletion: true`, so removing the marker first ORPHANS the
  `EksclusterWithVpc` rather than deleting it.
- Treat any prune/delete of a live cluster as high-risk: remove from Git, show
  the diff, and confirm before syncing with `--prune`.
- For full teardown use `destroy.sh`, never prune.
- ArgoCD CLI auth errors: `argocd-refresh-token && source ~/.bashrc.d/platform.sh`.
