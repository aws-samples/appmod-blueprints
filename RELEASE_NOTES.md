# Release Notes

## v0.2.7 (2026-05-08)

- Revert kro `omit()` change for tracking-id annotation (caused rendering issues)

---

## v0.2.6 (2026-05-07)

### Critical Fixes
- Push keycloak OIDC secrets directly to AWS SM from config Job (removes PushSecret race condition)
- Fix ROOTDIR calculation in deploy.sh — was `platform/infra` instead of repo root
- Push clean single-commit history to GitLab with `git init -b main`
- Use `git reset --hard origin/main` instead of `git pull --rebase` to sync IDE with GitLab
- Add `unzip` to config Job container for AWS CLI v2

### Improvements
- Add deployment architecture steering doc for IDE agent
- Use mise shims path for MCP servers in peeks agent config
- Add post-clone recovery script for git/NFS bootstrap failures
- Self-healing `argocd-refresh-token` with IDC-Keycloak auto-configuration
- Reorder zsh_history for better UX
- Improve Renovate regex to detect addon version bumps in addons.yaml
- Fix kro `omit()` for optional argocd tracking-id annotation
- Add download timeout to model prestage jobs
- Bump cni-metrics-helper to 1.21.1

### ArgoCD Drift Fixes
- Keycloak StatefulSet ignoreDifferences (pod template, volumeClaimTemplates, updateStrategy)
- Argo-rollouts CRD drift (conversion, preserveUnknownFields)

---

## v0.2.5 (2026-04-15)

- Fix Backstage kubernetes auth with long-lived SA token

---

## v0.2.4 (2026-04-15)

- Use EKS Capabilities for ACK/KRO on spoke clusters
- Harden IAM policies and rename progressive-app to rollout-demo
- Fix terraform destroy with `-refresh=false` after state rm
- Bump next.js to 15.5.15

---

## v0.2.3 (2026-04-12)

- Fix environment-specific AWS resource naming
- Fix KubeVela auto-reconciliation

---

## v0.2.2 (2026-04-03)

- Fix Playwright AWS Console onboarding tutorial handling
- Consolidate validation prompt
- Fix Renovate addons configuration
- Multiple dependency bumps (lodash, node-forge, handlebars, backstage plugins)

---

## v0.2.1 (2026-03-19)

- Add Spark to best-effort addon list
- Fix keycloak secret handling when value starts with `-`

---

## v0.2.0 (2026-03-18)

### Major Changes
- Platform updates for 2026 workshop season
- Fix external-secret ownership issues
- Make Argo Rollouts metrics analysis configurable
- Fix KubeVela publishVersion in CI/CD pipeline
- Add AWS_REGION env var to Kro and KubeVela deployment templates
- Fix pod identity race condition with init container wait
- Reduce KubeVela resync period
- Add display names to Kargo yaml-update steps
- Fix DORA pipeline
- Remove Kro-based deployment manifests for java dev/prod (use KubeVela)

---

## v0.1.5 (2026-02-03)

- Fix ArgoCD operation termination check
- Improve error handling in deploy scripts
- Dependency bumps (js-yaml, lodash)

---

## v0.1.4 (2026-02-02)

- Fix OpenTelemetry webhook readiness checks and wait dependency order
- Increase ArgoCD sync wave timeout from 30 to 45 minutes
- Multiple dependency bumps (vite, esbuild, backstage plugins)

---

## v0.1.3 (2026-01-29)

### Major Changes
- Riv25 evolution of the repository (#252)
- Add Ray Serve templates (CPU/GPU/Trainium)
- Workshop validation tools and infrastructure improvements
- Fix SOCI build workflow with containerd integration
- Dependency bumps (qs, lodash, tar)

---

## v0.1.2-riv25 (2026-01-09)

- Fix git tag handling to avoid switching to remote main
- Use tag name for branch creation instead of timestamp

---

## v0.1.1-riv25 (2026-01-08)

- Fix git tag detection in gitlab_repository_setup

---

## v0.1.0-riv25 (2026-01-08)

- Initial riv25 release
