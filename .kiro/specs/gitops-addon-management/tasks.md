# Implementation Plan: GitOps Addon Management

## Overview

Create a complete GitOps addon management platform under `gitops/` at the workspace root. The implementation adapts reference files from `reference-implementation-azure/packages/appset-chart/` and `appmod-blueprints/gitops/` into a new architecture with domain-split registries, selector-based enablement, and a two-phase Kind bootstrap. Each task builds incrementally, wiring components together at the end.

## Tasks

- [x] 1. Create appset-chart Helm chart with templates
  - [x] 1.1 Create Chart.yaml, .helmignore, and values.yaml for appset-chart
    - Create `gitops/charts/appset-chart/Chart.yaml` with chart metadata
    - Create `gitops/charts/appset-chart/.helmignore` based on reference
    - Create `gitops/charts/appset-chart/values.yaml` with global defaults (repoURLGit, repoURLGitRevision, repoURLGitBasePath, valueFiles, useSelectors, appsetPrefix, namespace, syncPolicy, syncPolicyAppSet)
    - _Requirements: 1.1, 1.2, 17.1_

  - [x] 1.2 Create _helpers.tpl template
    - Create `gitops/charts/appset-chart/templates/_helpers.tpl` adapted from `reference-implementation-azure/packages/appset-chart/templates/_helpers.tpl`
    - Include name normalization helper (underscores to hyphens, truncate to 63 chars)
    - _Requirements: 1.3_

  - [x] 1.3 Create _application_set.tpl partial template
    - Create `gitops/charts/appset-chart/templates/_application_set.tpl` adapted from Azure reference
    - Implement `additionalResources` as list iteration (not single object)
    - Support manifest-type, chart-type, and path-type additional resources
    - Include Helm releaseName, valuesObject, and valueFiles per additional resource
    - _Requirements: 2.4, 2.5_

  - [x] 1.4 Create _git_matrix.tpl partial template
    - Create `gitops/charts/appset-chart/templates/_git_matrix.tpl` adapted from Azure reference
    - Support matrixPath and matrixValues configuration
    - _Requirements: 16.1, 16.2_

  - [x] 1.5 Create _pod_identity.tpl partial template
    - Create `gitops/charts/appset-chart/templates/_pod_identity.tpl` adapted from Azure reference
    - Support flexible sourcing for pod-identity (not hardcoded paths)
    - _Requirements: 2.1_

  - [x] 1.6 Create application-set.yaml main template
    - Create `gitops/charts/appset-chart/templates/application-set.yaml` adapted from Azure reference
    - Iterate over `.Values` entries using `namespace` key as iteration check (not `enabled`)
    - Render one ApplicationSet per addon entry with `namespace` key
    - Skip entries without `namespace` key
    - Normalize ApplicationSet name: replace underscores with hyphens, truncate to 63 chars
    - Prepend `appsetPrefix` to ApplicationSet names when configured
    - Include Application template labels: addonVersion, addonName, environment, clusterName, kubernetesVersion
    - Support configurable `project` per addon (default to "default")
    - Render `annotationsApp` on generated Application template
    - Render `annotationsAppSet` on ApplicationSet metadata (sync-wave)
    - Support Helm chart source (chartRepository + defaultVersion)
    - Support git path-based source (path field)
    - Support directory block when both path and directory are specified
    - Fix duplicate ignoreDifferences bug: use `with` block to render exactly once
    - Support `selector.matchExpressions` for cluster matching
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 2.1, 2.2, 2.3, 3.1, 3.2, 7.3, 14.1_

  - [ ]* 1.7 Write property tests for appset-chart using helm-unittest
    - **Property 1: ApplicationSet-Registry Bijection** — verify count of rendered ApplicationSets equals count of entries with `namespace` key
    - **Property 2: ApplicationSet Name Normalization** — verify underscores replaced, 63 char limit, appsetPrefix applied
    - **Property 3: Application Template Required Labels** — verify addonVersion, addonName, environment, clusterName, kubernetesVersion labels present
    - **Property 4: Application Project Default** — verify project field or "default" fallback
    - **Property 5: Source Type Selection** — verify Helm vs git path vs manifest source rendering
    - **Property 6: Directory Source Preservation** — verify directory block included when path+directory specified
    - **Property 7: AdditionalResources List Cardinality** — verify N items produce N additional sources
    - **Property 8: No Duplicate ignoreDifferences** — verify at most one ignoreDifferences block per ApplicationSet
    - **Property 15: Sync-Wave Annotation Rendering** — verify annotationsAppSet rendered on ApplicationSet metadata
    - **Validates: Requirements 1.1-1.7, 2.1-2.5, 3.1-3.2, 14.1**

- [x] 2. Checkpoint - Ensure appset-chart templates are valid
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 3. Create addon registry domain files
  - [x] 3.1 Create _defaults.yaml with shared configuration
    - Create `gitops/addons/registry/_defaults.yaml`
    - Include shared syncPolicy, repoURL template expressions, valueFiles, useSelectors, and other global defaults
    - _Requirements: 4.2, 8.1_

  - [x] 3.2 Create core.yaml domain file
    - Create `gitops/addons/registry/core.yaml`
    - Include entries for: argocd, metrics-server, ingress-nginx, cert-manager, external-secrets
    - Each entry must have `namespace` key, `selector.matchExpressions` with `enable_<addon>`, and `annotationsAppSet` with sync-wave
    - No `enabled` field on any entry
    - Adapt entries from `appmod-blueprints/gitops/addons/bootstrap/default/addons.yaml`
    - _Requirements: 4.1, 4.3, 4.4, 14.2_

  - [x] 3.3 Create gitops.yaml domain file
    - Create `gitops/addons/registry/gitops.yaml`
    - Include entries for: argo-workflows, argo-events, argo-rollouts, kargo, flux
    - Same structure as core.yaml with appropriate sync-waves
    - _Requirements: 4.1, 4.3, 4.4, 14.2_

  - [x] 3.4 Create security.yaml domain file
    - Create `gitops/addons/registry/security.yaml`
    - Include entries for: keycloak, kyverno, cert-manager policies
    - _Requirements: 4.1, 4.3, 4.4, 14.2_

  - [x] 3.5 Create observability.yaml domain file
    - Create `gitops/addons/registry/observability.yaml`
    - Include entries for: grafana, grafana-operator, grafana-dashboards, otel
    - _Requirements: 4.1, 4.3, 4.4, 14.2_

  - [x] 3.6 Create platform.yaml domain file
    - Create `gitops/addons/registry/platform.yaml`
    - Include entries for: crossplane, crossplane-aws, backstage, kro, kro-manifests, platform-manifests, platform-manifests-bootstrap, multi-acct
    - _Requirements: 4.1, 4.3, 4.4, 14.2_

  - [x] 3.7 Create ml.yaml domain file
    - Create `gitops/addons/registry/ml.yaml`
    - Include entries for: jupyterhub, kubeflow, mlflow, ray-operator, spark-operator, airflow
    - _Requirements: 4.1, 4.3, 4.4, 14.2_

  - [ ]* 3.8 Write validation tests for registry domain files
    - **Property 9: Registry Entries Omit Enabled Field** — verify no entry contains `enabled` field
    - **Property 13: Selector-Enablement Pattern Consistency** — verify all selectors use `matchExpressions` with `enable_<addon>`, `operator: In`, `values: ['true']`
    - **Validates: Requirements 4.3, 4.4, 7.3**

- [ ] 4. Create fleet-secret chart with enable_* label generation
  - [x] 4.1 Create fleet-secret Chart.yaml and values.yaml
    - Create `gitops/charts/fleet-secret/Chart.yaml` with chart metadata
    - Create `gitops/charts/fleet-secret/values.yaml` with externalSecret defaults and empty enabledAddons map
    - Adapt from `appmod-blueprints/gitops/fleet/charts/fleet-secret/`
    - _Requirements: 5.1, 12.1_

  - [x] 4.2 Create fleet-secret templates (_helpers.tpl and external-secret.yaml)
    - Create `gitops/charts/fleet-secret/templates/_helpers.tpl` adapted from reference
    - Create `gitops/charts/fleet-secret/templates/external-secret.yaml` adapted from reference
    - Add `enabledAddons` range loop to generate `enable_*` labels on the cluster secret
    - Ensure `argocd.argoproj.io/secret-type: cluster` label is always present
    - Labels are additive (don't remove existing labels)
    - Addons with `false` value produce no label (absence = disabled)
    - _Requirements: 5.1, 5.2, 5.3, 5.4_

  - [ ]* 4.3 Write property tests for fleet-secret chart
    - **Property 10: Addon-Secret Label Consistency** — verify `enable_<addon>: 'true'` present iff addon value is true
    - **Property 11: Cluster Secret Type Label Invariant** — verify `argocd.argoproj.io/secret-type: cluster` always present
    - **Validates: Requirements 5.1, 5.2, 5.3**

- [x] 5. Checkpoint - Ensure charts and registry are valid
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 6. Create overlays and fleet member structure
  - [x] 6.1 Create environment overlay with enabled-addons.yaml
    - Create `gitops/overlays/environments/control-plane/enabled-addons.yaml` with enabledAddons map
    - All addon keys use underscores matching `enable_<addon>` convention
    - All values are boolean true/false
    - List all known addons explicitly
    - _Requirements: 6.1, 13.1, 13.2, 13.3_

  - [x] 6.2 Create cluster overlay placeholder structure
    - Create `gitops/overlays/clusters/.gitkeep` placeholder
    - Create example `gitops/overlays/environments/control-plane/overrides.yaml` for environment-level value overrides
    - Create example `gitops/overlays/clusters/.gitkeep` for cluster-level overrides
    - _Requirements: 6.2, 8.5, 17.2_

  - [x] 6.3 Create fleet member hub values file
    - Create `gitops/fleet/members/hub/values.yaml` with externalSecret configuration
    - Include clusterName, server, annotations (addonsRepoURL, addonsRepoRevision, addonsRepoBasepath, AWS metadata), and labels (environment, fleet_member, kubernetesVersion)
    - _Requirements: 12.1, 12.2, 12.3, 12.4_

  - [ ]* 6.4 Write validation tests for enabled-addons and fleet member files
    - **Property 16: Enabled Addons Map Validation** — verify keys match `[a-z][a-z0-9_]*` pattern and values are boolean
    - **Property 17: Fleet Member Schema Validation** — verify externalSecret with clusterName, server, required labels
    - **Validates: Requirements 12.2, 12.3, 13.1, 13.2**

- [ ] 7. Create bootstrap ApplicationSets (Phase 2 — Hub)
  - [x] 7.1 Create root-appset.yaml
    - Create `gitops/bootstrap/root-appset.yaml` as the single entry-point ApplicationSet
    - Deploy three child ApplicationSets: fleet-secrets, addons, clusters
    - _Requirements: 9.1_

  - [x] 7.2 Create addons.yaml bootstrap ApplicationSet
    - Create `gitops/bootstrap/addons.yaml`
    - Use clusters generator matching `fleet_member: control-plane`
    - Include all registry domain files as valueFiles in correct layering order: _defaults → core → gitops → security → observability → platform → ml → environment overlay → cluster overlay
    - Set `ignoreMissingValueFiles: true`
    - Render appset-chart with the layered valueFiles
    - _Requirements: 9.2, 8.1, 8.5_

  - [x] 7.3 Create fleet-secrets.yaml bootstrap ApplicationSet
    - Create `gitops/bootstrap/fleet-secrets.yaml`
    - Use matrix generator combining clusters and git directories for fleet/members/
    - Render fleet-secret chart per fleet member
    - Include environment's `enabled-addons.yaml` in valueFiles
    - _Requirements: 9.3, 9.4_

  - [x] 7.4 Create clusters.yaml bootstrap ApplicationSet
    - Create `gitops/bootstrap/clusters.yaml`
    - Deploy KRO-based cluster provisioning
    - _Requirements: 9.1_

- [ ] 8. Create bootstrap-kind files (Phase 1 — Ephemeral)
  - [x] 8.1 Create Taskfile.yml for bootstrap orchestration
    - Create `gitops/bootstrap-kind/Taskfile.yml`
    - Implement `install` task: kind create cluster, helm install argocd, helm install appset-chart with bootstrap-addons.yaml, wait-for-hub, kind delete cluster
    - Implement `destroy` / `destroy-kind` tasks
    - Implement `status` task for monitoring
    - _Requirements: 10.1, 10.6_

  - [x] 8.2 Create kind.yaml and config.yaml
    - Create `gitops/bootstrap-kind/kind.yaml` with Kind cluster configuration
    - Create `gitops/bootstrap-kind/config.yaml` with user configuration template (AWS region, repo URL, account ID, hub cluster settings)
    - _Requirements: 10.1, 17.4_

  - [x] 8.3 Create argocd-values.yaml
    - Create `gitops/bootstrap-kind/argocd-values.yaml` with ArgoCD Helm values for Kind phase
    - _Requirements: 10.1_

  - [x] 8.4 Create bootstrap-addons.yaml
    - Create `gitops/bootstrap-kind/bootstrap-addons.yaml` with addon registry for Kind phase
    - Include Crossplane, External Secrets Operator, ArgoCD entries
    - _Requirements: 10.2_

  - [x] 8.5 Create hub-seed.yaml
    - Create `gitops/bootstrap-kind/hub-seed.yaml` as seed ApplicationSet to bootstrap hub
    - Deploy ArgoCD and bootstrap/ ApplicationSets to the hub cluster
    - _Requirements: 10.5_

  - [x] 8.6 Create manifests/ directory structure
    - Create `gitops/bootstrap-kind/manifests/argocd/` with repo credentials and project manifests
    - Create `gitops/bootstrap-kind/manifests/crossplane/` with provider configs, compositions, and claims for VPC, EKS, IAM
    - Create `gitops/bootstrap-kind/manifests/external-secrets/` with SecretStore and ExternalSecret for hub kubeconfig
    - Create `gitops/bootstrap-kind/manifests/credentials/` with template for AWS credentials secret
    - _Requirements: 10.2, 10.3, 10.4, 11.1, 17.4_

- [x] 9. Checkpoint - Ensure all bootstrap files are valid
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 10. Create abstractions placeholder structure
  - [x] 10.1 Create abstractions directory with placeholder files
    - Create `gitops/abstractions/.gitkeep` placeholder for future KRO abstractions
    - _Requirements: 17.1_

- [ ] 11. Wire everything together and validate end-to-end structure
  - [x] 11.1 Validate complete directory structure
    - Verify all required directories exist: `gitops/addons/registry/`, `gitops/bootstrap/`, `gitops/bootstrap-kind/`, `gitops/charts/appset-chart/`, `gitops/charts/fleet-secret/`, `gitops/fleet/members/`, `gitops/overlays/`, `gitops/abstractions/`
    - Verify all required files are present per Requirements 17.1-17.4
    - Verify cross-references between bootstrap ApplicationSets and chart/registry paths are consistent
    - _Requirements: 17.1, 17.2, 17.3, 17.4_

  - [ ]* 11.2 Write integration validation tests
    - Run `helm template` on appset-chart with registry domain files as values to verify end-to-end rendering
    - Run `helm template` on fleet-secret chart with sample enabled-addons to verify label generation
    - Verify value layering order produces correct merged output
    - **Property 14: Value Layering Precedence** — verify later files override earlier files for same keys
    - **Validates: Requirements 8.1-8.5, 15.2**

- [x] 12. Final checkpoint - Ensure all files are created and valid
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- All files are created under `gitops/` at the workspace root
- Reference implementations in `reference-implementation-azure/` and `appmod-blueprints/` should be adapted, not copied verbatim
- The appset-chart is the most complex component — task 1 should be completed carefully before proceeding
