# Ray Service with AWS Trainium Support

## Overview

This document describes how to configure Ray Service deployments to use AWS Trainium accelerators instead of NVIDIA GPUs. vLLM supports both NVIDIA GPUs and AWS Neuron (Trainium/Inferentia), allowing you to leverage AWS-optimized ML accelerators for cost-effective inference.

## Prerequisites

- EKS cluster with Karpenter or EKS Auto Mode
- AWS Neuron device plugin installed
- Pre-compiled models for Neuron (available on HuggingFace under `aws-neuron/` namespace)

## Changes Required

### 1. Update GPU NodePool to Trainium NodePool

**File:** `gitops/addons/charts/platform-manifests/templates/gpu-nodepool.yaml`

Change from NVIDIA GPU instances to Trainium instances:

```yaml
apiVersion: karpenter.sh/v1
kind: NodePool
metadata:
  name: trainium  # or rename gpu to trainium
spec:
  disruption:
    budgets:
    - nodes: 10%
    consolidateAfter: 5m
    consolidationPolicy: WhenEmpty
  template:
    metadata:
      labels:
        node-type: trainium
    spec:
      nodeClassRef:
        group: eks.amazonaws.com
        kind: NodeClass
        name: default
      requirements:
        - key: "karpenter.sh/capacity-type"
          operator: In
          values: ["on-demand", "spot"]
        - key: "kubernetes.io/arch"
          operator: In
          values: ["amd64"]
        - key: "eks.amazonaws.com/instance-family"
          operator: In
          values:
          - trn1    # Trainium instances
          - trn1n   # Trainium with enhanced networking
      taints:
        - key: aws.amazon.com/neuron
          effect: NoSchedule
      terminationGracePeriod: 24h0m0s
```

### 2. Update KRO RayService Template

**File:** `gitops/addons/charts/kro/resource-groups/manifests/ray-service/ray-service.yaml`

Change GPU resource requests from `nvidia.com/gpu` to `aws.amazon.com/neuron`:

```yaml
# Find these lines (around line 302-306):
resources:
  limits:
    cpu: ${schema.spec.resources.worker.cpu}
    memory: ${schema.spec.resources.worker.memory}
    nvidia.com/gpu: ${schema.spec.resources.worker.gpu}  # OLD
  requests:
    cpu: ${schema.spec.resources.worker.cpu}
    memory: ${schema.spec.resources.worker.memory}
    nvidia.com/gpu: ${schema.spec.resources.worker.gpu}  # OLD

# Change to:
resources:
  limits:
    cpu: ${schema.spec.resources.worker.cpu}
    memory: ${schema.spec.resources.worker.memory}
    aws.amazon.com/neuron: ${schema.spec.resources.worker.gpu}  # NEW
  requests:
    cpu: ${schema.spec.resources.worker.cpu}
    memory: ${schema.spec.resources.worker.memory}
    aws.amazon.com/neuron: ${schema.spec.resources.worker.gpu}  # NEW
```

### 3. Build Trainium-Compatible Container Image

**File:** `platform/infra/terraform/common/Dockerfile.ray-neuron` (new file)

```dockerfile
# Use the official vLLM Neuron image as base
FROM public.ecr.aws/neuron/pytorch-inference-vllm-neuronx:0.9.1-neuronx-py311-sdk2.26.0-ubuntu22.04

# Set environment variables
ENV DEBIAN_FRONTEND=non-interactive
ENV NEURON_RT_NUM_CORES=2
ENV VLLM_NEURON_FRAMEWORK=neuronx-distributed-inference

# Set working directory
WORKDIR /app

# Install additional dependencies if needed
RUN pip install --no-cache-dir \
    huggingface_hub==0.35.3 \
    hf_transfer

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import vllm; import ray" || exit 1
```

### 4. Update Ray Serve Configuration

When deploying with Trainium, use pre-compiled Neuron models and adjust the vLLM command:

**Example deployment manifest:**

```yaml
spec:
  name: ray-trainium
  modelId: /mnt/models/models/mistral-7b-neuron  # Pre-compiled Neuron model
  s3ModelBucket: peeks-ray-models-586794472760
  awsRegion: us-west-2
  awsAccountId: "586794472760"
  resourcePrefix: peeks
  maxLength: "2048"
  rayServeFile: https://github.com/example/ray-serve-neuron.zip
  replicas: 2
  resources:
    head:
      cpu: "4"
      memory: 16Gi
    worker:
      cpu: "8"
      memory: 32Gi
      gpu: "1"  # This will map to aws.amazon.com/neuron: 1
```

### 5. Model Preparation

Use pre-compiled Neuron models from HuggingFace:

```bash
# Download pre-compiled model
pip install -U "huggingface_hub[cli]"
HF_HUB_ENABLE_HF_TRANSFER=1 hf download \
  aws-neuron/Mistral-7B-Instruct-v0.3-seqlen-2048-bs-1-cores-2 \
  --local-dir /models/mistral-7b-neuron

# Upload to S3
aws s3 sync /models/mistral-7b-neuron \
  s3://peeks-ray-models-586794472760/models/mistral-7b-neuron/
```

## vLLM Command Differences

### NVIDIA GPU:
```bash
vllm serve /models/mistral-7b \
  --device cuda \
  --tensor-parallel-size 1 \
  --dtype float16
```

### AWS Trainium:
```bash
vllm serve /models/mistral-7b-neuron \
  --device neuron \
  --tensor-parallel-size 2 \
  --max-num-seqs 4 \
  --use-v2-block-manager \
  --max-model-len 2048 \
  --dtype bfloat16
```

## Performance Considerations

- **Startup Time**: Trainium models are pre-compiled, so startup is faster than on-demand compilation
- **Throughput**: Trainium offers excellent throughput for batch inference
- **Cost**: Trainium instances (trn1) are typically more cost-effective than equivalent GPU instances
- **Memory**: Trainium has different memory characteristics; adjust batch sizes accordingly

## Available Trainium Instances

| Instance Type | Neuron Cores | vCPUs | Memory | Use Case |
|--------------|--------------|-------|---------|----------|
| trn1.2xlarge | 1 (2 cores) | 8 | 32 GiB | Small models, development |
| trn1.32xlarge | 16 (32 cores) | 128 | 512 GiB | Large models, production |
| trn1n.32xlarge | 16 (32 cores) | 128 | 512 GiB | Enhanced networking |

## Troubleshooting

### Pod stuck in Pending
- Check if Neuron device plugin is installed: `kubectl get daemonset -n kube-system neuron-device-plugin`
- Verify nodepool taint matches pod toleration

### Model loading fails
- Ensure model is pre-compiled for Neuron
- Check Neuron SDK version compatibility
- Verify `NEURON_RT_NUM_CORES` matches tensor-parallel-size

### Performance issues
- Adjust `--max-num-seqs` for optimal batch size
- Use `--max-model-len` to match your use case
- Monitor Neuron utilization: `neuron-top`

## References

- [vLLM Neuron Documentation](https://github.com/vllm-project/vllm)
- [AWS Neuron SDK](https://awsdocs-neuron.readthedocs-hosted.com/)
- [EKS Workshop - vLLM on Trainium](https://snapshots.eksworkshop.com/3a9836c5/docs/aiml/chatbot/)
- [Pre-compiled Neuron Models](https://huggingface.co/aws-neuron)

## Future Enhancements

- [ ] Add Trainium-specific template variant in Backstage
- [ ] Automate model compilation pipeline
- [ ] Add Neuron monitoring dashboards
- [ ] Create cost comparison metrics
