# EKS Capabilities Setup Guide

## Overview

This configuration has been updated to use **EKS Capabilities** - fully managed versions of ArgoCD, ACK (AWS Controllers for Kubernetes), and Kro that run in AWS-managed infrastructure. This eliminates the need to self-manage these components while providing better integration and reduced operational overhead.

## What's Changed

### 1. Updated EKS Module Version
- Upgraded from `~> 20.31.6` to `~> 21.10.1` to support EKS Capabilities

### 2. Added EKS Capabilities Resources
- **ArgoCD Capability**: Fully managed GitOps continuous deployment
- **ACK Capability**: AWS resource management from Kubernetes
- **Kro Capability**: Kubernetes resource orchestration

### 3. Identity Center Integration
The configuration supports AWS Identity Center groups for role-based access:
- **Admin Group**: Full ArgoCD admin access
- **Developer Group**: ArgoCD editor access (can deploy, limited admin functions)

## Required Variables

Add these variables when deploying:

```bash
# Identity Center configuration (optional but recommended)
export TF_VAR_identity_center_instance_arn="arn:aws:sso:::instance/ssoins-xxxxxxxxxx"
export TF_VAR_identity_center_admin_group_id="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
export TF_VAR_identity_center_developer_group_id="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
```

## Benefits of EKS Capabilities

### 1. Reduced Operational Overhead
- AWS manages the infrastructure, scaling, patching, and updates
- No need to manage ArgoCD, ACK, or Kro controllers yourself
- Automatic high availability and disaster recovery

### 2. Better Integration
- Native AWS service integration
- Optimized performance and security
- Consistent with AWS best practices

### 3. Cost Optimization
- No compute resources consumed in your cluster
- Pay only for what you use
- Reduced management overhead

### 4. Enhanced Security
- AWS-managed security updates
- Integrated with AWS Identity Center
- Proper IAM role separation

## Deployment Steps

1. **Set Environment Variables** (if using Identity Center):
   ```bash
   export TF_VAR_identity_center_instance_arn="your-instance-arn"
   export TF_VAR_identity_center_admin_group_id="your-admin-group-id"
   export TF_VAR_identity_center_developer_group_id="your-dev-group-id"
   ```

2. **Deploy the Infrastructure**:
   ```bash
   cd platform/infra/terraform/cluster
   ./deploy.sh
   ```

3. **Verify Capabilities**:
   ```bash
   # List capabilities
   aws eks list-capabilities --cluster-name peeks-hub --region us-west-2
   
   # Check capability status
   aws eks describe-capability --cluster-name peeks-hub --capability-name hub-argocd --region us-west-2
   ```

## Accessing Services

### ArgoCD UI
Once the ArgoCD capability is active, you can access the UI through the EKS console or directly via the ArgoCD endpoint.

### ACK Controllers
ACK controllers will be available to manage AWS resources through Kubernetes custom resources.

### Kro
Kro will be available for creating custom Kubernetes resource compositions.

## Migration from Self-Managed

If you're migrating from self-managed ArgoCD/ACK/Kro:

1. **Export existing configurations** before applying this change
2. **Scale down self-managed controllers** to avoid conflicts
3. **Apply the new configuration** with EKS Capabilities
4. **Migrate applications and resources** to use the managed capabilities

## Troubleshooting

### Capability Creation Issues
- Verify IAM roles have correct trust policies
- Check that Identity Center configuration is correct
- Ensure cluster is in ACTIVE state before creating capabilities

### Identity Center Integration
- Verify group IDs are correct
- Check that users are members of the appropriate groups
- Confirm Identity Center instance ARN is valid

## Cost Considerations

EKS Capabilities are billed separately:
- **ArgoCD**: ~$0.10 per hour when active
- **ACK**: ~$0.10 per hour when active  
- **Kro**: ~$0.10 per hour when active

This replaces the compute costs of running these services on your cluster nodes.
