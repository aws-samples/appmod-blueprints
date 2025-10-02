# AppMod Blueprints - Platform Architecture

## Bootstrap Script Improvements (2025-09-02)

### Enhanced ArgoCD Health Monitoring
The `scripts/0-bootstrap.sh` script has been improved with comprehensive health monitoring and waiting mechanisms:

#### New Features
- **ArgoCD Health Monitoring**: `wait_for_argocd_health()` monitors all applications for health status
- **Application Sync & Wait**: `sync_and_wait_app()` manages individual application synchronization
- **Intelligent Waiting**: After ArgoCD setup, waits for critical applications to be healthy
- **Status Reporting**: Real-time status display during deployment with color-coded indicators
- **Timeout Management**: Configurable timeouts (10min overall, 5min per app)
- **Graceful Degradation**: Continues deployment even if some apps are still syncing

#### Configuration
```bash
ARGOCD_WAIT_TIMEOUT=600      # 10 minutes overall timeout
ARGOCD_CHECK_INTERVAL=30     # 30 seconds between checks
```

#### Deployment Flow
1. **1-argocd-gitlab-setup.sh** - Sets up ArgoCD and GitLab integration
2. **Wait 30s** - Initial deployment stabilization
3. **Sync bootstrap app** - Forces sync of bootstrap ApplicationSet (5min timeout)
4. **Sync cluster-addons app** - Forces sync of cluster-addons ApplicationSet (5min timeout)  
5. **Monitor all apps** - Waits for all ArgoCD applications to be healthy (10min timeout)
6. **Final status report** - Shows ✓/⚠/✗ status for all applications
7. **2-bootstrap-accounts.sh** - Account setup (only after ArgoCD is healthy)
8. **6-tools-urls.sh** - Generate access URLs

### GitOps Configuration Fixes

#### Fleet-Secrets ApplicationSet Fix
**Issue**: The `fleet-secrets` ApplicationSet was using incorrect GitLab URL causing authentication failures.

**Solution**: Updated `gitops/fleet/bootstrap/fleet-secrets.yaml` to use correct GitLab URL:
```yaml
# Fixed URL from d1vvjck0a1cre3.cloudfront.net to d3lsxhpwx29bst.cloudfront.net
repoURL: https://d3lsxhpwx29bst.cloudfront.net/user1/platform-on-eks-workshop.git
```

#### Ingress Name Annotation Fix
**Issue**: The `ingress-nginx` ApplicationSet template expected `{{.metadata.annotations.ingress_name}}` but this annotation was missing from the hub cluster secret.

**Solution**: 
1. **Immediate fix**: Added annotation to cluster secret:
   ```bash
   kubectl annotate secret peeks-hub-cluster -n argocd ingress_name="peeks-hub-ingress-nginx"
   ```

2. **Permanent fix**: Updated `platform/infra/terraform/hub/locals.tf`:
   ```terraform
   addons_metadata = merge(
     # ... other metadata ...
     {
       ingress_name = var.ingress_name  # Added this line
       ingress_domain_name = local.ingress_domain_name
       # ... rest of config ...
     }
   )
   ```

#### Staging to Dev Rename
**Issue**: Fleet configuration still referenced "staging" environment after cluster rename.

**Solution**: Renamed and updated fleet member configuration:
```bash
# Renamed directory
mv gitops/fleet/members/fleet-spoke-staging gitops/fleet/members/fleet-spoke-dev

# Updated values.yaml
clusterName: peeks-spoke-dev
environment: dev
fleet_member: dev
secretManagerSecretName: peeks-hub-cluster/peeks-spoke-dev
```

### Deployment Dependencies
The bootstrap process now has proper dependency management:

```
1-argocd-gitlab-setup.sh
├── ArgoCD installation
├── GitLab integration  
├── Repository secrets setup
└── Wait for ArgoCD health ✓
    ├── bootstrap ApplicationSet (Synced/Healthy)
    ├── cluster-addons ApplicationSet (Synced/Healthy)  
    ├── fleet-secrets ApplicationSet (Synced/Healthy)
    └── All other applications (Monitored)
        ↓
2-bootstrap-accounts.sh (Only runs after ArgoCD is healthy)
        ↓  
6-tools-urls.sh (Generates access URLs)
```

### Status Indicators
The improved script provides clear status feedback:
- ✅ **Green ✓**: Application is Synced and Healthy
- ⚠️ **Yellow ⚠**: Application is Healthy but OutOfSync  
- ❌ **Red ✗**: Application is Degraded or Failed

### Error Handling
- **Retry Logic**: Each script retries up to 3 times with 30s delays
- **Timeout Management**: Prevents infinite waiting with configurable timeouts
- **Graceful Degradation**: Continues deployment even if some applications need more time
- **Detailed Logging**: Color-coded status messages with timestamps

## ArgoCD IAM Role Configuration Fix

### Issue
ArgoCD in the hub cluster was using the wrong IAM role (`argocd-hub-mgmt`) instead of the common role (`{resource_prefix}-argocd-hub...`) that spoke clusters trust for cross-cluster access.

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
  name = "{resource_prefix}-argocd-central-role"
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

### AWS Service Limits
- **Elastic IP Addresses**: Increase VPC Elastic IP limit from default 5 to at least 15
  ```bash
  aws service-quotas request-service-quota-increase \
    --service-code ec2 \
    --quota-code L-0263D0A3 \
    --desired-value 15 \
    --region us-west-2
  ```

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
## Resource Prefix Flow

The `resource_prefix` flows through the system as follows:

1. **Environment Variable**: `RESOURCE_PREFIX` (defaults to "peeks", CodeBuild sets to "peeks-workshop")
2. **Terraform**: Passed as `-var="resource_prefix=$RESOURCE_PREFIX"` to terraform
3. **Cluster Secrets**: Added to `addons_metadata` in terraform locals, becomes cluster secret annotation
4. **GitOps ApplicationSets**: Reference `{{.metadata.annotations.resource_prefix}}` from cluster secrets
5. **Helm Charts**: Receive via `global.resourcePrefix` value, used as `{{ .Values.global.resourcePrefix | default "peeks" }}`

This ensures consistent resource naming across all components using the same prefix source.
```

**Examples**:
- `{resource_prefix}-keycloak-admin-password`
- `{resource_prefix}-backstage-postgresql-password`
- `{resource_prefix}-argocd-admin-password`

### Secret Flow
```
AWS Secrets Manager → External Secrets Operator → Kubernetes Secrets → Applications
```

## Deployment Process

> **⚠️ IMPORTANT: Always use deployment scripts, never run terraform commands directly**
>
> Each Terraform stack (common, hub, spokes) has dedicated `deploy.sh` and `destroy.sh` scripts that handle:
> - Proper environment variable setup
> - Backend configuration and initialization  
> - State management and locking
> - Error handling and cleanup
> - Workspace management for spokes
>
> **✅ Correct usage:**
> ```bash
> # Deploy hub cluster
> cd platform/infra/terraform/hub && ./deploy.sh
> 
> # Deploy spoke cluster  
> cd platform/infra/terraform/spokes && ./deploy.sh dev
> 
> # Destroy resources
> cd platform/infra/terraform/hub && ./destroy.sh
> ```
>
> **❌ Never use direct terraform commands:**
> ```bash
> # DON'T DO THIS - bypasses proper setup
> terraform init
> terraform apply
> ```

### Phase 1: Common Infrastructure
Executed by CodeBuild from bootstrap infrastructure:

```bash
# Use the deployment script (handles init, plan, apply)
cd platform/infra/terraform/common
./deploy.sh
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
# Use the deployment script (handles init, plan, apply)
cd platform/infra/terraform/hub
./deploy.sh
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
# Use the deployment script with environment parameter
cd platform/infra/terraform/spokes
./deploy.sh dev
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
cd platform/infra/terraform/spokes && TFSTATE_BUCKET_NAME=tcat-{resource_prefix}-test--tfstatebackendbucketf0fc-8s2mpevyblwi ./deploy.sh staging

# Git push to both remotes
git push origin cdk-fleet:main
git push github cdk-fleet
```
## Helm Chart Dependencies in GitOps

### When to run `helm dependency build`

`helm dependency build` only needs to be run when:

1. **Chart dependencies are added/changed** - when you modify the `dependencies:` section in Chart.yaml
2. **Dependency versions are updated** - when you bump version numbers of dependencies  
3. **New charts with dependencies are added** - like flux/crossplane/kubevela charts

### What it's NOT needed for:
- Regular application deployments
- Configuration changes in values.yaml
- Template modifications
- Normal GitOps operations

### Best practices for GitOps:
- Run it once when setting up charts with dependencies
- Run it when dependency versions change
- Always commit the generated `Chart.lock` and `charts/` directory
- Consider adding a CI/CD check to ensure dependencies are built before merging

### Example fix:
```bash
# Add required helm repos
helm repo add crossplane-stable https://charts.crossplane.io/stable
helm repo add kubevela https://kubevela.github.io/charts

# Build dependencies for charts that need them
cd ./gitops/addons/charts/flux && helm dependency build
cd ./gitops/addons/charts/crossplane && helm dependency build  
cd ./gitops/addons/charts/kubevela && helm dependency build

# Commit the generated files
git add ./gitops/addons/charts/
git commit -m "Fix chart dependencies"
```

This ensures ArgoCD can properly render charts with their dependencies without needing to fetch them at runtime.

## Kro ResourceGraphDefinition readyWhen Conditions - Best Practices

### Key Principle

**readyWhen conditions should ONLY reference the current resource itself, never other resources.**

### Why This Matters

When Kro validates CEL expressions in `readyWhen` conditions, each resource is evaluated in isolation. The CEL expression context for `readyWhen` validation only has access to the current resource, not other resources in the RGD. This means:

- ✅ **Correct**: `${serviceaccount.metadata.name != ""}` (self-reference)
- ❌ **Incorrect**: `${eventsource.metadata.name != ""}` (reference to other resource)

### Correct Patterns by Resource Type

#### AWS ACK Resources
Use status conditions to check if the resource is actually ready:
```yaml
- id: ecrmainrepo
  readyWhen:
    - ${ecrmainrepo.status.conditions[0].status == "True"}

- id: iamrole
  readyWhen:
    - ${iamrole.status.conditions[0].status == "True"}

- id: podidentityassoc
  readyWhen:
    - ${podidentityassoc.status.conditions.exists(x, x.type == 'ACK.ResourceSynced' && x.status == "True")}
```

#### Kubernetes Resources with Status Phases
Check the appropriate status field:
```yaml
- id: appnamespace
  readyWhen:
    - ${appnamespace.status.phase == "Active"}
```

#### Simple Kubernetes Resources
Use metadata.name check or no readyWhen at all:
```yaml
- id: role
  readyWhen:
    - ${role.metadata.name != ""}

- id: configmap
  readyWhen:
    - ${configmap.metadata.name != ""}
```

#### Resources That Don't Need readyWhen
Some resources are created immediately and don't need readiness checks:
```yaml
- id: serviceaccount
  template:
    # No readyWhen needed

- id: setupworkflow
  template:
    # No readyWhen needed
```

### How Dependencies Work

Dependencies between resources are handled **implicitly through template variable usage**, not through readyWhen conditions.

#### Example: Correct Dependency Handling
```yaml
# The rolebinding depends on both role and serviceaccount
- id: rolebinding
  readyWhen:
    - ${rolebinding.metadata.name != ""}  # Only self-reference
  template:
    apiVersion: rbac.authorization.k8s.io/v1
    kind: RoleBinding
    subjects:
      - kind: ServiceAccount
        name: ${serviceaccount.metadata.name}  # Dependency expressed here
    roleRef:
      name: ${role.metadata.name}  # Dependency expressed here
```

### Common Mistakes to Avoid

#### ❌ Cross-Resource References in readyWhen
```yaml
# WRONG - This will cause "undeclared reference" errors
- id: sensor
  readyWhen:
    - ${sensor.metadata.name != ""}
    - ${eventsource.metadata.name != ""}  # ❌ References other resource
    - ${cicdworkflow.metadata.name != ""}  # ❌ References other resource
```

#### ✅ Correct Self-Reference Only
```yaml
# CORRECT - Only references itself
- id: sensor
  readyWhen:
    - ${sensor.metadata.name != ""}
  template:
    # Dependencies expressed through template variables
    dependencies:
      - name: gitlab-webhook
        eventSourceName: ${eventsource.metadata.name}  # ✅ Dependency in template
```

#### ❌ Incorrect Field References
```yaml
# WRONG - ServiceAccount doesn't have spec.name
- id: serviceaccount
  readyWhen:
    - ${serviceaccount.spec.name != ""}  # ❌ Field doesn't exist
```

#### ✅ Correct Field References
```yaml
# CORRECT - Use metadata.name for Kubernetes resources
- id: serviceaccount
  readyWhen:
    - ${serviceaccount.metadata.name != ""}  # ✅ Correct field
```

### Validation Errors and Solutions

#### Error: "undeclared reference to 'resourcename'"
**Cause**: readyWhen condition references another resource
**Solution**: Remove the cross-resource reference, keep only self-references

#### Error: "field doesn't exist"
**Cause**: Referencing incorrect field (e.g., spec.name on ServiceAccount)
**Solution**: Use correct field path (e.g., metadata.name for Kubernetes resources)

### Summary

1. **readyWhen = Self-reference only**: Check when THIS resource is ready
2. **Dependencies = Template variables**: Express dependencies through template variable usage
3. **Field validation**: Use correct field paths for each resource type
4. **Keep it simple**: Many resources don't need readyWhen conditions at all

This approach ensures that Kro can validate CEL expressions successfully and that resource dependencies are handled correctly through the implicit dependency resolution system.

## ACK Controller Role Management and Multi-Cluster Architecture

### Overview
The platform uses AWS Controllers for Kubernetes (ACK) to manage AWS resources from Kubernetes clusters. This requires careful IAM role configuration for cross-account and multi-cluster scenarios.

### Role Architecture

#### Hub Cluster ACK Controllers
The hub cluster runs ACK controllers that manage resources across multiple AWS accounts and clusters:

**Pod Identity Associations**:
- `ack-eks-controller` → `peeks-ack-eks-controller-role-mgmt`
- `ack-ec2-controller` → `peeks-ack-ec2-controller-role-mgmt`  
- `ack-iam-controller` → `peeks-ack-iam-controller-role-mgmt`
- `ack-ecr-controller` → `peeks-ack-ecr-controller-role-mgmt`
- `ack-s3-controller` → `peeks-ack-s3-controller-role-mgmt`
- `ack-dynamodb-controller` → `peeks-ack-dynamodb-controller-role-mgmt`

#### Cross-Account Role Assumption
ACK controllers use a **role chaining pattern** for cross-account access:

1. **Pod Identity Role** (e.g., `peeks-ack-eks-controller-role-mgmt`) - Base role with EKS Pod Identity trust
2. **Management Role** (e.g., `peeks-hub-cluster-cluster-mgmt-eks`) - Target role with actual AWS permissions

### ACK Role Team Map Configuration

#### ConfigMap Structure
The `ack-role-team-map` ConfigMap in the `ack-system` namespace maps namespaces to target roles:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: ack-role-team-map
  namespace: ack-system
data:
  # Format: namespace-name: "target-role-arn"
  peeks-spoke-staging: "arn:aws:iam::665742499430:role/peeks-hub-cluster-cluster-mgmt-eks"
```

#### Multi-Account Template
The ConfigMap is generated from Helm template in `/gitops/addons/charts/multi-acct/templates/configmap.yaml`:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: ack-role-team-map
  namespace: ack-system
data:
  {{- range $key, $value := .Values.clusters }}
  ec2.{{ $key }}: "arn:aws:iam::{{ $value }}:role/{{ $.Values.global.resourcePrefix | default "peeks" }}-cluster-mgmt-ec2"
  eks.{{ $key }}: "arn:aws:iam::{{ $value }}:role/{{ $.Values.global.resourcePrefix | default "peeks" }}-cluster-mgmt-eks"
  iam.{{ $key }}: "arn:aws:iam::{{ $value }}:role/{{ $.Values.global.resourcePrefix | default "peeks" }}-cluster-mgmt-iam"
  {{- end }}
```

#### Values Configuration
Clusters are defined in `/gitops/addons/tenants/tenant1/default/addons/multi-acct/values.yaml`:

```yaml
clusters:
  peeks-spoke-staging: "665742499430"
  # Add more clusters as needed
```

### Role Trust Relationships

#### Pod Identity Trust Policy
ACK controller roles must trust the EKS Pod Identity service:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "pods.eks.amazonaws.com"
      },
      "Action": [
        "sts:AssumeRole",
        "sts:TagSession"
      ]
    }
  ]
}
```

#### Cross-Account Role Chain
1. **EKS Pod Identity** assumes `peeks-ack-eks-controller-role-mgmt`
2. **ACK Controller** assumes `peeks-hub-cluster-cluster-mgmt-eks` (via role mapping)
3. **Management Role** has permissions to create/manage AWS resources

### Troubleshooting Common Issues

#### Issue: "User is not authorized to perform: sts:TagSession"
**Cause**: Role trust policy missing `sts:TagSession` permission
**Solution**: Add `sts:TagSession` to the trust policy alongside `sts:AssumeRole`

#### Issue: "Key not found in CARM configmap"
**Cause**: Missing entry in `ack-role-team-map` ConfigMap
**Solution**: Add namespace mapping to the multi-acct values.yaml and let ArgoCD sync

#### Issue: "Parsing role ARN: arn: invalid prefix"
**Cause**: ConfigMap contains account ID instead of full role ARN
**Solution**: Ensure ConfigMap values are full ARN format: `arn:aws:iam::ACCOUNT:role/ROLE-NAME`

#### Issue: ArgoCD Restores ConfigMap
**Cause**: Manual kubectl changes are reverted by ArgoCD GitOps sync
**Solution**: Always update the source Helm values in Git, never modify ConfigMap directly

### Best Practices

#### 1. Use GitOps for Role Mapping
Always update role mappings through Git commits to the multi-acct values.yaml file:

```bash
# Correct approach
vim /gitops/addons/tenants/tenant1/default/addons/multi-acct/values.yaml
git add . && git commit -m "Add cluster role mapping"
git push

# Incorrect approach (will be reverted)
kubectl patch configmap ack-role-team-map -n ack-system ...
```

#### 2. Consistent Role Naming
Follow the established naming pattern for management roles:
- `{resource-prefix}-cluster-mgmt-eks` for EKS permissions
- `{resource-prefix}-cluster-mgmt-ec2` for EC2 permissions  
- `{resource-prefix}-cluster-mgmt-iam` for IAM permissions

#### 3. Namespace-Based Isolation
Use Kubernetes namespaces to isolate resources by environment/cluster:
- `peeks-spoke-staging` namespace → staging cluster resources
- `peeks-spoke-prod` namespace → production cluster resources

#### 4. Monitor ACK Controller Logs
Check ACK controller logs for role assumption issues:

```bash
kubectl logs -n ack-system deployment/eks-chart --tail=50
kubectl logs -n ack-system deployment/ec2-chart --tail=50
```

### Kro Integration with ACK

#### Resource Graph Definitions (RGDs)
Kro RGDs create ACK resources in specific namespaces, triggering the role mapping:

```yaml
# RGD creates resources in peeks-spoke-staging namespace
apiVersion: kro.run/v1alpha1
kind: EksCluster
metadata:
  name: peeks-spoke-staging
  namespace: peeks-spoke-staging  # This triggers role mapping lookup
```

#### Role Mapping Flow
1. **Kro** creates ACK resources in namespace `peeks-spoke-staging`
2. **ACK Controller** looks up `peeks-spoke-staging` in `ack-role-team-map`
3. **ACK Controller** assumes role `peeks-hub-cluster-cluster-mgmt-eks`
4. **Management Role** creates AWS resources (EKS cluster, VPC, etc.)

### Security Considerations

#### Least Privilege Access
Management roles should have minimal permissions for their specific service:
- EKS management role: Only EKS, EC2 (for nodes), IAM (for service roles)
- ECR management role: Only ECR repository management
- S3 management role: Only S3 bucket operations

#### Cross-Account Boundaries
When managing resources across AWS accounts:
1. Create management roles in each target account
2. Update role mappings to point to correct account ARNs
3. Ensure hub cluster ACK roles can assume cross-account roles

#### Audit and Monitoring
- Enable CloudTrail for role assumption events
- Monitor ACK controller metrics and logs
- Set up alerts for failed role assumptions

This architecture provides secure, scalable multi-cluster resource management while maintaining clear separation of concerns and following AWS security best practices.