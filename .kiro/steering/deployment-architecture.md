# Deployment Architecture & Pitfalls

## Deployment Ordering (Workshop Studio)

```
1. IDE UserData (bootstrap.sh) — installs tools, clones repo from GitHub
2. ClustersStackDeploy CodeBuild — Terraform: EKS clusters + Identity Center
3. BootstrapStackDeploy CodeBuild — Terraform: GitLab, hub addons, ArgoCD bootstrap
   - Pushes clean single-commit history to GitLab (git init -b main)
4. SSM Document (0-init.sh) — syncs IDE with GitLab, waits for ArgoCD, configures IDC
```

## ArgoCD Sync Waves

- Waves only order resources **within the same phase** (Sync or PostSync)
- A regular resource at wave 11 runs BEFORE a PostSync hook at wave 10
- PostSync hooks only run if the Sync phase succeeds
- ArgoCD can only "wait" for Jobs (polls until Complete/Failed)
- Non-Job resources as PostSync hooks (PushSecret, ExternalSecret) are checked immediately — if not ready, the operation fails

## Git & NFS

- IDE workspace is NFS-mounted (EFS) — long ref names break clone
- Clone to /tmp, strip .git, move files, reinit with `git init -b main`
- CodeBuild pushes clean history to GitLab (no GitHub dependabot refs)
- 0-init.sh uses `git reset --hard origin/main` to sync IDE (not pull --rebase)

## Keycloak Secret Flow

- Config Job (PostSync wave 10): creates realm, users, OIDC clients, K8s secret, AND pushes to AWS SM directly
- No PushSecret dependency — the SM push is synchronous in the Job
- Pod Identity on `keycloak-config` SA provides AWS credentials
- Downstream apps (backstage, argo-workflows) use ExternalSecrets to pull from SM

## Container Images in Jobs

- ubuntu:22.04 does NOT have: `unzip`, `aws` CLI, `kubectl`
- AWS CLI v2 requires `unzip`
- For Playwright/Chromium: need system libs (atk, libXcomposite, mesa-libgbm, etc.)

## KubeVela publishVersion

- KubeVela only re-renders child resources when `publishVersion` annotation changes
- Changing spec fields without bumping publishVersion has NO effect
- Always bump when modifying manifests without a new CI build:
  ```bash
  sed -i "s|app.oam.dev/publishVersion:.*|app.oam.dev/publishVersion: \"$(date +%s)\"|" deployment/dev/application.yaml
  ```
