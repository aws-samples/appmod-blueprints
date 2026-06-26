# Multi-Repo GitOps Architecture

## Repository Layout

This workshop uses a multi-repo GitOps approach with clear separation of concerns:

| Repository | Location | Access | Purpose |
|---|---|---|---|
| `platform-on-eks-workshop/` | GitHub | **Read-only** | Platform source — charts, addons, bootstrap, registry |
| `fleet-config/` | GitLab | **Read-write** | Overlay customizations — user-editable |
| `java/`, `rust/`, `golang/`, `dotnet/`, `next-js/` | GitLab | **Read-write** | Application source code |

## Key Rule

> **Users must NOT modify `platform-on-eks-workshop/` directly.**
> All customizations go in `fleet-config/` on GitLab. ArgoCD merges both sources automatically.

## How ArgoCD Resolves Values

ArgoCD uses multi-source Applications with two refs:
- `$defaults/` → GitHub platform repo (addons, configs, overlays defaults)
- `$overlay/` → GitLab fleet-config repo (user overrides)

Resolution order (last wins):
1. `$defaults/<basepath>/addons/configs/<addon>/values.yaml` — Platform defaults
2. `$defaults/<basepath>/overlays/environments/<env>/<addon>/values.yaml` — Platform env defaults
3. `$defaults/<basepath>/overlays/clusters/<cluster>/<addon>/values.yaml` — Platform cluster defaults
4. `$overlay/configs/<addon>/values.yaml` — User global overrides
5. `$overlay/overlays/environments/<env>/<addon>/values.yaml` — User env overrides
6. `$overlay/overlays/clusters/<cluster>/<addon>/values.yaml` — User cluster overrides

All paths use `ignoreMissingValueFiles: true` — missing files are silently skipped.

## Fleet-Config Structure

```
fleet-config/
├── configs/
│   └── <addon>/values.yaml              # Global addon overrides
├── overlays/
│   ├── environments/
│   │   ├── control-plane/<addon>/values.yaml
│   │   ├── dev/<addon>/values.yaml
│   │   └── prod/<addon>/values.yaml
│   └── clusters/
│       └── <cluster>/<addon>/values.yaml
└── README.md
```

## Workflow for Users

1. Modify files in `fleet-config/` (cloned in `~/environment/fleet-config/`)
2. `git add`, `git commit`, `git push`
3. ArgoCD detects the change and syncs automatically

## Configuration

The overlay repo is connected via cluster secret annotations:
```yaml
overlay_repo_url: https://<gitlab-domain>/user1/fleet-config.git
overlay_repo_revision: main
overlay_repo_basepath: ""
```

These are written into the `<hub>/config` Secrets Manager secret by the
`hub:set-overlay-repo` task (which runs LATE in `task install`, after GitLab +
fleet-config exist), then reconciled by ESO onto the hub cluster secret and
passed to the addon ApplicationSets via `overlayRepoURLGit` / `valuesObject`.

## How the `$overlay` layer is activated (important)

The per-addon `$overlay/...` valueFiles (layers 4-6 above) are **only emitted by
the appset-chart when `overlay_repo_url` is set** on the cluster secret
(`{{- if $overlayRepoURLGit }}`). If `overlay_repo_url` is empty/unset:
- per-addon Applications resolve **only** `$defaults` (GitHub) value files;
- the `clusters` (crossplane) and `clusters-kro` ApplicationSets fall back to
  `fleetRepoURL` (GitHub), which does NOT contain user spoke definitions;
- so **every fleet-config override silently stops applying** even though the
  cluster secret/Applications still look healthy.

You can verify the overlay is live on the hub:
```bash
# SM config must carry overlay_repo_url (not null)
aws secretsmanager get-secret-value --secret-id <hub>/config --region <r> \
  --query SecretString --output text | jq -r '.metadata|fromjson|.overlay_repo_url'
# and the addon ApplicationSets should show an $overlay source pointing at GitLab
kubectl -n argocd get application <addon>-<cluster> \
  -o jsonpath='{range .spec.sources[*]}{.ref}={.repoURL}{"\n"}{end}'
```

## GOTCHA: re-seed must preserve `overlay_repo_url`

`secrets-manager:seed` (run by `hub:seed`, early in `task install`) rebuilds the
**entire** `<hub>/config` metadata from scratch and has **no `status:` guard**, so
it runs on every install. It must **re-merge** the existing
`overlay_repo_url`/`overlay_repo_revision`/`overlay_repo_basepath` from the current
secret, otherwise a re-install (or any second run) WIPES the overlay wiring that
`hub:set-overlay-repo` set on a previous run — disabling the whole fleet-config
overlay fleet-wide (and orphaning spokes that only exist in fleet-config). When
editing `secrets-manager:seed`, never drop the overlay-preservation read/merge.
Symptom of regression: `overlay_repo_url` is `null` in `<hub>/config` and addon
Applications show only `$defaults` sources.
