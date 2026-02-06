# Release Notes

---

## EKS Capabilities Integration (feat/eks-capabilities-integration)

### Overview

This release integrates Amazon EKS Capabilities - fully managed versions of Argo CD, ACK, and kro that run in AWS-managed infrastructure, eliminating the need to self-manage these components.

### Major Features

#### EKS Managed Capabilities

- **Managed Argo CD**: Replaced self-hosted Argo CD with EKS Capability for GitOps
- **Managed ACK Controllers**: AWS Controllers for Kubernetes as managed capability
- **Managed kro**: Kubernetes Resource Orchestrator as managed capability
- **Identity Center Integration**: RBAC via AWS Identity Center groups (`eks-argocd-admins`, `eks-argocd-developers`)

#### Infrastructure Changes

- **EKS Module Upgrade**: Updated from `~> 20.31.6` to `~> 21.10.1` for Capabilities support
- **Custom Karpenter Nodepools**: Switched from Auto Mode default nodepools to custom Karpenter nodepools
- **Identity Center Terraform Module**: New module at `platform/infra/terraform/identity-center/` for IDC group/user management
- **EKS Capabilities RBAC**: Added ClusterRole/ClusterRoleBinding for managed kro capability

#### HuggingFace Model Downloads

- **Kro RGD for Model Downloads**: New ResourceGraphDefinition replacing CodeBuild-based downloads
- **Argo Workflows Integration**: Model downloads run as Kubernetes-native workflows
- **Pod Identity**: Proper IAM integration for S3 uploads

#### Keycloak Improvements

- **Split-Brain Detector**: CronJob to detect and heal Keycloak cluster split-brain scenarios
- **Enhanced Secret Generation**: Improved secret management templates

#### Argo CD Recovery

- **Automatic Workflow Recovery**: Added recovery for stuck Argo Workflows
- **Improved Stuck App Detection**: Better handling of stale finished operations
- **Revision Conflict Recovery**: Enhanced sync wave monitoring

### New Documentation

- `docs/EKS-Capabilities-ArgoCD-Setup.md`: Configuration guide for EKS managed Argo CD
- `docs/huggingface-model-download.md`: Kro-based model download documentation
- `platform/infra/terraform/cluster/EKS_CAPABILITIES_SETUP.md`: EKS Capabilities deployment guide

### Bug Fixes

- Added lifecycle rule to prevent CloudFront VPC origin update conflicts
- Added EKS cluster security group to RDS ingress rules
- Fixed dynamic server in fleet-secrets ApplicationSet
- Removed duplicate ClusterSecretStore
- Updated Backstage external secret for EKS managed Argo CD

### Breaking Changes

- Argo CD now runs as EKS Capability (not self-hosted)
- Requires AWS Identity Center for Argo CD RBAC
- GitOps Bridge cluster secrets use EKS cluster ARN as server

### Migration Notes

- Associate `AmazonEKSClusterAdminPolicy` with `AmazonEKSCapabilityArgoCDRole`
- Update cluster secrets to use EKS cluster ARN instead of `https://kubernetes.default.svc`
- Configure Identity Center groups for Argo CD access

---

**Release Date**: February 2026
**Branch**: feat/eks-capabilities-integration → main

---

## riv25 Branch Merge

### Overview

This release merges the `riv25` branch into `main`, bringing significant platform enhancements, new features, and stability improvements for the EKS application modernization blueprint.

## Major Features

### Platform Architecture

- **Decoupled Deployment Model**: Separated cluster creation from bootstrap process for improved modularity
- **Multi-Cluster Fleet Management**: Enhanced spoke cluster (dev/prod) configuration and secret management
- **High Availability Configuration**: Comprehensive HA setup for critical platform addons including Argo CD, Keycloak, and KubeVela

### GitOps & CI/CD

- **KRO (Kubernetes Resource Orchestrator)**:
  - Upgraded to v0.6.1
  - Added CI/CD pipeline implementation using KRO Resource Graph Definitions (RGD)
  - Integrated KRO with Backstage for streamlined resource management
- **Argo Workflows**: Enabled and configured for workflow orchestration
- **Argo Events**: Added event-driven automation with GitLab webhook integration
- **Kargo**: Enabled progressive delivery and promotion workflows
- **Progressive Delivery**: Extended gate pauses and rollout tracking with Argo Rollouts

### Developer Platform

- **Backstage Enhancements**:
  - GitLab integration with custom plugin for improved timeout handling
  - Argo CD plugin integration (Roadie's Argo CD Plugin)
  - New templates for DynamoDB, S3, and EKS cluster provisioning
  - KRO catalog and pipeline templates
- **JupyterHub**: Added addon for ML/data science workloads

### Infrastructure as Code

- **Crossplane**:
  - Migrated to EKS Pod Identity
  - Separated core Crossplane from AWS provider
  - Added compositions and provider configurations
- **Flux CD**:
  - Enabled on spoke clusters
  - Integrated with GitOps bridge templating
- **ACK (AWS Controllers for Kubernetes)**:
  - Enabled S3, DynamoDB, ECR, and IAM controllers
  - Configured with EKS Pod Identity

### Observability

- **Grafana Operator**: Added and enabled
- **Rust Metrics Dashboard**: Custom dashboard for Rust application monitoring
- **AWS Observability Accelerator**: Integrated terraform-aws-observability-accelerator module
- **DevLake**: Added DORA metrics tracking and deployment

### Security & Compliance

- **Keycloak**:
  - Configured for PKCE authentication
  - StatefulSet deployment for HA
  - Automated client configuration for Argo CD, Grafana, and GitLab
- **Kyverno**: Configured policies (disabled by default for workshop)
- **External Secrets Operator**: Enhanced with ClusterSecretStore configurations
- **Security Hub**: Added Terraform integration

## Infrastructure Improvements

### Networking

- **GitLab**: Migrated to private NLB with VPC origin
- **CloudFront**: Increased timeout configurations
- **Ingress**: Priority routing for Argo Events webhooks

### Compute

- **EKS Auto Mode**: Optimized nodepool configurations
- **Critical Addons**: Moved to system nodepool with PodDisruptionBudgets
- **Topology Spread**: Configured nginx with zone-aware spreading

### Storage & Data

- **RDS**: Added security group ingress rules for EKS cluster
- **S3**: Force delete configuration for ECR repositories

## Application Updates

### Sample Applications

- **Rust Application**: Updated with metrics and dashboard
- **Java Application**: Fixed timeouts for rollout checks, updated components
- **HuggingFace Models**: Added download support and platform manifest updates

## Developer Experience

### Scripts & Automation

- **Idempotent Operations**: GitLab repository setup and webhook configuration
- **Retry Logic**: Added to deployment scripts for improved reliability
- **Cleanup Scripts**: Argo CD app deletion and webhook cleanup
- **Init Process**: Enhanced stability with proper sourcing and wait logic

### Docs Updates

- **README**: Comprehensive updates with architecture diagrams
- **CloudFormation**: Fixed instructions and template links
- **On Your Own**: Updated deployment instructions

## Bug Fixes

### Argo CD

- Improved stuck app detection and recovery
- Fixed operation termination checks
- Enhanced sync wave monitoring
- Resolved revision conflict recovery

### GitLab

- Fixed personal access token expiration (2026-12-31)
- Resolved git tag handling issues
- Fixed push stale info errors
- HTTPS token configuration

### Terraform

- Fixed EKS access entry ARN format conversion
- Resolved circular dependencies
- Added explicit dependencies for access policies
- Fixed timeout and retry logic

### Templates

- Fixed YAML syntax errors across Backstage templates
- Corrected API versions and resource references
- Updated action names (argocd:create-resources, kube:apply)
- Fixed variable references and hostname configurations

## Breaking Changes

- Crossplane now uses EKS Pod Identity instead of IRSA
- GitLab moved to private NLB (requires VPC access)
- Backstage templates updated to use `kube:apply` instead of `argocd:create-app`

## Migration Notes

- Existing clusters should review Pod Identity configurations
- Update any custom Backstage templates to use new action names
- Review and update GitLab access patterns for private NLB

## Dependencies

- KRO: v0.6.1
- KubeVela: v1.10.0
- External Secrets Operator: v0.19.2
- Flux: v2 with updated CRD APIs
- Observability Accelerator: v2.13.1

## New Documentation

- **GitOps Bridge Architecture**: Added comprehensive documentation explaining the GitOps Bridge pattern, three-tier configuration system, cluster secrets, ApplicationSets, and External Secrets integration (`docs/platform/gitops-bridge-architecture.md`)

## Contributors

Special thanks to all contributors who made this release possible through extensive testing, bug fixes, and feature development.

---

**Release Date**: February 2026
**Branch**: riv25 → main
**Commits**: 800+ commits merged
