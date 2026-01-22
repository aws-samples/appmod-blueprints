# CI/CD Pipeline Template Tests

This directory contains test and validation scripts for the Backstage CI/CD Pipeline template.

## Test Scripts

- `test-parameter-validation.sh` - Tests parameter validation for the template
- `test-webhook-integration.sh` - Tests webhook integration functionality

## Validation Scripts

- `validate-argocd-integration.sh` - Validates ArgoCD integration
- `validate-output-links.sh` - Validates output links functionality
- `validate-parameter-handling.sh` - Validates parameter handling
- `validate-template-simplification.sh` - Validates template simplification
- `validate-webhook-integration.sh` - Validates GitLab webhook integration

## Usage

Run scripts from the parent directory:

```bash
# Example: Validate webhook integration
./tests/validate-webhook-integration.sh {namespace} {app-name} {gitlab-hostname}

# Example: Test parameter validation
./tests/test-parameter-validation.sh
```

## Related Testing

For comprehensive Kro RGD testing, see the main Taskfile tasks:
- `task test-kro-unit` - Unit tests for the RGD
- `task test-kro-template` - Template execution tests
- `task test-kro-integration` - Integration tests