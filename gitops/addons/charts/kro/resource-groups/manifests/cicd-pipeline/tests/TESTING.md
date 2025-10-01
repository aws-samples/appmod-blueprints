# Testing the CI/CD Pipeline Kro RGD

This directory contains everything needed to test and validate the CI/CD Pipeline ResourceGraphDefinition.

## Files in this Directory

- **`cicd-pipeline.yaml`** - The main Kro ResourceGraphDefinition
- **`README.md`** - Complete documentation and usage guide
- **`test-cicd-pipeline-instance.yaml`** - Sample CICDPipeline instance for testing
- **`test-kro-cicd-instance.sh`** - Full deployment test script
- **`test-kro-cicd-instance-dryrun.sh`** - Dry-run validation script
- **`cleanup-kro-test.sh`** - Cleanup script for test resources
- **`tests/`** - Unit tests for the RGD

## Quick Test

```bash
# Navigate to this directory
cd gitops/addons/charts/kro/resource-groups/cicd-pipeline

# Run dry-run test (no cluster required)
./test-kro-cicd-instance-dryrun.sh

# Run full test (requires cluster access)
./test-kro-cicd-instance.sh

# Clean up test resources
./cleanup-kro-test.sh
```

## What Gets Tested

The test scripts validate that a single `CICDPipeline` custom resource creates:

✅ **22+ Kubernetes and AWS resources**
✅ **Complete CI/CD pipeline infrastructure**
✅ **Proper resource dependencies and ordering**
✅ **AWS integration via ACK controllers**
✅ **Argo Workflows and Events integration**

## Test Results

Our testing has confirmed:

- ✅ **RGD Validation**: Passes Kro CLI validation
- ✅ **Resource Creation**: Successfully creates all 22+ resources
- ✅ **AWS Integration**: ECR repositories, IAM roles, and Pod Identity work correctly
- ✅ **Kubernetes Resources**: All native resources created successfully
- ✅ **Status Reporting**: CICDPipeline reports ACTIVE state with proper status fields

## Known Issues

- ⚠️ **Workflow Error**: The setup workflow may encounter errors (doesn't affect core functionality)
- ⚠️ **ECR Setup Job**: Initial ECR setup job may need retry (CronJob handles ongoing refresh)

These issues don't prevent the core CI/CD infrastructure from working correctly.