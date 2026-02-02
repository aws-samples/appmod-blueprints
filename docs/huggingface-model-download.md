# Hugging Face Model Download with Kro RGD

## Overview

This implementation replaces CodeBuild-based model downloads with a Kubernetes-native solution using Kro ResourceGraphDefinition and Argo Workflows.

## Architecture

### Components Created

1. **Kro RGD**: `rg-huggingface-model.yaml`
   - Location: `gitops/addons/charts/kro/resource-groups/manifests/huggingface/`
   - Defines reusable pattern for model downloads

2. **Helm Template**: `huggingface-models.yaml`
   - Location: `gitops/addons/charts/platform-manifests/templates/`
   - Instantiates HuggingFaceModel resources

3. **Values Configuration**: `values.yaml`
   - Location: `gitops/addons/charts/platform-manifests/`
   - Defines which models to download

## How It Works

### Resource Graph Flow

```
HuggingFaceModel CR
  ├── Namespace (ray-system)
  ├── ServiceAccount (model-download-sa)
  ├── IAM Policy (S3 access)
  ├── IAM Role (Pod Identity)
  ├── PodIdentityAssociation
  └── Argo Workflow
      ├── Download from Hugging Face
      └── Upload to S3
```

### Workflow Steps

1. **Download Phase**:
   - Uses `python:3.11-slim` image
   - Installs `huggingface_hub`
   - Downloads model to `/workspace/model`
   - Uses 50Gi PVC for storage

2. **Upload Phase**:
   - Uses `amazon/aws-cli` image
   - Syncs model to S3: `s3://{bucket}/models/{model-name}/`
   - Uses Pod Identity for AWS credentials

## Usage

### Adding a New Model

Edit `gitops/addons/charts/platform-manifests/values.yaml`:

```yaml
huggingfaceModels:
  - name: llama-2-7b
    modelId: "meta-llama/Llama-2-7b-hf"
    s3Bucket: "{{ .Values.global.resourcePrefix }}-ray-models-{{ .Values.global.accountId }}"
    namespace: "ray-system"
    serviceAccount: "model-download-sa"
    accountId: "{{ .Values.global.accountId }}"
    region: "{{ .Values.global.region }}"
    clusterName: "{{ .Values.global.clusterName }}"
  
  - name: mistral-7b
    modelId: "mistralai/Mistral-7B-v0.1"
    # ... same configuration
```

### Enabling the Addon

In `hub-config.yaml`:

```yaml
clusters:
  hub:
    addons:
      enable_platform_manifests: true
```

### Monitoring Downloads

```bash
# Check HuggingFaceModel resources
kubectl get huggingfacemodel -A

# Check Argo Workflows
kubectl get workflows -n ray-system

# Watch workflow progress
kubectl logs -n ray-system -l workflows.argoproj.io/workflow=llama-2-7b-download -f

# Check S3 bucket
aws s3 ls s3://peeks-ray-models-{account-id}/models/
```

## Benefits Over CodeBuild

1. **Cost**: No CodeBuild charges, uses existing EKS compute
2. **GitOps**: Declarative model management through Git
3. **Visibility**: Better observability with Argo Workflows UI
4. **Reusability**: Kro RGD pattern for any Hugging Face model
5. **Consistency**: Same deployment pattern as other platform services
6. **Scalability**: Can run multiple downloads in parallel

## Terraform Cleanup

After deploying this solution, you can remove:

- `ray-image-build.tf` (if only used for models)
- CodeBuild-related resources in `model-storage.tf`
- Lambda trigger for CodeBuild

Keep:
- S3 bucket creation
- Base IAM structure (now managed by Kro)

## Troubleshooting

### Workflow Fails to Start

Check Pod Identity association:
```bash
kubectl get podidentityassociation -A
kubectl describe podidentityassociation llama-2-7b-podidentity -n ray-system
```

### Download Fails

Check workflow logs:
```bash
kubectl logs -n ray-system -l workflows.argoproj.io/workflow=llama-2-7b-download -c download
```

### Upload Fails

Check IAM permissions:
```bash
kubectl logs -n ray-system -l workflows.argoproj.io/workflow=llama-2-7b-download -c upload
```

### PVC Issues

Check storage:
```bash
kubectl get pvc -n ray-system
kubectl describe pvc -n ray-system
```

## Future Enhancements

1. **Caching**: Add model caching to avoid re-downloads
2. **Validation**: Add model validation step after download
3. **Notifications**: Send SNS/Slack notifications on completion
4. **Scheduling**: Add CronWorkflow for periodic model updates
5. **Multi-region**: Replicate models across regions
