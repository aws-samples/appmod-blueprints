# GitOps Addon Management

## Purpose

Ensures proper understanding and usage of the platform's GitOps-based addon management system for deploying and configuring platform services. Enforces GitOps-first approach for all cluster modifications.

## Instructions

### GitOps-First Principle

- NEVER manually update Kubernetes resources using kubectl apply, kubectl edit, kubectl patch, or kubectl delete without explicit user confirmation (ID: GITOPS_NO_MANUAL_KUBECTL)
- ALWAYS prefer GitOps workflow: modify files in Git repository, commit, push, and let ArgoCD sync changes (ID: GITOPS_PREFER_GITOPS)
- If manual kubectl operation is the ONLY solution, EXPLICITLY ask user for confirmation before proceeding and explain why GitOps cannot be used (ID: GITOPS_ASK_CONFIRMATION)
- Read-only kubectl operations (get, describe, logs, exec for inspection) are allowed without confirmation (ID: GITOPS_READONLY_ALLOWED)

### GitOps Architecture Understanding

- The platform uses a three-tier GitOps configuration system: addon definitions, environment enablement, and cluster configuration (ID: GITOPS_THREE_TIER)
- ALWAYS use the GitOps workflow instead of manual kubectl apply for platform addons (ID: GITOPS_NO_MANUAL_APPLY)
- Understand that addons are deployed via ArgoCD ApplicationSets that generate Applications based on cluster labels and annotations (ID: GITOPS_APPLICATIONSETS)

### Addon Configuration Layers

- **Addon Definitions**: Located in `gitops/addons/bootstrap/default/addons.yaml` - central registry of all available platform addons (ID: GITOPS_ADDON_DEFINITIONS)
- **Environment Configuration**: Located in `gitops/addons/environments/{environment}/addons.yaml` - environment-specific addon enablement (ID: GITOPS_ENV_CONFIG)
- **Cluster Configuration**: Located in `platform/infra/terraform/hub-config.yaml` - per-cluster addon activation via labels (ID: GITOPS_CLUSTER_CONFIG)

### Hub Config File Role

- `hub-config.yaml` defines cluster metadata (name, region, environment, tenant) and addon enablement flags (ID: GITOPS_HUB_CONFIG_ROLE)
- Terraform reads this file to create cluster secrets with proper labels like `enable_addon_name: "true"` (ID: GITOPS_HUB_CONFIG_LABELS)
- ArgoCD ApplicationSets use these cluster secret labels to determine which addons to deploy to which clusters (ID: GITOPS_HUB_CONFIG_SELECTION)
- This file is the single source of truth for cluster-level addon configuration (ID: GITOPS_HUB_CONFIG_SOURCE_TRUTH)

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
- Step 3: Add enablement flag to `platform/infra/terraform/hub-config.yaml` under the clusters.{cluster-name}.addons section (ID: GITOPS_ADD_CLUSTER_FLAG)
- Step 4: Apply Terraform changes using deployment scripts to update cluster secrets (ID: GITOPS_ADD_TERRAFORM_APPLY)
- Step 5: ArgoCD automatically detects and deploys the addon (ID: GITOPS_ADD_AUTO_DEPLOY)

### High Availability Configuration for Critical Addons

- ALWAYS configure critical platform addons with HA patterns following the established template (ID: GITOPS_HA_CRITICAL_ADDONS)
- ALWAYS use 2+ replicas for critical services (hub, proxy, controller components) (ID: GITOPS_HA_REPLICAS)
- ALWAYS add PodDisruptionBudgets with maxUnavailable: 1 for multi-replica services (ID: GITOPS_HA_PDB)
- ALWAYS configure topologySpreadConstraints for multi-AZ distribution (ID: GITOPS_HA_TOPOLOGY_SPREAD)
- ALWAYS define resource requests and memory limits (no CPU limits to prevent throttling) (ID: GITOPS_HA_RESOURCES)
- ALWAYS use system nodeSelector and CriticalAddonsOnly tolerations for platform services (ID: GITOPS_HA_NODE_PLACEMENT)

### HA Configuration Template for Critical Addons

Use this template for all critical platform addons (authentication, GitOps, ingress, etc.):

```yaml
addon-name:
  valuesObject:
    # Main service component
    serviceComponent:
      replicas: 2
      resources:
        requests:
          cpu: 200m        # CPU requests only (allows bursting)
          memory: 512Mi    # Memory requests for scheduling
        limits:
          memory: 512Mi    # Memory limits = requests (prevents OOM kills)
          # No CPU limits (prevents throttling)
      nodeSelector:
        karpenter.sh/nodepool: system
      tolerations:
      - key: "CriticalAddonsOnly"
        operator: "Exists"
        effect: "NoSchedule"
      topologySpreadConstraints:
      - maxSkew: 1
        topologyKey: topology.kubernetes.io/zone
        whenUnsatisfiable: DoNotSchedule
        labelSelector:
          matchLabels:
            app: addon-name
            component: service-component
      pdb:
        enabled: true
        maxUnavailable: 1
    
    # Secondary components (proxy, controller, etc.)
    secondaryComponent:
      replicas: 2
      resources:
        requests:
          cpu: 100m
          memory: 128Mi
        limits:
          memory: 128Mi
      nodeSelector:
        karpenter.sh/nodepool: system
      tolerations:
      - key: "CriticalAddonsOnly"
        operator: "Exists"
        effect: "NoSchedule"
      topologySpreadConstraints:
      - maxSkew: 1
        topologyKey: topology.kubernetes.io/zone
        whenUnsatisfiable: DoNotSchedule
        labelSelector:
          matchLabels:
            app: addon-name
            component: secondary-component
      pdb:
        enabled: true
        maxUnavailable: 1
```

### Resource Sizing Guidelines for Critical Addons

- **Hub/Controller components**: 200m CPU request, 512Mi-1Gi memory
- **Proxy/Gateway components**: 100m CPU request, 128Mi-256Mi memory  
- **Database components**: 100m CPU request, 300Mi-500Mi memory
- **Memory limits should equal requests** for critical components (QoS: Burstable with memory guarantees)
- **Never set CPU limits** on critical components (prevents throttling)
- **Always set memory limits** to prevent OOM kills

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
