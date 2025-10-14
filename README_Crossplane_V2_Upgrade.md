# Crossplane v2 Upgrade Guide
## From v1.17.1 to v2.0.2 with Upbound Providers

## 🎯 Overview

Successfully upgraded Crossplane from v1.17.1 to v2.0.2 with migration from community AWS providers to Upbound providers. All three core compositions (S3, DynamoDB, RDS) are now fully functional with Crossplane v2 pipeline mode.

### High-Level Summary
- **Crossplane Core**: v1.17.1 → v2.0.2
- **Provider Ecosystem**: Community AWS → Upbound AWS providers
- **Composition Mode**: Resources → Pipeline mode
- **Function Integration**: Added `function-patch-and-transform`
- **Result**: All compositions working with enhanced reliability

### Migration Results
| Service | Status | Managed Resources | Changes Required |
|---------|--------|------------------|------------------|
| **S3** | ✅ Working | 4 resources | Resource splitting, field fixes |
| **DynamoDB** | ✅ Working | 1 resource | Minimal (already v2 compatible) |
| **RDS** | ✅ Working | 3 resources | Major (provider + field changes) |

---

## 📋 Step-by-Step Upgrade Guide

### Phase 1: ArgoCD UI Updates

1. **Update ArgoCD Application Manifests**:
   
   **File**: `argocd/crossplane`
   ```yaml
   spec:
     source:
       targetRevision: 2.0.2  # was: 1.17.1
       targetRevision: crossplane-version-upgrade  # was: main
       repoURL: https://github.com/aws-samples/appmod-blueprints
   ```
   
   **Files**: `argocd/crossplane-dev`, `argocd/crossplane-prod`
   ```yaml
   spec:
     source:
       targetRevision: 2.0.2  # was: 1.17.1
   ```

### Phase 2: Management Cluster Upgrade

2. **Trigger Crossplane Upgrade**:
   ```bash
   kubectl patch application crossplane -n argocd --type='merge' \
     -p='{"metadata":{"annotations":{"argocd.argoproj.io/refresh":"hard"}}}'
   ```

3. **Verify Management Cluster**:
   ```bash
   kubectl get pods -n crossplane-system  # All should be Running
   kubectl get deployment crossplane -n crossplane-system \
     -o jsonpath='{.spec.template.spec.containers[0].image}'  # Should show v2.0.2
   ```

### Phase 3: Remote Clusters (Dev/Prod)

4. **Fix ArgoCD Applications** (from management cluster):
   ```bash
   # Disable auto-sync
   kubectl patch application crossplane-dev -n argocd --type='json' \
     -p='[{"op": "remove", "path": "/spec/syncPolicy/automated"}]'
   kubectl patch application crossplane-prod -n argocd --type='json' \
     -p='[{"op": "remove", "path": "/spec/syncPolicy/automated"}]'
   
   # Fix Helm values (remove --enable-environment-configs flag)
   kubectl patch application crossplane-dev -n argocd --type='json' \
     -p='[{"op": "replace", "path": "/spec/source/helm/values", "value": "args: []\n"}]'
   kubectl patch application crossplane-prod -n argocd --type='json' \
     -p='[{"op": "replace", "path": "/spec/source/helm/values", "value": "args: []\n"}]'
   
   # Re-enable auto-sync
   kubectl patch application crossplane-dev -n argocd --type='json' \
     -p='[{"op": "add", "path": "/spec/syncPolicy/automated", "value": {"selfHeal": true}}]'
   kubectl patch application crossplane-prod -n argocd --type='json' \
     -p='[{"op": "add", "path": "/spec/syncPolicy/automated", "value": {"selfHeal": true}}]'
   ```

5. **Switch to Dev Cluster and Verify**:
   ```bash
   kubectl config use-context <dev-cluster-context>
   kubectl get pods -n crossplane-system  # All should be Running
   kubectl get deployment crossplane -n crossplane-system \
     -o jsonpath='{.spec.template.spec.containers[0].image}'  # Should show v2.0.2
   ```

6. **Switch to Prod Cluster and Verify**:
   ```bash
   kubectl config use-context <prod-cluster-context>
   kubectl get pods -n crossplane-system  # All should be Running
   kubectl get deployment crossplane -n crossplane-system \
     -o jsonpath='{.spec.template.spec.containers[0].image}'  # Should show v2.0.2
   ```

### Phase 4: Composition Migration

7. **Install Required Function** (management cluster):
   ```bash
   kubectl apply -f - <<EOF
   apiVersion: pkg.crossplane.io/v1
   kind: Function
   metadata:
     name: function-patch-and-transform
   spec:
     package: xpkg.upbound.io/crossplane-contrib/function-patch-and-transform:v0.2.1
   EOF
   ```

8. **Install Missing EC2 Provider**:
   ```bash
   kubectl apply -f - <<EOF
   apiVersion: pkg.crossplane.io/v1
   kind: Provider
   metadata:
     name: provider-aws-ec2
   spec:
     package: xpkg.upbound.io/upbound/provider-aws-ec2:v1.13.1
   EOF
   ```

9. **Configure EC2 Provider IRSA**:
   ```bash
   # Wait for provider to install
   kubectl get providers.pkg.crossplane.io provider-aws-ec2
   
   # Get service account name
   SA_NAME=$(kubectl get serviceaccounts -n crossplane-system | grep provider-aws-ec2 | awk '{print $1}')
   
   # Add IRSA annotation (use your actual IAM role ARN)
   kubectl annotate serviceaccount $SA_NAME -n crossplane-system \
     eks.amazonaws.com/role-arn=arn:aws:iam::<account>:role/<crossplane-iam-role>
   
   # Restart provider pod
   kubectl delete pod -n crossplane-system -l pkg.crossplane.io/provider=provider-aws-ec2
   ```

10. **Deploy Updated Compositions**:
    ```bash
    # Apply all composition definitions and compositions
    kubectl apply -f compositions/s3/definition.yaml -f compositions/s3/general-purpose.yaml
    kubectl apply -f compositions/dynamodb/definition.yaml -f compositions/dynamodb/ddb-table.yml
    kubectl apply -f compositions/rds/definition.yaml -f compositions/rds/rds-postgres.yaml
    ```

### Phase 5: Final Verification

11. **Test All Compositions**:
    ```bash
    # Apply test resources
    kubectl apply -f examples/Crossplane_V2_Tests/test-s3-crossplane.yaml
    kubectl apply -f examples/Crossplane_V2_Tests/test-dynamodb-table.yaml
    kubectl apply -f examples/Crossplane_V2_Tests/test-rds-composition.yaml
    
    # Check status
    kubectl get objectstorages,dynamodbtables,relationaldatabases
    ```

12. **Verify ArgoCD Applications**:
    ```bash
    kubectl get applications -n argocd | grep crossplane
    # All should show "Synced" and "Healthy"
    ```

---

## 🚨 Critical Issues Encountered & Solutions

### Issue 1: Missing Function Dependency
**Problem**: Pipeline mode requires `function-patch-and-transform`
**Error**: `function "function-patch-and-transform" not found`
**Solution**: Install the function (see Phase 4, step 7)

### Issue 2: Removed Command Line Flag
**Problem**: `--enable-environment-configs` flag removed in v2
**Error**: `unknown flag --enable-environment-configs`
**Solution**: Remove flag from ArgoCD Helm values (see Phase 3, step 4)

### Issue 3: Missing EC2 Provider
**Problem**: SecurityGroup CRD not available for RDS composition
**Error**: `no matches for kind "SecurityGroup" in version "ec2.aws.upbound.io/v1beta1"`
**Solution**: Install EC2 provider + configure IRSA (see Phase 4, steps 8-9)

### Issue 4: EC2 Provider Credentials
**Problem**: EC2 provider missing IRSA annotation
**Error**: `token file name cannot be empty`
**Solution**: Add IRSA annotation and restart provider pod

### Issue 5: SecurityGroup External-Name Confusion
**Problem**: Composition trying to import existing SecurityGroup instead of creating new one
**Error**: `InvalidGroupId.Malformed: Invalid id: "name" (expecting "sg-...")`
**Solution**: Remove external-name annotation from SecurityGroup in RDS composition

### Issue 6: Secret Reference Mismatch
**Problem**: RDS composition looking for wrong secret name
**Error**: `InvalidParameterValue: Invalid master password`
**Solution**: Update composition secret reference to match test secret

### Issue 7: Invalid PostgreSQL Version
**Problem**: Hardcoded PostgreSQL version not available in AWS
**Error**: `Cannot find version 14.11 for postgres`
**Solution**: Use valid version (14.12) available in AWS region

### Issue 8: S3 Resource Splitting
**Problem**: Upbound S3 provider splits bucket features into separate CRDs
**Error**: Various field validation errors
**Solution**: Create 4 separate managed resources instead of 1 monolithic bucket

### Issue 9: String Transform Syntax
**Problem**: v2 requires explicit `type: Format` in string transforms
**Error**: Transform validation failures
**Solution**: Update all string transforms to include `type: Format`

### Issue 10: Region Requirements
**Problem**: Upbound providers require explicit region on all resources
**Error**: `region is required`
**Solution**: Add region patches to all managed resources

---

## 📊 Composition Changes Summary

### S3 Composition
- **Resources**: 1 → 4 (Bucket + PublicAccessBlock + OwnershipControls + SSE)
- **API Version**: `s3.aws.crossplane.io/v1beta1` → `s3.aws.upbound.io/v1beta2`
- **Key Changes**: Resource splitting, region requirements, field format fixes

### DynamoDB Composition  
- **Resources**: 1 (Table)
- **API Version**: Already using `dynamodb.aws.upbound.io/v1beta2`
- **Key Changes**: Minimal - already v2 compatible

### RDS Composition
- **Resources**: 3 (SecurityGroup + SubnetGroup + Instance)
- **API Versions**: Multiple provider changes
- **Key Changes**: Field name updates, provider installation, credential fixes

---

## ✅ Success Indicators

### Crossplane Core
- All pods in `crossplane-system` namespace show `Running` status
- Crossplane deployment shows image version `v2.0.2`
- No CrashLoopBackOff pods

### ArgoCD Applications
```bash
kubectl get applications -n argocd | grep crossplane
```
All should show:
- **SYNC STATUS**: `Synced`
- **HEALTH STATUS**: `Healthy`

### Compositions
```bash
kubectl get objectstorages,dynamodbtables,relationaldatabases
```
All should show:
- **SYNCED**: `True`
- **READY**: `True`

### AWS Resources
- S3 buckets created with proper security settings
- DynamoDB tables accessible and functional
- RDS instances available and connectable

---

## 🔧 Troubleshooting Commands

### Check Crossplane Status
```bash
# Core components
kubectl get pods -n crossplane-system
kubectl get providers.pkg.crossplane.io
kubectl get functions.pkg.crossplane.io

# Compositions
kubectl get compositions
kubectl get xrd

# Test resources
kubectl get managed
```

### Debug Issues
```bash
# Check events
kubectl get events --sort-by='.lastTimestamp' -n crossplane-system

# Check logs
kubectl logs -n crossplane-system deployment/crossplane
kubectl logs -n crossplane-system -l pkg.crossplane.io/provider=provider-aws-rds

# Describe resources
kubectl describe <resource-type> <resource-name>
```

### AWS Verification
```bash
# Check S3 buckets
aws s3 ls

# Check DynamoDB tables
aws dynamodb list-tables

# Check RDS instances
aws rds describe-db-instances --query 'DBInstances[].{ID:DBInstanceIdentifier,Status:DBInstanceStatus}'
```

---

## 📚 Additional Resources

- **Individual Composition Guides**:
  - [S3 Migration Guide](compositions/s3/S3-Crossplane-V2.md)
  - [DynamoDB Migration Guide](compositions/dynamodb/DynamoDB-Crossplane-V2.md)
  - [RDS Migration Guide](compositions/rds/RDS-Crossplane-V2.md)

- **Test Examples**: `examples/Crossplane_V2_Tests/`
- **Crossplane v2 Documentation**: https://docs.crossplane.io/
- **Upbound Provider Documentation**: https://marketplace.upbound.io/

---

## 🎉 Migration Complete

Your Crossplane v2 upgrade is now complete with all compositions fully functional. The platform now benefits from:

- **Enhanced Reliability**: Upbound provider ecosystem
- **Better Observability**: Granular managed resources
- **Future-Proof Architecture**: Crossplane v2 pipeline mode
- **Improved Error Handling**: Individual resource management
- **Comprehensive Documentation**: Troubleshooting guides for all issues encountered