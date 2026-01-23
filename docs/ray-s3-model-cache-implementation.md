# Ray Service S3 Model Cache Implementation Plan

## Overview
Implement S3-based model caching to reduce Ray Service startup time from 5-10 minutes to 30-60 seconds by pre-downloading models from HuggingFace and storing them in S3.

## Architecture

### Components
1. **S3 Bucket**: Central model cache storage
2. **Bootstrap Script**: Downloads models from HuggingFace and uploads to S3
3. **Kro RGD Enhancement**: Add S3 bucket parameter
4. **Backstage Template Update**: Add S3 bucket configuration
5. **Ray Serve App Modification**: Check S3 first, fallback to HuggingFace

## Implementation Steps

### 1. Bootstrap Script: `scripts/setup-s3-model-cache.sh`

```bash
#!/bin/bash
# Setup S3 model cache for Ray Services

set -e

BUCKET_NAME="${1:-ray-model-cache-${AWS_ACCOUNT_ID}}"
REGION="${AWS_REGION:-us-west-2}"

# Supported models from Backstage template
MODELS=(
  "microsoft/DialoGPT-medium"
  "microsoft/phi-2"
  "TinyLlama/TinyLlama-1.1B-Chat-v1.0"
  "mistralai/Mistral-7B-Instruct-v0.2"
  "meta-llama/Llama-2-7b-chat-hf"
)

echo "Creating S3 bucket: ${BUCKET_NAME}"
aws s3 mb "s3://${BUCKET_NAME}" --region "${REGION}" || echo "Bucket already exists"

# Enable versioning
aws s3api put-bucket-versioning \
  --bucket "${BUCKET_NAME}" \
  --versioning-configuration Status=Enabled

# Create lifecycle policy to manage old versions
cat > /tmp/lifecycle-policy.json << EOF
{
  "Rules": [
    {
      "Id": "DeleteOldVersions",
      "Status": "Enabled",
      "NoncurrentVersionExpiration": {
        "NoncurrentDays": 30
      }
    }
  ]
}
EOF

aws s3api put-bucket-lifecycle-configuration \
  --bucket "${BUCKET_NAME}" \
  --lifecycle-configuration file:///tmp/lifecycle-policy.json

echo "Downloading and uploading models to S3..."

# Create Python script to download and upload models
cat > /tmp/download-models.py << 'PYTHON_EOF'
import os
import sys
import boto3
from transformers import AutoTokenizer, AutoModelForCausalLM
from pathlib import Path

bucket_name = sys.argv[1]
models = sys.argv[2:]

s3 = boto3.client('s3')
cache_dir = Path("/tmp/model-cache")
cache_dir.mkdir(exist_ok=True)

for model_id in models:
    print(f"\n{'='*60}")
    print(f"Processing: {model_id}")
    print(f"{'='*60}")
    
    model_path = cache_dir / model_id.replace("/", "--")
    
    try:
        # Download model and tokenizer
        print(f"Downloading tokenizer...")
        tokenizer = AutoTokenizer.from_pretrained(model_id)
        tokenizer.save_pretrained(model_path)
        
        print(f"Downloading model...")
        model = AutoModelForCausalLM.from_pretrained(
            model_id,
            torch_dtype="auto",
            device_map="cpu"
        )
        model.save_pretrained(model_path)
        
        # Upload to S3
        print(f"Uploading to S3...")
        s3_prefix = f"models/{model_id.replace('/', '--')}"
        
        for file_path in model_path.rglob("*"):
            if file_path.is_file():
                s3_key = f"{s3_prefix}/{file_path.relative_to(model_path)}"
                print(f"  Uploading: {s3_key}")
                s3.upload_file(str(file_path), bucket_name, s3_key)
        
        print(f"✓ Successfully cached: {model_id}")
        
    except Exception as e:
        print(f"✗ Failed to cache {model_id}: {e}")
        continue

print(f"\n{'='*60}")
print("Model caching complete!")
print(f"{'='*60}")
PYTHON_EOF

# Install dependencies and run
pip install transformers torch boto3 accelerate

python /tmp/download-models.py "${BUCKET_NAME}" "${MODELS[@]}"

echo ""
echo "S3 Model Cache Setup Complete!"
echo "Bucket: s3://${BUCKET_NAME}"
echo ""
echo "Next steps:"
echo "1. Update Kro RGD to add modelCacheBucket parameter"
echo "2. Update Backstage template to include S3 bucket configuration"
echo "3. Update Ray Serve app.py to use S3 cache"
```

### 2. Kro RGD Enhancement

**File**: `gitops/addons/charts/kro/resource-groups/manifests/ray-service/ray-service.yaml`

**Changes to schema:**
```yaml
spec:
  schema:
    apiVersion: v1alpha1
    group: kro.run
    kind: RayService
    spec:
      # ... existing fields ...
      modelCacheBucket: string | default=""  # NEW: S3 bucket for model cache
      useModelCache: boolean | default=false  # NEW: Enable S3 caching
```

**Changes to serveConfigV2:**
```yaml
serveConfigV2: |
  applications:
    - name: gpu_text_generation
      import_path: app:deployment
      route_prefix: /generate
      runtime_env:
        working_dir: "${schema.spec.rayServeFile}"
        pip:
          - torch>=2.0.0
          - transformers>=4.30.0
          - accelerate
          - bitsandbytes
          - boto3  # NEW: For S3 access
        env_vars:
          MODEL_ID: "${schema.spec.modelId}"
          MAX_LENGTH: "${schema.spec.maxLength}"
          MODEL_CACHE_BUCKET: "${schema.spec.modelCacheBucket}"  # NEW
          USE_MODEL_CACHE: "${schema.spec.useModelCache}"  # NEW
```

**Add IAM role for S3 access:**
```yaml
- id: rayS3Role
  includeWhen:
  - ${schema.spec.useModelCache == true}
  template:
    apiVersion: iam.services.k8s.aws/v1alpha1
    kind: Role
    metadata:
      namespace: "${schema.spec.name}"
      name: "${schema.spec.name}-ray-s3-role"
    spec:
      name: "${schema.spec.name}-ray-s3-role"
      assumeRolePolicyDocument: |
        {
          "Version": "2012-10-17",
          "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "pods.eks.amazonaws.com"},
            "Action": ["sts:AssumeRole", "sts:TagSession"]
          }]
        }
      inlinePolicies:
        s3-model-cache:
          Version: "2012-10-17"
          Statement:
            - Effect: Allow
              Action:
                - s3:GetObject
                - s3:ListBucket
              Resource:
                - "arn:aws:s3:::${schema.spec.modelCacheBucket}"
                - "arn:aws:s3:::${schema.spec.modelCacheBucket}/*"

- id: rayS3PodIdentity
  includeWhen:
  - ${schema.spec.useModelCache == true}
  readyWhen:
  - ${rayS3PodIdentity.status.conditions.exists(x, x.type == 'ACK.ResourceSynced' && x.status == "True")}
  template:
    apiVersion: eks.services.k8s.aws/v1alpha1
    kind: PodIdentityAssociation
    metadata:
      namespace: "${schema.spec.name}"
      name: "${schema.spec.name}-ray-s3"
    spec:
      clusterName: "${schema.spec.clusterName}"
      namespace: "${schema.metadata.namespace}"
      roleARN: "${rayS3Role.status.ackResourceMetadata.arn}"
      serviceAccount: ray-head-sa  # Need to create this
```

### 3. Backstage Template Update

**File**: `platform/backstage/templates/ray-serve/template-ray-serve.yaml`

**Add parameters:**
```yaml
- title: Model Cache Configuration
  description: Configure S3 model caching for faster startup
  properties:
    useModelCache:
      title: Enable Model Cache
      description: Use S3 bucket for pre-downloaded models
      type: boolean
      default: false
      ui:help: 'Reduces startup time from 5-10min to 30-60sec'
    modelCacheBucket:
      title: Model Cache Bucket
      description: S3 bucket name containing cached models
      type: string
      default: ""
      ui:help: 'Leave empty to download from HuggingFace'
      ui:options:
        condition:
          functionName: equals
          params:
            - useModelCache
            - true
```

**Update skeleton values:**
```yaml
values:
  # ... existing values ...
  useModelCache: ${{parameters.useModelCache}}
  modelCacheBucket: ${{parameters.modelCacheBucket}}
```

### 4. Ray Serve App Modification

**File**: `gitops/workloads/ray/gpu-demo-serve-config/app.py`

**Enhanced version with S3 caching:**
```python
import os
import boto3
from pathlib import Path
from transformers import AutoTokenizer, AutoModelForCausalLM
from ray import serve
from starlette.requests import Request

# Configuration from environment
MODEL_ID = os.getenv("MODEL_ID", "microsoft/DialoGPT-medium")
MAX_LENGTH = int(os.getenv("MAX_LENGTH", "100"))
USE_MODEL_CACHE = os.getenv("USE_MODEL_CACHE", "false").lower() == "true"
MODEL_CACHE_BUCKET = os.getenv("MODEL_CACHE_BUCKET", "")

def load_model_from_s3(model_id: str, bucket: str, local_path: Path):
    """Download model from S3 cache"""
    print(f"Loading model from S3: s3://{bucket}/models/{model_id.replace('/', '--')}")
    
    s3 = boto3.client('s3')
    s3_prefix = f"models/{model_id.replace('/', '--')}"
    
    # List all objects in the model prefix
    paginator = s3.get_paginator('list_objects_v2')
    for page in paginator.paginate(Bucket=bucket, Prefix=s3_prefix):
        for obj in page.get('Contents', []):
            s3_key = obj['Key']
            local_file = local_path / s3_key.replace(s3_prefix + '/', '')
            local_file.parent.mkdir(parents=True, exist_ok=True)
            
            print(f"  Downloading: {s3_key}")
            s3.download_file(bucket, s3_key, str(local_file))
    
    print(f"✓ Model downloaded from S3 cache")
    return local_path

def load_model(model_id: str):
    """Load model from S3 cache or HuggingFace"""
    cache_dir = Path("/tmp/model-cache")
    model_path = cache_dir / model_id.replace("/", "--")
    
    # Try S3 cache first if enabled
    if USE_MODEL_CACHE and MODEL_CACHE_BUCKET:
        try:
            if not model_path.exists():
                load_model_from_s3(model_id, MODEL_CACHE_BUCKET, model_path)
            
            print(f"Loading model from cache: {model_path}")
            tokenizer = AutoTokenizer.from_pretrained(model_path)
            model = AutoModelForCausalLM.from_pretrained(
                model_path,
                torch_dtype="auto",
                device_map="auto"
            )
            print(f"✓ Model loaded from S3 cache")
            return tokenizer, model
            
        except Exception as e:
            print(f"⚠ S3 cache failed: {e}")
            print(f"Falling back to HuggingFace download...")
    
    # Fallback to HuggingFace
    print(f"Downloading model from HuggingFace: {model_id}")
    tokenizer = AutoTokenizer.from_pretrained(model_id)
    model = AutoModelForCausalLM.from_pretrained(
        model_id,
        torch_dtype="auto",
        device_map="auto"
    )
    print(f"✓ Model loaded from HuggingFace")
    return tokenizer, model

@serve.deployment(
    ray_actor_options={"num_gpus": 1 if "gpu" in MODEL_ID.lower() else 0}
)
class TextGenerator:
    def __init__(self):
        print(f"Initializing TextGenerator with model: {MODEL_ID}")
        self.tokenizer, self.model = load_model(MODEL_ID)
        print(f"TextGenerator ready!")

    async def __call__(self, request: Request):
        data = await request.json()
        prompt = data.get("prompt", "")
        
        inputs = self.tokenizer(prompt, return_tensors="pt").to(self.model.device)
        outputs = self.model.generate(
            **inputs,
            max_length=MAX_LENGTH,
            do_sample=True,
            temperature=0.7
        )
        
        response = self.tokenizer.decode(outputs[0], skip_special_tokens=True)
        return {"response": response}

deployment = TextGenerator.bind()
```

## Deployment Workflow

### Initial Setup (One-time)
```bash
# 1. Run bootstrap script
cd platform-on-eks-workshop
./scripts/setup-s3-model-cache.sh ray-model-cache-123456789012

# 2. Update Kro RGD with S3 parameters
git add gitops/addons/charts/kro/resource-groups/manifests/ray-service/
git commit -m "Add S3 model cache support to Ray RGD"
git push

# 3. Update Backstage template
git add platform/backstage/templates/ray-serve/
git commit -m "Add S3 model cache option to Ray template"
git push

# 4. Update Ray Serve app
git add gitops/workloads/ray/gpu-demo-serve-config/
git commit -m "Add S3 model cache support to Ray Serve app"
git push

# 5. Sync ArgoCD
kubectl patch application kro-manifests-peeks-hub -n argocd --type merge \
  -p '{"operation":{"initiatedBy":{"username":"admin"},"sync":{"revision":"HEAD"}}}'
```

### Using S3 Cache (via Backstage)
1. Create new Ray Service through Backstage
2. Enable "Use Model Cache" checkbox
3. Enter S3 bucket name: `ray-model-cache-123456789012`
4. Select model (must be pre-cached)
5. Deploy - startup time: ~30-60 seconds instead of 5-10 minutes

## Benefits

### Performance
- **First deployment**: Same time (5-10 min) - downloads and caches
- **Subsequent deployments**: 30-60 seconds
- **Pod restarts**: 30-60 seconds (no re-download)
- **Scaling**: Fast worker startup

### Reliability
- Reduces dependency on HuggingFace availability
- Consistent model versions across deployments
- Faster recovery from pod failures

### Cost
- S3 storage: ~$0.023/GB/month
- Model sizes: 1-15GB per model
- Transfer: Free within same region
- **Total**: ~$5-20/month for 5 models

## Future Enhancements

1. **Automatic cache warming**: Lambda function to auto-download new models
2. **Cache invalidation**: Webhook to update models when new versions released
3. **Multi-region replication**: S3 cross-region replication for global deployments
4. **Cache metrics**: CloudWatch metrics for cache hit/miss rates
5. **Shared cache**: Single bucket for multiple clusters

## Testing Plan

1. Deploy without cache - measure startup time
2. Run bootstrap script to populate S3
3. Deploy with cache enabled - measure startup time
4. Verify model inference works correctly
5. Test cache miss scenario (model not in S3)
6. Test pod restart with cache
7. Test scaling with cache

## Rollback Plan

If S3 caching causes issues:
1. Set `useModelCache: false` in deployments
2. Services fall back to HuggingFace download
3. No data loss - models still accessible
4. Can re-enable after fixing issues

## Documentation Updates

- Add S3 cache setup to workshop README
- Update Ray Service deployment guide
- Add troubleshooting section for S3 access issues
- Document cost implications
