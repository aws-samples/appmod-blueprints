# Requirements Document

## Introduction

This document defines the requirements for a GitOps-based addon management platform for Kubernetes clusters. The system uses ArgoCD ApplicationSets, a unified Helm chart (appset-chart), domain-split addon registries, and a selector-based enablement mechanism to provide git-auditable addon lifecycle management. A two-phase Kind bootstrap provisions the entire platform from a single `task install` command with zero Terraform dependency.

## Glossary

- **Appset_Chart**: A unified Helm chart that renders ArgoCD ApplicationSets from addon registry entries
- **Addon_Registry**: A set of domain-split YAML files defining available addons and their configuration
- **Fleet_Secret_Chart**: A Helm chart that generates ArgoCD cluster secrets with `enable_*` labels derived from `enabled-addons.yaml` files
- **Enabled_Addons_Map**: A YAML file (`enabled-addons.yaml`) mapping addon names to boolean enabled/disabled states per environment
- **Addon_Override**: A per-cluster YAML file (`addon-overrides.yaml`) that overrides environment-level addon enablement
- **Cluster_Secret**: A Kubernetes Secret of type `argocd.argoproj.io/secret-type: cluster` containing cluster connection info and `enable_*` labels
- **ApplicationSet**: An ArgoCD resource that generates Application resources based on generators and templates
- **Sync_Wave**: An ArgoCD annotation (`argocd.argoproj.io/sync-wave`) controlling the ordering of resource synchronization
- **Value_Layering**: The ordered merge of Helm values from defaults → domain files → environment overlays → cluster overlays
- **Bootstrap_Kind**: The Phase 1 ephemeral Kind cluster used to provision AWS infrastructure and seed the hub
- **Hub_Cluster**: The permanent EKS cluster that self-manages via ArgoCD after Phase 1 completes
- **Root_AppSet**: The single entry-point ApplicationSet (`root-appset.yaml`) applied to the hub that deploys all other bootstrap ApplicationSets
- **Fleet_Member**: A cluster registered in `fleet/members/` with its own values.yaml defining connection and metadata
- **Domain_File**: A registry YAML file scoped to a specific domain (core, gitops, security, observability, platform, ml)
- **Defaults_File**: The `_defaults.yaml` file providing shared configuration merged before domain files
- **Crossplane**: A Kubernetes-native infrastructure provisioning tool used during bootstrap to create AWS resources
- **KRO**: Kubernetes Resource Orchestrator used for cluster provisioning on the hub

## Requirements

### Requirement 1: ApplicationSet Rendering from Registry Entries

**User Story:** As a platform engineer, I want the appset-chart to render one ApplicationSet per addon registry entry, so that each addon is independently deployable to matching clusters.

#### Acceptance Criteria

1. WHEN the Appset_Chart processes registry values, THE Appset_Chart SHALL render exactly one ApplicationSet resource for each map entry that contains a `namespace` key
2. WHEN the Appset_Chart encounters a map entry without a `namespace` key, THE Appset_Chart SHALL skip that entry without rendering an ApplicationSet
3. WHEN rendering an ApplicationSet name, THE Appset_Chart SHALL normalize the addon key by replacing underscores with hyphens and truncating to 63 characters
4. WHEN `appsetPrefix` is configured, THE Appset_Chart SHALL prepend the prefix to all rendered ApplicationSet names
5. WHEN rendering the Application template, THE Appset_Chart SHALL include labels for addonVersion, addonName, environment, clusterName, and kubernetesVersion
6. WHEN an addon entry specifies a `project` field, THE Appset_Chart SHALL set the Application project to that value; WHILE no `project` field is specified, THE Appset_Chart SHALL default the Application project to "default"
7. WHEN an addon entry includes `annotationsApp`, THE Appset_Chart SHALL render those annotations on the generated Application template

### Requirement 2: Helm and Git Source Support

**User Story:** As a platform engineer, I want the appset-chart to support both Helm chart and git path-based sources, so that addons can be sourced from Helm repositories or git directories.

#### Acceptance Criteria

1. WHEN an addon entry specifies `chartRepository` and `defaultVersion`, THE Appset_Chart SHALL render a Helm chart source in the ApplicationSet
2. WHEN an addon entry specifies a `path` field, THE Appset_Chart SHALL render a git path-based source in the ApplicationSet
3. WHEN an addon entry specifies both `path` and `directory` fields, THE Appset_Chart SHALL include the directory block in the rendered source
4. WHEN an addon entry includes `additionalResources` as a list, THE Appset_Chart SHALL render one additional source entry per list item
5. WHEN an addon entry specifies `type: "manifest"`, THE Appset_Chart SHALL skip the Helm block in the rendered source

### Requirement 3: Duplicate ignoreDifferences Prevention

**User Story:** As a platform engineer, I want the appset-chart to render ignoreDifferences exactly once per ApplicationSet, so that duplicate configuration bugs are eliminated.

#### Acceptance Criteria

1. WHEN an addon entry includes `ignoreDifferences`, THE Appset_Chart SHALL render exactly one `ignoreDifferences` block using a `with` guard in the template
2. THE Appset_Chart SHALL produce at most one `ignoreDifferences` block per rendered ApplicationSet regardless of template structure

### Requirement 4: Domain-Split Addon Registry

**User Story:** As a platform engineer, I want the addon registry split into domain-specific files, so that the monolithic registry is replaced with maintainable, focused files.

#### Acceptance Criteria

1. THE Addon_Registry SHALL organize addon entries into domain-specific files: `_defaults.yaml`, `core.yaml`, `gitops.yaml`, `security.yaml`, `observability.yaml`, `platform.yaml`, and `ml.yaml`
2. THE Defaults_File SHALL contain shared configuration (syncPolicy, repoURL, valueFiles) merged before all domain files
3. WHEN an addon entry is defined in a Domain_File, THE Addon_Registry SHALL omit any `enabled` field from the entry, relying on selector-based enablement instead
4. WHEN an addon entry defines enablement, THE Addon_Registry SHALL use `selector.matchExpressions` referencing `enable_<addon_name>` labels on Cluster_Secrets

### Requirement 5: Fleet-Secret Label Generation

**User Story:** As a platform engineer, I want the fleet-secret chart to generate `enable_*` labels on cluster secrets from `enabled-addons.yaml`, so that addon enablement is driven by git-auditable configuration.

#### Acceptance Criteria

1. WHEN the Fleet_Secret_Chart processes an Enabled_Addons_Map, THE Fleet_Secret_Chart SHALL generate a label `enable_<addon>: 'true'` on the Cluster_Secret for each addon where the value is `true`
2. WHEN an addon value is `false` in the Enabled_Addons_Map, THE Fleet_Secret_Chart SHALL omit the corresponding `enable_<addon>` label from the Cluster_Secret
3. THE Fleet_Secret_Chart SHALL preserve the `argocd.argoproj.io/secret-type: cluster` label on every generated Cluster_Secret
4. WHEN the Fleet_Secret_Chart generates labels, THE Fleet_Secret_Chart SHALL treat labels as additive without removing existing labels on the secret

### Requirement 6: Addon Enablement Resolution with Overrides

**User Story:** As a platform engineer, I want per-cluster addon overrides to take precedence over environment defaults, so that individual clusters can deviate from their environment's addon configuration.

#### Acceptance Criteria

1. WHEN resolving addon enablement for a cluster, THE Fleet_Secret_Chart SHALL load the environment-level `enabled-addons.yaml` as the base configuration
2. WHEN an Addon_Override file exists for a cluster, THE Fleet_Secret_Chart SHALL merge the override values with the environment defaults, with override values taking precedence
3. WHEN an Addon_Override enables an addon that the environment disables, THE Cluster_Secret SHALL include the `enable_<addon>` label for that cluster
4. WHEN an Addon_Override disables an addon that the environment enables, THE Cluster_Secret SHALL omit the `enable_<addon>` label for that cluster

### Requirement 7: Selector-Enablement Equivalence

**User Story:** As a platform engineer, I want addon deployment to be determined solely by the match between cluster secret labels and registry selectors, so that enablement is deterministic and auditable.

#### Acceptance Criteria

1. WHEN a Cluster_Secret has label `enable_<addon>: 'true'` AND the Addon_Registry entry for that addon has a matching `selector.matchExpressions`, THE ApplicationSet SHALL generate an Application for that cluster
2. WHEN a Cluster_Secret lacks the `enable_<addon>` label for an addon, THE ApplicationSet for that addon SHALL NOT generate an Application for that cluster
3. THE Appset_Chart SHALL use `selector.matchExpressions` with `operator: In` and `values: ['true']` as the standard enablement pattern

### Requirement 8: Value Layering and Override Ordering

**User Story:** As a platform engineer, I want configuration values to be layered in a deterministic order, so that environment and cluster overrides predictably control addon behavior.

#### Acceptance Criteria

1. THE Appset_Chart SHALL merge value files in the order: Defaults_File → Domain_Files → environment overlay → cluster overlay
2. WHEN a key exists in both a Domain_File and the Defaults_File, THE Appset_Chart SHALL use the Domain_File value
3. WHEN a key exists in both an environment overlay and a Domain_File, THE Appset_Chart SHALL use the environment overlay value
4. WHEN a key exists in both a cluster overlay and an environment overlay, THE Appset_Chart SHALL use the cluster overlay value
5. WHEN an overlay file does not exist, THE Appset_Chart SHALL silently ignore the missing file by setting `ignoreMissingValueFiles: true`

### Requirement 9: Hub Bootstrap ApplicationSets

**User Story:** As a platform engineer, I want the hub cluster to self-manage via root ApplicationSets, so that the bootstrap directory is the single entry point for all platform management.

#### Acceptance Criteria

1. THE Root_AppSet SHALL deploy three child ApplicationSets: fleet-secrets, addons, and clusters
2. WHEN the addons ApplicationSet renders, THE addons ApplicationSet SHALL use a clusters generator matching `fleet_member: control-plane` and include all registry Domain_Files as valueFiles
3. WHEN the fleet-secrets ApplicationSet renders, THE fleet-secrets ApplicationSet SHALL use a matrix generator combining clusters and git directories to render one fleet-secret per Fleet_Member
4. WHEN the fleet-secrets ApplicationSet renders for a Fleet_Member, THE fleet-secrets ApplicationSet SHALL include the environment's `enabled-addons.yaml` in the valueFiles

### Requirement 10: Kind Bootstrap Orchestration (Phase 1)

**User Story:** As a platform engineer, I want to bootstrap the entire platform from a single `task install` command using a Kind cluster, so that no Terraform is required for initial provisioning.

#### Acceptance Criteria

1. WHEN `task install` is executed, THE Bootstrap_Kind SHALL create a Kind cluster, install ArgoCD, and install the Appset_Chart with bootstrap-addons.yaml
2. WHEN ArgoCD is running on the Kind cluster, THE Bootstrap_Kind SHALL deploy Crossplane and External Secrets Operator via the bootstrap addons
3. WHEN Crossplane is ready, THE Bootstrap_Kind SHALL provision AWS VPC, EKS cluster, and IAM roles via Crossplane compositions
4. WHEN the Hub_Cluster EKS endpoint is available, THE Bootstrap_Kind SHALL generate a hub Cluster_Secret via External Secrets Operator
5. WHEN the hub Cluster_Secret exists, THE Bootstrap_Kind SHALL deploy ArgoCD and bootstrap ApplicationSets to the Hub_Cluster via hub-seed.yaml
6. WHEN the Hub_Cluster is self-managing, THE Bootstrap_Kind SHALL delete the Kind cluster

### Requirement 11: Bootstrap Idempotency

**User Story:** As a platform engineer, I want the bootstrap process to be idempotent, so that re-running `task install` does not create duplicate resources.

#### Acceptance Criteria

1. WHEN `task install` is executed and a Hub_Cluster already exists, THE Bootstrap_Kind SHALL adopt existing AWS resources via Crossplane's `crossplane.io/external-name` annotation instead of creating duplicates
2. WHEN Crossplane adopts existing resources, THE Hub_Cluster SHALL continue operating without disruption

### Requirement 12: Fleet Member Management

**User Story:** As a platform engineer, I want to manage fleet members via git-stored values files, so that cluster registration and configuration is version-controlled.

#### Acceptance Criteria

1. THE Fleet_Member configuration SHALL be stored at `fleet/members/<cluster>/values.yaml`
2. WHEN a Fleet_Member values file is created, THE Fleet_Member values file SHALL include externalSecret configuration with clusterName, server endpoint, annotations, and labels
3. WHEN a Fleet_Member specifies labels, THE Fleet_Member labels SHALL include `environment`, `fleet_member`, and `kubernetesVersion`
4. WHEN a Fleet_Member specifies annotations, THE Fleet_Member annotations SHALL include `addonsRepoURL`, `addonsRepoRevision`, `addonsRepoBasepath`, and AWS-specific metadata

### Requirement 13: Enabled Addons Map Validation

**User Story:** As a platform engineer, I want the enabled-addons map to follow consistent naming conventions, so that label generation is predictable and error-free.

#### Acceptance Criteria

1. THE Enabled_Addons_Map SHALL use underscore-separated addon keys matching the `enable_<addon>` label convention
2. THE Enabled_Addons_Map SHALL use boolean `true` or `false` values for all addon entries
3. THE Enabled_Addons_Map SHALL list all known addons explicitly rather than relying on implicit defaults

### Requirement 14: Sync-Wave Ordering

**User Story:** As a platform engineer, I want addons to be ordered by sync-wave annotations, so that dependencies are deployed before dependents.

#### Acceptance Criteria

1. WHEN an addon entry includes `annotationsAppSet` with `argocd.argoproj.io/sync-wave`, THE Appset_Chart SHALL render that annotation on the ApplicationSet metadata
2. THE Addon_Registry SHALL assign sync-wave values following the ordering: -5 (multi-account) → -3 (abstractions) → -2 (KRO resource groups) → -1 (controllers) → 0 (core) → 1 (ingress) → 2 (certificates) → 3 (security/policy) → 4 (platform tools) → 5 (ML/AI) → 6 (infrastructure) → 7 (data)

### Requirement 15: Error Handling and Recovery

**User Story:** As a platform engineer, I want the system to handle failures gracefully, so that issues are visible and recoverable without manual intervention.

#### Acceptance Criteria

1. IF the Fleet_Secret_Chart fails to create a Cluster_Secret, THEN THE ArgoCD Application for that fleet-secret SHALL show degraded status and no ApplicationSets SHALL match the missing cluster
2. IF a registry Domain_File contains invalid YAML, THEN THE Appset_Chart `helm template` SHALL fail and ArgoCD SHALL mark the addons Application as OutOfSync with an error status
3. IF Crossplane fails to create AWS resources during bootstrap, THEN THE Crossplane claim SHALL show `NotReady` status and the bootstrap sequence SHALL stall at the corresponding wait step
4. IF a Value_Layering overlay overrides a critical field such as `namespace`, THEN THE Appset_Chart SHALL deploy the addon using the overridden value as determined by the layering order

### Requirement 16: Git Matrix Generator Support

**User Story:** As a platform engineer, I want the appset-chart to support git matrix generators, so that advanced use cases like dynamic configuration from git files are possible.

#### Acceptance Criteria

1. WHEN an addon entry sets `gitMatrix: true`, THE Appset_Chart SHALL use a git matrix generator instead of a standard cluster generator
2. WHEN a git matrix generator is used, THE Appset_Chart SHALL read the `matrixPath` and `matrixValues` from the addon entry to configure the generator

### Requirement 17: Directory Structure and File Layout

**User Story:** As a platform engineer, I want a well-defined directory structure under `gitops/`, so that all components are organized and discoverable.

#### Acceptance Criteria

1. THE system SHALL organize files under the `gitops/` root directory with subdirectories: `addons/registry/`, `bootstrap/`, `bootstrap-kind/`, `charts/appset-chart/`, `charts/fleet-secret/`, `fleet/members/`, and `overlays/`
2. THE `overlays/` directory SHALL contain `environments/<env>/` and `clusters/<cluster>/` subdirectories for configuration overrides
3. THE `bootstrap/` directory SHALL contain `root-appset.yaml`, `addons.yaml`, `clusters.yaml`, and `fleet-secrets.yaml`
4. THE `bootstrap-kind/` directory SHALL contain `Taskfile.yml`, `kind.yaml`, `config.yaml`, `argocd-values.yaml`, `bootstrap-addons.yaml`, `hub-seed.yaml`, and a `manifests/` subdirectory
