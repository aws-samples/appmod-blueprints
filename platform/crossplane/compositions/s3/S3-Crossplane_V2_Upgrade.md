# S3 Composition - Crossplane v2 + Upbound Provider Migration

## Migration Overview
Successfully migrated S3 composition from Crossplane v1 with community providers to Crossplane v2 with Upbound providers. The composition now creates 4 separate managed resources instead of 1 monolithic bucket.

## Major Changes Made

### 1. Pipeline Mode Conversion
**Before (v1):**
```yaml
spec:
  patchSets:
    - name: common-fields
      patches: [...]
  resources:
    - name: s3-bucket
      base: [...]
      patches: [...]
```

**After (v2):**
```yaml
spec:
  mode: Pipeline
  pipeline:
    - step: s3-bucket
      functionRef:
        name: function-patch-and-transform
      input:
        apiVersion: pt.fn.crossplane.io/v1beta1
        kind: Resources
        resources:
          - name: bucket
            base: [...]
            patches: [...]
```

### 2. Split S3 Features into Separate Resources
**Before (v1):** Single Bucket with nested configuration
```yaml
spec:
  forProvider:
    publicAccessBlockConfiguration:
      blockPublicPolicy: true
    objectOwnership: BucketOwnerEnforced
    serverSideEncryptionConfiguration:
      rules: [...]
```

**After (v2):** Four separate managed resources
```yaml
resources:
  - name: bucket                    # Core S3 bucket
  - name: bucket-public-access-block # BucketPublicAccessBlock
  - name: bucket-ownership          # BucketOwnershipControls  
  - name: bucket-sse               # BucketServerSideEncryptionConfiguration
```

### 3. API Version Updates
- `s3.aws.crossplane.io/v1beta1` → `s3.aws.upbound.io/v1beta2` (Bucket)
- Added `s3.aws.upbound.io/v1beta1` (BucketPublicAccessBlock)
- Added `s3.aws.upbound.io/v1beta2` (BucketOwnershipControls)
- Added `s3.aws.upbound.io/v1beta2` (BucketServerSideEncryptionConfiguration)

### 4. Field Format Fixes
**Region Requirements:**
```yaml
# Added to all S3 companion resources
spec:
  forProvider:
    region: us-west-2
patches:
  - type: FromCompositeFieldPath
    fromFieldPath: spec.resourceConfig.region
    toFieldPath: spec.forProvider.region
```

**Connection Secret Namespace:**
```yaml
# Added to bucket resource
patches:
  - fromFieldPath: spec.writeConnectionSecretToRef.namespace
    toFieldPath: spec.writeConnectionSecretToRef.namespace
```

**Rule Format Fix:**
```yaml
# Before (array)
rule:
  - objectOwnership: BucketOwnerEnforced

# After (object)  
rule:
  objectOwnership: BucketOwnerEnforced
```

### 5. String Transform Syntax
**Before (v1):**
```yaml
transforms:
  - type: string
    string:
      fmt: "%s-bucket"
```

**After (v2):**
```yaml
transforms:
  - type: string
    string:
      type: Format
      fmt: "%s-bucket"
```

## Why These Changes Were Necessary

### Crossplane v2 Requirements
- **Pipeline Mode:** v2 requires `mode: Pipeline` with function-based composition
- **Function Integration:** All patch logic must go through `function-patch-and-transform`

### Upbound Provider Differences
- **Separate CRDs:** Upbound models S3 features as individual managed resources instead of nested fields
- **Stricter Validation:** Field names and formats are more strictly enforced
- **Region Mandatory:** All S3 resources require explicit region specification
- **Schema Changes:** Some field structures changed (arrays vs objects)

### Benefits Gained
- **Better Resource Granularity:** Each S3 feature is a separate managed resource
- **Improved Error Handling:** Issues with individual features don't block entire bucket creation
- **Enhanced Observability:** Can monitor and troubleshoot each S3 feature independently
- **Future-Proof:** Aligned with Crossplane v2 architecture and Upbound provider ecosystem

## Validation
- ✅ All 4 S3 managed resources create successfully
- ✅ Bucket accessible with proper security settings
- ✅ Connection details published correctly
- ✅ Original functionality preserved