# GitOps Addon Management

## Purpose

Ensures proper understanding and usage of the platform's GitOps-based addon management system for deploying and configuring platform services.

## Instructions

### GitOps Architecture Understanding

- The platform uses a three-tier GitOps configuration system: addon definitions, environment enablement, and cluster configuration (ID: GITOPS_THREE_TIER)
- ALWAYS use the GitOps workflow instead of manual kubectl apply for platform addons (ID: GITOPS_NO_MANUAL_APPLY)
- Understand that addons are deployed via ArgoCD ApplicationSets that generate Applications based on cluster labels and annotations (ID: GITOPS_APPLICATIONSETS)

### Addon Configuration Layers

- **Addon Definitions**: Located in `gitops/addons/bootstrap/default/addons.yaml` - central registry of all available platform addons (ID: GITOPS_ADDON_DEFINITIONS)
- **Environment Configuration**: Located in `gitops/addons/environments/{environment}/addons.yaml` - environment-specific addon enablement (ID: GITOPS_ENV_CONFIG)
- **Cluster Configuration**: Located in `platform/infra/terraform/hub-config.yaml` - per-cluster addon activation via labels (ID: GITOPS_CLUSTER_CONFIG)

### Cluster Secret Annotations and Labels

- Cluster secrets contain metadata annotations used for templating: `resource_prefix`, `ingress_domain_name`, `aws_region`, `aws_cluster_name` (ID: GITOPS_CLUSTER_ANNOTATIONS)
- Cluster secrets contain labels for addon enablement: `enable_addon_name: "true"` (ID: GITOPS_CLUSTER_LABELS)
- NEVER modify cluster secrets manually - always update through Terraform hub-config.yaml (ID: GITOPS_NO_MANUAL_SECRETS)

### Sync Wave Orchestration

- Addons use ArgoCD sync waves for proper deployment ordering (-5 to 6) (ID: GITOPS_SYNC_WAVES)
- Infrastructure addons deploy first (waves -5 to -1), core platform services in waves 0-2, identity management in wave 3, applications in waves 4+ (ID: GITOPS_WAVE_ORDER)
- When adding new addons, choose appropriate sync wave based on dependencies (ID: GITOPS_WAVE_DEPENDENCIES)

### Adding New Addons Process

- Step 1: Define addon in `gitops/addons/bootstrap/default/addons.yaml` with proper selector and valuesObject (ID: GITOPS_ADD_DEFINITION)
- Step 2: Enable in environment config `gitops/addons/environments/{env}/addons.yaml` (ID: GITOPS_ADD_ENV_ENABLE)
- Step 3: Add enablement flag to `platform/infra/terraform/hub-config.yaml` (ID: GITOPS_ADD_CLUSTER_FLAG)
- Step 4: Apply Terraform changes to update cluster secrets (ID: GITOPS_ADD_TERRAFORM_APPLY)
- Step 5: ArgoCD automatically detects and deploys the addon (ID: GITOPS_ADD_AUTO_DEPLOY)

### SSO Integration Pattern

- Platform addons integrate with Keycloak for centralized authentication using OIDC (ID: GITOPS_SSO_KEYCLOAK)
- OIDC clients are automatically created by keycloak-config job (ID: GITOPS_SSO_AUTO_CLIENT)
- Client secrets are managed via External Secrets Operator from AWS Secrets Manager (ID: GITOPS_SSO_EXTERNAL_SECRETS)

## Priority

Critical

## Error Handling

- If addon not deploying, check cluster secret has correct `enable_addon_name: "true"` label
- If template resolution fails, verify cluster secret annotations contain required metadata
- If sync issues occur, check sync wave dependencies and ArgoCD Application events
