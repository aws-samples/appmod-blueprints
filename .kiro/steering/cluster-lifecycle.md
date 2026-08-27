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
  /crossplane, in `gitops/bootstrap/`) are hardened with deliberate guardrails —
  do NOT weaken them (each is a documented two-way door in the appset YAML):
    - `prune: false` and `selfHeal: false` on the generated Apps.
    - `syncPolicy.applicationsSync: create-update` — the appset may create/update
      Apps but NEVER delete them, so a transient empty/failed generation cannot
      remove a cluster.
    - the Application template carries **NO**
      `resources-finalizer.argocd.argoproj.io` — deleting an App orphans
      (preserves) the live cluster instead of cascade-deleting it.
- App naming: KRO = one app **per cluster** (`clusters-kro-<name>`); Crossplane =
  one app **per tenant** (`clusters-<tenant>`, e.g. `clusters-workshop`).

## Why these guardrails exist (do not "fix" them)

Cluster specs live only in the overlay. If the overlay is ever
reachable-but-empty (re-seed/reset, or `overlay_repo_url` transiently unset so
apps fall back to the base `clusters: {}`), an unguarded appset would
cascade-delete a live EKS cluster + VPC. `allowEmpty: false` does NOT prevent it
(it only blocks a fully-empty render, not removal of one cluster entry).

Two real incidents shaped these guardrails:
1. A `prune: true` + `hub:set-overlay-repo` re-run pruned a live cluster → fixed
   with `prune: false` and by hardening `hub:set-overlay-repo` (it skips when the
   overlay is already wired, and on a failed flip restores the previous overlay
   instead of dropping to base).
2. A generator change created a brief empty generation; the appset removed the
   cluster's App, and because the App template still had
   `resources-finalizer.argocd.argoproj.io`, ArgoCD cascade-deleted the live
   `EksclusterWithVpc` → EKS cluster + VPC. `preserveResourcesOnDeletion: true`
   did NOT save it (the per-App finalizer wins). Fixed by removing the finalizer
   from the template AND setting `applicationsSync: create-update` so the appset
   can never delete an App. Recovery from the resulting stuck tombstones is in
   `troubleshooting.md` → "Spoke Cluster Stuck Deletion / Recovery".
3. `secrets-manager:seed` (run by `hub:seed`, early in `task install`, no
   `status:` guard) rebuilt `<hub>/config` from scratch and dropped
   `overlay_repo_url` — so a re-install unset the overlay, apps fell back to the
   GitHub base (`clusters: {}` + `$defaults`-only values), and the whole
   fleet-config layer went dark. Fixed by making `secrets-manager:seed`
   re-merge the existing `overlay_repo_url`/`overlay_repo_revision`/
   `overlay_repo_basepath` before rewriting (see multi-repo-architecture.md →
   "GOTCHA: re-seed must preserve overlay_repo_url"). The cluster guardrails
   above are what kept the live spokes alive while the overlay was unset.

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
- Deletion is now explicit-only: removing the `clusters/<name>.json` marker (or a
  values entry) does NOT delete the App (`applicationsSync: create-update`) and
  never cascade-deletes the cluster (no `resources-finalizer`). To actually tear a
  cluster down: remove it from the overlay, then run an explicit
  `argocd app delete clusters-kro-<name> --cascade` (or delete the
  `EksclusterWithVpc`/claim, then the App). See the DELETION RUNBOOK comment in the
  appset YAML, or the disable tasks above.
- Treat any prune/delete of a live cluster as high-risk: remove from Git, show
  the diff, and confirm before syncing with `--prune`.
- For full teardown use `destroy.sh`, never prune.
- ArgoCD CLI auth errors: `argocd-refresh-token && source ~/.bashrc.d/platform.sh`.
