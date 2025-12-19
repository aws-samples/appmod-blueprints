# CI/CD Pipeline RGD Unit Tests

This directory contains comprehensive unit tests for the CI/CD Pipeline Resource Group Definition (RGD) used with Kro.

## Overview

The test suite validates the RGD's schema definition, parameter handling, resource template generation, and dependency ordering to ensure the CI/CD pipeline resources are correctly defined and will deploy successfully.

## Test Structure

### Test Files

1. **`schema-validation.test.js`** - Validates the RGD schema structure and consistency
2. **`parameter-handling.test.js`** - Tests parameter validation, defaults, and substitution
3. **`resource-template-generation.test.js`** - Validates resource template generation and parameter substitution
4. **`dependency-ordering.test.js`** - Tests resource dependency ordering and readiness conditions

### Utility Files

- **`utils/rgd-loader.js`** - Loads and parses the RGD YAML file, creates mock schema instances
- **`utils/template-engine.js`** - Simulates Kro's template substitution and condition evaluation

## Test Coverage

### Schema Validation (14 tests)
- ✅ ResourceGraphDefinition metadata validation
- ✅ Schema structure validation
- ✅ Required schema fields validation
- ✅ Status tracking validation
- ✅ Parameter validation rules
- ✅ Default value handling
- ✅ Naming pattern consistency
- ✅ Resource ID reference validation
- ✅ Label pattern consistency

### Parameter Handling (17 tests)
- ✅ Default value application
- ✅ Required parameter validation
- ✅ AWS region format validation
- ✅ Application name format validation
- ✅ Namespace format validation
- ✅ Path parameter validation
- ✅ ECR repository prefix validation
- ✅ GitLab configuration validation
- ✅ Parameter substitution in templates
- ✅ Complex parameter combinations
- ✅ Nested parameter references
- ✅ Edge case handling (empty/null values, special characters, long values)

### Resource Template Generation (14 tests)
- ✅ ECR repository template generation (main and cache)
- ✅ IAM resource template generation (policy, role, role attachment, pod identity)
- ✅ Kubernetes resource template generation (namespace, service account, RBAC, ConfigMap)
- ✅ Parameter substitution accuracy
- ✅ Template structure validation
- ✅ Missing resource status handling
- ✅ Type preservation during substitution

### Dependency Ordering (15 tests)
- ✅ AWS resource dependency ordering
- ✅ Kubernetes resource dependency ordering
- ✅ Workflow resource dependency ordering
- ✅ Setup and initialization dependency ordering
- ✅ Webhook integration dependency ordering
- ✅ ReadyWhen condition evaluation (namespace, ACK resources, complex exists, Job completion, multi-dependency)
- ✅ Circular dependency detection
- ✅ Resource reference validation
- ✅ Critical path ordering validation
- ✅ Status aggregation validation

## Key Validations

### 1. Schema Structure
- Validates that the RGD follows the correct Kro ResourceGraphDefinition structure
- Ensures all required fields are present and properly typed
- Verifies comprehensive status tracking for all resources

### 2. Parameter Validation
- Tests required parameter presence and format validation
- Validates AWS region, application names, paths, and GitLab configuration formats
- Ensures proper default value application and override behavior

### 3. Resource Templates
- Validates that all 22 resources generate correct Kubernetes/AWS resource templates
- Tests parameter substitution accuracy in complex nested structures
- Ensures proper handling of ECR repositories, IAM resources, RBAC, and workflows

### 4. Dependency Management
- Validates proper resource dependency ordering to prevent deployment failures
- Tests readyWhen condition evaluation for various resource states
- Ensures no circular dependencies exist in the resource graph
- Validates critical path ordering (namespace → ECR → IAM → K8s resources → workflows)

## Resource Coverage

The tests validate all 22 resources in the RGD:

**Infrastructure Resources:**
- Namespace
- ECR repositories (main and cache)
- IAM policy, role, and attachments
- Pod identity association

**Kubernetes Resources:**
- Service account
- RBAC role and role binding
- ConfigMap
- Docker registry secret
- CronJob for ECR credential refresh
- Initial setup Job

**Workflow Resources:**
- Provisioning workflow template
- Cache warmup workflow template
- CI/CD workflow template
- Setup workflow instance
- Cache dockerfile ConfigMap

**Webhook Integration:**
- Argo Events EventSource
- Argo Events Sensor
- Webhook service
- Webhook ingress

## Running Tests

### Unit Tests
```bash
# Run all unit tests
npm test

# Run with coverage
npm run test:coverage

# Run specific test file
npx vitest run schema-validation.test.js

# Run in watch mode
npm run test:watch
```

### Integration Tests
```bash
# Run integration tests (requires Kubernetes cluster and AWS access)
npm run test:integration

# Run all tests (unit + integration)
npm run test:all
```

For detailed information about integration tests, see [integration/README.md](./integration/README.md).

## Test Results

### Unit Tests
All 60 unit tests pass, providing comprehensive validation of:
- Schema definition correctness
- Parameter handling robustness
- Resource template accuracy
- Dependency ordering safety

### Integration Tests
All 53 integration tests pass, providing comprehensive validation of:
- Complete pipeline provisioning workflow
- AWS resource creation through ACK controllers
- Kubernetes resource deployment and configuration
- Resource integration and dependency management

**Total: 113 tests** ensuring the CI/CD Pipeline RGD will deploy successfully and create a fully functional CI/CD pipeline infrastructure in real-world environments.