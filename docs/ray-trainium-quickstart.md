# Ray Service with AWS Trainium - Quick Start

## Overview

This platform now supports AWS Trainium accelerators for cost-effective AI inference alongside NVIDIA GPUs. Trainium instances (trn1) provide excellent performance for LLM inference at lower cost.

## Prerequisites

1. **AWS Trainium Quota**: Request quota increase for Trn1 instances
   ```bash
   aws service-quotas request-service-quota-increase \
     --service-code ec2 \
     --quota-code L-6B0D517C \
     --desired-value 32 \
     --region $AWS_REGION
   ```

2. **Pre-compiled Neuron Models**: Download from HuggingFace
   ```bash
   # Install HuggingFace CLI
   pip install -U "huggingface_hub[cli]"
   
   # Download Mistral-7B compiled for Neuron
   HF_HUB_ENABLE_HF_TRANSFER=1 huggingface-cli download \
     aws-neuron/Mistral-7B-Instruct-v0.3-seqlen-2048-bs-1-cores-2 \
     --local-dir /tmp/mistral-7b-neuron
   
   # Upload to S3
   aws s3 sync /tmp/mistral-7b-neuron \
     s3://${RESOURCE_PREFIX}-ray-models-${AWS_ACCOUNT_ID}/models/mistral-7b-neuron/
   ```

## Deployment via Backstage

1. Navigate to Backstage → Create Component
2. Select **"Ray Service - Trainium (AWS Neuron)"** template
3. Configure:
   - **Service Name**: `my-trainium-service`
   - **Model**: Mistral-7B-Instruct (Neuron-compiled)
   - **Worker Replicas**: 2
   - **Resources**: 8 CPU, 32GB RAM, 1 Neuron (default for trn1.2xlarge)

## Instance Types

| Instance | Neuron Cores | vCPUs | Memory | Best For |
|----------|--------------|-------|---------|----------|
| trn1.2xlarge | 2 | 8 | 32GB | Mistral-7B, development |
| trn1.32xlarge | 32 | 128 | 512GB | Large models, production |

## Key Differences from GPU

| Aspect | GPU (g5.xlarge) | Trainium (trn1.2xlarge) |
|--------|-----------------|-------------------------|
| Resource | `nvidia.com/gpu` | `aws.amazon.com/neuron` |
| Memory | 16GB RAM | 32GB RAM |
| Model Format | Standard PyTorch | Pre-compiled Neuron |
| vLLM Backend | CUDA | Neuron SDK |
| Cost | Higher | Lower (~40% savings) |

## Troubleshooting

### Pods Pending
Check Trainium quota:
```bash
aws service-quotas get-service-quota \
  --service-code ec2 \
  --quota-code L-6B0D517C \
  --region $AWS_REGION
```

### Model Not Found
Verify model exists in S3:
```bash
aws s3 ls s3://${RESOURCE_PREFIX}-ray-models-${AWS_ACCOUNT_ID}/models/mistral-7b-neuron/
```

### Performance Issues
Check Neuron utilization:
```bash
kubectl exec -it <pod-name> -n ray-system -- neuron-top
```

## References

- [AWS Neuron SDK Documentation](https://awsdocs-neuron.readthedocs-hosted.com/)
- [vLLM Neuron Backend](https://github.com/vllm-project/vllm)
- [EKS Workshop - Trainium](https://eksworkshop.com/docs/aiml/chatbot/)
- [Pre-compiled Models](https://huggingface.co/aws-neuron)
