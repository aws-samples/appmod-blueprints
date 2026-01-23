# Backstage Build and Deployment Process

This document explains how Backstage is built and deployed in the platform, including the Kro integration.

## Overview

Backstage deployment follows a GitOps approach where:
1. **Docker Image Building**: Handled by `build_backstage.sh` script
2. **Kubernetes Deployment**: Managed through ArgoCD and the addons system
3. **RBAC Configuration**: Integrated into the Backstage Helm chart

## Build Process

### Docker Image Building

The `appmod-blueprints/scripts/build_backstage.sh` script handles:
- Building the Backstage Docker image
- Pushing to ECR repository
- **Does NOT handle Kubernetes resources** (this is managed by GitOps)

```bash
# Build and push Backstage image
./appmod-blueprints/scripts/build_backstage.sh [optional-app-path]
```

### Environment Variables

The build script uses these environment variables:
- `RESOURCE_PREFIX`: Prefix for AWS resources (e.g., "peeks")
- `AWS_REGION`: AWS region for ECR repository
- `AWS_ACCOUNT_ID`: AWS account ID for ECR repository

## Deployment Process

### GitOps-Managed Deployment

Backstage deployment is managed through the addons system:

1. **Addon Configuration**: `appmod-blueprints/gitops/addons/bootstrap/default/addons.yaml`
2. **Helm Chart**: `appmod-blueprints/gitops/addons/charts/backstage/`
3. **Environment Config**: `appmod-blueprints/gitops/addons/environments/control-plane/addons.yaml`

### Kro Integration

The Kro integration is built into the Backstage Helm chart and includes:

#### RBAC Configuration
- **ClusterRole**: `backstage-kro-reader` with read access to Kro resources
- **ClusterRoleBinding**: Links the Backstage service account to Kro permissions
- **Integrated with existing**: `read-all` ClusterRole for general Kubernetes access

#### Backstage Configuration
- **Kro Plugin Settings**: Cluster connections and authentication
- **kubernetesIngestor**: Configured to discover Kro resources
- **Custom Resources**: ResourceGraphDefinitions and Kro instances

#### Supported Kro Resources
- ResourceGraphDefinitions
- CICDPipeline instances
- EksCluster instances
- EksclusterWithVpc instances
- Vpc instances

## Deployment Flow

### 1. Image Build and Push
```bash
# Build new Backstage image with Kro plugin
./appmod-blueprints/scripts/build_backstage.sh

# Image is pushed to: ${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${RESOURCE_PREFIX}-backstage:latest
```

### 2. GitOps Deployment
The deployment happens automatically through ArgoCD:

1. **ArgoCD detects changes** in the addons configuration
2. **Backstage addon is synced** with sync-wave 10 (after dependencies)
3. **RBAC resources are created** including Kro permissions
4. **Backstage deployment is updated** with new image and configuration

### 3. Dependencies

Backstage deployment depends on:
- **Kro Controller** (sync-wave -3)
- **External Secrets** (sync-wave -1)
- **Keycloak** (sync-wave 3)
- **ArgoCD** (sync-wave 0)

## Configuration Updates

### Adding New Kro Resource Types

To add support for new Kro resource types:

1. **Update the Helm chart** (`appmod-blueprints/gitops/addons/charts/backstage/templates/install.yaml`):
   ```yaml
   # Add to kubernetesIngestor.resources
   - apiVersion: 'kro.run/v1alpha1'
     kind: 'NewKroResourceType'
   
   # Add to k8s-config.yaml customResources
   - group: 'kro.run'
     apiVersion: 'v1alpha1'
     plural: 'newkroresourcetypes'
   ```

2. **Update RBAC if needed** (usually covered by the wildcard `kro.run/*` permission)

3. **Commit changes** and let ArgoCD sync the updates

### Environment-Specific Configuration

Environment-specific settings are managed in:
- `appmod-blueprints/gitops/addons/environments/control-plane/addons.yaml`

To enable/disable Backstage:
```yaml
backstage:
  enabled: true  # or false
```

## Troubleshooting

### Build Issues

If the build script fails:
1. Check AWS credentials and permissions
2. Verify ECR repository exists or can be created
3. Check Docker daemon is running

### Deployment Issues

If Backstage deployment fails:
1. Check ArgoCD application status
2. Verify dependencies are healthy (Kro, Keycloak, External Secrets)
3. Check service account permissions
4. Verify Kro controller is running

### Kro Integration Issues

If Kro resources don't appear in Backstage:
1. Verify Kro controller is running
2. Check RBAC permissions with `kubectl auth can-i`
3. Verify ResourceGraphDefinitions exist
4. Check Backstage logs for connection errors

## Manual RBAC Testing

To test RBAC permissions manually:

```bash
# Test ResourceGraphDefinition access
kubectl auth can-i get resourcegraphdefinitions \
  --as=system:serviceaccount:backstage:backstage

# Test Kro instance access
kubectl auth can-i get cicdpipelines \
  --as=system:serviceaccount:backstage:backstage

# List current permissions
kubectl describe clusterrole backstage-kro-reader
```

## Security Considerations

### Principle of Least Privilege
- Backstage service account has read-only access to Kro resources
- No write permissions to prevent accidental modifications
- Scoped to necessary resource types only

### Token Management
- Uses Kubernetes service account tokens
- Automatic token rotation through Kubernetes
- No long-lived tokens stored in configuration

## Monitoring

### Health Checks
- Backstage startup probe checks authentication
- ArgoCD monitors application health
- External Secrets monitors secret synchronization

### Logs
- Backstage application logs: `kubectl logs -n backstage deployment/backstage`
- ArgoCD sync logs: Check ArgoCD UI for backstage application
- Kro controller logs: `kubectl logs -n kro-system deployment/kro`

## Conclusion

The Backstage build and deployment process is designed to:
1. **Separate concerns**: Build script handles images, GitOps handles deployment
2. **Ensure security**: Proper RBAC with minimal required permissions
3. **Enable automation**: Full GitOps workflow with dependency management
4. **Support Kro integration**: Built-in support for Kro resource discovery

No manual RBAC application is needed - everything is managed through the GitOps workflow.