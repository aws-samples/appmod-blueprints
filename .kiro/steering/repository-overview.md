---
inclusion: auto
---

# Platform Engineering on Amazon EKS - Repository Overview

## Repository Purpose
This repository provides a comprehensive platform engineering solution for application modernization on Amazon EKS. It enables organizations to adopt cloud-native practices through GitOps patterns, developer self-service capabilities, and production-ready blueprints.

## Core Architecture Principles

### GitOps-First Approach
- All infrastructure and applications managed through Git
- ArgoCD as the primary GitOps engine
- Declarative configuration for all platform components
- Environment promotion through Git workflows

### Multi-Tenancy & Team Isolation
- Team-based namespace isolation
- RBAC integration with Keycloak
- Per-team resource quotas and policies
- Shared platform services with tenant isolation

### Developer Self-Service
- Backstage developer portal for service creation
- Software templates for common patterns
- Kro (Kubernetes Resource Orchestrator) for complex resource provisioning
- Automated CI/CD pipeline generation

## Key Technology Stack

### Core Platform
- **Amazon EKS**: Kubernetes orchestration
- **ArgoCD**: GitOps continuous delivery
- **Backstage**: Developer portal and service catalog
- **Keycloak**: Identity and access management
- **Kro**: Custom resource orchestration and composition

### Infrastructure as Code
- **Terraform**: EKS cluster and AWS infrastructure provisioning
- **Crossplane**: Cloud resource provisioning from Kubernetes
- **Helm**: Package management for Kubernetes applications

### CI/CD & Progressive Delivery
- **Argo Workflows**: Workflow orchestration
- **Argo Rollouts**: Progressive delivery and canary deployments
- **GitLab**: Source control and CI/CD pipelines
- **Flagger**: Automated canary analysis

### Observability
- **Grafana**: Metrics visualization and dashboards
- **Prometheus**: Metrics collection (via addons)
- **DevLake**: Engineering metrics and analytics

### ML/AI Platform
- **Kubeflow**: ML workflow orchestration
- **MLflow**: ML experiment tracking and model registry
- **Ray**: Distributed computing for ML/AI workloads
- **JupyterHub**: Interactive notebook environment
- **Airflow**: Data pipeline orchestration

## Repository Structure

### `/applications`
Multi-language application blueprints demonstrating containerization:
- Java (Spring Boot, Micronaut)
- Node.js and Next.js
- Python, Go, .NET, Rust
- Legacy app containerization with App2Container

### `/gitops`
Complete GitOps structure for platform and applications:
- `addons/`: 25+ platform addons with Helm charts
- `apps/`: Application deployment manifests
- `fleet/`: Multi-cluster fleet management
- `platform/`: Platform-level configurations
- `workloads/`: Workload definitions (Ray, Spark)

### `/platform`
Platform infrastructure and templates:
- `backstage/`: Developer portal templates
- `infra/terraform/`: Infrastructure as Code
- `validation/`: Testing and validation tools

### `/backstage`
Full Backstage implementation with custom plugins:
- Kro integration plugin
- Custom software templates
- Catalog entity definitions
- Keycloak SSO integration

### `/docs`
Comprehensive documentation:
- Architecture and design documents
- Feature guides (Argo Rollouts, Ray, Kro)
- Workshop materials
- Platform setup guides

## Development Workflow

### Local Development
1. Use the provided Taskfile for common operations
2. Test Helm charts locally before committing
3. Validate Backstage changes with `task backstage-validate`
4. Run Kro tests with `task test-kro-*` commands

### GitOps Workflow
1. Make changes in feature branches
2. Test locally using `helm template` or `kubectl apply --dry-run`
3. Commit and push changes
4. ArgoCD automatically syncs changes to clusters
5. Monitor deployment status in ArgoCD UI

### Adding New Addons
1. Create Helm chart in `gitops/addons/charts/`
2. Add values files in `gitops/addons/default/addons/`
3. Register in ApplicationSet configuration
4. Test with `task test-applicationsets`

## Modernization Pathways

### 1. Containerization
- Move legacy applications to containers
- Use provided Dockerfiles or App2Container
- Implement health checks and graceful shutdown

### 2. Cloud-Native Patterns
- Adopt 12-factor app principles
- Implement observability (metrics, logs, traces)
- Use managed services for databases and caching

### 3. GitOps & Automation
- Declarative infrastructure and application definitions
- Automated deployments through ArgoCD
- Environment promotion via Git workflows

### 4. Progressive Delivery
- Canary deployments with Argo Rollouts
- Automated rollback on metric degradation
- Traffic splitting and analysis

## Important Conventions

### Naming
- Use kebab-case for resource names
- Prefix resources with team or environment identifiers
- Follow Kubernetes naming conventions

### Configuration Management
- Store sensitive data in AWS Secrets Manager
- Use External Secrets Operator for secret injection
- Environment-specific values in separate files

### Resource Organization
- Group related resources in Helm charts
- Use labels for resource categorization
- Implement proper RBAC boundaries

## Testing Strategy

### Helm Chart Testing
- Use `helm template` for dry-run validation
- Test with multiple value file combinations
- Validate generated manifests with `kubectl apply --dry-run`

### Kro Testing
- Unit tests for schema validation
- Integration tests for resource creation
- Template execution tests for Backstage integration

### Backstage Testing
- TypeScript compilation checks
- Plugin integration tests
- Frontend component tests

## Common Tasks

Run `task` or `task default` to see all available tasks including:
- Helm dependency management
- Backstage validation
- Kro testing suite
- ApplicationSet testing
