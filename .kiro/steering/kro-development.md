---
inclusion: fileMatch
fileMatchPattern: "**/kro/**/*"
---

# Kro (Kubernetes Resource Orchestrator) Development Guidelines

## What is Kro?

Kro is a Kubernetes controller that enables composition of complex resources through ResourceGraphDefinitions (RGDs). It allows platform teams to create reusable, self-service resource templates that abstract complexity from end users.

## Core Concepts

### ResourceGraphDefinition (RGD)
A declarative specification that defines:
- Input schema (parameters users provide)
- Resource templates (Kubernetes resources to create)
- Dependencies between resources
- Status conditions and readiness checks

### ResourceGroup
An instance created from an RGD. When a user creates a ResourceGroup, Kro:
1. Validates input against the RGD schema
2. Renders resource templates with provided parameters
3. Creates resources in dependency order
4. Monitors resource status and updates ResourceGroup status

## Repository Structure

```
gitops/addons/charts/kro/
├── resource-groups/          # RGD definitions
│   ├── cicd-pipeline/       # CI/CD pipeline RGD
│   │   ├── rgd.yaml         # RGD specification
│   │   ├── tests/           # Test suite
│   │   │   ├── unit/        # Schema and template tests
│   │   │   ├── integration/ # Resource creation tests
│   │   │   └── template-execution/ # Backstage integration tests
│   │   └── README.md        # Documentation
│   └── <other-rgds>/
└── instances/               # ResourceGroup instances
    └── <instance-name>.yaml
```

## RGD Development

### RGD Structure
```yaml
apiVersion: kro.run/v1alpha1
kind: ResourceGraphDefinition
metadata:
  name: cicd-pipeline
  namespace: kro-system
spec:
  # Input schema - what users provide
  schema:
    apiVersion: v1alpha1
    kind: CICDPipeline
    spec:
      type: object
      properties:
        applicationName:
          type: string
          description: Name of the application
        gitRepository:
          type: string
          description: Git repository URL
        targetNamespace:
          type: string
          description: Target deployment namespace
      required:
        - applicationName
        - gitRepository
        - targetNamespace
  
  # Resources to create
  resources:
    - id: ecr-repository
      template:
        apiVersion: v1
        kind: ConfigMap
        metadata:
          name: ${schema.spec.applicationName}-ecr
          namespace: ${schema.spec.targetNamespace}
    
    - id: argo-workflow
      template:
        apiVersion: argoproj.io/v1alpha1
        kind: Workflow
        metadata:
          name: ${schema.spec.applicationName}-build
        spec:
          entrypoint: build-and-push
      dependsOn:
        - ecr-repository
```

### Schema Design Best Practices

1. **Clear Property Names**: Use descriptive, self-documenting names
2. **Comprehensive Descriptions**: Help users understand each parameter
3. **Sensible Defaults**: Provide defaults where appropriate
4. **Validation Rules**: Use JSON Schema validation (pattern, enum, min/max)
5. **Required vs Optional**: Mark truly required fields only

Example:
```yaml
spec:
  type: object
  properties:
    applicationName:
      type: string
      description: "Application name (lowercase, alphanumeric, hyphens only)"
      pattern: "^[a-z0-9-]+$"
      minLength: 3
      maxLength: 63
    environment:
      type: string
      description: "Deployment environment"
      enum: ["dev", "staging", "prod"]
      default: "dev"
    replicas:
      type: integer
      description: "Number of replicas"
      minimum: 1
      maximum: 10
      default: 2
```

### Resource Templates

#### Variable Substitution
Access input parameters using `${schema.spec.<property>}`:
```yaml
metadata:
  name: ${schema.spec.applicationName}-service
  namespace: ${schema.spec.targetNamespace}
  labels:
    app: ${schema.spec.applicationName}
    environment: ${schema.spec.environment}
```

#### Conditional Resources
Use expressions for conditional logic:
```yaml
- id: production-monitoring
  template:
    apiVersion: v1
    kind: ConfigMap
    metadata:
      name: monitoring-config
  condition: ${schema.spec.environment == "prod"}
```

#### Resource Dependencies
Define dependencies to control creation order:
```yaml
- id: database
  template:
    apiVersion: v1
    kind: Service
    metadata:
      name: ${schema.spec.applicationName}-db

- id: application
  template:
    apiVersion: apps/v1
    kind: Deployment
    metadata:
      name: ${schema.spec.applicationName}
  dependsOn:
    - database  # Wait for database to be ready
```

### Status Conditions

Define readiness conditions for the ResourceGroup:
```yaml
status:
  conditions:
    - type: Ready
      status: "True"
      reason: AllResourcesReady
      message: "All resources are ready"
  observedGeneration: 1
```

## Testing Strategy

### Unit Tests
Test schema validation and template rendering without cluster access.

**Location**: `resource-groups/<rgd-name>/tests/unit/`

**Run**: `task test-kro-unit`

**What to test**:
- Schema validation with valid/invalid inputs
- Parameter substitution in templates
- Conditional resource logic
- Dependency ordering

### Template Execution Tests
Test Backstage template integration and manifest generation.

**Location**: `resource-groups/<rgd-name>/tests/template-execution/`

**Run**: `task test-kro-template`

**What to test**:
- Template parameter validation
- YAML manifest generation
- GitLab integration
- ArgoCD application creation

### Dry-Run Validation
Validate RGD syntax and structure without cluster deployment.

**Run**: `task test-kro-dryrun`

**What to test**:
- YAML syntax correctness
- RGD schema validity
- Template rendering without errors

### Integration Tests
Test actual resource creation in a Kubernetes cluster.

**Location**: `resource-groups/<rgd-name>/tests/integration/`

**Run**: `task test-kro-integration`

**Requirements**: Active Kubernetes cluster access

**What to test**:
- RGD registration in cluster
- ResourceGroup instance creation
- Resource creation and status
- Dependency resolution
- Error handling

### Deployment Tests
Full end-to-end deployment test in a real cluster.

**Run**: `task test-kro-deployment`

**Requirements**: Active Kubernetes cluster and AWS access

**What to test**:
- Complete RGD deployment
- Test instance creation
- Resource readiness validation
- Status propagation
- Cleanup procedures

### Cleanup
Remove test resources from cluster.

**Run**: `task test-kro-clean`

## CI/CD Pipeline RGD Example

The repository includes a comprehensive CI/CD pipeline RGD that demonstrates best practices:

**Location**: `gitops/addons/charts/kro/resource-groups/cicd-pipeline/`

**Features**:
- ECR repository creation
- IAM roles and policies
- Argo Workflow for build/push
- GitLab webhook integration
- ArgoCD application deployment

**Resources Created**:
1. ECR repository for container images
2. IAM role for workflow execution
3. Argo Workflow template
4. GitLab webhook configuration
5. ArgoCD Application for deployment

**Testing**:
- Comprehensive unit test suite
- Template execution tests
- Integration tests with AWS
- Deployment validation

## Backstage Integration

### Template Action
Create a custom Backstage action for Kro:

```typescript
// In Backstage backend plugin
export const createKroResourceGroupAction = () => {
  return createTemplateAction({
    id: 'kro:create',
    schema: {
      input: {
        type: 'object',
        required: ['rgdName', 'instanceName', 'parameters'],
        properties: {
          rgdName: { type: 'string' },
          instanceName: { type: 'string' },
          parameters: { type: 'object' },
        },
      },
    },
    async handler(ctx) {
      // Create ResourceGroup instance
      const resourceGroup = {
        apiVersion: 'kro.run/v1alpha1',
        kind: ctx.input.rgdName,
        metadata: {
          name: ctx.input.instanceName,
        },
        spec: ctx.input.parameters,
      };
      
      // Apply to cluster or commit to Git
      await applyResourceGroup(resourceGroup);
    },
  });
};
```

### Software Template
Reference the RGD in a Backstage template:

```yaml
apiVersion: scaffolder.backstage.io/v1beta3
kind: Template
metadata:
  name: create-cicd-pipeline
  title: Create CI/CD Pipeline
spec:
  parameters:
    - title: Application Details
      properties:
        applicationName:
          type: string
        gitRepository:
          type: string
  steps:
    - id: create-pipeline
      name: Create CI/CD Pipeline
      action: kro:create
      input:
        rgdName: CICDPipeline
        instanceName: ${{ parameters.applicationName }}-pipeline
        parameters:
          applicationName: ${{ parameters.applicationName }}
          gitRepository: ${{ parameters.gitRepository }}
          targetNamespace: ${{ parameters.applicationName }}
```

## Best Practices

### RGD Design
1. **Single Responsibility**: Each RGD should solve one specific use case
2. **Composability**: Design RGDs to work together
3. **Sensible Defaults**: Minimize required parameters
4. **Clear Documentation**: Include comprehensive README
5. **Version Control**: Use semantic versioning for RGDs

### Resource Management
1. **Namespace Isolation**: Create resources in appropriate namespaces
2. **Label Everything**: Use consistent labeling for resource tracking
3. **Owner References**: Set owner references for garbage collection
4. **Resource Limits**: Include resource requests/limits in templates

### Error Handling
1. **Validation**: Validate inputs thoroughly in schema
2. **Status Reporting**: Provide clear status messages
3. **Rollback Strategy**: Design for safe rollback
4. **Idempotency**: Ensure operations are idempotent

### Security
1. **Least Privilege**: Create minimal IAM roles/policies
2. **Secret Management**: Use External Secrets for sensitive data
3. **RBAC**: Implement proper Kubernetes RBAC
4. **Network Policies**: Include network policies in templates

## Common Patterns

### Multi-Resource Composition
```yaml
resources:
  - id: namespace
    template:
      apiVersion: v1
      kind: Namespace
      metadata:
        name: ${schema.spec.applicationName}
  
  - id: service-account
    template:
      apiVersion: v1
      kind: ServiceAccount
      metadata:
        name: ${schema.spec.applicationName}
        namespace: ${schema.spec.applicationName}
    dependsOn: [namespace]
  
  - id: deployment
    template:
      apiVersion: apps/v1
      kind: Deployment
      spec:
        template:
          spec:
            serviceAccountName: ${schema.spec.applicationName}
    dependsOn: [service-account]
```

### AWS Resource Integration
```yaml
- id: s3-bucket
  template:
    apiVersion: s3.aws.crossplane.io/v1beta1
    kind: Bucket
    metadata:
      name: ${schema.spec.applicationName}-data
    spec:
      forProvider:
        region: us-west-2
        acl: private
```

### GitOps Integration
```yaml
- id: argocd-app
  template:
    apiVersion: argoproj.io/v1alpha1
    kind: Application
    metadata:
      name: ${schema.spec.applicationName}
      namespace: argocd
    spec:
      project: default
      source:
        repoURL: ${schema.spec.gitRepository}
        path: k8s
        targetRevision: main
      destination:
        server: https://kubernetes.default.svc
        namespace: ${schema.spec.targetNamespace}
```

## Troubleshooting

### RGD Not Discovered
- Verify RGD is in correct namespace (usually `kro-system`)
- Check Kro controller logs
- Validate RGD YAML syntax

### ResourceGroup Stuck
- Check resource status: `kubectl describe resourcegroup <name>`
- Review dependency chain
- Check for missing CRDs or permissions

### Template Rendering Errors
- Validate variable substitution syntax
- Check for undefined schema properties
- Review Kro controller logs

### Test Failures
- Ensure cluster connectivity for integration tests
- Verify AWS credentials for AWS resource tests
- Check test data validity
- Review test logs for specific errors
