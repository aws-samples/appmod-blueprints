# Backstage Template Execution Tests

This directory contains comprehensive tests for the Backstage CI/CD Pipeline template execution, validating that the template correctly generates Kro instances and integrates with GitLab and ArgoCD.

## Test Coverage

### 1. Parameter Combinations Testing (`parameter-combinations.test.js`)
- **Purpose**: Validates template parameter handling with various input combinations
- **Coverage**:
  - Parameter validation patterns and constraints
  - Default value handling
  - Edge cases and boundary conditions
  - AWS region validation
  - Path pattern validation
  - Application name constraints

### 2. YAML Manifest Validation (`yaml-manifest-validation.test.js`)
- **Purpose**: Validates inline YAML manifest generation for Kro instances
- **Coverage**:
  - Kro CICDPipeline manifest structure
  - Parameter templating in manifests
  - Metadata labels and annotations
  - Spec structure validation
  - Default value handling in manifests
  - System information integration

### 3. GitLab and ArgoCD Integration (`gitlab-argocd-integration.test.js`)
- **Purpose**: Tests GitLab repository creation and ArgoCD application setup
- **Coverage**:
  - GitLab repository configuration
  - System information fetching
  - ArgoCD application creation
  - Sync policy configuration
  - Catalog registration
  - Output link generation
  - Step dependency validation

### 4. Pipeline Creation Validation (`pipeline-creation.test.js`)
- **Purpose**: Verifies that a single Kro instance creates complete CI/CD pipeline
- **Coverage**:
  - Kro RGD completeness
  - Template to RGD integration
  - Complete pipeline infrastructure
  - Resource orchestration and dependencies
  - End-to-end pipeline validation

### 5. Template Execution Flow (`template-execution.test.js`)
- **Purpose**: Comprehensive template execution and quality validation
- **Coverage**:
  - Template structure and metadata
  - Execution flow and step ordering
  - Multiple deployment scenarios
  - Error handling and validation
  - Output documentation
  - Integration points
  - Template completeness

## Running the Tests

### Prerequisites
```bash
cd appmod-blueprints/gitops/addons/charts/kro/resource-groups/cicd-pipeline/tests/template-execution
npm install
```

### Run All Tests
```bash
npm test
```

### Run Specific Test Suites
```bash
# Parameter validation tests
npm run test:parameters

# YAML manifest validation
npm run test:yaml

# GitLab and ArgoCD integration
npm run test:integration

# Pipeline creation validation
npm run test:pipeline

# Template execution flow
npm run test:template
```

### Run with Coverage
```bash
npm run test:coverage
```

### Watch Mode (for development)
```bash
npm run test:watch
```

## Test Scenarios

### Parameter Combinations Tested
1. **Minimal Configuration**: Default values with minimal required parameters
2. **Custom Paths**: Custom dockerfile and deployment paths
3. **EU Region**: European region deployment
4. **Complex Application**: Nested paths and complex naming
5. **Edge Cases**: Single character names, boundary conditions

### Deployment Scenarios Tested
1. **Production Deployment**: Custom cluster, production paths
2. **Development Deployment**: Default configuration
3. **Microservice Deployment**: Nested service paths

### Integration Points Validated
- ✅ Backstage catalog integration
- ✅ GitLab repository creation
- ✅ ArgoCD application setup
- ✅ Kro resource orchestration
- ✅ AWS resource provisioning via ACK
- ✅ Kubernetes resource creation

## Test Results Interpretation

### Success Criteria
- All parameter combinations validate correctly
- Inline YAML manifests are properly structured
- GitLab and ArgoCD integrations are configured correctly
- Single Kro instance creates complete CI/CD pipeline (20+ resources)
- Template execution flow is logical and complete

### Common Issues to Watch For
- Parameter validation pattern mismatches
- Missing template variables in manifests
- Incorrect step dependencies
- Missing output links or documentation
- Resource dependency ordering issues

## Validation Against Requirements

These tests validate the following requirements from the specification:

### Requirement 7.1: Inline YAML Manifests
- ✅ Template uses inline YAML manifests for all kube:apply actions
- ✅ No external file references in kube:apply actions

### Requirement 7.2: Parameter Templating
- ✅ Parameters are properly templated into Kro resource instance
- ✅ Default values are handled correctly

### Requirement 7.3: GitLab Integration
- ✅ GitLab repositories are created correctly
- ✅ ArgoCD applications are registered

### Requirement 7.4: Resource Organization
- ✅ Resources are organized in team-specific namespaces
- ✅ Proper resource naming and labeling

### Requirement 7.5: Output Links
- ✅ Comprehensive output links to relevant tools and dashboards
- ✅ Informative text output with next steps

## Continuous Integration

These tests should be run:
- Before any template changes are merged
- As part of the CI/CD pipeline for the template
- When the underlying Kro RGD is modified
- During release validation

## Troubleshooting

### Test Failures
1. **Parameter Validation Failures**: Check parameter patterns in template
2. **YAML Structure Failures**: Verify manifest template syntax
3. **Integration Failures**: Check step dependencies and system integration
4. **Pipeline Creation Failures**: Verify Kro RGD completeness

### Common Fixes
- Update parameter patterns to match validation requirements
- Fix template variable syntax in manifests
- Correct step ordering and dependencies
- Update output links and documentation

## Contributing

When adding new tests:
1. Follow the existing test structure and naming conventions
2. Add comprehensive test descriptions
3. Include both positive and negative test cases
4. Update this README with new test coverage
5. Ensure tests are deterministic and don't depend on external state