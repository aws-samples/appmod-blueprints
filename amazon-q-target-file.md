# AppMod Blueprints - Platform Architecture

## ArgoCD IAM Role Configuration Fix

### Issue
ArgoCD in the hub cluster was using the wrong IAM role (`argocd-hub-mgmt`) instead of the common role (`peeks-workshop-gitops-argocd-hub...`) that spoke clusters trust for cross-cluster access.

### Root Cause
- **Common terraform** creates `aws_iam_role.argocd_central` role for cross-cluster access
- **Hub terraform** was creating its own `argocd-hub-mgmt` role via `argocd_hub_pod_identity` module
- **Spoke clusters** trust the common role, but hub ArgoCD was using the hub-specific role
- This caused ArgoCD to fail connecting to spoke clusters with authentication errors

### Solution
Modified `/home/ec2-user/environment/platform-on-eks-workshop/platform/infra/terraform/hub/pod-identity.tf`:

1. **Removed the module approach** and replaced with direct EKS Pod Identity associations
2. **Added data source** to fetch the common ArgoCD role from SSM parameter
3. **Created direct associations** for all ArgoCD service accounts using the common role

```terraform
# Added data source for common ArgoCD role
data "aws_ssm_parameter" "argocd_hub_role" {
  name = "peeks-workshop-gitops-argocd-central-role"
}

# Replaced module with direct associations
resource "aws_eks_pod_identity_association" "argocd_controller" {
  cluster_name    = local.cluster_info.cluster_name
  namespace       = "argocd"
  service_account = "argocd-application-controller"
  role_arn        = data.aws_ssm_parameter.argocd_hub_role.value
}

resource "aws_eks_pod_identity_association" "argocd_server" {
  cluster_name    = local.cluster_info.cluster_name
  namespace       = "argocd"
  service_account = "argocd-server"
  role_arn        = data.aws_ssm_parameter.argocd_hub_role.value
}

resource "aws_eks_pod_identity_association" "argocd_repo_server" {
  cluster_name    = local.cluster_info.cluster_name
  namespace       = "argocd"
  service_account = "argocd-repo-server"
  role_arn        = data.aws_ssm_parameter.argocd_hub_role.value
}
```

4. **Updated references** in `argocd.tf` and `locals.tf` to use the common role ARN

### Deployment
Use the deploy script to apply changes:
```bash
cd /home/ec2-user/environment/platform-on-eks-workshop/platform/infra/terraform/hub
./deploy.sh
```

### Verification
After deployment, ArgoCD should be able to connect to spoke clusters and sync applications successfully.

## Project Overview
This repository contains the **Modern Engineering on AWS** platform implementation that works with the bootstrap infrastructure created by the CloudFormation stack. It provides Terraform modules, GitOps configurations, and platform services for a complete EKS-based development platform.

## Infrastructure Prerequisites
This platform assumes the following infrastructure has been created by the CloudFormation stack from the `platform-engineering-on-eks` repository:

### Bootstrap Infrastructure
- **CodeBuild Projects**: Automated deployment pipelines for Terraform modules
- **S3 Terraform State Bucket**: Backend storage for Terraform state
- **IAM Roles**: Cross-account access and service permissions
- **VSCode IDE Environment**: Browser-based development environment with Gitea
- **Environment Variables**: `GIT_PASSWORD`, cluster configurations, domain settings

### Development Environment
- **Gitea Service**: Local Git repository hosting with SSH access
- **Docker Support**: Container development capabilities
- **Git Configuration**: Automated SSH key management and repository access

## Repository Structure
```
appmod-blueprints/
├── platform/                        # Platform infrastructure and services
│   ├── infra/terraform/             # Terraform infrastructure modules
│   │   ├── common/                  # Shared infrastructure (VPC, EKS, S3)
│   │   ├── hub/                     # Hub cluster and platform services
│   │   ├── spokes/                  # Spoke clusters for workloads
│   │   └── old/                     # Legacy configurations
│   ├── backstage/                   # Backstage developer portal
│   │   ├── templates/               # Software templates for scaffolding
│   │   └── components/              # Service catalog components
│   └── components/                  # Platform CUE components
├── gitops/                          # GitOps configurations
│   ├── addons/                      # Platform addon configurations
│   │   ├── charts/                  # Helm charts for platform services
│   │   ├── bootstrap/               # Bootstrap configurations
│   │   ├── environments/            # Environment-specific configs
│   │   └── tenants/                 # Tenant-specific configurations
│   ├── fleet/                       # Fleet management configurations
│   └── workloads/                   # Application workload configurations
├── packages/                        # Package configurations
│   └── backstage/                   # Backstage package configs
└── scripts/                         # Utility and deployment scripts
```

## Terraform Module Architecture

### Common Module (`platform/infra/terraform/common/`)
**Purpose**: Foundational infrastructure shared across all environments

**Key Resources**:
- **VPC Configuration**: Multi-AZ networking with public/private subnets
- **EKS Cluster**: Managed Kubernetes cluster with auto-scaling node groups
- **S3 Backend**: Terraform state storage with DynamoDB locking
- **IAM Configuration**: Cluster access roles and service account policies
- **Core Addons**: AWS Load Balancer Controller, EBS CSI Driver
- **Security Groups**: Network access control for cluster components

**Key Files**:
```
common/
├── main.tf                    # Main infrastructure resources
├── variables.tf               # Input variables and configuration
├── outputs.tf                 # Output values for other modules
├── versions.tf                # Provider version constraints
├── github.tf                  # GitHub integration (optional)
└── backend.tf                 # S3 backend configuration
```

### Hub Module (`platform/infra/terraform/hub/`)
**Purpose**: Central platform services and GitOps control plane

**Key Resources**:
- **Backstage Developer Portal**: Service catalog and software templates
- **ArgoCD GitOps Controller**: Continuous deployment management
- **Keycloak Identity Provider**: SSO and OIDC authentication
- **External Secrets Operator**: AWS Secrets Manager integration
- **Ingress Controllers**: Traffic routing and SSL termination
- **Monitoring Stack**: CloudWatch integration and observability

**Key Files**:
```
hub/
├── main.tf                    # Hub cluster configuration
├── backstage.tf               # Backstage setup and configuration
├── argocd.tf                  # ArgoCD installation and setup
├── keycloak.tf                # Identity management configuration
├── external-secrets.tf       # Secret management setup
└── ingress.tf                 # Load balancer and routing
```

### Spokes Module (`platform/infra/terraform/spokes/`)
**Purpose**: Application workload environments (staging, production)

**Key Resources**:
- **Separate EKS Clusters**: Isolated environments for applications
- **ArgoCD Registration**: Connection to hub cluster GitOps
- **Environment-Specific Networking**: Workload-appropriate configurations
- **Application Monitoring**: Environment-specific observability
- **Workload Security**: RBAC and network policies

## GitOps Architecture

### Repository Structure
The GitOps configuration follows a hierarchical structure for multi-tenant, multi-environment management:

```
gitops/
├── addons/                          # Platform services
│   ├── charts/                      # Helm charts for services
│   │   ├── backstage/               # Backstage chart
│   │   ├── argocd/                  # ArgoCD chart
│   │   ├── keycloak/                # Keycloak chart
│   │   ├── external-secrets/        # External Secrets chart
│   │   └── ...                      # Other platform services
│   ├── bootstrap/default/           # Default addon configurations
│   ├── environments/                # Environment-specific overrides
│   └── tenants/                     # Tenant-specific configurations
├── fleet/                           # Multi-cluster management
│   └── bootstrap/                   # Fleet ApplicationSets
└── workloads/                       # Application deployments
    ├── environments/                # Environment configurations
    └── tenants/                     # Tenant workload configurations
```

### ArgoCD ApplicationSets
ApplicationSets generate Applications dynamically based on cluster and tenant configurations:

**Key ApplicationSets**:
- **Addons ApplicationSet**: Deploys platform services to clusters
- **Workloads ApplicationSet**: Manages application deployments
- **Fleet ApplicationSet**: Handles multi-cluster coordination

**Template Variables**:
```yaml
{{.metadata.annotations.addons_repo_basepath}}    # = "gitops/addons/"
{{.metadata.annotations.ingress_domain_name}}     # = Platform domain
{{.metadata.labels.environment}}                  # = "control-plane"
{{.metadata.labels.tenant}}                       # = "tenant1"
{{.name}}                                          # = Cluster name
```

## Platform Services

### Identity and Access Management

#### Keycloak Configuration
- **Database**: PostgreSQL with persistent storage
- **Realms**: `master` (admin) and `platform` (applications)
- **OIDC Clients**: Backstage, ArgoCD, Argo Workflows, Kargo
- **User Management**: Test users with role-based access
- **Integration**: External Secrets for client secret management

#### Authentication Flow
```
User Login → Keycloak OIDC → JWT Token → Platform Services
```

### Developer Portal

#### Backstage Integration
- **Service Catalog**: Centralized service discovery
- **Software Templates**: Application scaffolding and deployment
- **Tech Docs**: Documentation as code
- **OIDC Authentication**: Keycloak integration for SSO
- **Database**: PostgreSQL for catalog storage

#### Template Structure
```
platform/backstage/
├── templates/                    # Software templates
│   ├── eks-cluster-template/     # EKS cluster creation
│   ├── app-deploy/              # Application deployment
│   └── cicd-pipeline/           # CI/CD pipeline setup
└── components/                   # Catalog components
```

### Git Repository Management

#### Gitea Service (from Bootstrap)
- **Local Git Hosting**: Repository management within the platform
- **SSH Access**: Automated key management for Git operations
- **API Integration**: RESTful API for repository automation
- **User Management**: Workshop user with platform access

#### GitHub Integration (Optional)
- **External Repositories**: GitHub as alternative to local Gitea
- **Terraform Provider**: Automated repository creation
- **Authentication**: Personal access tokens via `git_password`

**Configuration Variables**:
```hcl
variable "create_github_repos" {
  description = "Enable GitHub repository creation"
  type        = bool
  default     = false
}

variable "git_password" {
  description = "Git authentication token"
  type        = string
}

variable "gitea_user" {
  description = "Git service username"
  type        = string
  default     = "user1"
}
```

## Secret Management Architecture

### External Secrets Operator
The platform uses a comprehensive secret management strategy:

**Secret Stores**:
- **AWS Secrets Manager**: Primary external secret store
- **Kubernetes Secrets**: Local cluster secret references
- **ClusterSecretStores**: `argocd`, `keycloak` for cross-namespace access

**Secret Categories**:
1. **Database Credentials**: PostgreSQL passwords for services
2. **OIDC Client Secrets**: Keycloak client authentication
3. **Git Credentials**: Repository access tokens
4. **Platform Configuration**: Domain names, cluster metadata

### Secret Naming Convention
```
{project_context_prefix}-{service}-{type}-password
```

**Examples**:
- `peeks-workshop-gitops-keycloak-admin-password`
- `peeks-workshop-gitops-backstage-postgresql-password`
- `peeks-workshop-gitops-argocd-admin-password`

### Secret Flow
```
AWS Secrets Manager → External Secrets Operator → Kubernetes Secrets → Applications
```

## Deployment Process

### Phase 1: Common Infrastructure
Executed by CodeBuild from bootstrap infrastructure:

```bash
# Deploy foundational infrastructure
terraform init
terraform plan -var-file="common.tfvars"
terraform apply
```

**Creates**:
- VPC with multi-AZ subnets
- EKS cluster with managed node groups
- S3 backend for state management
- IAM roles and policies
- Core Kubernetes addons

### Phase 2: Hub Cluster Services
Deploys platform services to the hub cluster:

```bash
# Deploy platform services
terraform init
terraform plan -var-file="hub.tfvars"
terraform apply
```

**Creates**:
- ArgoCD GitOps controller
- Backstage developer portal
- Keycloak identity provider
- External Secrets Operator
- Ingress and networking

### Phase 3: Spoke Clusters (Optional)
Deploys application environments:

```bash
# Deploy workload clusters
terraform init
terraform plan -var-file="spokes.tfvars"
terraform apply
```

**Creates**:
- Separate EKS clusters for staging/production
- ArgoCD registration with hub cluster
- Environment-specific configurations

### Phase 4: GitOps Applications
ArgoCD automatically deploys applications based on Git configurations:

```
Git Commit → ArgoCD Sync → Kubernetes Apply → Application Running
```

## Configuration Management

### Environment Variables (from Bootstrap)
```bash
# Git service configuration
GIT_PASSWORD=${GIT_PASSWORD}           # From IDE_PASSWORD
GITEA_USERNAME=workshop-user           # Git service user
GITEA_EXTERNAL_URL=https://domain/gitea # Git service URL

# Deployment configuration
WORKSHOP_GIT_URL=https://github.com/aws-samples/appmod-blueprints
TFSTATE_BUCKET_NAME=${bucket_name}     # From CloudFormation
```

### Terraform Variables
```hcl
# Git integration
variable "git_password" {
  description = "Git authentication token"
  type        = string
}

# Cluster configuration
variable "cluster_name" {
  description = "EKS cluster name"
  type        = string
}

variable "region" {
  description = "AWS region"
  type        = string
}

# GitHub integration (optional)
variable "create_github_repos" {
  description = "Enable GitHub repository creation"
  type        = bool
  default     = false
}
```

## Networking Architecture

### VPC Configuration
- **Multi-AZ Deployment**: High availability across availability zones
- **Public Subnets**: Load balancers, NAT gateways, bastion hosts
- **Private Subnets**: EKS worker nodes, application pods
- **Security Groups**: Fine-grained network access control
- **VPC Endpoints**: Private connectivity to AWS services

### Ingress and Load Balancing
- **AWS Load Balancer Controller**: Kubernetes-native load balancing
- **Application Load Balancer**: Layer 7 routing and SSL termination
- **CloudFront Integration**: Global content delivery (from bootstrap)
- **Route 53**: DNS management and health checks
- **Certificate Manager**: Automated SSL/TLS certificates

## Monitoring and Observability

### CloudWatch Integration
- **Container Insights**: EKS cluster and pod metrics
- **Log Aggregation**: Centralized logging for all services
- **Custom Metrics**: Application-specific monitoring
- **Alerting**: CloudWatch alarms for operational events

### Application Monitoring
- **Health Checks**: Kubernetes liveness and readiness probes
- **Service Mesh**: Optional Istio integration for advanced observability
- **Distributed Tracing**: Application performance monitoring
- **Metrics Collection**: Prometheus-compatible metrics

## Security Architecture

### Cluster Security
- **RBAC Integration**: Kubernetes role-based access control
- **Pod Security Standards**: Enforced security policies
- **Network Policies**: Micro-segmentation for workloads
- **Image Security**: Container image scanning and policies

### Secret Security
- **Encryption at Rest**: AWS KMS encryption for secrets
- **Encryption in Transit**: TLS for all service communication
- **Secret Rotation**: Automated credential rotation
- **Least Privilege**: Minimal required permissions

## Backup and Disaster Recovery

### Data Persistence
- **Database Backups**: Automated PostgreSQL backups
- **Git Repositories**: Distributed version control provides inherent backup
- **Terraform State**: S3 versioning and cross-region replication
- **Kubernetes Resources**: GitOps ensures declarative recovery

### Recovery Procedures
1. **Infrastructure Recovery**: Terraform re-deployment from state
2. **Application Recovery**: ArgoCD sync from Git repositories
3. **Data Recovery**: Database restoration from backups
4. **Configuration Recovery**: External Secrets Operator re-sync

## Scalability and Performance

### Horizontal Scaling
- **EKS Node Groups**: Auto-scaling based on resource demands
- **Application Pods**: Horizontal Pod Autoscaler (HPA)
- **Database Scaling**: Read replicas and connection pooling
- **Load Distribution**: Multi-AZ deployment patterns

### Performance Optimization
- **Resource Management**: Proper Kubernetes requests and limits
- **Caching Strategies**: Application and infrastructure caching
- **Database Optimization**: Query optimization and indexing
- **Network Optimization**: VPC endpoints and efficient routing

## Development Workflow

### GitOps Workflow
1. **Code Development**: Developer creates/modifies applications
2. **Git Commit**: Changes pushed to Git repository
3. **ArgoCD Detection**: Monitors repository for changes
4. **Automated Deployment**: Applies changes to target clusters
5. **Health Monitoring**: Validates deployment success

### Platform Management
1. **Infrastructure Changes**: Terraform modifications
2. **CodeBuild Execution**: Automated infrastructure updates
3. **Service Updates**: Platform service configuration changes
4. **GitOps Sync**: ArgoCD applies service updates

### Application Lifecycle
1. **Template Selection**: Developer chooses Backstage template
2. **Repository Creation**: Automated Git repository setup
3. **CI/CD Pipeline**: Automated build and deployment pipeline
4. **Environment Promotion**: Staging to production workflow

## Integration Points

### Cross-Service Dependencies
1. **Identity Federation**: Keycloak provides SSO for all services
2. **Secret Management**: External Secrets Operator for credential sharing
3. **Git Integration**: Gitea/GitHub for source control
4. **Monitoring Integration**: Unified observability across services

### External Integrations
1. **AWS Services**: Secrets Manager, CloudWatch, Route 53
2. **Git Providers**: GitHub, GitLab (optional)
3. **Container Registries**: ECR, Docker Hub
4. **Monitoring Systems**: Prometheus, Grafana (optional)

This architecture provides a production-ready platform engineering solution that combines infrastructure automation, GitOps workflows, developer productivity tools, and enterprise security in a scalable, maintainable manner.

## Deployment and Git Configuration (2025-08-29)

### Load Balancer Naming Fix
- Fixed ingress load balancer naming from "hub-ingress" to "peeks-hub-ingress"
- Updated terraform.tfvars: `ingress_name = "peeks-hub-ingress"`
- Fixed Git conflict marker in spokes/deploy.sh script
- Successfully deployed hub and spoke staging clusters

### Git Push Configuration
- **Origin (GitLab)**: Push `cdk-fleet:main` 
- **GitHub**: Push `cdk-fleet` branch
- Both deployments completed successfully with correct security groups and naming

### Key Commands
```bash
# Deploy hub cluster
cd platform/infra/terraform/hub && ./deploy.sh

# Deploy spoke staging
cd platform/infra/terraform/spokes && TFSTATE_BUCKET_NAME=tcat-peeks-workshop-test--tfstatebackendbucketf0fc-8s2mpevyblwi ./deploy.sh staging

# Git push to both remotes
git push origin cdk-fleet:main
git push github cdk-fleet
```
