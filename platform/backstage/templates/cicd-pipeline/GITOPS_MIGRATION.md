# CICDPipeline GitOps Migration

## Problem Statement

The current implementation creates CICDPipeline Kro resources directly via `kubectl apply` from the Backstage scaffolder. This approach has several limitations:

### Current Issues
- ❌ **No ArgoCD Visibility**: CICDPipeline resources are not visible in ArgoCD UI
- ❌ **No GitOps Management**: Resources are not version controlled or managed declaratively
- ❌ **No Drift Detection**: ArgoCD cannot detect or correct configuration drift
- ❌ **Limited Rollback**: No easy way to rollback to previous configurations
- ❌ **No Audit Trail**: Changes are not tracked in Git history

## Proposed Solution: GitOps Approach

Move CICDPipeline creation from direct `kubectl apply` to GitOps-managed ArgoCD applications.

### Architecture Comparison

#### Current (Direct Apply)
```
Backstage Scaffolder
       ↓ (kubectl apply)
   CICDPipeline Resource
       ↓
   Kro Controller
       ↓
   AWS/K8s Resources
```

#### Proposed (GitOps)
```
Backstage Scaffolder
       ↓ (creates repo + ArgoCD app)
   GitLab Repository
       ↓ (ArgoCD sync)
   ArgoCD Application
       ↓ (applies manifests)
   CICDPipeline Resource
       ↓
   Kro Controller
       ↓
   AWS/K8s Resources
```

## Implementation Changes

### 1. New Template Structure

```
skeleton/
├── manifests/
│   ├── namespace.yaml              # Namespace with sync-wave: 0
│   └── kro-cicd-pipeline.yaml     # CICDPipeline with sync-wave: 1
├── argocd/
│   └── application.yaml            # ArgoCD Application definition
└── catalog-info.yaml               # Updated with ArgoCD annotations
```

### 2. Enhanced Scaffolder Template

- **New Template**: `template-cicd-pipeline-gitops.yaml`
- **GitOps First**: Creates repository with manifests, then ArgoCD application
- **Proper Ordering**: Uses ArgoCD sync waves for resource creation order
- **Enhanced Monitoring**: Better status tracking and health checks

### 3. ArgoCD Integration Features

#### Sync Waves
```yaml
# namespace.yaml
argocd.argoproj.io/sync-wave: "0"  # Create namespace first

# kro-cicd-pipeline.yaml  
argocd.argoproj.io/sync-wave: "1"  # Create CICDPipeline after namespace
```

#### Health Checks
```yaml
ignoreDifferences:
  - group: kro.run
    kind: CICDPipeline
    jsonPointers:
      - /status  # Ignore status changes for health calculation
```

#### Finalizers
```yaml
argocd.argoproj.io/finalizer: resources-finalizer.argocd.argoproj.io
```

## Benefits of GitOps Approach

### ✅ Full ArgoCD Visibility
- CICDPipeline resources appear in ArgoCD application tree
- Real-time sync status and health monitoring
- Visual representation of resource relationships
- Integration with ArgoCD notifications and alerts

### ✅ Version Control & Audit Trail
- All configuration changes tracked in Git
- Complete history of who changed what and when
- Easy to see configuration evolution over time
- Compliance and audit requirements satisfied

### ✅ Rollback Capabilities
- Easy rollback to any previous Git commit
- ArgoCD history shows all previous sync states
- Can rollback individual resources or entire application
- Automated rollback on sync failures

### ✅ Drift Detection & Self-Healing
- ArgoCD continuously monitors actual vs desired state
- Automatic correction of configuration drift
- Alerts when manual changes are detected
- Self-healing ensures consistency

### ✅ Enhanced Operations
- **Declarative**: Infrastructure as Code approach
- **Reproducible**: Consistent deployments across environments
- **Scalable**: Easy to replicate for multiple applications
- **Testable**: Can test changes in branches before merging

## Migration Path

### Phase 1: Parallel Deployment
1. Deploy new GitOps template alongside existing template
2. Test with new applications
3. Validate ArgoCD integration works correctly

### Phase 2: Migration
1. Update existing applications to use GitOps approach
2. Migrate CICDPipeline resources to ArgoCD management
3. Update documentation and training materials

### Phase 3: Deprecation
1. Mark old template as deprecated
2. Remove direct `kubectl apply` approach
3. Standardize on GitOps-only approach

## Usage Examples

### Creating New CICDPipeline (GitOps)
```bash
# User selects "Deploy CI/CD Pipeline With KRO (GitOps)" template
# Backstage creates:
# 1. GitLab repository with manifests
# 2. ArgoCD project and application
# 3. ArgoCD syncs and creates CICDPipeline
# 4. CICDPipeline visible in ArgoCD UI
```

### Updating CICDPipeline Configuration
```bash
# User updates manifests/kro-cicd-pipeline.yaml in Git
git add manifests/kro-cicd-pipeline.yaml
git commit -m "Update AWS region configuration"
git push origin main

# ArgoCD automatically detects change and syncs
# CICDPipeline updated with new configuration
# Change visible in ArgoCD UI and Git history
```

### Rollback Scenario
```bash
# Issue detected with latest configuration
# Rollback via ArgoCD UI or CLI
argocd app rollback myapp-cicd

# Or rollback via Git
git revert HEAD
git push origin main
# ArgoCD syncs and applies previous configuration
```

## Monitoring & Observability

### ArgoCD Dashboard
- Application sync status
- Resource health status
- Sync history and events
- Configuration drift alerts

### Kro Resource Status
- CICDPipeline conditions and status
- Managed resource health
- AWS resource provisioning status
- Workflow execution status

### Git Integration
- Commit history for configuration changes
- Branch-based testing and validation
- Pull request workflows for changes
- Integration with CI/CD for manifest validation

## Conclusion

The GitOps approach provides significant benefits over direct resource creation:

1. **Better Visibility**: Full integration with ArgoCD UI
2. **Improved Management**: Version control and rollback capabilities
3. **Enhanced Reliability**: Drift detection and self-healing
4. **Operational Excellence**: Audit trails and compliance
5. **Developer Experience**: Familiar Git-based workflows

This migration aligns with modern GitOps best practices and provides a more robust, scalable, and maintainable approach to managing Kro CICDPipeline resources.