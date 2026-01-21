# Ray Service S3 Model Cache Implementation

## Overview
This document describes the implemented S3-based model caching system for Ray Services, which reduces startup time from 5-10 minutes to under 1 minute by pre-staging models from HuggingFace to S3.

## Quick Start: Adding New Models

To add a new model to the cache:

1. Update `gitops/addons/bootstrap/default/addons.yaml`:
```yaml
ray-operator:
  valuesObject:
    modelPrestage:
      models:
        - name: new-model
          huggingfaceId: "org/model-name"
          s3Path: "models/new-model"
```

2. Sync ray-operator addon:
```bash
kubectl patch application ray-operator-peeks-hub -n argocd \
  --type merge -p '{"operation":{"sync":{"revision":"HEAD"}}}'
```

3. Wait for prestage job to complete (~10 minutes):
```bash
kubectl get jobs -n ray-system | grep prestage
```

4. Update Backstage template with new model option in `platform/backstage/templates/ray-serve/template-ray-serve.yaml`

## Architecture

### Components
1. **S3 Bucket**: Central model storage (`peeks-ray-models-{account-id}`)
2. **Model Prestage Jobs**: Kubernetes Jobs that download models to S3
3. **S3 CSI Driver**: Mounts S3 bucket as persistent volume
4. **KRO RayService Template**: Enhanced with S3 volume mounts
5. **Ray Serve Apps**: Load models from mounted S3 path

## Implementation

### 1. S3 Bucket and IAM Roles

**Created by Terraform**: `platform/infra/terraform/common/model-storage.tf`

```hcl
# S3 bucket for model storage
resource "aws_s3_bucket" "ray_models" {
  bucket = "${local.context_prefix}-ray-models-${data.aws_caller_identity.current.account_id}"
}

# IAM role for model prestage jobs
resource "aws_iam_role" "model_prestage" {
  name = "${local.context_prefix}-model-prestage-role"
  # Permissions: s3:PutObject, s3:GetObject, s3:ListBucket
}

# IAM role for Ray workers
resource "aws_iam_role" "ray_worker" {
  name = "${local.context_prefix}-ray-worker-role"
  # Permissions: s3:GetObject, s3:ListBucket (read-only)
}
```

**Outputs**:
- Bucket: `peeks-ray-models-<AWS_ACCOUNT_ID>`
- Models path: `s3://peeks-ray-models-<AWS_ACCOUNT_ID>/models/`

**GitOps Bridge Integration**:

The S3 bucket name is dynamically injected into the ray-operator addon via GitOps bridge cluster secret annotations:

1. **Terraform adds metadata** to cluster secret (`platform/infra/terraform/common/locals.tf`):
```hcl
addons_metadata = {
  resource_prefix = var.resource_prefix  # "peeks"
  aws_account_id  = data.aws_caller_identity.current.account_id  # "<AWS_ACCOUNT_ID>"
  # ... other metadata
}
```

2. **ArgoCD ApplicationSet** reads annotations (`gitops/addons/bootstrap/default/addons.yaml`):
```yaml
ray-operator:
  valuesObject:
    modelPrestage:
      s3Bucket: '{{.metadata.annotations.resource_prefix}}-ray-models-{{.metadata.annotations.aws_account_id}}'
```

3. **Result**: `peeks-ray-models-<AWS_ACCOUNT_ID>` is automatically constructed from cluster metadata

This approach ensures the S3 bucket name is consistent across all environments without hardcoding.

### 2. Model Prestage Jobs

**Location**: `gitops/addons/charts/ray-operator/templates/model-prestage-job.yaml`

**Configuration**: `gitops/addons/bootstrap/default/addons.yaml`

```yaml
ray-operator:
  enabled: true
  valuesObject:
    modelPrestage:
      enabled: true
      s3Bucket: "peeks-ray-models-<AWS_ACCOUNT_ID>"
      models:
        - name: tinyllama
          huggingfaceId: "TinyLlama/TinyLlama-1.1B-Chat-v1.0"
          s3Path: "models/tinyllama"
        - name: mistral-7b
          huggingfaceId: "mistralai/Mistral-7B-Instruct-v0.2"
          s3Path: "models/mistral-7b"
```

**Job Execution**:
- Runs as Kubernetes Job in `ray-system` namespace
- Downloads models from HuggingFace using `transformers` library
- Uploads to S3 using AWS CLI
- Takes ~10 minutes per model
- Runs once, can be re-triggered by deleting the job

### 3. S3 CSI Driver Integration

**Enabled in**: `gitops/addons/bootstrap/default/addons.yaml`

```yaml
mountpoint-s3-csi-driver:
  enabled: true
```

**PersistentVolume**: Created by KRO RayService template

```yaml
apiVersion: v1
kind: PersistentVolume
metadata:
  name: ${schema.spec.name}-ray-models-pv
spec:
  capacity:
    storage: 100Gi
  accessModes:
    - ReadOnlyMany
  mountOptions:
    - allow-delete
    - region ${schema.spec.?awsRegion.orValue('us-west-2')}
  csi:
    driver: s3.csi.aws.com
    volumeHandle: peeks-ray-models-<AWS_ACCOUNT_ID>
```

**Note**: The region is dynamically set from the `awsRegion` schema parameter, which comes from the GitOps bridge cluster annotation (`aws_region`). The default `us-west-2` is only used as a fallback.

**Mounted at**: `/mnt/models/` in Ray pods

### 4. KRO RayService Template

**Location**: `gitops/addons/charts/kro/resource-groups/manifests/ray-service/ray-service.yaml`

**Key Changes**:

```yaml
spec:
  schema:
    spec:
      modelId: string | default="/mnt/models/models/tinyllama"
      awsRegion: string | default="us-west-2"
      # Models available:
      # - /mnt/models/models/tinyllama (CPU)
      # - /mnt/models/models/mistral-7b (GPU)
```

**Note**: The `awsRegion` parameter is automatically populated from the GitOps bridge cluster annotation and used throughout the template for ECR image URLs and S3 mount options.

**Volume Configuration**:
```yaml
volumes:
  - name: ray-models
    persistentVolumeClaim:
      claimName: ${schema.spec.name}-ray-models-pvc
      readOnly: true

volumeMounts:
  - name: ray-models
    mountPath: /mnt/models
    readOnly: true
```

### 5. Ray Serve Application

**Location**: `gitops/workloads/ray/cpu-serve-config.zip`

**Key Implementation**:

```python
import os
from transformers import AutoTokenizer, AutoModelForCausalLM

class TextGenerator:
    def __init__(self, model_id: str = None):
        # Model ID from environment or default
        self.model_id = model_id or os.environ.get('MODEL_ID', 
            '/mnt/models/models/tinyllama')
        
        # Load from local S3-mounted path
        self.tokenizer = AutoTokenizer.from_pretrained(
            self.model_id, 
            local_files_only=True  # Critical: prevents HuggingFace download
        )
        self.model = AutoModelForCausalLM.from_pretrained(
            self.model_id,
            torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
            device_map="auto",
            local_files_only=True  # Critical: prevents HuggingFace download
        )
```

**Important**: `local_files_only=True` is required to prevent fallback to HuggingFace downloads.

### 6. Backstage Template

**Location**: `platform/backstage/templates/ray-serve/template-ray-serve.yaml`

**Model Selection**:
```yaml
- title: Model Configuration
  properties:
    modelId:
      title: Model
      type: string
      enum:
        - /mnt/models/models/tinyllama
        - /mnt/models/models/mistral-7b
      enumNames:
        - TinyLlama 1.1B (CPU)
        - Mistral 7B Instruct (GPU)
```

**Auto GPU Selection**:
```yaml
workerGpu: ${{ parameters.modelId === '/mnt/models/models/mistral-7b' and '1' or '0' }}
workerMemory: ${{ parameters.modelId === '/mnt/models/models/mistral-7b' and '48Gi' or '16Gi' }}
```

## Deployment Workflow

### Initial Setup (Already Completed)

1. ✅ Terraform creates S3 bucket and IAM roles
2. ✅ Ray operator addon enabled with modelPrestage config
3. ✅ Model prestage jobs run and populate S3 bucket
4. ✅ S3 CSI driver installed
5. ✅ KRO RayService template updated with S3 volumes
6. ✅ Backstage template updated with model selection

### Deploying a Ray Service

1. Open Backstage: `https://$BACKSTAGE_URL/backstage`
2. Navigate to "Create" → "Ray Serve Deployment"
3. Fill in:
   - Name: `my-service`
   - Model: Select from dropdown (TinyLlama or Mistral-7B)
   - Workers: 1-3
4. Review computed values (GPU auto-selected)
5. Deploy

**Startup Time**: ~30-60 seconds (vs 5-10 minutes without cache)

### Verifying Model Cache

```bash
# Check S3 bucket contents
aws s3 ls s3://peeks-ray-models-${AWS_ACCOUNT_ID}/models/ --recursive | head -20

# Check model prestage jobs (prefixed with resourcePrefix)
kubectl get jobs -n ray-system | grep prestage

# Note: Prestage job pods are cleaned up after successful completion
# To verify models were uploaded, check S3 directly (command above)

# Check if models are mounted in Ray pod
kubectl exec -n ray-system <ray-pod> -- ls -lh /mnt/models/models/

# Expected output:
# drwxr-xr-x tinyllama/
# drwxr-xr-x mistral-7b/
```

## Performance Metrics

### Startup Times
- **Without S3 cache**: 5-10 minutes (HuggingFace download)
- **With S3 cache**: 30-60 seconds (local mount)
- **Pod restart**: 30-60 seconds (mount persists)
- **Scaling workers**: 30-60 seconds per worker

### Storage
- TinyLlama: ~500MB
- Mistral-7B: ~14GB
- S3 cost: ~$0.023/GB/month = ~$0.35/month total

## Troubleshooting

### Model Not Found Error
```
Error: [Errno 2] No such file or directory: '/mnt/models/models/tinyllama'
```

**Solution**: Check if model prestage job completed
```bash
kubectl get jobs -n ray-system
kubectl logs -n ray-system job/peeks-tinyllama-prestage
```

### HuggingFace Download Attempted
```
Error: Repo id must be in the form 'repo_name' or 'namespace/repo_name'
```

**Solution**: Missing `local_files_only=True` in model loading code

### S3 Mount Failed
```
Error: Failed to mount s3 bucket
```

**Solution**: Check S3 CSI driver and IAM permissions
```bash
kubectl get pods -n kube-system | grep s3-csi
kubectl logs -n kube-system <s3-csi-pod>
```

## Adding New Models

See [Quick Start: Adding New Models](#quick-start-adding-new-models) at the top of this document for step-by-step instructions.

## Future Enhancements

1. **Trainium Support**: Add Neuron-optimized models for AWS Trainium
2. **Model Versioning**: Track model versions in S3 with metadata
3. **Multi-Region**: Replicate models across regions
4. **Monitoring**: Add metrics for model load times and cache hits

## Related Documentation

- [Ray Trainium Support](./features/ray-trainium-support.md)
- [KRO RayService Template](../gitops/addons/charts/kro/resource-groups/manifests/ray-service/)
- [Backstage Ray Template](../platform/backstage/templates/ray-serve/)
