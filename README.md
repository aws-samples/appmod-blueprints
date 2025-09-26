---
title: "Platform Engineering on EKS - Application Modernization Blueprints"
persona: ["platform-adopter", "infrastructure-engineer", "developer"]
deployment-scenario: ["platform-only", "full-workshop"]
difficulty: "intermediate"
estimated-time: "30 minutes"
prerequisites: ["AWS Account", "kubectl", "Basic Kubernetes knowledge"]
related-pages: ["GETTING-STARTED.md", "ARCHITECTURE.md", "DEPLOYMENT-GUIDE.md"]
repository: "appmod-blueprints"
last-updated: "2025-01-19"
---

# Platform Engineering on EKS - Application Modernization Blueprints

## What is this?

This repository contains the platform implementation and application modernization blueprints for building modern, cloud-native applications on AWS. It provides GitOps configurations, platform components, application templates, and operational patterns that work together to create a comprehensive platform engineering solution.

## Quick Start

Choose your path:

- **🚀 Try it now** (30 min): [GETTING-STARTED.md](GETTING-STARTED.md)
- **🏗️ Deploy it**: [DEPLOYMENT-GUIDE.md](DEPLOYMENT-GUIDE.md)
- **🔧 Understand it**: [ARCHITECTURE.md](ARCHITECTURE.md)
- **❓ Fix issues**: [TROUBLESHOOTING.md](TROUBLESHOOTING.md)

## Repository Relationship

This repository works with [platform-engineering-on-eks](https://gitlab.aws.dev/aws-tfc-containers/containers-hands-on-content/platform-engineering-on-eks) to provide a complete platform engineering solution.

- **This repo (appmod-blueprints)**: Platform implementation, GitOps configurations, application blueprints, and operational patterns
- **Other repo (platform-engineering-on-eks)**: Infrastructure bootstrap, CDK deployment, workshop environment setup

## Key Features

- **GitOps Platform**: Complete ArgoCD-based platform with multi-environment support
- **Application Blueprints**: Ready-to-use templates for .NET, Java, Node.js, Python, Rust, and Go applications
- **Platform Components**: Crossplane, Backstage, monitoring, security, and networking configurations
- **Developer Experience**: Self-service capabilities through Backstage templates and GitOps workflows
- **Production Ready**: Scalable patterns for real-world platform adoption

## Who Should Use This

- **👩‍💻 Developers**: Building and deploying applications on the platform
- **🏢 Platform Adopters**: Implementing platform engineering in their organization
- **⚙️ Platform Engineers**: Customizing and extending platform capabilities
- **🎯 DevOps Teams**: Establishing GitOps workflows and operational practices

## Application Blueprints

Our repository includes various application blueprints demonstrating modern engineering practices:

### Supported Technologies

- **.NET**: Northwind sample application with clean architecture
- **Java**: Spring Boot microservices with observability
- **Node.js**: Express applications with modern tooling
- **Python**: FastAPI services with async patterns
- **Rust**: High-performance web services
- **Go**: Cloud-native microservices

### Architecture Patterns

- Microservices architectures with service mesh
- Event-driven architectures with messaging
- Serverless integration patterns
- Progressive delivery and canary deployments
- Observability and monitoring integration

## Platform Components

### Core Services

- **Backstage**: Developer portal and service catalog
- **ArgoCD**: GitOps continuous delivery
- **Crossplane**: Infrastructure as code and composition
- **Grafana**: Monitoring and observability
- **Keycloak**: Identity and access management

### Development Tools

- **GitLab**: Source code management and CI/CD
- **VS Code**: Cloud-based development environment
- **Argo Workflows**: Workflow orchestration
- **External Secrets**: Secure secret management

## Need Help?

- Check [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for common platform and application issues
- Review [ARCHITECTURE.md](ARCHITECTURE.md) for platform design and component relationships
- Explore [applications/](applications/) for example implementations
- Visit the [platform-engineering-on-eks repository](https://gitlab.aws.dev/aws-tfc-containers/containers-hands-on-content/platform-engineering-on-eks) for infrastructure setup

## Quick Reference

### Prerequisites

Before using the platform, ensure you have the required setup:

- **📋 Setup Guide**: See [GETTING-STARTED.md](GETTING-STARTED.md#prerequisites) for complete prerequisites
- **🔧 Platform Access**: GitLab URL, ArgoCD URL, Backstage portal access
- **⚙️ Environment**: IDE with required environment variables and credentials

### For Developers

```bash
# Access platform services (URLs provided after deployment)
# - Backstage Developer Portal: Self-service application creation
# - GitLab: Source code management and CI/CD
# - ArgoCD: GitOps deployment status and management

# Deploy applications using Backstage templates
# 1. Access Backstage developer portal
# 2. Choose application template
# 3. Fill in application details
# 4. GitOps workflow handles deployment automatically
```

### For Platform Teams

```bash
# Platform components are managed via GitOps
# Key directories for customization:
# - gitops/platform/ - Core platform services
# - packages/ - Helm charts and configurations
# - platform/components/ - Crossplane compositions
# - platform/traits/ - Application deployment patterns
```

### Repository Structure

- `applications/` - Application blueprints and examples
- `gitops/` - GitOps configurations for ArgoCD
- `packages/` - Helm charts and platform packages
- `platform/` - Platform components and compositions
- `deployment/` - Environment-specific configurations

## Getting Started Paths

### 🚀 Quick Evaluation (30 minutes)

Perfect for decision makers and teams evaluating platform engineering:

1. Use the [platform-engineering-on-eks](https://gitlab.aws.dev/aws-tfc-containers/containers-hands-on-content/platform-engineering-on-eks) repository to deploy infrastructure
2. Access the pre-configured development environment
3. Deploy a sample application using Backstage templates
4. Experience the complete developer workflow

### 🏗️ Platform Adoption

For teams ready to implement platform engineering:

1. Review [ARCHITECTURE.md](ARCHITECTURE.md) to understand the platform design
2. Follow [DEPLOYMENT-GUIDE.md](DEPLOYMENT-GUIDE.md) for production deployment
3. Customize platform components in `platform/` directory
4. Adapt application blueprints for your technology stack

### 👩‍💻 Application Development

For developers using an existing platform:

1. Access your organization's Backstage developer portal
2. Browse available application templates
3. Create new applications using self-service workflows
4. Follow GitOps patterns for deployment and updates

## Helm Chart Dependencies

This repository uses Taskfile to automate Helm chart dependency management. Available tasks:

```bash
# Check which charts have dependencies and their status
task check-helm-dependencies

# Build all Helm chart dependencies automatically
task build-helm-dependencies

# Clean all generated dependency files
task clean-helm-dependencies
```

**Note:** Run `task build-helm-dependencies` when:
- Setting up the repository for the first time
- Adding new charts with dependencies
- Updating dependency versions in Chart.yaml files

The task automatically handles adding required Helm repositories and building dependencies for flux, crossplane, and kubevela charts.

## Contributing

We welcome contributions to improve the platform and add new application blueprints:

- Read our [CONTRIBUTING.md](CONTRIBUTING.md) guide
- Follow our [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)
- Submit issues for bugs or feature requests
- Create pull requests for improvements

## Security

See [CONTRIBUTING.md](CONTRIBUTING.md#security-issue-notifications) for information on reporting security issues.

## License

This project is licensed under the MIT-0 License. See the [LICENSE](LICENSE) file for details.