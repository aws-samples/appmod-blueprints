# Ray Serve Model Management

## Overview

Ray Serve deployments use models pre-uploaded to S3 and mounted via the S3 CSI driver. This approach provides:
- Fast deployment (no HuggingFace downloads during pod startup)
- Consistent model versions across deployments
- Shared model storage across multiple Ray services

## Current Models

| Model | Size | Path | Best For |
|-------|------|------|----------|
| TinyLlama-1.1B | 2 GB | `/mnt/models/models/tinyllama` | CPU deployments, fast inference, testing |
| Mistral-7B-Instruct | 13.5 GB | `/mnt/models/models/mistral-7b` | GPU deployments, high-quality generation |

## Adding New Models

### Step 1: Update Model Prestage Job

Edit `gitops/addons/charts/ray-operator/templates/model-prestage-job.yaml` and add a new job:

```yaml
---
apiVersion: batch/v1
kind: Job
metadata:
  name: {{ .Values.global.resourcePrefix }}-new-model-prestage
  namespace: ray-system
spec:
  template:
    spec:
      serviceAccountName: {{ .Values.global.resourcePrefix }}-ray-s3-sa
      containers:
      - name: model-downloader
        image: python:3.11-slim
        command:
          - /bin/bash
          - -c
          - |
            pip install -q huggingface_hub
            python3 << 'EOF'
            from huggingface_hub import snapshot_download
            import os
            
            model_id = "organization/model-name"  # e.g., "meta-llama/Llama-3.2-3B"
            local_dir = "/mnt/models/models/new-model"
            
            print(f"Downloading {model_id} to {local_dir}")
            snapshot_download(
                repo_id=model_id,
                local_dir=local_dir,
                local_dir_use_symlinks=False
            )
            print("Download complete!")
            EOF
        volumeMounts:
        - name: model-storage
          mountPath: /mnt/models
      volumes:
      - name: model-storage
        persistentVolumeClaim:
          claimName: {{ .Values.global.resourcePrefix }}-ray-models-pvc
      restartPolicy: OnFailure
```

### Step 2: Update Backstage Template

Edit `platform/backstage/templates/ray-serve/template-ray-serve.yaml` and add the new model option:

```yaml
modelId:
  title: Model
  type: string
  default: "/mnt/models/models/tinyllama"
  enum:
    - "/mnt/models/models/tinyllama"
    - "/mnt/models/models/mistral-7b"
    - "/mnt/models/models/new-model"  # Add your new model
  enumNames:
    - "TinyLlama-1.1B (2GB, fast)"
    - "Mistral-7B-Instruct (14GB, high quality)"
    - "New Model Name (XGB, description)"  # Add description
```

### Step 3: Deploy Model Upload Job

```bash
# Commit changes
cd /home/ec2-user/environment/platform-on-eks-workshop
git add gitops/addons/charts/ray-operator/templates/model-prestage-job.yaml
git commit -m "Add new model prestage job"
git push

# Wait for ArgoCD to sync (or manually sync ray-operator addon)
# Then trigger the job
kubectl create job --from=cronjob/peeks-new-model-prestage manual-upload-$(date +%s) -n ray-system

# Monitor upload progress
kubectl logs -f job/manual-upload-XXXXX -n ray-system
```

### Step 4: Verify Model Upload

```bash
# Check S3 bucket
aws s3 ls s3://peeks-ray-models/models/new-model/ --recursive --human-readable

# Test model mount in a Ray pod
kubectl exec -n ray-system <ray-pod-name> -c ray-head -- ls -lh /mnt/models/models/new-model/
```

## Model Size Guidelines

- **CPU Deployments**: Use models ≤ 3B parameters (~6GB)
  - TinyLlama-1.1B: 2GB
  - Phi-2: ~5GB
  - Gemma-2B: ~5GB

- **GPU Deployments**: Can handle larger models
  - Mistral-7B: 13.5GB
  - Llama-3-8B: ~16GB
  - Mixtral-8x7B: ~90GB (requires multiple GPUs)

## Serve Configuration Files

### CPU Serve Config (`cpu-serve-config.zip`)
- Uses Transformers library
- Loads models from S3-mounted path
- Supports both CPU and GPU (auto-detects)
- File: `app.py`, `serve_config.py`, `requirements.txt`

### GPU Serve Config (`gpu-serve-config.zip`)
- Uses vLLM for optimized inference
- Requires GPU nodes
- Better performance for larger models
- File: `vllm_serve.py`

## S3 Bucket Configuration

The S3 bucket name is configured in `platform/backstage/templates/catalog-info.yaml`:

```yaml
spec:
  type: system
  lifecycle: production
  owner: platform-team
  model_s3_bucket: 'peeks-ray-models'  # Change this for different environments
```

## Troubleshooting

### Model Not Found
```bash
# Check S3 CSI driver Pod Identity
kubectl get podidentityassociation -A | grep s3-csi

# Restart S3 CSI controller
kubectl rollout restart deployment s3-csi-controller -n kube-system

# Verify model files in pod
kubectl exec -n ray-system <pod-name> -c ray-head -- ls -lh /mnt/models/models/
```

### Upload Job Fails
```bash
# Check job logs
kubectl logs -n ray-system job/<job-name>

# Verify service account has S3 permissions
kubectl get sa -n ray-system peeks-ray-s3-sa -o yaml

# Check Pod Identity association
aws eks describe-pod-identity-association --cluster-name peeks-hub --association-id <id>
```

### Model Loading Errors
- Ensure `local_files_only=True` in model loading code
- Verify model files are complete (check file sizes)
- Check Ray pod has sufficient memory for model size
