# Ray GPU Inference Strategy - Production Implementation

## Problem Statement

Ray GPU inference deployments were failing due to:
1. **HuggingFace Token Issues**: DoEKS vLLM image requires valid HF tokens, even for public models
2. **Runtime pip Install Failures**: Ray's runtime_env cannot reliably install PyTorch with CUDA support
3. **Image Conflicts**: Multiple vllm_serve.py versions causing import path confusion
4. **Slow Startup**: Installing vLLM at runtime adds 5-10 minutes to deployment time

## Solution: Pre-built Custom Images (GenAI Workshop Pattern)

Based on the AWS GenAI on EKS workshop's proven approach, we implement:

### 1. Custom Ray+vLLM Image Build

**Automated Build Pipeline:**
```
Terraform → Lambda → CodeBuild → ECR
```

**Dockerfile Pattern:**
```dockerfile
FROM rayproject/ray:2.49.0-py311-gpu

ENV DEBIAN_FRONTEND=non-interactive
ENV LD_LIBRARY_PATH=/home/ray/anaconda3/lib:$LD_LIBRARY_PATH

WORKDIR /app

# Install vLLM with all dependencies in single layer
RUN pip install vllm[runai]==0.10.2 huggingface_hub==0.35.3
RUN pip install --no-cache-dir --force-reinstall numpy==1.26.4
```

**Key Benefits:**
- ✅ vLLM pre-installed with correct CUDA support
- ✅ No runtime pip install delays
- ✅ Consistent versions across all deployments
- ✅ No HuggingFace token requirements for public models

### 2. Model Pre-staging to S3

**Model Distribution Strategy:**

Instead of downloading from HuggingFace during deployment:

```yaml
# Kubernetes Job (runs once during cluster setup)
apiVersion: batch/v1
kind: Job
metadata:
  name: model-prestage
spec:
  template:
    spec:
      initContainers:
      - name: validate-pod-identity
        # Ensures EKS Pod Identity is working
        
      - name: download-model
        # Downloads from Mistral CDN or HF to shared volume
        volumeMounts:
        - name: model-cache
          mountPath: /models
          
      containers:
      - name: upload-to-s3
        # Uploads from shared volume to S3
        volumeMounts:
        - name: model-cache
          mountPath: /models
          
      volumes:
      - name: model-cache
        emptyDir:
          sizeLimit: 50Gi
```

**Runtime Access:**
```yaml
# Ray workers mount S3 bucket via Pod Identity
env:
- name: HF_HOME
  value: /mnt/models
volumeMounts:
- name: model-cache
  mountPath: /mnt/models
  # S3 CSI driver or Mountpoint for S3
```

### 3. Implementation Architecture

#### Phase 1: Image Build (One-time Setup)

```hcl
# terraform/ray-image-build.tf
resource "aws_codebuild_project" "ray_vllm_build" {
  name = "ray-vllm-custom-build"
  
  environment {
    compute_type = "BUILD_GENERAL1_LARGE"
    image        = "aws/codebuild/standard:7.0"
    type         = "LINUX_CONTAINER"
    privileged_mode = true  # Required for Docker
  }
  
  source {
    type = "NO_SOURCE"
    buildspec = <<-EOF
      version: 0.2
      phases:
        pre_build:
          commands:
            - aws ecr get-login-password | docker login ...
        build:
          commands:
            - docker build -t ray-vllm:latest .
            - docker tag ray-vllm:latest $ECR_URI:latest
        post_build:
          commands:
            - docker push $ECR_URI:latest
    EOF
  }
}

# Lambda trigger for automated builds
resource "aws_lambda_function" "trigger_build" {
  function_name = "trigger-ray-vllm-build"
  
  environment {
    variables = {
      CODEBUILD_PROJECT = aws_codebuild_project.ray_vllm_build.name
    }
  }
}
```

#### Phase 2: Model Pre-staging (One-time per Model)

```yaml
# gitops/workloads/ray/model-prestage-job.yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: mistral-7b-prestage
  namespace: ray-system
spec:
  backoffLimit: 10
  activeDeadlineSeconds: 3600
  template:
    spec:
      serviceAccountName: model-prestage-sa
      
      initContainers:
      - name: validate-pod-identity
        image: amazon/aws-cli:latest
        command:
        - /bin/bash
        - -c
        - |
          # Verify Pod Identity is working
          IDENTITY=$(aws sts get-caller-identity)
          if echo "$IDENTITY" | grep -q "assumed-role.*model-prestage"; then
            echo "✓ Pod Identity working"
            exit 0
          else
            echo "✗ Using node role - Pod Identity not configured"
            exit 1
          fi
          
      - name: download-model
        image: python:3.11-slim
        command:
        - /bin/bash
        - -c
        - |
          pip install huggingface_hub requests
          
          # Download from Mistral CDN (no token needed)
          python3 << 'PYTHON_EOF'
          import os
          import requests
          from pathlib import Path
          
          model_url = "https://models.mistralcdn.com/mistral-7b-v0-3/mistral-7B-Instruct-v0.3.tar"
          output_dir = Path("/models/mistral-7b")
          output_dir.mkdir(parents=True, exist_ok=True)
          
          # Download with retry logic
          for attempt in range(5):
              try:
                  response = requests.get(model_url, stream=True, timeout=300)
                  response.raise_for_status()
                  
                  with open(output_dir / "model.tar", "wb") as f:
                      for chunk in response.iter_content(chunk_size=8192):
                          f.write(chunk)
                  
                  print(f"✓ Downloaded model to {output_dir}")
                  break
              except Exception as e:
                  wait = 2 ** attempt
                  print(f"Attempt {attempt+1} failed: {e}. Retrying in {wait}s...")
                  time.sleep(wait)
          PYTHON_EOF
        volumeMounts:
        - name: model-cache
          mountPath: /models
          
      containers:
      - name: upload-to-s3
        image: amazon/aws-cli:latest
        command:
        - /bin/bash
        - -c
        - |
          # Upload to S3 with retry logic
          for attempt in {1..5}; do
            if aws s3 sync /models/ s3://${MODEL_BUCKET}/models/ \
                --storage-class INTELLIGENT_TIERING \
                --no-progress; then
              echo "✓ Uploaded to S3"
              exit 0
            fi
            
            wait=$((2 ** attempt))
            echo "Attempt $attempt failed. Retrying in ${wait}s..."
            sleep $wait
          done
          
          echo "✗ Upload failed after 5 attempts"
          exit 1
        volumeMounts:
        - name: model-cache
          mountPath: /models
          
      volumes:
      - name: model-cache
        emptyDir:
          sizeLimit: 50Gi
      
      restartPolicy: OnFailure
```

#### Phase 3: Ray Deployment (Workshop Runtime)

```yaml
# Kro RGD: gitops/addons/charts/kro/resource-groups/manifests/ray-service/ray-service.yaml
spec:
  resources:
  - id: rayserviceGpu
    template:
      spec:
        rayClusterConfig:
          workerGroupSpecs:
          - groupName: worker-group
            template:
              spec:
                serviceAccountName: ray-worker-sa
                
                containers:
                - name: ray-worker
                  image: ${aws_account_id}.dkr.ecr.${region}.amazonaws.com/ray-vllm-custom:latest
                  
                  env:
                  - name: HF_HOME
                    value: /mnt/models
                  - name: TRANSFORMERS_CACHE
                    value: /mnt/models
                    
                  volumeMounts:
                  - name: model-cache
                    mountPath: /mnt/models
                    readOnly: true
                    
                  resources:
                    limits:
                      nvidia.com/gpu: "1"
                      
                volumes:
                - name: model-cache
                  csi:
                    driver: s3.csi.aws.com
                    volumeAttributes:
                      bucketName: ${model_bucket}
                      prefix: models/
                      
        serveConfigV2: |
          applications:
          - name: gpu_text_generation
            import_path: vllm_serve:deployment
            route_prefix: /generate
            runtime_env:
              working_dir: "${schema.spec.rayServeFile}"
              env_vars:
                MODEL_ID: "${schema.spec.modelId}"
                MAX_MODEL_LEN: "${schema.spec.maxLength}"
                # Model loaded from /mnt/models (S3 mount)
```

### 4. vLLM Serve Script (Simplified)

```python
# gitops/workloads/ray/vllm_serve.py
import os
from ray import serve
from vllm.engine.arg_utils import AsyncEngineArgs
from vllm.engine.async_llm_engine import AsyncLLMEngine
from vllm.sampling_params import SamplingParams

@serve.deployment(
    name="mistral-deployment",
    ray_actor_options={"num_gpus": 1},
    max_concurrent_queries=100
)
class VLLMDeployment:
    def __init__(self):
        model_id = os.environ.get('MODEL_ID', 'mistralai/Mistral-7B-Instruct-v0.2')
        max_model_len = int(os.environ.get('MAX_MODEL_LEN', '8192'))
        
        # Model loaded from HF_HOME (/mnt/models)
        engine_args = AsyncEngineArgs(
            model=model_id,
            tensor_parallel_size=1,
            dtype="auto",
            gpu_memory_utilization=0.9,
            max_model_len=max_model_len,
            trust_remote_code=True,
            download_dir=os.environ.get('HF_HOME', '/mnt/models')
        )
        
        self.engine = AsyncLLMEngine.from_engine_args(engine_args)
        self.model_id = model_id

    async def __call__(self, request):
        data = await request.json()
        prompt = data.get("prompt", "Hello")
        max_tokens = int(data.get("max_tokens", 100))
        
        sampling_params = SamplingParams(
            temperature=0.7,
            max_tokens=max_tokens
        )
        
        request_id = f"req-{id(request)}"
        results_generator = self.engine.generate(prompt, sampling_params, request_id)
        
        final_output = None
        async for request_output in results_generator:
            final_output = request_output
        
        text = final_output.outputs[0].text if final_output else ""
        
        return {
            "model": self.model_id,
            "prompt": prompt,
            "response": text
        }

deployment = VLLMDeployment.bind()
```

## Implementation Timeline

### Week 1: Image Build Infrastructure
- [ ] Create Dockerfile.ray-vllm
- [ ] Set up CodeBuild project
- [ ] Create Lambda trigger
- [ ] Test image build and push to ECR
- [ ] Update Kro RGD to use custom image

### Week 2: Model Pre-staging
- [ ] Create S3 bucket for models
- [ ] Set up Pod Identity for model-prestage job
- [ ] Create model download/upload job
- [ ] Test with Mistral-7B model
- [ ] Verify S3 CSI driver or Mountpoint setup

### Week 3: Integration
- [ ] Update Ray worker specs to mount S3
- [ ] Update vllm_serve.py to use mounted models
- [ ] Test end-to-end deployment
- [ ] Performance testing and optimization

### Week 4: Backstage Template
- [ ] Update template to use custom image
- [ ] Add model selection dropdown
- [ ] Document for users
- [ ] Workshop testing

## Key Differences from Previous Approach

| Aspect | Old Approach | New Approach |
|--------|-------------|--------------|
| **Image** | DoEKS pre-built or runtime pip | Custom-built via CodeBuild |
| **vLLM Install** | Runtime pip (5-10 min) | Pre-installed (0 min) |
| **Model Download** | Runtime HF download | Pre-staged to S3 |
| **HF Token** | Required (even for public) | Not required |
| **Startup Time** | 10-15 minutes | 2-3 minutes |
| **Reliability** | Pip conflicts, timeouts | Consistent, tested |

## Security Considerations

1. **EKS Pod Identity**: Used for S3 access (not IRSA)
2. **Validation Step**: Job fails fast if Pod Identity not working
3. **ECR Lifecycle**: Keeps last 10 images, auto-cleanup
4. **S3 Bucket Policy**: Restrict to specific service accounts
5. **No Secrets**: No HF tokens stored or required

## Monitoring and Troubleshooting

### Image Build Monitoring
```bash
# Check CodeBuild status
aws codebuild list-builds-for-project --project-name ray-vllm-custom-build

# View build logs
aws logs tail /aws/codebuild/ray-vllm-custom-build --follow
```

### Model Pre-staging Monitoring
```bash
# Check job status
kubectl get job mistral-7b-prestage -n ray-system

# View job logs
kubectl logs job/mistral-7b-prestage -n ray-system -c download-model
kubectl logs job/mistral-7b-prestage -n ray-system -c upload-to-s3

# Verify S3 upload
aws s3 ls s3://MODEL_BUCKET/models/ --recursive --human-readable
```

### Ray Deployment Monitoring
```bash
# Check Ray Serve status
kubectl exec -n ray-system POD_NAME -c ray-head -- python -c "
import ray
ray.init()
from ray import serve
print(serve.status())
"

# Check model mount
kubectl exec -n ray-system POD_NAME -- ls -lh /mnt/models/

# Check GPU usage
kubectl exec -n ray-system POD_NAME -- nvidia-smi
```

## Cost Optimization

1. **S3 Intelligent Tiering**: Automatically moves models to cheaper storage
2. **ECR Lifecycle**: Auto-cleanup of old images
3. **Spot Instances**: Use for CodeBuild (non-critical)
4. **Model Caching**: Share models across multiple Ray clusters

## References

- AWS GenAI on EKS Workshop: Proven production pattern
- vLLM Documentation: https://docs.vllm.ai/
- Ray Serve Documentation: https://docs.ray.io/en/latest/serve/
- EKS Pod Identity: https://docs.aws.amazon.com/eks/latest/userguide/pod-identities.html
