# Crossplane v2 + Upbound Provider Testing Instructions

## ✅ Migration Status
All compositions successfully migrated to Crossplane v2 with Upbound providers:
- **DynamoDB**: Fully operational (minimal changes)
- **S3**: Fully operational (split into 4 managed resources)
- **RDS**: Fully operational (3 managed resources with field updates)

## Prerequisites

1. **Install Required Function**
   ```bash
   kubectl apply -f - <<EOF
   apiVersion: pkg.crossplane.io/v1
   kind: Function
   metadata:
     name: function-patch-and-transform
   spec:
     package: xpkg.upbound.io/crossplane-contrib/function-patch-and-transform:v0.2.1
   EOF
   ```

2. **Install EC2 Provider** (Required for RDS SecurityGroup)
   ```bash
   kubectl apply -f - <<EOF
   apiVersion: pkg.crossplane.io/v1
   kind: Provider
   metadata:
     name: provider-aws-ec2
   spec:
     package: xpkg.upbound.io/upbound/provider-aws-ec2:v1.13.1
   EOF
   ```

3. **Configure EC2 Provider IRSA** (Critical for RDS)
   ```bash
   # Wait for provider to install
   kubectl get providers.pkg.crossplane.io provider-aws-ec2
   
   # Get service account name
   SA_NAME=$(kubectl get serviceaccounts -n crossplane-system | grep provider-aws-ec2 | awk '{print $1}')
   
   # Add IRSA annotation (replace with your actual IAM role ARN)
   kubectl annotate serviceaccount $SA_NAME -n crossplane-system \
     eks.amazonaws.com/role-arn=arn:aws:iam::<account>:role/<crossplane-iam-role>
   
   # Restart provider pod
   kubectl delete pod -n crossplane-system -l pkg.crossplane.io/provider=provider-aws-ec2
   ```

4. **Update RDS Test File**
   Edit `test-rds-composition.yaml` and replace:
   ```yaml
   # Use valid PostgreSQL version
   engineVersion: "14.12"  # NOT "14.11"
   
   # Use actual VPC/subnet IDs
   subnetIds:
     - subnet-XXXXXXXXX  # Your subnet ID 1
     - subnet-YYYYYYYYY  # Your subnet ID 2
   vpcId: vpc-ZZZZZZZZZ   # Your VPC ID
   
   # Use unique name to avoid conflicts
   name: crossplane-v2-test-postgres-db  # NOT crossplane-v2-test-db
   ```

5. **Get Your AWS Network Info**
   ```bash
   # Get VPC ID
   aws ec2 describe-vpcs --query 'Vpcs[0].VpcId' --output text
   
   # Get subnet IDs (any subnets work, not just private)
   aws ec2 describe-subnets --filters "Name=vpc-id,Values=YOUR_VPC_ID" \
     --query 'Subnets[].SubnetId' --output text
   
   # Check valid PostgreSQL versions
   aws rds describe-db-engine-versions --engine postgres \
     --query 'DBEngineVersions[?contains(EngineVersion, `14.`)].EngineVersion'
   ```

## Test Sequence

### 1. Test DynamoDB Composition ✅
```bash
# Apply DynamoDB test
kubectl apply -f test-dynamodb-table.yaml

# Check status
kubectl get dynamodbtables
kubectl describe dynamodbtable rust-service-table-test

# Verify Upbound managed resource
kubectl get tables.dynamodb.aws.upbound.io
```

### 2. Test S3 Composition ✅
```bash
# Apply S3 test
kubectl apply -f test-s3-composition.yaml

# Check status
kubectl get objectstorages
kubectl describe objectstorage test-s3-composition

# Verify Upbound managed resources (4 total)
kubectl get buckets.s3.aws.upbound.io
kubectl get bucketpublicaccessblocks.s3.aws.upbound.io
kubectl get bucketownershipcontrols.s3.aws.upbound.io
kubectl get bucketserversideencryptionconfigurations.s3.aws.upbound.io
```

### 3. Test RDS Composition ✅ (after prerequisites)
```bash
# IMPORTANT: Complete all prerequisites first!
# - Install function-patch-and-transform
# - Install provider-aws-ec2
# - Configure EC2 provider IRSA
# - Update test file with valid values

# Apply RDS test
kubectl apply -f test-rds-composition.yaml

# Check status (may take 5-15 minutes for RDS)
kubectl get relationaldatabases
kubectl describe relationaldatabase test-rds-composition

# Verify Upbound managed resources (3 total)
kubectl get subnetgroups.rds.aws.upbound.io
kubectl get securitygroups.ec2.aws.upbound.io
kubectl get instances.rds.aws.upbound.io

# Check AWS directly
aws rds describe-db-instances --query 'DBInstances[].{ID:DBInstanceIdentifier,Status:DBInstanceStatus}'
```

## Expected Results

### Success Indicators
- **SYNCED: True** - Composition applied successfully
- **READY: True** - AWS resource provisioned (may take 5-15 minutes for RDS)
- **Connection Secret**: Created with resource details
- **AWS Resources**: Visible in AWS console

### Resource Counts
| Service | Managed Resources | Notes |
|---------|------------------|-------|
| **DynamoDB** | 1 Table | Single resource, fast provisioning |
| **S3** | 4 Resources | Bucket + PublicAccessBlock + OwnershipControls + SSE |
| **RDS** | 3 Resources | SubnetGroup + SecurityGroup + Instance (slow) |

### Troubleshooting
```bash
# Check all managed resources
kubectl get managed

# Check events for errors
kubectl get events --sort-by='.lastTimestamp' | tail -20

# Check composition logs
kubectl logs -n crossplane-system deployment/crossplane

# Check provider logs
kubectl logs -n crossplane-system -l pkg.crossplane.io/provider=provider-aws-s3
kubectl logs -n crossplane-system -l pkg.crossplane.io/provider=provider-aws-rds
kubectl logs -n crossplane-system -l pkg.crossplane.io/provider=provider-aws-dynamodb
kubectl logs -n crossplane-system -l pkg.crossplane.io/provider=provider-aws-ec2
```

### Common Issues & Solutions

#### Critical RDS Issues
1. **Missing EC2 Provider** ❌→✅
   - **Error**: `no matches for kind "SecurityGroup" in version "ec2.aws.upbound.io/v1beta1"`
   - **Fix**: Install `provider-aws-ec2` (see Prerequisites #2)

2. **EC2 Provider Missing IRSA** ❌→✅
   - **Error**: `token file name cannot be empty`
   - **Fix**: Add IRSA annotation to EC2 provider service account (see Prerequisites #3)

3. **SecurityGroup External-Name Issue** ❌→✅
   - **Error**: `InvalidGroupId.Malformed: Invalid id: "name" (expecting "sg-...")`
   - **Fix**: Remove external-name annotation from SecurityGroup in composition

4. **Invalid PostgreSQL Version** ❌→✅
   - **Error**: `Cannot find version 14.11 for postgres`
   - **Fix**: Use valid version like `14.12` (check with AWS CLI)

5. **Secret Reference Mismatch** ❌→✅
   - **Error**: `InvalidParameterValue: Invalid master password`
   - **Fix**: Ensure composition references correct secret name

#### General Issues
6. **Function not found**: Install `function-patch-and-transform` first
7. **S3 region errors**: All S3 companion resources need region field
8. **RDS field errors**: Use `username` not `masterUsername`, `instanceClass` not `dbInstanceClass`
9. **Name conflicts**: Use unique resource names to avoid AWS conflicts

## Cleanup
```bash
# Delete test resources
kubectl delete -f test-s3-composition.yaml
kubectl delete -f test-rds-composition.yaml
kubectl delete -f test-dynamodb-table.yaml

# Verify cleanup
kubectl get managed
```

## What This Validates

✅ **Crossplane v2 Pipeline Mode**: All compositions use new pipeline architecture  
✅ **Upbound Providers**: Using latest Upbound provider ecosystem  
✅ **S3 Multi-Resource**: Bucket security features as separate managed resources  
✅ **RDS Field Updates**: Correct field names for Upbound RDS provider  
✅ **DynamoDB Compatibility**: Minimal changes needed for DynamoDB  
✅ **EC2 Provider Integration**: SecurityGroup support for RDS  
✅ **IRSA Configuration**: Proper AWS credentials for all providers  
✅ **Error Recovery**: All critical issues identified and resolved  
✅ **Workshop Compatibility**: All compositions work for student use  

## Migration Summary
- **Pipeline Mode**: All compositions converted from `spec.resources` to `spec.mode: Pipeline`
- **API Updates**: Community providers → Upbound providers
- **Field Changes**: Updated field names to match Upbound schemas
- **Resource Splitting**: S3 features split into separate CRDs
- **Provider Installation**: Added EC2 provider for SecurityGroup support
- **Credential Configuration**: IRSA setup for all providers
- **Error Resolution**: 10+ critical issues identified and fixed
- **Version Compatibility**: PostgreSQL and other version validations
- **Network Configuration**: Real VPC/subnet ID requirements

## Testing Results

### Final Status ✅
```bash
kubectl get objectstorages,dynamodbtables,relationaldatabases
```
**Expected Output:**
```
NAME                                                 SYNCED   READY
objectstorage.awsblueprints.io/test-s3-composition   True     True

NAME                                                     SYNCED   READY
dynamodbtable.awsblueprints.io/rust-service-table-test   True     True

NAME                                                       SYNCED   READY
relationaldatabase.awsblueprints.io/test-rds-composition   True     True
```

### AWS Resource Verification
```bash
# Verify S3 bucket
aws s3 ls | grep crossplane-v2-test-bucket

# Verify DynamoDB table
aws dynamodb describe-table --table-name rust-service-table-test

# Verify RDS instance
aws rds describe-db-instances --query 'DBInstances[?contains(DBInstanceIdentifier, `crossplane`)].{ID:DBInstanceIdentifier,Status:DBInstanceStatus}'
```