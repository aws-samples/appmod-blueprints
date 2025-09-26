---
title: "AI Context Document - Application Modernization Blueprints Platform"
persona: ["ai-assistant"]
deployment-scenario: ["platform-only", "full-workshop", "manual"]
difficulty: "advanced"
estimated-time: "reference"
prerequisites: ["AI assistant context", "Platform knowledge"]
related-pages: ["README.md", "ARCHITECTURE.md", "platform-engineering-on-eks/AI-CONTEXT.md"]
repository: "appmod-blueprints"
last-updated: "2025-01-19"
---

# AI Context Document - Application Modernization Blueprints Platform

## Project Overview

This repository contains the **platform implementation** and application modernization blueprints for building modern, cloud-native applications on AWS EKS. It provides GitOps configurations, platform components, application templates, and operational patterns that create a comprehensive platform engineering solution.

### Repository Purpose
- **Primary Role**: Platform services, GitOps workflows, and application blueprints
- **Target Users**: Developers, platform adopters, platform engineers, DevOps teams
- **Key Output**: Complete GitOps-based platform with self-service capabilities
- **Integration**: Works with [platform-engineering-on-eks](https://gitlab.aws.dev/aws-tfc-containers/containers-hands-on-content/platform-engineering-on-eks) for infrastructure bootstrap

### What This Repository Provides
1. **GitOps Platform**: Complete ArgoCD-based platform with multi-environment support
2. **Application Blueprints**: Ready-to-use templates for multiple technology stacks
3. **Platform Components**: Crossplane, Backstage, monitoring, security, and networking
4. **Developer Experience**: Self-service capabilities through Backstage templates and GitOps workflows

## Architecture Overview

### High-Level Platform Components
```
Developer Interface Layer
├── Backstage Portal (Self-Service Templates)
├── Development Environment (VSCode + GitLab)
└── Git Repositories (Source Code & GitOps)

Platform Control Plane (Hub Cluster)
├── ArgoCD (GitOps Controller)
├── Crossplane (Infrastructure as Code)
├── External Secrets Operator (Secret Management)
├── Cert Manager (TLS Automation)
└── GitLab (Git Repository Hosting)

Application Runtime (Spoke Clusters)
├── AWS Load Balancer Controller (Traffic Routing)
├── Monitoring Stack (Prometheus + Grafana)
├── Logging Stack (Fluent Bit + CloudWatch)
└── Application Workloads (Multi-Language Support)

AWS Infrastructure Services
├── EKS Clusters (Hub + Spoke Architecture)
├── VPC & Networking (Multi-AZ Configuration)
├── AWS Secrets Manager (Centralized Secrets)
├── RDS Databases (Managed Databases)
├── S3 Storage (Object Storage)
└── IAM Roles (Pod Identity)
```

### Repository Relationship
- **This repo**: Platform implementation, GitOps configurations, application blueprints
- **platform-engineering-on-eks**: Infrastructure bootstrap, CDK deployment, workshop environment
- **Integration Flow**: Bootstrap creates infrastructure → This repo deploys platform services → GitOps manages applications

## Key Concepts and Terminology

### Platform Architecture Terms
- **Platform Services**: Core Kubernetes operators and controllers providing platform capabilities
- **GitOps Workflow**: Declarative deployment pattern using Git as source of truth
- **Hub-and-Spoke Architecture**: Multi-cluster pattern with centralized control plane and distributed workload clusters
- **Application Blueprints**: Standardized templates for different technology stacks and deployment patterns
- **Self-Service Infrastructure**: Developer-accessible APIs for provisioning cloud resources

### GitOps Terms
- **ArgoCD**: GitOps controller managing continuous deployment from Git repositories
- **ApplicationSets**: ArgoCD resources enabling templated, multi-cluster application deployment
- **GitOps Bridge**: Data pipeline connecting infrastructure metadata to GitOps applications
- **Cluster Registration**: Process where clusters automatically register metadata for GitOps discovery
- **Sync Waves**: Ordered deployment phases ensuring proper dependency management

### Platform Components
- **Backstage**: Developer portal providing self-service application creation and service catalog
- **Crossplane**: Kubernetes-native infrastructure as code for cloud resource provisioning
- **External Secrets Operator**: Kubernetes operator for syncing secrets from external systems
- **Ingress Controller**: Traffic routing and load balancing for applications
- **Service Mesh**: Communication layer providing security, observability, and traffic management

### Infrastructure Integration Terms
- **CloudFormation Integration**: AWS native infrastructure as code service integration patterns
- **Pod Identity**: AWS EKS feature for secure, credential-free access to AWS services
- **Resource Prefix**: Consistent naming convention for all platform resources
- **Environment Isolation**: Separation of development, staging, and production environments
- **Multi-Tenant Architecture**: Platform design supporting multiple teams and applications securely

## File Structure and Key Components

### Platform Infrastructure (`platform/`)
```
platform/
├── infra/terraform/               # Terraform infrastructure modules
│   ├── common/                    # Shared infrastructure (VPC, EKS, S3)
│   ├── hub/                       # Hub cluster and platform services
│   ├── spokes/                    # Spoke clusters for workloads
│   └── old/                       # Legacy configurations
├── backstage/                     # Backstage developer portal
│   ├── templates/                 # Software templates for scaffolding
│   └── components/                # Service catalog components
└── components/                    # Platform CUE components
```

### GitOps Configurations (`gitops/`)
```
gitops/
├── addons/                        # Platform addon configurations
│   ├── charts/                    # Helm charts for platform services
│   ├── bootstrap/                 # Bootstrap configurations
│   ├── environments/              # Environment-specific configs
│   └── tenants/                   # Tenant-specific configurations
├── fleet/                         # Fleet management configurations
│   ├── bootstrap/                 # Fleet ApplicationSets
│   └── members/                   # Fleet member configurations
├── platform/                     # Platform service configurations
└── workloads/                     # Application workload configurations
```

### Application Blueprints (`applications/`)
```
applications/
├── dotnet/                        # .NET applications with clean architecture
├── java/                          # Java Spring Boot microservices
├── node/                          # Node.js Express applications
├── python/                        # Python FastAPI services
├── rust/                          # Rust high-performance web services
├── golang/                        # Go cloud-native microservices
├── next-js/                       # Next.js React applications
└── mono-a2c/                      # Monolith to containers migration
```

### Package Configurations (`packages/`)
```
packages/
├── ack/                           # AWS Controllers for Kubernetes
├── argocd/                        # ArgoCD configurations
├── backstage/                     # Backstage configurations
├── cert-manager/                  # Certificate management
├── crossplane/                    # Infrastructure as code
├── external-secrets/              # Secret management
├── grafana/                       # Monitoring and dashboards
├── ingress-nginx/                 # Ingress controller
├── keycloak/                      # Identity and access management
└── kyverno/                       # Policy engine
```

## Terraform Module Architecture

### Common Module (`platform/infra/terraform/common/`)
**Purpose**: Foundational infrastructure shared across all environments

**Key Resources**:
- VPC Configuration (Multi-AZ networking with public/private subnets)
- EKS Cluster (Managed Kubernetes with auto-scaling node groups)
- S3 Backend (Terraform state storage with DynamoDB locking)
- IAM Configuration (Cluster access roles and service account policies)
- Core Addons (AWS Load Balancer Controller, EBS CSI Driver)
- Security Groups (Network access control for cluster components)

### Hub Module (`platform/infra/terraform/hub/`)
**Purpose**: Central platform services and GitOps control plane

**Key Resources**:
- Backstage Developer Portal (Service catalog and software templates)
- ArgoCD GitOps Controller (Continuous deployment management)
- Keycloak Identity Provider (SSO and OIDC authentication)
- External Secrets Operator (AWS Secrets Manager integration)
- Ingress Controllers (Traffic routing and SSL termination)
- Monitoring Stack (CloudWatch integration and observability)

### Spokes Module (`platform/infra/terraform/spokes/`)
**Purpose**: Application workload environments (staging, production)

**Key Resources**:
- Separate EKS Clusters (Isolated environments for applications)
- ArgoCD Registration (Connection to hub cluster GitOps)
- Environment-Specific Networking (Workload-appropriate configurations)
- Application Monitoring (Environment-specific observability)
- Workload Security (RBAC and network policies)

## GitOps Architecture and Patterns

### GitOps Repository Structure
```
GitOps Flow:
Git Repositories → ArgoCD ApplicationSets → Kubernetes Manifests → Running Applications

Repository Types:
├── Platform Repo (Core platform services)
├── Addons Repo (Cluster addons)
├── Workloads Repo (Applications)
└── Fleet Repo (Multi-cluster config)
```

### Cluster Registration Pattern
**Key Feature**: Automatic cluster discovery and configuration

**How it Works**:
1. Infrastructure tools (Terraform/KRO/Crossplane) create EKS clusters
2. Cluster registration secret created in AWS Secrets Manager with metadata
3. External Secrets Operator syncs secrets to hub cluster
4. ArgoCD ApplicationSets discover clusters and deploy applications dynamically

**Cluster Registration Secret Format**:
```json
{
  "cluster_name": "spoke-dev-us-east-1",
  "cluster_endpoint": "https://ABC123.gr7.us-east-1.eks.amazonaws.com",
  "resource_prefix": "peeks-workshop",
  "environment": "dev",
  "tenant": "platform-team",
  "cluster_type": "spoke",
  "labels": {
    "environment": "dev",
    "cluster-type": "spoke",
    "tenant": "platform-team"
  },
  "annotations": {
    "addons_repo_basepath": "gitops/addons/",
    "workloads_repo_basepath": "gitops/workloads/",
    "kustomize_path": "environments/dev",
    "resource_prefix": "peeks-workshop"
  }
}
```

### ApplicationSet Integration
ArgoCD ApplicationSets use cluster metadata for dynamic configuration:
- **Cluster Discovery**: Automatically find new clusters via secrets
- **Environment-Specific Deployment**: Use labels for environment targeting
- **Multi-Tenant Support**: Tenant-based application deployment
- **Configuration Templating**: Annotations provide deployment customization

## Platform Components Deep Dive

### ArgoCD - GitOps Controller
**Configuration**: `gitops/platform/charts/argo-cd/`
**Key Features**:
- Multi-cluster application deployment
- ApplicationSets for environment promotion
- RBAC integration with external identity providers
- Automated sync and drift detection
- Web UI for deployment visualization

### Backstage - Developer Portal
**Configuration**: `platform/backstage/`
**Key Features**:
- Application templates and scaffolding
- Service catalog and documentation
- CI/CD pipeline integration
- Infrastructure visibility
- Plugin ecosystem for extensibility

### Crossplane - Infrastructure as Code
**Configuration**: `platform/crossplane/`
**Key Features**:
- AWS resource compositions (RDS, S3, IAM)
- Self-service infrastructure through Kubernetes CRDs
- Policy-driven resource management
- Cost optimization through resource lifecycle management
- GitOps-native infrastructure provisioning

### External Secrets Operator - Secret Management
**Key Features**:
- AWS Secrets Manager integration
- Automatic secret rotation
- Cross-namespace secret sharing
- Pod Identity authentication
- Multiple secret store support

## Application Blueprints and Technology Support

### Supported Technology Stacks

#### .NET Applications (`applications/dotnet/`)
- **Architecture**: Clean Architecture pattern with Entity Framework
- **Database**: PostgreSQL integration with migrations
- **Observability**: Health checks, metrics, and logging
- **Deployment**: Multi-stage Dockerfile with optimized builds

#### Java Applications (`applications/java/`)
- **Framework**: Spring Boot microservices with Spring Data JPA
- **Build System**: Maven with multi-module projects
- **Monitoring**: Actuator endpoints and Micrometer metrics
- **Testing**: JUnit 5 with integration test support

#### Node.js Applications (`applications/node/`)
- **Framework**: Express.js with TypeScript support
- **Package Management**: npm/yarn with lock files
- **Development**: Hot reload and debugging support
- **Security**: Helmet.js and security best practices

#### Python Applications (`applications/python/`)
- **Framework**: FastAPI with async/await patterns
- **Dependency Management**: Poetry for reproducible builds
- **Type Safety**: Type hints and Pydantic validation
- **Testing**: pytest with async test support

#### Rust Applications (`applications/rust/`)
- **Performance**: High-performance web services with Tokio
- **Build System**: Cargo with workspace support
- **Safety**: Memory safety and zero-cost abstractions
- **Deployment**: Minimal container images with multi-stage builds

#### Go Applications (`applications/golang/`)
- **Concurrency**: Goroutine-based concurrent processing
- **Modules**: Go modules for dependency management
- **Performance**: Compiled binaries with small footprint
- **Cloud Native**: Kubernetes-native patterns and health checks

### Application Deployment Pattern
```
Developer Workflow:
Backstage Template → Generated Repository → Code Development → Git Push → 
CI Pipeline → Container Build → GitOps Config Update → ArgoCD Sync → 
Kubernetes Deployment → Application Running
```

## Deployment Process and Commands

### Terraform Deployment (Use Scripts Only)
**⚠️ IMPORTANT**: Always use deployment scripts, never run terraform commands directly

```bash
# Deploy common infrastructure
cd platform/infra/terraform/common && ./deploy.sh

# Deploy hub cluster
cd platform/infra/terraform/hub && ./deploy.sh

# Deploy spoke cluster
cd platform/infra/terraform/spokes && ./deploy.sh dev

# Destroy resources
cd platform/infra/terraform/hub && ./destroy.sh
```

### GitOps Deployment Flow
1. **Infrastructure Deployment**: Terraform creates EKS clusters and AWS resources
2. **Cluster Registration**: Clusters automatically register in AWS Secrets Manager
3. **ArgoCD Bootstrap**: ArgoCD discovers clusters and begins application deployment
4. **Platform Services**: Core platform services deploy via GitOps
5. **Application Deployment**: Applications deploy through Backstage templates and GitOps

### Bootstrap Script Workflow
```bash
# Enhanced bootstrap process with health monitoring
scripts/0-bootstrap.sh
├── 1-argocd-gitlab-setup.sh    # ArgoCD and GitLab integration
├── Wait for ArgoCD health      # Monitor application sync status
├── 2-bootstrap-accounts.sh     # Account setup after ArgoCD ready
└── 6-tools-urls.sh            # Generate access URLs
```

## Secret Management Architecture

### Predictable Naming Convention
The platform uses consistent secret naming that eliminates dynamic configuration needs:

**Pattern**: `{resource_prefix}-{service}-{type}-password`

**Examples**:
- `peeks-workshop-gitops-keycloak-admin-password`
- `peeks-workshop-gitops-backstage-postgresql-password`
- `peeks-workshop-gitops-argocd-admin-password`

### Secret Management Flow
```
AWS Secrets Manager → External Secrets Operator → Kubernetes Secrets → Applications
```

**Benefits**:
- **Decoupling**: GitOps templates don't need dynamic infrastructure details
- **Predictability**: Secret names follow consistent patterns
- **Security**: Centralized secret management in AWS Secrets Manager
- **Maintainability**: Infrastructure changes don't require GitOps updates

## Common Interaction Patterns

### Developer Workflow
1. **Access Platform**: Use Backstage developer portal for self-service
2. **Create Application**: Choose technology template and generate repository
3. **Develop Locally**: Clone repository and develop using preferred tools
4. **Deploy Application**: Push code triggers CI/CD and GitOps deployment
5. **Monitor Application**: Use platform observability tools for monitoring

### Platform Engineer Workflow
1. **Customize Platform**: Modify Terraform modules and GitOps configurations
2. **Add Services**: Extend platform with new operators and services
3. **Manage Environments**: Configure environment-specific settings and policies
4. **Monitor Platform**: Use ArgoCD and monitoring tools for platform health
5. **Troubleshoot Issues**: Use logs, metrics, and diagnostic tools

### Platform Adopter Workflow
1. **Evaluate Platform**: Deploy platform-only configuration for assessment
2. **Customize Components**: Adapt platform services for organizational needs
3. **Integrate Systems**: Connect platform with existing tools and processes
4. **Train Teams**: Onboard development teams to platform capabilities
5. **Scale Adoption**: Expand platform usage across organization

### DevOps Team Workflow
1. **Establish GitOps**: Set up GitOps workflows and repository structures
2. **Configure Environments**: Create development, staging, and production environments
3. **Implement Policies**: Define security, compliance, and operational policies
4. **Monitor Operations**: Set up alerting, logging, and incident response
5. **Optimize Performance**: Tune platform performance and resource utilization

## Troubleshooting Patterns

### Common Platform Issues
- **ArgoCD Sync Failures**: Applications not syncing due to configuration errors
- **Secret Management**: External Secrets Operator not syncing from AWS Secrets Manager
- **Cluster Registration**: New clusters not discovered by ArgoCD ApplicationSets
- **Network Connectivity**: Services unable to communicate across clusters
- **Resource Constraints**: Insufficient cluster resources for platform services

### Diagnostic Commands
```bash
# Check ArgoCD application status
kubectl get applications -n argocd

# Verify External Secrets Operator
kubectl get externalsecrets -A
kubectl get secretstores -A

# Check cluster registration secrets
kubectl get secrets -n argocd | grep cluster

# Monitor platform service health
kubectl get pods -n backstage
kubectl get pods -n crossplane-system
kubectl get pods -n external-secrets
```

### Recovery Procedures
1. **ArgoCD Issues**: Check application logs, verify Git repository access, validate RBAC
2. **Secret Sync Issues**: Verify Pod Identity permissions, check AWS Secrets Manager
3. **Cluster Discovery**: Validate cluster registration secrets and External Secrets config
4. **Network Issues**: Check security groups, network policies, and ingress configurations
5. **Resource Issues**: Scale cluster nodes, adjust resource requests/limits

## Security Considerations

### Identity and Access Management
- **Pod Identity**: Eliminates long-lived credentials for AWS service access
- **RBAC**: Fine-grained Kubernetes permissions for users and services
- **OIDC Integration**: Centralized authentication through Keycloak
- **Multi-Tenant Security**: Namespace isolation and tenant-based access control

### Secret Management Security
- **External Secrets**: Centralized secret management through AWS Secrets Manager
- **Automatic Rotation**: Secrets rotated without application downtime
- **Encryption**: Secrets encrypted at rest and in transit
- **Audit Trail**: All secret access logged and monitored

### Network Security
- **VPC Isolation**: Network-level isolation between environments
- **Security Groups**: Application-level firewall rules
- **Network Policies**: Kubernetes-native network segmentation
- **TLS Everywhere**: End-to-end encryption for all communications

### GitOps Security
- **Git Repository Security**: Access control and audit logging for GitOps repositories
- **Signed Commits**: Cryptographic verification of configuration changes
- **Policy as Code**: Automated policy enforcement through Kyverno
- **Compliance Monitoring**: Continuous compliance checking and reporting

## Key Success Metrics

### Platform Health Indicators
- **ArgoCD Sync Status**: All applications synced and healthy
- **Platform Services**: Backstage, Crossplane, and other services operational
- **Cluster Connectivity**: Hub cluster can manage all spoke clusters
- **Secret Synchronization**: All secrets syncing from AWS Secrets Manager
- **Application Deployments**: Applications deploying successfully through GitOps

### Developer Experience Metrics
- **Time to First Application**: How quickly developers can deploy first application
- **Self-Service Adoption**: Usage of Backstage templates and self-service features
- **Deployment Frequency**: How often applications are deployed through platform
- **Mean Time to Recovery**: How quickly issues are resolved
- **Developer Satisfaction**: Feedback on platform usability and capabilities

This context provides AI assistants with comprehensive understanding of the platform implementation repository, its components, and common interaction patterns for different user types.