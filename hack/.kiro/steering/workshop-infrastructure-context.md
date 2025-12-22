# Workshop Infrastructure Context

## Purpose

Provides context about the workshop's infrastructure and proper deployment patterns for the platform-on-eks-workshop repository.

## Instructions

### Workshop Repository Structure

- Workshop participants work in the `platform-on-eks-workshop` repository (ID: WORKSHOP_MAIN_REPO)
- Infrastructure is located in `platform/infra/terraform/` with organized modules: cluster/, common/ (ID: WORKSHOP_TERRAFORM_STRUCTURE)
- GitOps configurations are in `gitops/addons/` with charts, bootstrap, environments, and tenants (ID: WORKSHOP_GITOPS_STRUCTURE)

### Deployment Script Usage

- ALWAYS use deployment scripts `deploy.sh` and `destroy.sh` instead of direct terraform commands (ID: WORKSHOP_USE_DEPLOY_SCRIPTS)
- Deployment scripts handle proper environment variable setup, backend configuration, and state management (ID: WORKSHOP_SCRIPT_BENEFITS)
- For cluster infrastructure: `cd platform/infra/terraform/cluster && ./deploy.sh` (ID: WORKSHOP_CLUSTER_DEPLOY)
- For platform addons: `cd platform/infra/terraform/common && ./deploy.sh` (ID: WORKSHOP_COMMON_DEPLOY)

### Infrastructure Phases

- **Phase 1**: Cluster infrastructure (hub, dev, prod EKS clusters) via cluster/ module (ID: WORKSHOP_PHASE1_CLUSTERS)
- **Phase 2**: Platform addons (ArgoCD, Backstage, Keycloak, External Secrets, ACK controllers) via common/ module (ID: WORKSHOP_PHASE2_ADDONS)
- **Phase 3**: GitOps applications automatically deployed by ArgoCD based on Git configurations (ID: WORKSHOP_PHASE3_GITOPS)

### EKS Auto Mode and Capabilities

- Clusters use EKS Auto Mode - Karpenter is NOT running inside clusters (ID: WORKSHOP_EKS_AUTO_MODE)
- EKS Capabilities are enabled for ArgoCD, Kro, and ACK - these controllers run as managed services (ID: WORKSHOP_EKS_CAPABILITIES)
- Node management is handled automatically by EKS Auto Mode (ID: WORKSHOP_AUTO_NODE_MGMT)

### Resource Prefix and Naming

- Resource prefix flows from environment variable `RESOURCE_PREFIX` (defaults to "peeks") (ID: WORKSHOP_RESOURCE_PREFIX)
- Terraform passes prefix to cluster secrets as annotation, used by GitOps for consistent naming (ID: WORKSHOP_PREFIX_FLOW)
- All resources use consistent naming: `{resource_prefix}-{service}-{cluster}` pattern (ID: WORKSHOP_NAMING_PATTERN)

### Multi-Cluster Architecture

- Hub cluster (control-plane) runs platform services: ArgoCD, Backstage, Keycloak (ID: WORKSHOP_HUB_CLUSTER)
- Spoke clusters (dev, prod) run workloads and connect to hub for management (ID: WORKSHOP_SPOKE_CLUSTERS)
- ACK controllers in hub manage AWS resources across all clusters via role assumption (ID: WORKSHOP_CROSS_CLUSTER_ACK)

### Workshop File Paths

- All file paths reference the workshop repository: `/home/ec2-user/environment/platform-on-eks-workshop/` (ID: WORKSHOP_BASE_PATH)
- Terraform modules: `/home/ec2-user/environment/platform-on-eks-workshop/platform/infra/terraform/` (ID: WORKSHOP_TF_PATH)
- GitOps configs: `/home/ec2-user/environment/platform-on-eks-workshop/gitops/addons/` (ID: WORKSHOP_GITOPS_PATH)

## Priority

Critical

## Error Handling

- If deployment fails, check environment variables are set correctly
- If resources not found, verify correct terraform module and deployment phase
- If GitOps not working, ensure ArgoCD is deployed and cluster secrets exist
