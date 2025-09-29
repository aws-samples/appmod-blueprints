# CI/CD Pipeline Kro Resource Graph Definition

This directory contains a Kro ResourceGraphDefinition (RGD) that creates a complete CI/CD pipeline infrastructure from a single custom resource.

## Overview

The `CICDPipeline` custom resource creates **22+ Kubernetes and AWS resources** automatically, providing a complete CI/CD pipeline with:
- ECR repositories for container images
- IAM roles and policies for secure access
- Kubernetes RBAC and service accounts
- Argo Workflows for CI/CD operations
- Argo Events for GitLab webhook integration
- Docker registry secrets with automatic refresh

## Quick Start

### 1. Apply the ResourceGraphDefinition

```bash
kubectl apply -f cicd-pipeline.yaml
```

### 2. Create a CICDPipeline Instance

```bash
kubectl apply -f test-cicd-pipeline-instance.yaml
```

### 3. Verify Resources

```bash
# Check the CICDPipeline status
kubectl get cicdpipeline test-cicd-pipeline -n default

# View all created resources
kubectl get all,secrets,configmaps,roles,rolebindings,serviceaccounts -n test-cicd-pipeline
```

## Resources Created

When you create a `CICDPipeline` custom resource, the following resources are automatically created:

### AWS Resources (via ACK Controllers)

#### ECR Repositories (2)
- **Main Repository**: `{name}-main-repo` - Stores application container images
- **Cache Repository**: `{name}-cache-repo` - Stores build cache layers

```bash
kubectl get repository -n {namespace}
```

#### IAM Resources (2)
- **ECR Policy**: `{name}-ecr-policy` - Permissions for ECR access
- **IAM Role**: `{name}-role` - Role with EKS pod identity trust policy

```bash
kubectl get policy.iam.services.k8s.aws,role.iam.services.k8s.aws -n {namespace}
```

#### EKS Pod Identity (1)
- **Pod Identity Association**: `{name}-pod-association` - Links service account to IAM role

```bash
kubectl get podidentityassociation -n {namespace}
```

### Kubernetes Native Resources

#### Core Resources (7)
- **Namespace**: `{namespace}` - Isolated environment for pipeline resources
- **ServiceAccount**: `{name}-sa` - Service account with IAM role binding
- **RBAC Role**: `{name}-role` - Kubernetes permissions for CI/CD operations
- **RoleBinding**: `{name}-rolebinding` - Binds role to service account
- **ConfigMap**: `{name}-config` - Configuration data for workflows
- **ConfigMap**: `{name}-cache-dockerfile` - Dockerfile for cache warmup
- **Secret**: `{name}-docker-config` - Docker registry credentials

```bash
kubectl get all,secrets,configmaps,roles,rolebindings,serviceaccounts -n {namespace}
```

#### Workload Resources (3)
- **CronJob**: `{name}-ecr-refresh` - Refreshes ECR credentials every 6 hours
- **Job**: `{name}-initial-ecr-setup` - Initial ECR credential setup
- **Service**: `{name}-webhook-service` - Exposes webhook endpoint

### Argo Workflows & Events (6)

#### WorkflowTemplates (3)
- **Provisioning Workflow**: `{name}-provisioning-workflow` - Sets up infrastructure
- **Cache Warmup Workflow**: `{name}-cache-warmup-workflow` - Warms build cache
- **CI/CD Workflow**: `{name}-cicd-workflow` - Main build and deployment pipeline

```bash
kubectl get workflowtemplate -n {namespace}
```

#### Workflow Execution (1)
- **Setup Workflow**: `{name}-setup-workflow` - Executes initial provisioning

```bash
kubectl get workflow -n {namespace}
```

#### Argo Events (2)
- **EventSource**: `{name}-gitlab-eventsource` - Listens for GitLab webhooks
- **Sensor**: `{name}-gitlab-sensor` - Triggers workflows on events

```bash
kubectl get eventsource,sensor -n {namespace}
```

#### Networking (1)
- **Ingress**: `{name}-webhook-ingress` - External access to webhook endpoint

```bash
kubectl get ingress -n {namespace}
```

## CICDPipeline Schema

```yaml
apiVersion: kro.run/v1alpha1
kind: CICDPipeline
metadata:
  name: my-pipeline
  namespace: default
spec:
  name: my-pipeline                    # Pipeline name
  namespace: my-pipeline-ns            # Target namespace
  aws:
    region: us-west-2                  # AWS region
    clusterName: my-cluster            # EKS cluster name
  application:
    name: my-app                       # Application name
    dockerfilePath: "."                # Path to Dockerfile (default: ".")
    deploymentPath: "./deployment"     # Path to deployment manifests (default: "./deployment")
  ecr:
    repositoryPrefix: "my-org"         # ECR repository prefix (default: "peeks")
  gitlab:
    hostname: "gitlab.example.com"     # GitLab hostname
    username: "my-user"                # GitLab username
```

## Status Information

The CICDPipeline provides status information about created resources:

```bash
 kubectl get cicdpipeline test-cicd-pipeline -n default -o yaml 
```

**Status Fields:**
- `ecrMainRepositoryURI`: URI of the main ECR repository
- `ecrCacheRepositoryURI`: URI of the cache ECR repository
- `iamRoleARN`: ARN of the created IAM role
- `serviceAccountName`: Name of the created service account
- `namespace`: Target namespace
- `state`: Overall state (ACTIVE/ERROR)

## Testing Scripts

This directory includes testing scripts to validate the RGD:

### Dry-Run Test
```bash
./test-kro-cicd-instance-dryrun.sh
```
Validates YAML files and shows what resources would be created without requiring cluster access.

### Full Deployment Test
```bash
./test-kro-cicd-instance.sh
```
Deploys a test instance and validates all created resources.

### Cleanup
```bash
./cleanup-kro-test.sh
```
Removes test resources and cleans up the cluster.

## Monitoring Resources

### Check Overall Status
```bash
# View CICDPipeline status
kubectl get cicdpipeline -A

# Check specific instance
kubectl describe cicdpipeline my-pipeline -n default
```

### Monitor AWS Resources
```bash
# ECR repositories
kubectl get repository -A

# IAM resources
kubectl get policy.iam.services.k8s.aws,role.iam.services.k8s.aws -A

# Pod Identity associations
kubectl get podidentityassociation -A
```

### Monitor Kubernetes Resources
```bash
# All resources in pipeline namespace
kubectl get all -n my-pipeline-ns

# Secrets and configs
kubectl get secrets,configmaps -n my-pipeline-ns

# RBAC resources
kubectl get roles,rolebindings,serviceaccounts -n my-pipeline-ns
```

### Monitor Workflows
```bash
# Workflow templates
kubectl get workflowtemplate -n my-pipeline-ns

# Running workflows
kubectl get workflow -n my-pipeline-ns

# Workflow logs
kubectl logs -n my-pipeline-ns -l workflows.argoproj.io/workflow=my-workflow-name
```

### Monitor Events
```bash
# Argo Events resources
kubectl get eventsource,sensor -n my-pipeline-ns

# Event logs
kubectl logs -n my-pipeline-ns -l eventsource-name=my-eventsource-name
```

## Troubleshooting

### Common Issues

#### 1. CICDPipeline in ERROR State
```bash
# Check status and conditions
kubectl describe cicdpipeline my-pipeline -n default

# Check Kro controller logs
kubectl logs -n kro-system -l app=kro --tail=100
```

#### 2. AWS Resources Not Created
```bash
# Verify ACK controllers are running
kubectl get pods -n ack-system

# Check ACK controller logs
kubectl logs -n ack-system -l app.kubernetes.io/name=ecr-controller
```

#### 3. Workflow Failures
```bash
# Check workflow status
kubectl get workflow -n my-pipeline-ns

# View workflow logs
kubectl logs -n my-pipeline-ns -l workflows.argoproj.io/workflow=my-workflow-name

# Check service account permissions
kubectl describe serviceaccount my-pipeline-sa -n my-pipeline-ns
```

#### 4. ECR Authentication Issues
```bash
# Check docker config secret
kubectl get secret my-pipeline-docker-config -n my-pipeline-ns -o yaml

# Verify ECR credential refresh job
kubectl get cronjob my-pipeline-ecr-refresh -n my-pipeline-ns
kubectl get jobs -n my-pipeline-ns
```

### Cleanup

To remove a CICDPipeline and all its resources:

```bash
# Delete the CICDPipeline instance
kubectl delete cicdpipeline my-pipeline -n default

# Verify namespace cleanup
kubectl get namespace my-pipeline-ns

# If namespace is stuck, force cleanup
kubectl delete namespace my-pipeline-ns --force --grace-period=0
```

## Development

### Validating Changes

Before applying changes to the RGD:

```bash
# Validate RGD syntax
kubectl apply --dry-run=client -f cicd-pipeline.yaml

# Run dry-run test
./test-kro-cicd-instance-dryrun.sh
```

### Testing New Features

1. Make changes to `cicd-pipeline.yaml`
2. Apply the updated RGD: `kubectl apply -f cicd-pipeline.yaml`
3. Test with a new instance: `./test-kro-cicd-instance.sh`
4. Clean up: `./cleanup-kro-test.sh`

## Architecture

The CICDPipeline RGD creates a complete CI/CD infrastructure that follows these patterns:

1. **Infrastructure First**: AWS resources (ECR, IAM) are created first
2. **Kubernetes Integration**: Service accounts and RBAC are configured with AWS IAM
3. **Workflow Orchestration**: Argo Workflows handle CI/CD operations
4. **Event-Driven**: GitLab webhooks trigger automated builds
5. **Security**: Least-privilege access with Pod Identity and RBAC
6. **Automation**: Credential refresh and cache management

This design provides a production-ready CI/CD pipeline that scales with your applications while maintaining security and operational best practices.