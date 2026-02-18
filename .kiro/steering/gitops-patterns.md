---
inclusion: auto
---

# GitOps Patterns and Best Practices

## ArgoCD Application Structure

### Application Hierarchy
This repository uses the "App of Apps" pattern:
- Bootstrap applications create child applications
- Environment-specific configurations in separate directories
- ApplicationSets for dynamic application generation

### Directory Structure Pattern
```
gitops/
├── addons/           # Platform addons (ArgoCD, Backstage, etc.)
│   ├── bootstrap/    # Bootstrap configurations
│   ├── charts/       # Helm charts for addons
│   ├── default/      # Default addon values
│   ├── environments/ # Environment-specific overrides
│   └── tenants/      # Tenant-specific configurations
├── apps/             # Application deployments
├── fleet/            # Multi-cluster fleet management
├── platform/         # Platform-level resources
└── workloads/        # Workload definitions
```

## Helm Chart Development

### Chart Structure
All addon charts follow this structure:
```
charts/<addon-name>/
├── Chart.yaml        # Chart metadata
├── values.yaml       # Default values (optional)
├── templates/        # Kubernetes manifests
│   ├── application.yaml      # ArgoCD Application
│   ├── namespace.yaml        # Namespace definition
│   └── <resource>.yaml       # Other resources
└── Chart.lock        # Dependency lock file (if dependencies exist)
```

### Chart Best Practices
1. Use `{{ .Values.global.resourcePrefix }}` for resource naming
2. Include namespace creation in templates
3. Add proper labels for resource tracking
4. Use ArgoCD sync waves for ordering: `argocd.argoproj.io/sync-wave: "1"`
5. Implement health checks for custom resources

### Values File Organization
- `default/addons/<addon>/values.yaml`: Base configuration
- `environments/<env>/addons.yaml`: Environment overrides
- `tenants/<tenant>/addons.yaml`: Tenant-specific settings

## ApplicationSet Patterns

### List Generator Pattern
Used for deploying multiple instances of the same addon:
```yaml
generators:
  - list:
      elements:
        - name: addon-name
          namespace: addon-namespace
          values: |
            key: value
```

### Git Directory Generator Pattern
Used for dynamic discovery of applications:
```yaml
generators:
  - git:
      repoURL: https://github.com/org/repo
      revision: main
      directories:
        - path: gitops/apps/*
```

## Sync Waves and Ordering

### Wave Strategy
- Wave -5 to -1: Prerequisites (namespaces, CRDs)
- Wave 0: Default (most resources)
- Wave 1-5: Dependent resources
- Wave 10+: Applications and workloads

### Common Wave Assignments
- Namespaces: -5
- CRDs: -4
- Operators: -3
- Configuration (ConfigMaps, Secrets): -2
- Core Services: -1
- Applications: 0
- Ingress/Routes: 1

## Environment Management

### Environment Promotion Strategy
1. **Development**: Automatic sync enabled, prune enabled
2. **Staging**: Automatic sync enabled, manual approval for prune
3. **Production**: Manual sync, manual approval required

### Configuration Overrides
Use Helm value precedence:
1. Base values in chart's `values.yaml`
2. Default values in `default/addons/<addon>/values.yaml`
3. Environment values in `environments/<env>/addons.yaml`
4. Tenant values in `tenants/<tenant>/addons.yaml`

## Secret Management

### External Secrets Pattern
1. Store secrets in AWS Secrets Manager
2. Create ExternalSecret resources
3. External Secrets Operator syncs to Kubernetes Secrets
4. Applications reference Kubernetes Secrets

### Secret Naming Convention
- Format: `<environment>/<team>/<application>/<secret-name>`
- Example: `prod/platform/backstage/database-credentials`

## Multi-Tenancy Patterns

### Namespace Isolation
- One namespace per team/application
- ResourceQuotas for resource limits
- NetworkPolicies for network isolation
- RBAC for access control

### Shared Services
- Platform services in dedicated namespaces
- Service mesh for cross-namespace communication
- Ingress controller with path-based routing

## Kro Integration

### Resource Graph Definitions (RGDs)
- Define complex resource compositions
- Located in `gitops/addons/charts/kro/resource-groups/`
- Registered with Backstage for self-service

### Instance Management
- Instances in `gitops/addons/charts/kro/instances/`
- Created via Backstage templates or kubectl
- Managed by Kro controller

## Testing GitOps Changes

### Pre-Commit Testing
```bash
# Test Helm chart rendering
helm template <chart-name> ./gitops/addons/charts/<chart-name> \
  -f ./gitops/addons/default/addons/<chart-name>/values.yaml

# Test ApplicationSet generation
task test-applicationsets

# Validate Kubernetes manifests
kubectl apply --dry-run=client -f <manifest>
```

### ArgoCD Sync Testing
1. Create feature branch
2. Update ArgoCD Application to point to feature branch
3. Sync and validate
4. Merge to main after validation

## Common Patterns

### Adding a New Addon
1. Create Helm chart in `gitops/addons/charts/<addon-name>/`
2. Add default values in `gitops/addons/default/addons/<addon-name>/values.yaml`
3. Register in ApplicationSet at `gitops/addons/charts/application-sets/`
4. Test with `task test-applicationsets`
5. Commit and let ArgoCD sync

### Updating Addon Configuration
1. Modify values in appropriate values file
2. Test locally with `helm template`
3. Commit changes
4. ArgoCD detects drift and syncs automatically

### Troubleshooting Sync Issues
1. Check ArgoCD Application status: `argocd app get <app-name>`
2. Review sync operation: `argocd app sync <app-name> --dry-run`
3. Check resource health: `kubectl get <resource> -n <namespace>`
4. Review ArgoCD logs for errors
5. Use sync waves to fix ordering issues

## Dependency Management

### Helm Dependencies
- Declare in `Chart.yaml` under `dependencies:`
- Run `task build-helm-dependencies` to fetch
- Commit `Chart.lock` and `charts/` directory
- Update with `helm dependency update`

### Resource Dependencies
- Use ArgoCD sync waves for ordering
- Implement health checks for custom resources
- Use `argocd.argoproj.io/sync-options: SkipDryRunOnMissingResource=true` for CRD-dependent resources
