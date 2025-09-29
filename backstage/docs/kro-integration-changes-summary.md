# Kro Integration Changes Summary

## Changes Made to Support Kro Integration

### ✅ **No Changes Required to `build_backstage.sh`**

The existing `build_backstage.sh` script **does not need to be updated** because:

1. **Separation of Concerns**: The build script only handles Docker image building and pushing to ECR
2. **GitOps Management**: All Kubernetes resources (including RBAC) are managed through the addons system
3. **Automated Deployment**: ArgoCD handles the deployment of Backstage with Kro integration

### ✅ **GitOps Integration Completed**

The Kro RBAC and configuration have been integrated into the existing GitOps workflow:

#### 1. **Updated Backstage Helm Chart**
**File**: `appmod-blueprints/gitops/addons/charts/backstage/templates/install.yaml`

**Changes Made**:
- ✅ Added `backstage-kro-reader` ClusterRole with Kro-specific permissions
- ✅ Added ClusterRoleBinding for Kro permissions
- ✅ Updated Backstage configuration with Kro plugin settings
- ✅ Added kubernetesIngestor configuration for Kro resources
- ✅ Updated k8s-config.yaml with Kro custom resources

#### 2. **Updated Addons Configuration**
**File**: `appmod-blueprints/gitops/addons/bootstrap/default/addons.yaml`

**Changes Made**:
- ✅ Added Backstage addon configuration
- ✅ Set proper sync-wave (10) to ensure dependencies are ready
- ✅ Configured ignore differences for External Secrets and deployments

#### 3. **Environment Configuration**
**File**: `appmod-blueprints/gitops/addons/environments/control-plane/addons.yaml`

**Status**: ✅ Already enabled (`backstage: enabled: true`)

## How the Integration Works

### 1. **Build Process** (Unchanged)
```bash
# This remains the same - only builds and pushes Docker image
./appmod-blueprints/scripts/build_backstage.sh
```

### 2. **Deployment Process** (Enhanced with Kro)
1. **ArgoCD detects changes** in the addons configuration
2. **Dependencies are deployed first**:
   - Kro Controller (sync-wave -3)
   - External Secrets (sync-wave -1)
   - Keycloak (sync-wave 3)
3. **Backstage is deployed** (sync-wave 10) with:
   - Kro RBAC permissions automatically applied
   - Kro plugin configuration included
   - Service account with proper permissions created

### 3. **Kro Resources Discovered**
Once deployed, Backstage automatically discovers:
- ResourceGraphDefinitions
- CICDPipeline instances
- EksCluster instances
- EksclusterWithVpc instances
- Vpc instances

## Permissions Granted

The Backstage service account now has read-only access to:

### Kro Resources
- `resourcegraphdefinitions` (and status)
- All Kro instances (`kro.run/*`)

### Related Resources
- ACK resources (`ecr.services.k8s.aws/*`, `iam.services.k8s.aws/*`, `eks.services.k8s.aws/*`)
- Argo Workflows (`argoproj.io/*`)
- External Secrets (`external-secrets.io/*`)

## Environment Variables

The following environment variables are used by the Backstage deployment:

### Required for Build
- `RESOURCE_PREFIX`: AWS resource prefix (e.g., "peeks")
- `AWS_REGION`: AWS region
- `AWS_ACCOUNT_ID`: AWS account ID

### Used by GitOps Deployment
- `ingress_domain_name`: Domain for Backstage ingress
- `backstage_image`: Docker image URL (set by build script output)
- `resource_prefix`: Resource prefix for naming

## Verification Steps

### 1. **Check ArgoCD Application**
```bash
# Verify Backstage application is healthy
kubectl get application backstage -n argocd
```

### 2. **Verify RBAC Permissions**
```bash
# Test Kro permissions
kubectl auth can-i get resourcegraphdefinitions \
  --as=system:serviceaccount:backstage:backstage

kubectl auth can-i get cicdpipelines \
  --as=system:serviceaccount:backstage:backstage
```

### 3. **Check Backstage Logs**
```bash
# Verify Backstage can connect to Kubernetes and discover Kro resources
kubectl logs -n backstage deployment/backstage
```

### 4. **Access Backstage UI**
- Navigate to `https://${DOMAIN_NAME}/backstage`
- Check that Kro resources appear in the catalog
- Verify Kubernetes plugin shows Kro resources

## Troubleshooting

### If Backstage Doesn't Deploy
1. Check ArgoCD application status
2. Verify dependencies (Kro, Keycloak, External Secrets) are healthy
3. Check sync-wave ordering

### If Kro Resources Don't Appear
1. Verify Kro controller is running
2. Check RBAC permissions
3. Verify ResourceGraphDefinitions exist
4. Check Backstage configuration and logs

### If Build Fails
1. Check AWS credentials
2. Verify ECR repository permissions
3. Check Docker daemon

## Migration Path

For existing environments:

### 1. **Update GitOps Configuration**
The changes are already made to the GitOps configuration files. When you commit and push these changes:

1. ArgoCD will detect the updates
2. Backstage will be redeployed with Kro integration
3. RBAC permissions will be automatically applied

### 2. **No Manual Steps Required**
- No need to run RBAC setup scripts manually
- No need to update the build script
- No need to create service accounts manually

### 3. **Verification**
After ArgoCD syncs the changes:
1. Verify Backstage pod restarts successfully
2. Check that Kro resources appear in Backstage catalog
3. Test navigation between Kubernetes and Kro views

## Conclusion

✅ **The build script does NOT need to be updated**

✅ **All Kro integration is handled through GitOps**

✅ **RBAC configuration is automatically deployed**

✅ **No manual intervention required**

The integration is designed to be:
- **Automated**: No manual steps required
- **Secure**: Minimal required permissions
- **Maintainable**: All configuration in version control
- **Scalable**: Works across all environments

When you deploy these changes, Backstage will automatically have Kro integration enabled with proper RBAC permissions.