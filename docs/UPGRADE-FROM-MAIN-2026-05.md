# Upgrade Plan: Port `origin/main` Updates into `feature/cloudfront-on-agent-platform`

**Date:** 2026-05-29
**Source branch:** `origin/main` @ `289f3c8c` (PR #692)
**Target branch:** `feature/cloudfront-on-agent-platform` @ `ca6e4649`
**Merge-base:** `b219604e` (PR #570)
**Branch divergence at start:** 173 ahead, 98 behind main

## Status

- ✅ Phase 1 — Chart version bumps (commits `5209db8c`, `85f4ba5f`, `17e8adac`, `b6519ded`, `01642006`, `70539d8b`)
- ✅ Phase 2 — ESO pod identity policy fix (commit `21027cc2`)
- ✅ Phase 3 — Chart template ports (commits `e7af10d0`, `95e36f4c`, `77b48d4d`, `53ef6b5c`, `4cc2f2a1`, `1fb85f0a`)
- ✅ Phase 4 — Terraform / scripts (commits `67e0cf62`, `5bb97ca5`)
- ⏳ Phase 5 — Validation (deploy + smoke test, requires cluster access)
- ⏳ Phase 6 — `external-secrets` schema reconciliation (deferred sub-task per user direction)

15 commits applied. 31 files changed, 735 insertions, 265 deletions.

## Deviations from the original plan

| Item | Plan said | Outcome | Reason |
|---|---|---|---|
| `aws-for-fluentbit` version bump | 0.1.34 → 0.2.0 in `observability.yaml` | **Skipped** | Feature was already at `0.2.0` (ahead of main's prior state) |
| `ack-ecr` / `ack-s3` regression fix | Not in plan | **Added** to Phase 1e | Discovered feature had regressed `ack-ecr 1.0.19` (vs main `1.5.1`) and `ack-s3 1.0.14` (vs main `1.3.1`) at the registry split — fixed in same `platform.yaml` commit |
| `kro/resource-groups/manifests/appmod-service.yaml` rateInterval port | Plan listed it as 3-way merge | **Skipped** | Feature branch removed the CEL `evaluationCriteria` mechanism that main's change extends. Not portable. The kubevela `appmod-service.yaml` rateInterval port was applied (commit `77b48d4d`). |
| `mlflow` 1.7.2 → 1.8.1 | Plan listed in `ml.yaml` | **Skipped** | Feature uses a local wrapper chart with subchart `mlflow:0.7.19` (different version track from upstream's 1.x line). Needs manual review of how to bump the wrapper. |
| Backstage `startupProbe` path | Plan said port main's `/.backstage/health/v1/readiness` | **Kept feature's** `/backstage/api/catalog/entities/by-query?limit=0` | Feature deliberately changed it (commit ca6e4649). Both branches modified the same line; feature's choice is more recent and intentional. |
| Backstage spoke clusters | Plan said apply main's parameterization | **Applied + documented** | Added `spoke_clusters: []` default in `values.yaml` so the new `{{- range .Values.spoke_clusters }}` blocks render safely with no input (hub-only mode preserved). |

## Why this porting is needed

Since the merge-base, `main` has received **chart version bumps for 19 addons**, **5 chart-template fixes**, an **ESO pod-identity policy security fix**, and **16 Terraform/script updates**. The feature branch independently restructured the addons layout (registry split, `default/addons` → `configs`, `crossplane-aws` refactored to `crossplane-base` + `crossplane-pod-identity`, ingress-nginx moved to direct Terraform install), so a straight merge is not viable — each change must be ported to its new location in the feature branch.

The set of enabled addons (`hub-config.yaml`) is identical between both branches.

## Structural mapping (main → feature)

| Subject | Path in main | Path in feature |
|---|---|---|
| Chart versions registry | `gitops/addons/bootstrap/default/addons.yaml` | `gitops/addons/registry/{core,gitops,ml,observability,platform,security}.yaml` |
| Default addon values | `gitops/addons/default/addons/<addon>/values.yaml` | `gitops/addons/configs/<addon>/values.yaml` |
| Helm chart templates | `gitops/addons/charts/<addon>/` | `gitops/addons/charts/<addon>/` (same) |
| ESO pod-identity policy | `gitops/addons/default/addons/external-secrets/pod-identity/values.yaml` | `gitops/addons/charts/crossplane-pod-identity/values.yaml` |
| `crossplane-aws` addon | dedicated | refactored into `crossplane-base` + `crossplane-pod-identity` |
| ingress-nginx install | ArgoCD ApplicationSet | direct Terraform (`platform/infra/terraform/common/ingress-nginx.tf`) |

---

## Phase 1 — Chart version bumps (registry files)

One commit per registry file (6 files, 6 commits) so each is reviewable in isolation. Status: **TODO**.

### `core.yaml`
- [ ] argocd: `7.9.1` → `9.5.12`
- [ ] external-secrets: `0.19.2` → `2.4.1` *(major rebrand — see Phase 6 sub-task for values schema reconciliation)*
- [ ] metrics-server: `3.12.1` → `3.13.0`
- [ ] aws-efs-csi-driver: `3.0.7` → `4.1.0`
- [ ] cert-manager: `v1.15.2` → `v1.20.2`
- [ ] external-dns: `1.14.5` → `1.21.1`

### `observability.yaml`
- [ ] aws-for-fluentbit: → `0.2.0`
- [ ] opentelemetry-operator: `0.71.1` → `0.112.1`
- [ ] cni-metrics-helper: `1.19.2` → `1.21.1`
- [ ] kube-state-metrics: `5.25.1` → `7.3.0`
- [ ] prometheus-node-exporter: `4.39.0` → `4.55.0`

### `gitops.yaml`
- [ ] argo-rollouts: `2.39.5` → `2.40.9`
- [ ] argo-events: `2.4.20` → `2.4.21`

### `security.yaml`
- [ ] kyverno: `3.3.6` → `3.8.0`
- [ ] kyverno-policies: `3.3.6` → `3.8.0`
- [ ] kyverno-policy-reporter: `3.1.0` → `3.7.4`

### `platform.yaml`
- [ ] crossplane: `2.2.0` → `2.2.1`

### `ml.yaml`
- [ ] mlflow: `1.7.2` → `1.8.1`

### Special case — `ingress-nginx`
- [ ] Bump in `platform/infra/terraform/common/ingress-nginx.tf` (or its Helm release): `4.12.2` → `4.15.1`

---

## Phase 2 — ESO pod identity policy (security fix)

Source: main commit `7aa70cd6` (`fix(external-secrets): add DeleteResourcePolicy permission to pod identity`).

Target file: `gitops/addons/charts/crossplane-pod-identity/values.yaml` (refactored location).

Add the missing IAM actions to ESO's pod identity policy:
- [ ] `secretsmanager:BatchGetSecretValue`
- [ ] `secretsmanager:ListSecretVersionIds`
- [ ] `secretsmanager:GetResourcePolicy`
- [ ] `secretsmanager:DeleteSecret` (with `secretsmanager:ResourceTag/managed-by == external-secrets` condition)
- [ ] `secretsmanager:DeleteResourcePolicy`
- [ ] `kms:Decrypt` on `key/*`
- [ ] `ssm:DescribeParameters`, `ssm:GetParametersByPath`, `ssm:GetParameters`, `ssm:GetParameter`

One commit.

---

## Phase 3 — Chart template ports (3-way merges)

Both feature and main modified these. Each is a separate commit. Order = lowest blast radius first.

| # | File | feat / main commits | Source change in main | Status |
|---|---|---|---|---|
| 1 | `gitops/addons/charts/gitlab/templates/gitlab.yaml` | 2 / 1 | remove mattermost (deprecated in GitLab 19.0) — `4a6025c4` | [ ] |
| 2 | `gitops/addons/charts/ray-operator/templates/model-prestage-job.yaml` | 1 / 1 | add download timeout for stall detection — `85d8d8ba` | [ ] |
| 3 | `gitops/addons/charts/kro/resource-groups/manifests/appmod-service.yaml` | 0 / 1 | use `omit()` instead of `orValue("")` for argocd tracking-id — `d8de7174`/`9eb93344` | [ ] |
| 4 | `gitops/addons/charts/kubevela/templates/components/appmod-service.yaml` | 0 / 1 | rateInterval support for counter metrics — `6790377d` | [ ] |
| 5 | `gitops/addons/charts/keycloak/templates/install.yaml` | 2 / 3 | StatefulSet drift fixes — `014e117a`, `a85cfe73`, `4f1136b2` | [ ] |
| 6 | `gitops/addons/charts/keycloak/templates/keycloak-config.yaml` | 6 / 5 | push secrets directly to SM, AWS CLI v2 install, PushSecret hook policy — multiple commits | [ ] |
| 7 | `gitops/addons/charts/backstage/templates/install.yaml` | 4 / 8 | force Keycloak OIDC, disable guest auth, RGD cleanup — `1d718191`, `edb24211`, `4639d8e5`, `206b02d3` | [ ] |

For each, perform a per-file 3-way merge:
- `base` = file at merge-base `b219604e`
- `ours` = `HEAD` (feature)
- `theirs` = `origin/main`

Validate by running `helm template` on the affected chart after merge.

---

## Phase 4 — Terraform / scripts (clean ports)

Feature branch has **not** modified any of these files (`feat=0` everywhere), so each can be applied with `git checkout origin/main -- <file>`. Group into two commits.

### Commit 4a — Provider pins + module updates
- [ ] `platform/infra/terraform/cluster/main.tf`
- [ ] `platform/infra/terraform/cluster/destroy.sh` (+27 lines)
- [ ] `platform/infra/terraform/cluster/versions.tf` (pin AWS provider `>= 6.42.0, <= 6.46.0`)
- [ ] `platform/infra/terraform/common/versions.tf` (same pin)
- [ ] `platform/infra/terraform/common/gitlab_infra/versions.tf`
- [ ] `platform/infra/terraform/identity-center/versions.tf`
- [ ] `platform/infra/terraform/common/deploy.sh`
- [ ] `platform/infra/terraform/common/pod-identity.tf` (+5 lines)
- [ ] `platform/infra/terraform/common/variables.tf`
- [ ] `platform/infra/terraform/common/gitlab_infra/main.tf`

### Commit 4b — Scripts
- [ ] `platform/infra/terraform/scripts/0-init.sh` (significant refactor, +116)
- [ ] `platform/infra/terraform/scripts/2-gitlab-init.sh`
- [ ] `platform/infra/terraform/scripts/argocd-utils.sh`
- [ ] `platform/infra/terraform/scripts/argocd_token_automation.py`
- [ ] `platform/infra/terraform/scripts/fix-bootstrap-post-clone.sh` (NEW)
- [ ] `platform/infra/terraform/scripts/utils.sh` (+107 lines)

Validate with `terraform validate` + `terraform plan` (no apply at this stage).

---

## Phase 5 — Validation

- [ ] `argocd-sync` and confirm all ApplicationSets sync without errors
- [ ] All ArgoCD applications Healthy & Synced
- [ ] Run validation in `platform/validation/cluster/`
- [ ] Smoke tests: Backstage login (Keycloak OIDC), GitLab login, Argo Workflows UI, Grafana, Crossplane provider health
- [ ] Verify ESO can read & write secrets to/from AWS Secrets Manager (incl. delete with tag)

---

## Phase 6 — `external-secrets` schema reconciliation (sub-task)

Reconcile values for the major version jump `0.19.2 → 2.4.1`:
- [ ] Cross-check `gitops/addons/configs/external-secrets/values.yaml` against the [external-secrets v2 chart values schema](https://github.com/external-secrets/external-secrets/tree/main/deploy/charts/external-secrets)
- [ ] Migrate any deprecated/renamed keys
- [ ] Confirm with `helm template` against the new chart version

---

## Out of scope (intentionally left in feature branch)

These are feature-branch-specific changes, not present in main; they remain unchanged:
- `agent-gateway` addon (the entire feature)
- `crossplane-base` + `crossplane-pod-identity` (refactor of `crossplane-aws`)
- `pod-identity-restart-hook` chart
- `aws-load-balancer-controller` registry entry
- `cw-prometheus` chart
- `observability-aws` chart
- Registry split itself (`gitops/addons/registry/*.yaml`)
- ingress-nginx via Terraform (instead of GitOps)

## Rollback strategy

Each phase is a single commit (or small commit group). To roll back any phase, `git revert <commit>` and re-sync ArgoCD. Phases 1-3 affect cluster state via ArgoCD only; Phase 4 affects Terraform state — re-run `deploy.sh` after revert.
