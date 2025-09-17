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

2. **Update RDS Test File**
   Edit `test-rds-composition.yaml` and replace:
   ```yaml
   subnetIds:
     - subnet-XXXXXXXXX  # Your private subnet ID 1
     - subnet-YYYYYYYYY  # Your private subnet ID 2
   vpcId: vpc-ZZZZZZZZZ   # Your VPC ID
   ```

3. **Get Your AWS Network Info**
   ```bash
   # Get VPC ID
   aws ec2 describe-vpcs --query 'Vpcs[0].VpcId' --output text
   
   # Get private subnet IDs
   aws ec2 describe-subnets --filters "Name=vpc-id,Values=YOUR_VPC_ID" \
     --query 'Subnets[?MapPublicIpOnLaunch==`false`].SubnetId' --output text
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

### 3. Test RDS Composition ✅ (after updating subnet/VPC)
```bash
# Apply RDS test
kubectl apply -f test-rds-composition.yaml

# Check status
kubectl get relationaldatabases
kubectl describe relationaldatabase test-rds-composition

# Verify Upbound managed resources (3 total)
kubectl get subnetgroups.rds.aws.upbound.io
kubectl get securitygroups.ec2.aws.upbound.io
kubectl get instances.rds.aws.upbound.io
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

### Common Issues
1. **Function not found**: Install `function-patch-and-transform` first
2. **S3 region errors**: All S3 companion resources need region field
3. **RDS field errors**: Use `username` not `masterUsername`, `instanceClass` not `dbInstanceClass`
4. **EC2 provider missing**: Install `provider-aws-ec2` for SecurityGroup support

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
✅ **Workshop Compatibility**: All compositions work for student use  

## Migration Summary
- **Pipeline Mode**: All compositions converted from `spec.resources` to `spec.mode: Pipeline`
- **API Updates**: Community providers → Upbound providers
- **Field Changes**: Updated field names to match Upbound schemas
- **Resource Splitting**: S3 features split into separate CRDs
- **Provider Installation**: Added EC2 provider for SecurityGroup support