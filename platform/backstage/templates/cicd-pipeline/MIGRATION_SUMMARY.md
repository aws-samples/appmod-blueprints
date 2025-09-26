# CI/CD Pipeline Template Migration Summary

## Overview
This document summarizes the migration of the CI/CD pipeline template from Crossplane-based file references to Kro-based inline YAML manifests.

## Changes Made

### 1. Template Structure Updates
- **File**: `template-cicd-pipeline.yaml`
- **Changes**:
  - Updated metadata description to reflect Kro-based approach
  - Added `cluster_name` parameter for EKS cluster specification
  - Replaced file-based `kube:apply` actions with inline YAML manifests
  - Removed dependencies on external provisioner files

### 2. Inline YAML Manifests

#### Kro CI/CD Pipeline Instance
- **Action**: `apply-kro-instance`
- **Resource**: `CICDPipeline` (Kro custom resource)
- **Purpose**: Creates all AWS and Kubernetes resources through Kro RGD
- **Benefits**:
  - Single resource definition
  - Proper dependency management
  - ACK-based AWS resource provisioning

#### Setup Workflow (Now in Kro RGD)
- **Resource**: Argo `Workflow` (created by Kro RGD)
- **Purpose**: Automatically sets up ECR credentials, GitLab webhooks, and cache warmup
- **Trigger**: Automatically created when Kro instance is ready
- **Templates**: Uses provisioning WorkflowTemplate with setup tasks

### 3. Skeleton Updates
- **File**: `skeleton/manifests/cicd-pipeline.yaml`
- **Changes**:
  - Updated to reference Kro-managed ConfigMaps and Secrets
  - Changed secret names to match Kro RGD naming conventions
  - Updated environment variable references for ECR repositories

### 4. GitLab Webhook Integration Updates
- **Component**: Argo Events integration
- **Changes**:
  - Added EventSource for GitLab webhook reception
  - Added Sensor for event processing and workflow triggering
  - Added Service and Ingress for webhook endpoint exposure
  - Updated webhook configuration script to use Argo Events endpoint
  - Enhanced RBAC permissions for Argo Events resources

### 5. Deprecated Files
- **Directory**: `provisioner/`
- **Status**: Deprecated but preserved for reference
- **Added**: `README.md` explaining migration and file mappings

## Key Improvements

### 1. Simplified Template Execution
- **Before**: Multiple file-based `kube:apply` actions with external dependencies and manual workflow execution
- **After**: Single Kro instance creation with automatic setup workflow execution
- **Benefit**: Eliminates file reference issues, simplifies template maintenance, and provides automatic setup

### 2. Better Resource Orchestration
- **Before**: Manual dependency management with wait steps
- **After**: Kro handles dependencies and readiness conditions automatically
- **Benefit**: More reliable resource provisioning and better error handling

### 3. Native AWS Integration
- **Before**: Crossplane providers for AWS resources
- **After**: ACK controllers for native AWS resource management
- **Benefit**: Better AWS integration, status reporting, and resource lifecycle management

### 4. Enhanced Observability
- **Before**: Limited visibility into resource creation status
- **After**: Comprehensive status tracking through Kro RGD
- **Benefit**: Better debugging and monitoring capabilities

### 5. Improved Webhook Integration
- **Before**: Direct GitLab webhook configuration with limited error handling
- **After**: Argo Events-based webhook processing with EventSource and Sensor
- **Benefit**: Better reliability, error handling, and event processing capabilities

## Resource Mapping

### AWS Resources (Now via ACK in Kro RGD)
| Old (Crossplane)                                    | New (ACK)                                              | Purpose                   |
|-----------------------------------------------------|--------------------------------------------------------|---------------------------|
| `iam.aws.upbound.io/v1beta1/Role`                   | `iam.services.k8s.aws/v1alpha1/Role`                   | IAM role for pod identity |
| `iam.aws.upbound.io/v1beta1/Policy`                 | `iam.services.k8s.aws/v1alpha1/Policy`                 | ECR access policy         |
| `iam.aws.upbound.io/v1beta1/RolePolicyAttachment`   | `iam.services.k8s.aws/v1alpha1/RolePolicyAttachment`   | Policy attachment         |
| `eks.aws.upbound.io/v1beta1/PodIdentityAssociation` | `eks.services.k8s.aws/v1alpha1/PodIdentityAssociation` | Pod identity binding      |
| Manual ECR creation                                 | `ecr.services.k8s.aws/v1alpha1/Repository`             | ECR repositories          |

### Kubernetes Resources (Now via Kro RGD)
| Resource         | Old Location                   | New Location | Purpose                 |
|------------------|--------------------------------|--------------|-------------------------|
| Namespace        | `provisioner/podidentity.yaml` | Kro RGD      | Team namespace          |
| ServiceAccount   | `provisioner/podidentity.yaml` | Kro RGD      | CI/CD service account   |
| Role/RoleBinding | `provisioner/podidentity.yaml` | Kro RGD      | RBAC configuration      |
| ConfigMap        | Workflow creation              | Kro RGD      | ECR repository info     |
| Secret           | Workflow creation              | Kro RGD      | Docker registry config  |
| EventSource      | Not implemented                | Kro RGD      | GitLab webhook receiver |
| Sensor           | Not implemented                | Kro RGD      | Event processing        |
| Webhook Service  | Not implemented                | Kro RGD      | Internal webhook access |
| Webhook Ingress  | Not implemented                | Kro RGD      | External webhook access |

## Validation Steps

### 1. Template Syntax
- ✅ YAML structure validated
- ✅ Backstage template schema compliance
- ✅ Inline manifest syntax verification

### 2. Resource References
- ✅ Kro RGD resource names match template references
- ✅ ConfigMap and Secret names updated in skeleton files
- ✅ Parameter substitution verified

### 3. Workflow Integration
- ✅ Service account references updated
- ✅ ECR repository references use ConfigMap values
- ✅ Docker secret references updated

### 4. Webhook Integration
- ✅ Argo Events EventSource and Sensor resources added to Kro RGD
- ✅ Webhook service and ingress configuration implemented
- ✅ GitLab webhook configuration updated to use Argo Events endpoint
- ✅ RBAC permissions updated for Argo Events resources

## Testing Recommendations

1. **Template Execution**: Test with various parameter combinations
2. **Resource Creation**: Verify Kro RGD creates all expected resources
3. **Workflow Execution**: Test ECR authentication and image building
4. **GitLab Integration**: Verify webhook creation and Argo Events triggering
5. **ArgoCD Integration**: Confirm application creation and deployment

## Rollback Plan

If issues arise, the old provisioner files are preserved and can be restored by:
1. Reverting `template-cicd-pipeline.yaml` to use file-based actions
2. Re-enabling the provisioner directory files
3. Updating the template to reference external files again

## Next Steps

1. Deploy updated template to development environment
2. Test end-to-end pipeline creation
3. Validate resource provisioning and workflow execution
4. Monitor for any issues or performance improvements
5. Update documentation and training materials