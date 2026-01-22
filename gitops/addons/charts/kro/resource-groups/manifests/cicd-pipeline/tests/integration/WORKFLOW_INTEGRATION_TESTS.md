# Workflow Integration Tests

This document describes the workflow integration tests for the CI/CD Pipeline Kro Resource Group Definition (RGD). These tests validate the integration between Argo Workflows, ECR authentication, and webhook triggering according to requirements 5.1-5.5.

## Overview

The workflow integration tests verify:

1. **Argo Workflows Access to Provisioned Resources** (Requirement 5.3)
   - WorkflowTemplates are created and accessible
   - Service accounts have proper RBAC permissions
   - ConfigMaps with ECR repository information are accessible
   - Docker registry secrets for ECR authentication are available

2. **ECR Authentication and Image Operations** (Requirement 5.4)
   - ECR repositories are created with proper configuration
   - ECR credential refresh CronJob is configured
   - Workflow templates are configured for Kaniko image building
   - ECR authentication workflow execution works

3. **Webhook Triggering and Build Processes** (Requirements 5.1, 5.2, 5.5)
   - Argo Events EventSource is configured for GitLab webhooks
   - Argo Events Sensor is configured to trigger workflows
   - Webhook endpoint is accessible via Ingress
   - Workflow templates execute CI/CD operations
   - GitLab repository update capability is validated

## Prerequisites

Before running the workflow integration tests, ensure the following are installed and configured:

### Required Components

1. **Kubernetes Cluster** with kubectl access
2. **Kro** - Resource orchestration controller
3. **Argo Workflows** - Workflow execution engine
4. **Argo Events** - Event-driven workflow triggering
5. **CI/CD Pipeline RGD** - The ResourceGraphDefinitionDefinition being tested

### Optional Components (for full functionality)

1. **ACK Controllers** - AWS Controller for Kubernetes
   - ECR Controller
   - IAM Controller  
   - EKS Controller
2. **External Secrets Operator** - For GitLab credential management
3. **Ingress Controller** - For webhook endpoint exposure

### Installation Commands

```bash
# Install Kro
kubectl apply -f https://github.com/awslabs/kro/releases/latest/download/kro.yaml

# Install Argo Workflows
kubectl create namespace argo
kubectl apply -n argo -f https://github.com/argoproj/argo-workflows/releases/latest/download/install.yaml

# Install Argo Events
kubectl create namespace argo-events
kubectl apply -f https://raw.githubusercontent.com/argoproj/argo-events/stable/manifests/install.yaml

# Install CI/CD Pipeline RGD
kubectl apply -f ../cicd-pipeline.yaml
```

## Running the Tests

### Quick Test Run

```bash
# Navigate to the test directory
cd appmod-blueprints/gitops/addons/charts/kro/resource-groups/cicd-pipeline/tests

# Run workflow integration tests
./run-workflow-integration-tests.sh
```

### Manual Test Execution

```bash
# Navigate to integration test directory
cd integration

# Install test dependencies
npm install

# Run workflow integration tests
npm run test:workflow

# Run with specific configuration
npx vitest run workflow-integration.test.js --config vitest.workflow.config.js
```

### Test Options

```bash
# Run tests with cleanup only
./run-workflow-integration-tests.sh --cleanup-only

# Run tests without cleanup (for debugging)
./run-workflow-integration-tests.sh --skip-cleanup

# Show help
./run-workflow-integration-tests.sh --help
```

## Test Structure

### Test Files

- `workflow-integration.test.js` - Main test suite
- `vitest.workflow.config.js` - Test configuration
- `setup/workflow-global-setup.js` - Global setup and teardown
- `utils/workflow-test-utils.js` - Utility functions
- `run-workflow-integration-tests.sh` - Test runner script

### Test Scenarios

#### 1. Argo Workflows Access Tests

```javascript
describe('Argo Workflows Access to Provisioned Resources', () => {
  it('should have WorkflowTemplates created and accessible')
  it('should have service account with proper RBAC permissions')
  it('should have ConfigMap with ECR repository information accessible to workflows')
  it('should have Docker registry secret for ECR authentication')
})
```

#### 2. ECR Authentication Tests

```javascript
describe('ECR Authentication and Image Operations', () => {
  it('should have ECR repositories created with proper configuration')
  it('should have ECR credential refresh CronJob configured')
  it('should have workflow templates configured for Kaniko image building')
  it('should test ECR authentication workflow execution')
})
```

#### 3. Webhook Integration Tests

```javascript
describe('Webhook Triggering and Build Processes', () => {
  it('should have Argo Events EventSource configured for GitLab webhooks')
  it('should have Argo Events Sensor configured to trigger workflows')
  it('should have webhook endpoint accessible via Ingress')
  it('should test workflow template execution for CI/CD operations')
  it('should validate GitLab repository update capability in workflow templates')
})
```

#### 4. End-to-End Integration Tests

```javascript
describe('End-to-End Workflow Integration', () => {
  it('should validate complete pipeline workflow execution')
})
```

## Test Configuration

### Environment Variables

- `NODE_ENV=test` - Test environment
- `VITEST_WORKFLOW_INTEGRATION=true` - Workflow integration test flag

### Test Timeouts

- **Test Timeout**: 10 minutes (600,000ms)
- **Hook Timeout**: 10 minutes (600,000ms)
- **Teardown Timeout**: 5 minutes (300,000ms)

### Test Namespace

Tests run in isolated namespace: `test-workflow-integration`

## Expected Test Results

### Successful Test Run

```
✅ Argo Workflows access to provisioned resources
✅ ECR authentication and image operations  
✅ Webhook triggering and build processes
✅ End-to-end workflow integration

All workflow integration tests passed!
```

### Test Artifacts

- **WorkflowTemplates**: 3 templates (provisioning, cicd, cache-warmup)
- **Kubernetes Resources**: 22+ resources created
- **AWS Resources**: ECR repositories, IAM roles (via ACK)
- **Argo Events**: EventSource and Sensor for webhooks

## Troubleshooting

### Common Issues

#### 1. Missing CRDs

```
Error: Kro CRDs not found. Please install Kro first.
```

**Solution**: Install Kro controller
```bash
kubectl apply -f https://github.com/awslabs/kro/releases/latest/download/kro.yaml
```

#### 2. ACK Controllers Not Available

```
Warning: ACK ECR controller not found. Some tests may fail.
```

**Solution**: Install ACK controllers or expect some tests to fail gracefully

#### 3. Workflow Execution Failures

```
Error: Workflow failed: ECR repository not found
```

**Solution**: This is expected in test environments without real AWS resources

#### 4. Timeout Issues

```
Error: Timeout waiting for CICDPipeline to be Ready
```

**Solution**: Increase timeout or check cluster resources

### Debug Commands

```bash
# Check CICDPipeline status
kubectl get cicdpipeline -n test-workflow-integration

# Check created resources
kubectl get all,workflowtemplate,eventsource,sensor -n test-workflow-integration

# Check workflow logs
kubectl logs -l workflows.argoproj.io/workflow=<workflow-name> -n test-workflow-integration

# Check Kro controller logs
kubectl logs -n kro-system -l app.kubernetes.io/name=kro
```

## Test Coverage

The workflow integration tests cover:

- ✅ **Resource Creation**: All 22+ resources from RGD
- ✅ **RBAC Configuration**: Service accounts and role bindings
- ✅ **ConfigMap Access**: ECR repository information
- ✅ **Secret Management**: Docker registry secrets
- ✅ **Workflow Templates**: All 3 workflow templates
- ✅ **Event Configuration**: EventSource and Sensor setup
- ✅ **Ingress Configuration**: Webhook endpoint exposure
- ✅ **End-to-End Flow**: Complete pipeline workflow

## Integration with CI/CD

### GitHub Actions Example

```yaml
name: Workflow Integration Tests
on: [push, pull_request]

jobs:
  workflow-integration:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v3
    - name: Setup Kubernetes
      uses: helm/kind-action@v1.4.0
    - name: Install Prerequisites
      run: |
        # Install Kro, Argo Workflows, Argo Events
    - name: Run Workflow Integration Tests
      run: |
        cd appmod-blueprints/gitops/addons/charts/kro/resource-groups/cicd-pipeline/tests
        ./run-workflow-integration-tests.sh
```

### GitLab CI Example

```yaml
workflow-integration-tests:
  stage: test
  image: bitnami/kubectl:latest
  script:
    - cd appmod-blueprints/gitops/addons/charts/kro/resource-groups/cicd-pipeline/tests
    - ./run-workflow-integration-tests.sh
  artifacts:
    reports:
      junit: integration/workflow-integration-results.json
```

## Contributing

When adding new workflow integration tests:

1. Follow the existing test structure
2. Use the utility functions in `utils/workflow-test-utils.js`
3. Add proper cleanup in test teardown
4. Update this documentation
5. Ensure tests are idempotent and can run multiple times

## References

- [Kro Documentation](https://kro.run/)
- [Argo Workflows Documentation](https://argoproj.github.io/argo-workflows/)
- [Argo Events Documentation](https://argoproj.github.io/argo-events/)
- [ACK Documentation](https://aws-controllers-k8s.github.io/community/)
- [Vitest Documentation](https://vitest.dev/)