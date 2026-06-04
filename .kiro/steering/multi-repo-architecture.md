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

These are set by the `hub:seed` task during bootstrap and passed to the `cluster-addons` ApplicationSet via `valuesObject`.
