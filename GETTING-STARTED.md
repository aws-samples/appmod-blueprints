# Getting Started with Application Modernization Blueprints

## What are Application Modernization Blueprints?

Application Modernization Blueprints provide a comprehensive set of patterns, templates, and configurations for building modern, cloud-native applications on AWS. This repository contains the platform implementation that enables organizations to adopt platform engineering practices and accelerate application modernization initiatives.

The blueprints include:

- **GitOps Platform**: Complete ArgoCD-based continuous delivery platform
- **Application Templates**: Ready-to-use blueprints for multiple programming languages
- **Platform Components**: Crossplane, Backstage, monitoring, and security integrations
- **Operational Patterns**: Best practices for observability, security, and scalability
- **Developer Experience**: Self-service capabilities and standardized workflows

## Why Use These Blueprints?

### For Developers
- **Faster Time-to-Production**: Pre-configured templates and automated workflows
- **Consistent Patterns**: Standardized approaches across all applications
- **Self-Service Capabilities**: Deploy and manage applications independently
- **Built-in Best Practices**: Security, monitoring, and scalability included by default

### For Platform Teams
- **Reference Implementation**: Production-ready platform engineering patterns
- **Extensible Architecture**: Customize and extend for organizational needs
- **Operational Excellence**: Integrated monitoring, logging, and alerting
- **Developer Productivity**: Reduce cognitive load and improve developer experience

### For Organizations
- **Accelerated Modernization**: Proven patterns for application transformation
- **Reduced Risk**: Battle-tested configurations and security practices
- **Improved Governance**: Consistent policies and compliance across applications
- **Cost Optimization**: Efficient resource utilization and automated scaling

## 40-Minute Platform Evaluation

This quick start helps you evaluate the platform capabilities and understand the developer experience in under 40 minutes.

### Prerequisites (5 minutes)

#### If Using Existing Infrastructure
If you have the platform infrastructure already deployed (via CloudFormation template, manually deployed, or at an AWS event):

- Access to the deployed VSCode IDE environment
- Platform services (ArgoCD, GitLab, Backstage) running
- Basic familiarity with Kubernetes and GitOps concepts

#### If Starting Fresh
You'll need to deploy the infrastructure first using one of these options:

**Option A: CloudFormation Template (Recommended for Public Users)**
- **What**: Pre-generated CloudFormation template for complete workshop setup
- **When**: First-time evaluation or workshop participation
- **Requirements**: AWS CLI, basic AWS knowledge
- **Time**: ~45 minutes for complete deployment

**Option B: IDE-Only CloudFormation Template**
- **What**: Lightweight template that deploys only VSCode IDE environment
- **When**: You have existing platform services or want to explore platform concepts
- **Requirements**: AWS CLI, basic AWS knowledge  
- **Time**: ~15 minutes for IDE deployment

**Option C: Manual Platform Setup**
- **What**: Step-by-step manual deployment using provided guides
- **When**: Custom requirements or production-like deployment
- **Requirements**: Advanced AWS/Kubernetes knowledge
- **Time**: 2+ hours for complete setup

**CloudFormation Deployment Steps:**

1. **Download Template**: Get the appropriate CloudFormation template:
   - **Full Workshop Template**: `peeks-workshop-team-stack-self.json` - Complete platform with all services
   - **Central Stack Template**: `peeks-workshop-central-stack-self.json` - Central platform services
   - Available from: [GitHub Releases](https://github.com/aws-samples/appmod-blueprints/releases) or AWS Workshop Studio

2. **Deploy via AWS Console**:
   ```bash
   # Option 1: AWS Console
   # 1. Open CloudFormation in AWS Console
   # 2. Create Stack → Upload template file
   # 3. Fill in required parameter: ParticipantAssumedRoleArn
   # 4. Deploy and wait for completion (~45 minutes for full, ~15 minutes for IDE-only)
   
   # Option 2: AWS CLI
   aws cloudformation create-stack \
     --stack-name platform-engineering-workshop \
     --template-body file://peeks-workshop-team-stack-self.json \
     --parameters ParameterKey=ParticipantAssumedRoleArn,ParameterValue=arn:aws:iam::YOUR-ACCOUNT-ID:role/YourRoleName \
     --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM \
     --region us-west-2
   ```

3. **Configure Parameters**:
   - **ParticipantAssumedRoleArn**: IAM role ARN that the deployment will assume for AWS operations
   - Example: `arn:aws:iam::123456789012:role/WorkshopParticipantRole`
   - This role needs permissions for EKS, EC2, CloudFormation, and other AWS services used by the platform

4. **Access Environment**: After deployment completes, check CloudFormation outputs for:
   - **VSCode IDE URL**: Your development environment
   - **IDE Password**: Auto-generated access credentials

5. **Access Platform Services**: Once in the IDE environment:
   ```bash
   # Get all platform service URLs and credentials
   ./scripts/6-tools-urls.sh
   
   # This script provides a table with:
   # - Service URLs (ArgoCD, GitLab, Backstage, Grafana)
   # - Access credentials for each service
   # - Direct links to access the platform services
   ```

### Step 1: Explore the Platform (10 minutes)

#### Access Platform Services

From your development environment, get all platform service URLs and credentials:

```bash
# Get comprehensive service information
./scripts/6-tools-urls.sh

# This provides a formatted table with:
# - ArgoCD URL and admin credentials
# - GitLab URL and root credentials  
# - Backstage URL and access information
# - Grafana URL and admin credentials
# - All other platform service endpoints

# Check platform status
kubectl get applications -n argocd
```

#### Explore Repository Structure

```bash
# Navigate to the blueprints repository
cd appmod-blueprints

# Explore key directories
ls -la applications/     # Application blueprints and examples
ls -la gitops/          # GitOps configurations for ArgoCD
ls -la platform/        # Platform components and compositions
ls -la packages/        # Helm charts and platform packages
```

### Step 2: Deploy a Sample Application (10 minutes)

#### Option A: Using Backstage (Recommended)

1. **Access Backstage Developer Portal**
   - Open Backstage URL in your browser
   - Browse the software catalog
   - Explore available application templates

2. **Create New Application**
   - Click "Create Component"
   - Choose an application template (e.g., .NET Northwind, Java Spring Boot)
   - Fill in application details
   - Submit the template

3. **Monitor Deployment**
   - Watch GitOps workflow in ArgoCD
   - Observe application deployment progress
   - Verify application health and status

#### Option B: Using GitOps Directly

```bash
# Deploy a sample .NET application
kubectl apply -f applications/dotnet/northwind/manifests/

# Monitor deployment
kubectl get applications -n argocd
kubectl get pods -n northwind-app

# Check application logs
kubectl logs -n northwind-app -l app=northwind-api
```

### Step 3: Understand the Developer Workflow (10 minutes)

#### GitOps Flow

1. **Code Changes**: Developers push code to GitLab repositories
2. **CI Pipeline**: Automated builds and tests run in GitLab CI
3. **Image Build**: Container images built and pushed to registry
4. **GitOps Sync**: ArgoCD detects changes and deploys to clusters
5. **Monitoring**: Applications monitored via Grafana and Prometheus

#### Self-Service Capabilities

```bash
# View available Crossplane compositions
kubectl get compositions

# Check platform APIs
kubectl get crds | grep -E "(backstage|crossplane|argo)"

# Explore monitoring setup
kubectl get servicemonitors --all-namespaces
```

## Deployment Scenarios Comparison

Choose the approach that best fits your evaluation or adoption needs:

| Scenario                       | Time      | Complexity | Use Case                      | Prerequisites                    |
|--------------------------------|-----------|------------|-------------------------------|----------------------------------|
| **🚀 CloudFormation Workshop** | 45 min    | Low        | Complete platform evaluation  | AWS account, basic AWS knowledge |
| **💻 CloudFormation IDE-Only** | 15 min    | Low        | Development environment only  | AWS account, basic AWS knowledge |
| **🏗️ Platform Adoption**      | 2-4 hours | Medium     | Organizational implementation | Kubernetes knowledge             |
| **⚙️ Custom Implementation**   | 1-2 weeks | High       | Production deployment         | Advanced platform engineering    |

### CloudFormation Workshop (Recommended for First-Time Users)
- **What**: Deploy complete platform using pre-generated CloudFormation template
- **When**: First-time evaluation, workshops, or comprehensive platform assessment
- **Includes**: Full platform stack, VSCode IDE, sample applications, GitOps workflows
- **Next Steps**: Explore platform capabilities, plan organizational adoption

### Platform Adoption
- **What**: Implement the platform for organizational use
- **When**: Ready to adopt platform engineering practices
- **Includes**: Full platform deployment, team training, application migration
- **Next Steps**: Customize platform components, onboard development teams

### Developer Onboarding
- **What**: Learn platform workflows and self-service capabilities
- **When**: Onboarding developers to existing platform
- **Includes**: Application templates, GitOps workflows, monitoring practices
- **Next Steps**: Deploy production applications, contribute to platform evolution

### Custom Implementation
- **What**: Adapt platform for specific organizational requirements
- **When**: Production deployment with custom needs
- **Includes**: Platform customization, security integration, operational procedures
- **Next Steps**: Production rollout, team training, continuous improvement

## Application Blueprints Overview

### Supported Technologies

#### .NET Applications
- **Northwind Sample**: Clean architecture demonstration with Entity Framework
- **Microservices**: Service-to-service communication patterns
- **API Gateway**: Centralized API management and routing

#### Java Applications  
- **Spring Boot**: Microservices with Spring Cloud patterns
- **Observability**: Integrated tracing, metrics, and logging
- **Data Access**: JPA patterns with PostgreSQL integration

#### Node.js Applications
- **Express APIs**: RESTful service patterns with modern tooling
- **Event-Driven**: Message queue integration with SQS/SNS
- **Frontend Integration**: React/Vue.js deployment patterns

#### Python Applications
- **FastAPI Services**: High-performance async API patterns
- **Data Processing**: ETL pipelines with AWS services
- **Machine Learning**: MLOps patterns for model deployment

#### Rust Applications
- **High-Performance Services**: Memory-safe system programming
- **WebAssembly**: Browser and edge deployment patterns
- **Async Patterns**: Tokio-based concurrent applications

#### Go Applications
- **Cloud-Native Services**: Kubernetes-native application patterns
- **gRPC Services**: High-performance service communication
- **CLI Tools**: Platform tooling and automation utilities

### Architecture Patterns

#### Microservices Architecture
- Service mesh integration with Istio
- Inter-service communication patterns
- Distributed tracing and observability
- Circuit breaker and retry patterns

#### Event-Driven Architecture
- Message queue integration (SQS, SNS, EventBridge)
- Event sourcing and CQRS patterns
- Saga pattern for distributed transactions
- Dead letter queue handling

#### Serverless Integration
- Lambda function deployment patterns
- API Gateway integration
- Event-driven serverless workflows
- Cost optimization strategies

## What's Next?

After completing the evaluation, choose your path forward:

### 🎯 Platform Adopters
1. **Architecture Review**: Study [ARCHITECTURE.md](ARCHITECTURE.md) for platform design details
2. **Deployment Planning**: Review [DEPLOYMENT-GUIDE.md](DEPLOYMENT-GUIDE.md) for production setup
3. **Team Preparation**: Plan developer onboarding and training programs
4. **Customization**: Identify platform modifications for your organization

### 👩‍💻 Developers
1. **Template Exploration**: Try different application blueprints
2. **Workflow Mastery**: Practice GitOps deployment patterns
3. **Platform Services**: Learn to use Backstage, monitoring, and security tools
4. **Contribution**: Add new templates or improve existing patterns

### ⚙️ Platform Engineers
1. **Component Deep Dive**: Understand Crossplane compositions and platform APIs
2. **Customization**: Extend platform capabilities for organizational needs
3. **Operations**: Set up monitoring, alerting, and maintenance procedures
4. **Security**: Implement organization-specific security and compliance requirements

## Troubleshooting Common Issues

### IDE Configuration Issues

**Platform Services Not Available or Environment Variables Missing**
```bash
# Re-run the configuration entrypoint script
./scripts/0-install.sh

# This script will:
# - Set up environment variables for platform services
# - Configure kubectl access to clusters
# - Install required tools and dependencies
# - Verify platform service connectivity
```

**IDE Environment Corrupted or Incomplete Setup**
```bash
# From within the VSCode IDE terminal, re-run setup
cd /workspace/appmod-blueprints
./scripts/0-install.sh

# Check if environment variables are properly set
echo $ARGOCD_URL
echo $GITLAB_URL
echo $BACKSTAGE_URL
```

### Platform Access Problems

**Cannot Access Backstage/ArgoCD**
```bash
# Check service status
kubectl get services -n backstage
kubectl get services -n argocd

# Verify ingress configuration
kubectl get ingress --all-namespaces

# Check pod health
kubectl get pods -n backstage
kubectl get pods -n argocd
```

**GitLab Authentication Issues**
```bash
# Verify GitLab service
kubectl get services -n gitlab

# Check GitLab pod logs
kubectl logs -n gitlab -l app=gitlab

# Verify external access
curl -k $GITLAB_URL/api/v4/version
```

### Application Deployment Issues

**ArgoCD Sync Failures**
```bash
# Check ArgoCD application status
kubectl get applications -n argocd

# View application details
kubectl describe application <app-name> -n argocd

# Check ArgoCD logs
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-server
```

**Application Pod Failures**
```bash
# Check pod status
kubectl get pods -n <namespace>

# View pod logs
kubectl logs <pod-name> -n <namespace>

# Describe pod for events
kubectl describe pod <pod-name> -n <namespace>
```

### Getting Help

- **Platform Issues**: Check [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for detailed solutions
- **Architecture Questions**: Review [ARCHITECTURE.md](ARCHITECTURE.md) for platform design
- **Deployment Problems**: See [DEPLOYMENT-GUIDE.md](DEPLOYMENT-GUIDE.md) for alternative approaches
- **Infrastructure Setup**: Use provided CloudFormation templates or follow [DEPLOYMENT-GUIDE.md](DEPLOYMENT-GUIDE.md)

## Validation and Success Criteria

### Platform Readiness Checklist

Verify your platform is ready for application deployment:

- [ ] **ArgoCD**: Applications syncing successfully
- [ ] **Backstage**: Developer portal accessible with templates
- [ ] **GitLab**: Repositories accessible with CI/CD pipelines
- [ ] **Monitoring**: Grafana dashboards showing platform metrics
- [ ] **Networking**: Service mesh and ingress working correctly

### Application Deployment Validation

After deploying a sample application:

- [ ] **Deployment**: Application pods running and healthy
- [ ] **Networking**: Application accessible via ingress
- [ ] **Monitoring**: Metrics and logs flowing to observability stack
- [ ] **GitOps**: Changes sync automatically from Git repositories
- [ ] **Security**: Security policies applied and enforced

### Developer Experience Validation

Confirm the developer experience meets expectations:

- [ ] **Self-Service**: Developers can deploy applications independently
- [ ] **Templates**: Application blueprints work as expected
- [ ] **Feedback**: Clear status and error messages throughout workflows
- [ ] **Documentation**: Developers can find help and guidance easily
- [ ] **Performance**: Reasonable response times for platform operations

## Security and Compliance

### Security Best Practices

The platform implements several security patterns:

- **Network Policies**: Kubernetes network segmentation
- **RBAC**: Role-based access control for platform services
- **Secret Management**: External Secrets Operator integration
- **Image Security**: Container image scanning and policies
- **Service Mesh**: mTLS for service-to-service communication

### Compliance Considerations

For production deployments, consider:

- **Data Governance**: Data classification and handling policies
- **Audit Logging**: Comprehensive audit trails for all platform operations
- **Access Controls**: Integration with organizational identity providers
- **Vulnerability Management**: Regular security scanning and patching
- **Backup and Recovery**: Data protection and disaster recovery procedures

### Security Validation

```bash
# Check network policies
kubectl get networkpolicies --all-namespaces

# Verify RBAC configuration
kubectl get rolebindings --all-namespaces
kubectl get clusterrolebindings

# Check security policies
kubectl get psp  # Pod Security Policies (if enabled)
kubectl get pss  # Pod Security Standards (if enabled)

# Review service mesh security
kubectl get peerauthentications --all-namespaces
kubectl get authorizationpolicies --all-namespaces
```